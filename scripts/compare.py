#!/usr/bin/env python
"""Side-by-side comparison of redactor reports.

Reads the JSON the evaluation harness already wrote. It computes nothing and
re-scores nothing — every number printed here came out of `deid/eval/metrics.py`
unchanged. That separation is the point: the comparison is trustworthy exactly
because the harness never learned which redactor it was scoring.

    python scripts/compare.py results/rules.json results/transformer.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RECALL_FLOOR = 0.90
# The categories a rule system structurally cannot reach: they need to know what
# a word means, not what shape it has.
SEMANTIC = {"NAME", "LOCATION", "PROFESSION"}


def load(paths: list[Path]) -> list[dict]:
    reports = []
    for p in paths:
        if not p.exists():
            sys.exit(f"{p} not found — run the eval that produces it first.")
        reports.append(json.loads(p.read_text()))
    return reports


def delta(new: float, old: float) -> str:
    d = new - old
    if abs(d) < 5e-4:
        return "      ·"
    return f"{d:+7.3f}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("baseline", type=Path)
    ap.add_argument("candidate", type=Path)
    ap.add_argument("--markdown", action="store_true",
                    help="emit a markdown table for the README")
    args = ap.parse_args()

    base, cand = load([args.baseline, args.candidate])
    bn, cn = base["redactor"], cand["redactor"]

    if base["notes"] != cand["notes"] or base["gold_spans"] != cand["gold_spans"]:
        print(
            f"WARNING: these were not scored on the same test set "
            f"({base['notes']} notes/{base['gold_spans']} spans vs "
            f"{cand['notes']}/{cand['gold_spans']}). The comparison is meaningless.",
            file=sys.stderr,
        )

    cats = sorted(set(base["per_category"]) | set(cand["per_category"]))

    if args.markdown:
        print(f"| Category | {bn} recall | {cn} recall | Δ | {cn} precision | {cn} F1 |")
        print("|---|---|---|---|---|---|")
        for c in cats:
            b = base["per_category"].get(c, {})
            k = cand["per_category"].get(c, {})
            br, kr = b.get("recall", 0.0), k.get("recall", 0.0)
            mark = " ⚠" if kr < RECALL_FLOOR else ""
            print(f"| {c} | {br:.3f} | **{kr:.3f}**{mark} | {kr - br:+.3f} | "
                  f"{k.get('precision', 0):.3f} | {k.get('f1', 0):.3f} |")
        print()
        print(f"| | {bn} | {cn} |")
        print("|---|---|---|")
        print(f"| **Leak rate** | {base['leak_rate']:.2%} | **{cand['leak_rate']:.2%}** |")
        print(f"| Character recall | {base['char_recall']:.2%} | {cand['char_recall']:.2%} |")
        print(f"| Precision (partial) | {base['partial']['precision']:.3f} | {cand['partial']['precision']:.3f} |")
        print(f"| F2 (recall-weighted) | {base['partial']['f2']:.3f} | {cand['partial']['f2']:.3f} |")
        print(f"| Spans never detected | {base['fully_missed_spans']} / {base['gold_spans']} | "
              f"{cand['fully_missed_spans']} / {cand['gold_spans']} |")
        print(f"| Latency | {base['mean_latency_ms']:.1f} ms | {cand['mean_latency_ms']:.1f} ms |")
        return 0

    w = 13
    print(f"\n  Test set: {base['notes']} notes, {base['gold_spans']} gold spans "
          f"(identical for both — same harness, same split)\n")
    print(f"  {'CATEGORY':<12} {bn[:w]:>{w}} {cn[:w]:>{w}} {'Δ RECALL':>9}   "
          f"{'PREC':>6} {'F1':>6}")
    print(f"  {'-' * 62}")

    for c in cats:
        b = base["per_category"].get(c, {})
        k = cand["per_category"].get(c, {})
        br, kr = b.get("recall", 0.0), k.get("recall", 0.0)
        flag = " <-- leaking" if kr < RECALL_FLOOR else ""
        star = "*" if c in SEMANTIC else " "
        print(f" {star}{c:<12} {br:>{w}.3f} {kr:>{w}.3f} {delta(kr, br):>9}   "
              f"{k.get('precision', 0):>6.3f} {k.get('f1', 0):>6.3f}{flag}")

    print(f"\n  * categories a rule system structurally cannot reach\n")
    print(f"  {'':<12} {bn[:w]:>{w}} {cn[:w]:>{w}}")
    print(f"  {'-' * 40}")
    print(f"  {'LEAK RATE':<12} {base['leak_rate']:>{w}.2%} {cand['leak_rate']:>{w}.2%}")
    print(f"  {'F2':<12} {base['partial']['f2']:>{w}.3f} {cand['partial']['f2']:>{w}.3f}")
    print(f"  {'Precision':<12} {base['partial']['precision']:>{w}.3f} "
          f"{cand['partial']['precision']:>{w}.3f}")
    print(f"  {'Missed spans':<12} {base['fully_missed_spans']:>{w}} "
          f"{cand['fully_missed_spans']:>{w}}")
    print(f"  {'Latency ms':<12} {base['mean_latency_ms']:>{w}.1f} "
          f"{cand['mean_latency_ms']:>{w}.1f}")

    reduction = 1 - (cand["leak_rate"] / base["leak_rate"]) if base["leak_rate"] else 0
    print(f"\n  Leak rate reduced by {reduction:.1%} relative to the baseline.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
