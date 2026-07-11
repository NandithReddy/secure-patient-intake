"""Train/test contamination guards.

`generate_corpus(n)` is a deterministic prefix sequence: the first 200 notes of
`generate_corpus(600)` are exactly `generate_corpus(200)`. That is a useful
property and also a loaded gun.

Training with `--n-synth 600` and evaluating with `--n-synth 200` means the
eval's *test* split (notes 150-199) lies inside the train's *train* split
(notes 0-359). The model would be scored on notes it memorised, and the result
would look like a triumph.

These tests exist so that failure is loud rather than flattering.
"""

from __future__ import annotations

from deid.synth import generate_corpus, split


def test_corpus_is_a_deterministic_prefix_sequence():
    small = generate_corpus(20)
    large = generate_corpus(60)
    assert [n.doc_id for n in small] == [n.doc_id for n in large[:20]]
    assert [n.text for n in small] == [n.text for n in large[:20]]


def test_corpus_is_reproducible_across_calls():
    assert [n.text for n in generate_corpus(10)] == [n.text for n in generate_corpus(10)]


def test_splits_are_disjoint():
    train, dev, test = split(generate_corpus(200))
    ids = [{n.doc_id for n in part} for part in (train, dev, test)]
    assert ids[0] & ids[1] == set()
    assert ids[0] & ids[2] == set()
    assert ids[1] & ids[2] == set()
    assert sum(len(s) for s in ids) == 200


def test_baseline_test_split_is_50_notes():
    """The published 20.81% figure was measured on exactly these notes."""
    _, _, test = split(generate_corpus(200))
    assert len(test) == 50
    assert test[0].doc_id == "synth-0150"
    assert test[-1].doc_id == "synth-0199"


def test_mismatched_corpus_sizes_contaminate():
    """This is the trap, asserted rather than described.

    Train on 600 and the train split is notes 0-359. Evaluate on 200 and the
    test split is notes 150-199 — wholly contained in it. Every single test
    note was memorised. A comparison built that way is worthless, and it would
    have looked like the best result in the project.
    """
    train_600, _, _ = split(generate_corpus(600))
    _, _, test_200 = split(generate_corpus(200))

    train_ids = {n.doc_id for n in train_600}
    leaked = train_ids & {n.doc_id for n in test_200}
    assert len(leaked) == 50, "the contamination this guard exists to prevent"
    assert len(leaked) == len(test_200), "100% of the test set, in fact"


def test_matched_corpus_sizes_are_clean():
    """The configuration we actually use."""
    train, dev, test = split(generate_corpus(200))
    seen = {n.doc_id for n in train} | {n.doc_id for n in dev}
    assert seen & {n.doc_id for n in test} == set()
