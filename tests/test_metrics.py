"""The metrics decide whether every other number in this project is real.

The case that matters most is `test_partial_redaction_is_a_leak`: a span metric
that scores a half-redacted name as a hit is a metric that will tell you the
system is safe while it publishes surnames.
"""

from __future__ import annotations

import pytest

from deid.eval.metrics import Report, score
from deid.types import PhiCategory, PhiSpan, apply_redaction, merge_spans


def S(start, end, cat=PhiCategory.NAME):
    return PhiSpan(start=start, end=end, category=cat)


def test_perfect_match_has_no_leak():
    r = Report()
    gold = (S(0, 5),)
    score(gold, gold, 20, r)
    assert r.leak_rate == 0.0
    assert r.strict.f1 == 1.0
    assert r.fully_missed_spans == 0


def test_total_miss_leaks_everything():
    r = Report()
    score((S(0, 5),), (), 20, r)
    assert r.leak_rate == 1.0
    assert r.fully_missed_spans == 1
    assert r.missed_by_category["NAME"] == 1


def test_partial_redaction_is_a_leak():
    """Gold 'Nandith Reddy' [0,13); we redact only 'Nandith' [0,7).

    Span-partial matching calls this a true positive — and it is, in the sense
    that we did detect the entity. But six characters of surname were published.
    The character metric is the only one that says so.
    """
    r = Report()
    score((S(0, 13),), (S(0, 7),), 13, r)

    assert r.partial.tp == 1          # span-level: "detected"
    assert r.strict.tp == 0           # boundaries wrong
    assert r.fully_missed_spans == 0  # not a wholesale miss
    assert r.covered_chars == 7
    assert r.gold_chars == 13
    assert r.leak_rate == pytest.approx(6 / 13)


def test_leak_rate_is_category_agnostic():
    """Redacting a name but labelling it a DATE still protects the patient."""
    r = Report()
    score((S(0, 5, PhiCategory.NAME),), (S(0, 5, PhiCategory.DATE),), 10, r)
    assert r.leak_rate == 0.0          # the characters are covered
    assert r.partial.tp == 0           # but the category is wrong
    assert r.partial.fn == 1
    assert r.fully_missed_spans == 0   # and it is not a disclosure


def test_overlapping_predictions_do_not_double_count_coverage():
    r = Report()
    score((S(0, 10),), (S(0, 6), S(4, 10)), 10, r)
    assert r.covered_chars == 10
    assert r.leak_rate == 0.0


def test_greedy_matching_is_order_independent():
    """Two predictions touching one gold span: the better one must win.

    A first-match loop would let the order of `pred` decide the score, which
    makes results depend on how a redactor happened to sort its output.
    """
    gold = (S(10, 20),)
    good, poor = S(10, 20), S(19, 25)

    a, b = Report(), Report()
    score(gold, (good, poor), 30, a)
    score(gold, (poor, good), 30, b)

    assert a.strict.as_dict() == b.strict.as_dict()
    assert a.strict.tp == 1 and a.strict.fp == 1


def test_f2_weights_recall_over_precision():
    high_recall = Report()
    high_recall.partial.tp, high_recall.partial.fp, high_recall.partial.fn = 90, 30, 10

    high_precision = Report()
    high_precision.partial.tp, high_precision.partial.fp, high_precision.partial.fn = 90, 10, 30

    # Mirror images: F1 is identical, F2 prefers the one that leaks less.
    assert high_recall.partial.f1 == pytest.approx(high_precision.partial.f1)
    assert high_recall.partial.f2 > high_precision.partial.f2


def test_empty_gold_does_not_divide_by_zero():
    r = Report()
    score((), (S(0, 4),), 10, r)
    assert r.leak_rate == 0.0
    assert r.partial.fp == 1


class TestSpanMerging:
    def test_nested_spans_collapse(self):
        merged = merge_spans([S(0, 10), S(2, 5)])
        assert [(s.start, s.end) for s in merged] == [(0, 10)]

    def test_adjacent_spans_join(self):
        merged = merge_spans([S(0, 5), S(5, 9)])
        assert [(s.start, s.end) for s in merged] == [(0, 9)]

    def test_disjoint_spans_survive(self):
        merged = merge_spans([S(0, 5), S(7, 9)])
        assert [(s.start, s.end) for s in merged] == [(0, 5), (7, 9)]


class TestApplyRedaction:
    def test_offsets_survive_multiple_replacements(self):
        text = "Nandith saw Reddy"
        out = apply_redaction(text, (S(0, 7), S(12, 17)))
        assert out == "[**NAME**] saw [**NAME**]"

    def test_overlapping_spans_do_not_corrupt_output(self):
        """Two detectors firing on 'Mr. Reddy' and 'Reddy' must yield one tag."""
        text = "Mr. Reddy came in"
        out = apply_redaction(text, (S(0, 9), S(4, 9)))
        assert out == "[**NAME**] came in"
