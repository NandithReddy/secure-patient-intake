"""Scoring for de-identification.

The central claim of this project is that de-identification is *not* a
symmetric classification problem, and scoring it like one hides the thing you
actually care about.

  - A false negative is a disclosure of protected health information.
  - A false positive is a slightly less useful clinical note.

These are not equally bad, so F1 — which weights precision and recall equally
— is the wrong headline number. We report it anyway, because the literature
does and you need a comparable figure. But the number that decides whether a
system can be deployed is the **leak rate**: the fraction of gold PHI
*characters* left un-redacted.

Why characters and not spans
----------------------------
Span-level recall counts a prediction as correct if it overlaps the gold span.
Under that rule, detecting "Nandith" inside the gold span "Nandith Reddy"
scores as a hit — while "Reddy" is published to the world. Character-level
recall is the only span metric that cannot lie to you about a partial
redaction, so it is what we lead with.

We report three views, in increasing strictness:

  leak_rate      1 - (gold PHI chars covered by any prediction) / (gold chars)
                 Category-agnostic: a redaction is a redaction. This is the
                 compliance number.
  partial P/R/F1 A predicted span matches a gold span if they overlap AND the
                 category agrees. Comparable to most published results.
  strict P/R/F1  Exact boundary and category match. Useful for spotting
                 systematic off-by-one boundary errors in a token classifier.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from ..types import PhiCategory, PhiSpan


def _f_beta(precision: float, recall: float, beta: float) -> float:
    if precision <= 0.0 and recall <= 0.0:
        return 0.0
    b2 = beta * beta
    denom = b2 * precision + recall
    return 0.0 if denom == 0 else (1 + b2) * precision * recall / denom


@dataclass
class PRF:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else 0.0

    @property
    def f1(self) -> float:
        return _f_beta(self.precision, self.recall, 1.0)

    @property
    def f2(self) -> float:
        """Weights recall 2x precision. The deployment-relevant summary score."""
        return _f_beta(self.precision, self.recall, 2.0)

    def as_dict(self) -> dict:
        return {
            "tp": self.tp, "fp": self.fp, "fn": self.fn,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
            "f2": round(self.f2, 4),
        }


@dataclass
class Report:
    strict: PRF = field(default_factory=PRF)
    partial: PRF = field(default_factory=PRF)
    per_category: dict[str, PRF] = field(default_factory=lambda: defaultdict(PRF))

    gold_chars: int = 0
    covered_chars: int = 0
    gold_spans: int = 0
    fully_missed_spans: int = 0
    missed_by_category: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    notes: int = 0
    hallucinated: int = 0
    total_latency_ms: float = 0.0
    total_cost_usd: float = 0.0

    @property
    def leak_rate(self) -> float:
        """Fraction of gold PHI characters left exposed. Lower is safer."""
        if self.gold_chars == 0:
            return 0.0
        return 1.0 - (self.covered_chars / self.gold_chars)

    @property
    def char_recall(self) -> float:
        return 1.0 - self.leak_rate

    @property
    def mean_latency_ms(self) -> float:
        return self.total_latency_ms / self.notes if self.notes else 0.0

    def as_dict(self) -> dict:
        return {
            "notes": self.notes,
            "leak_rate": round(self.leak_rate, 5),
            "char_recall": round(self.char_recall, 5),
            "gold_spans": self.gold_spans,
            "fully_missed_spans": self.fully_missed_spans,
            "missed_by_category": dict(sorted(self.missed_by_category.items())),
            "hallucinated_spans": self.hallucinated,
            "strict": self.strict.as_dict(),
            "partial": self.partial.as_dict(),
            "per_category": {
                k: v.as_dict() for k, v in sorted(self.per_category.items())
            },
            "mean_latency_ms": round(self.mean_latency_ms, 2),
            "total_cost_usd": round(self.total_cost_usd, 4),
        }


def _char_mask(spans: tuple[PhiSpan, ...], n: int) -> bytearray:
    mask = bytearray(n)
    for s in spans:
        for i in range(max(0, s.start), min(n, s.end)):
            mask[i] = 1
    return mask


def _greedy_match(
    gold: list[PhiSpan], pred: list[PhiSpan], *, strict: bool
) -> tuple[int, int, int, list[PhiSpan]]:
    """One-to-one matching between gold and predicted spans.

    Greedy by descending overlap so that when two predictions both touch one
    gold span, the better one claims it and the other is correctly counted as a
    false positive. A naive first-match loop would let span order decide the
    score, which makes results depend on how the redactor happened to sort.

    Returns (tp, fp, fn, unmatched_gold).
    """
    unmatched_gold = list(gold)
    unmatched_pred = list(pred)
    tp = 0

    candidates: list[tuple[int, int, int]] = []  # (-overlap, gold_idx, pred_idx)
    for gi, g in enumerate(unmatched_gold):
        for pi, p in enumerate(unmatched_pred):
            if g.category is not p.category:
                continue
            if strict:
                if g.start == p.start and g.end == p.end:
                    candidates.append((-len(g), gi, pi))
            else:
                ov = g.overlap_chars(p)
                if ov > 0:
                    candidates.append((-ov, gi, pi))

    candidates.sort()
    used_g: set[int] = set()
    used_p: set[int] = set()
    for _, gi, pi in candidates:
        if gi in used_g or pi in used_p:
            continue
        used_g.add(gi)
        used_p.add(pi)
        tp += 1

    fn_spans = [g for gi, g in enumerate(unmatched_gold) if gi not in used_g]
    fp = len(unmatched_pred) - len(used_p)
    return tp, fp, len(fn_spans), fn_spans


def score(
    gold: tuple[PhiSpan, ...],
    pred: tuple[PhiSpan, ...],
    text_len: int,
    report: Report,
) -> None:
    """Accumulate one note's results into `report`."""
    report.notes += 1
    report.gold_spans += len(gold)

    # --- Character coverage: the compliance metric, category-agnostic --------
    gold_mask = _char_mask(gold, text_len)
    pred_mask = _char_mask(pred, text_len)
    gold_total = sum(gold_mask)
    covered = sum(1 for i in range(text_len) if gold_mask[i] and pred_mask[i])
    report.gold_chars += gold_total
    report.covered_chars += covered

    # A gold span with zero predicted overlap is a wholesale disclosure — a
    # different failure from a boundary error, and worth counting separately.
    for g in gold:
        if not any(g.overlaps(p) for p in pred):
            report.fully_missed_spans += 1
            report.missed_by_category[g.category.value] += 1

    # --- Span-level, both strictnesses --------------------------------------
    for mode, bucket in (("strict", report.strict), ("partial", report.partial)):
        tp, fp, fn, _ = _greedy_match(list(gold), list(pred), strict=(mode == "strict"))
        bucket.tp += tp
        bucket.fp += fp
        bucket.fn += fn

    # --- Per-category, partial matching -------------------------------------
    for cat in PhiCategory:
        g_cat = [s for s in gold if s.category is cat]
        p_cat = [s for s in pred if s.category is cat]
        if not g_cat and not p_cat:
            continue
        tp, fp, fn, _ = _greedy_match(g_cat, p_cat, strict=False)
        b = report.per_category[cat.value]
        b.tp += tp
        b.fp += fp
        b.fn += fn
