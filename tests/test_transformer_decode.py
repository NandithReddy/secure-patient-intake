"""BIO tagging and decoding.

These are pure functions — no torch, no checkpoint. They are also the most
dangerous code in the transformer path: a decode bug turns a model that found
the PHI into a redactor that misses it, and the metrics would faithfully report
the miss as a model failure. Test them independently of the model.
"""

from __future__ import annotations

from deid.redactors.transformer import bio_to_spans, label_list, spans_to_bio
from deid.types import PhiCategory, PhiSpan

LABELS = label_list()
L2I = {l: i for i, l in enumerate(LABELS)}
I2L = {i: l for l, i in L2I.items()}


def test_label_list_shape():
    # O + B-/I- per category. Index 0 must be O — the o_logit_penalty relies on it.
    assert LABELS[0] == "O"
    assert len(LABELS) == 1 + 2 * len(PhiCategory)


def test_roundtrip_single_span():
    text = "Seen by Dr. Thorne today"
    #                    ^12    ^18
    spans = (PhiSpan(12, 18, PhiCategory.NAME, "Thorne"),)
    offsets = [(0, 0), (0, 4), (5, 7), (8, 11), (12, 18), (19, 24), (0, 0)]
    seq_ids = [None, 0, 0, 0, 0, 0, None]

    tags = spans_to_bio(spans, offsets, seq_ids, L2I)
    assert tags[0] == -100 and tags[-1] == -100
    assert I2L[tags[4]] == "B-NAME"

    decoded = bio_to_spans(
        [0 if t == -100 else t for t in tags],
        [(0, 0) if s is None else o for o, s in zip(offsets, seq_ids)],
        I2L, text,
    )
    assert len(decoded) == 1
    assert (decoded[0].start, decoded[0].end) == (12, 18)
    assert decoded[0].category is PhiCategory.NAME
    assert decoded[0].text == "Thorne"


def test_multitoken_span_merges_into_one():
    """'Presbyterian Medical Center' is three tokens and one entity."""
    text = "at Presbyterian Medical Center on"
    offsets = [(0, 2), (3, 15), (16, 23), (24, 30), (31, 33)]
    seq_ids = [0] * 5
    spans = (PhiSpan(3, 30, PhiCategory.LOCATION, "Presbyterian Medical Center"),)

    tags = spans_to_bio(spans, offsets, seq_ids, L2I)
    assert [I2L[t] for t in tags] == [
        "O", "B-LOCATION", "I-LOCATION", "I-LOCATION", "O",
    ]

    decoded = bio_to_spans(tags, offsets, I2L, text)
    assert len(decoded) == 1
    assert (decoded[0].start, decoded[0].end) == (3, 30)


def test_adjacent_spans_of_same_category_stay_separate():
    """B- must start a new entity even when it follows the same category.

    'Thorne Halloway' as two doctors is two spans, not one. Decoding them as a
    single span would over-redact — tolerable — but the reverse error, merging
    across a B-, silently corrupts span counts in the metrics.
    """
    text = "Thorne Halloway"
    offsets = [(0, 6), (7, 15)]
    tags = [L2I["B-NAME"], L2I["B-NAME"]]
    decoded = bio_to_spans(tags, offsets, I2L, text)
    assert [(s.start, s.end) for s in decoded] == [(0, 6), (7, 15)]


def test_category_switch_without_b_prefix_splits():
    text = "Reddy 1984"
    offsets = [(0, 5), (6, 10)]
    tags = [L2I["B-NAME"], L2I["I-DATE"]]
    decoded = bio_to_spans(tags, offsets, I2L, text)
    assert len(decoded) == 2
    assert decoded[0].category is PhiCategory.NAME
    assert decoded[1].category is PhiCategory.DATE


def test_orphan_i_tag_still_yields_a_span():
    """A bare I- with no preceding B- is a common model error.

    Strict BIO decoding drops it. Dropping it discards PHI, which is the one
    failure mode this project exists to prevent — so we keep it.
    """
    text = "Reddy came in"
    offsets = [(0, 5), (6, 10), (11, 13)]
    tags = [L2I["I-NAME"], 0, 0]
    decoded = bio_to_spans(tags, offsets, I2L, text)
    assert len(decoded) == 1
    assert (decoded[0].start, decoded[0].end) == (0, 5)


def test_special_tokens_never_become_spans():
    text = "Reddy"
    offsets = [(0, 0), (0, 5), (0, 0)]
    tags = [L2I["B-NAME"], L2I["B-NAME"], L2I["I-NAME"]]
    decoded = bio_to_spans(tags, offsets, I2L, text)
    assert [(s.start, s.end) for s in decoded] == [(0, 5)]


def test_partial_token_overlap_is_labelled():
    """A subword straddling a span boundary must be tagged, not skipped.

    Under-tagging here would leave part of a name unredacted — the exact
    partial-leak the character metric was built to catch.
    """
    spans = (PhiSpan(2, 6, PhiCategory.NAME, "ddy "),)
    offsets = [(0, 4), (4, 8)]     # both tokens straddle the span
    seq_ids = [0, 0]
    tags = spans_to_bio(spans, offsets, seq_ids, L2I)
    assert [I2L[t] for t in tags] == ["B-NAME", "I-NAME"]
