"""Guards for the adversarial evaluation set.

The set is worth having only because the baseline's behaviour on every span in
it is *known* -- 71 false negatives, and 3 that the set itself turned into
catches by exposing age formats a regex can handle. Two things quietly destroy
that: an offset that stops indexing the text it claims, and a regex change that
makes a note stop testing what it advertises. Neither raises on its own, so
both are asserted here.

`test_truncated_name_captures_are_character_leaks` is the one to read. It is
the same argument as `test_partial_redaction_is_a_leak` in test_metrics.py,
made on real detector output instead of hand-built spans: three names where
the baseline fires, scores a partial-match true positive, and publishes the
rest of the surname anyway.
"""

from __future__ import annotations

import re

import pytest

from deid.eval.metrics import Report, score
from deid.redactors.rules import RuleRedactor
from deid.synth import DEFAULT, generate_corpus, generate_heldout_corpus
from deid.types import N2C2_SUBTYPE_MAP
from scripts.generate_adversarial_spans import (
    ADVERSARIAL_NOTES,
    baseline_outcome,
    build_notes,
    covered_chars,
    resolved,
)

ALL_SPANS = [(n.doc_id, s) for n in ADVERSARIAL_NOTES for s in n.spans]
ALL_PLANTED = [(n.doc_id, p, s) for n in ADVERSARIAL_NOTES
               for p, s in resolved(n.doc_id)]


def _ids(pairs):
    return [f"{doc_id}-{span.text}" for doc_id, span in pairs]


# --- the offsets ----------------------------------------------------------

@pytest.mark.parametrize("doc_id,span", ALL_SPANS, ids=_ids(ALL_SPANS))
def test_every_span_indexes_the_text_it_claims(doc_id, span):
    """The guarantee `str.find()` at load time cannot give you."""
    note = next(n for n in ADVERSARIAL_NOTES if n.doc_id == doc_id)
    assert note.text[span.start : span.end] == span.text
    assert 0 <= span.start < span.end <= len(note.text)


def test_resolution_is_deterministic():
    first, second = build_notes(), build_notes()
    assert [n.spans for n in first] == [n.spans for n in second]


def test_gold_spans_never_overlap():
    """Nested gold manufactures a false negative no detector can clear.

    `_greedy_match` pairs gold to predicted one-to-one, so annotating both
    `Ignatia Van Oorschot` and the `Van Oorschot` inside it would leave one
    gold span permanently unmatched and depress recall for a reason that has
    nothing to do with the detector.
    """
    for note in ADVERSARIAL_NOTES:
        for a, b in zip(note.spans, note.spans[1:]):
            assert not a.overlaps(b), f"{note.doc_id}: {a.text!r} / {b.text!r}"


def test_subtypes_map_to_their_declared_category():
    """A mis-bucketed subtype corrupts per-category recall silently."""
    for _doc_id, _p, span in ALL_PLANTED:
        assert N2C2_SUBTYPE_MAP[span.subtype] is span.category


def test_occurrence_pinning_selects_the_intended_instance():
    """Both values appear twice; the span must be the declared occurrence."""
    spans = {n.doc_id: n.spans for n in ADVERSARIAL_NOTES}

    mrn = next(s for s in spans["adv-0003"] if s.text == "773410")
    note3 = next(n for n in ADVERSARIAL_NOTES if n.doc_id == "adv-0003")
    assert note3.text[mrn.start - 7 : mrn.start] == "M.R.N. "
    assert mrn.subtype == "MEDICALRECORD"
    # ...and not the copy embedded in the device serial, which is its own span.
    assert any(s.text == "RPM-773410-C7" for s in spans["adv-0003"])
    assert not mrn.overlaps(
        next(s for s in spans["adv-0003"] if s.text == "RPM-773410-C7")
    )

    note2 = next(n for n in ADVERSARIAL_NOTES if n.doc_id == "adv-0002")
    bare = next(s for s in spans["adv-0002"] if s.text == "Van Oorschot")
    full = next(s for s in spans["adv-0002"] if s.text == "Ignatia Van Oorschot")
    assert bare.start > full.end, "the bare surname is the prose mention"
    assert note2.text.count("Van Oorschot") == 2


# --- the evasions ---------------------------------------------------------

@pytest.mark.parametrize("doc_id,planted,span", ALL_PLANTED,
                         ids=[f"{d}-{p.entity}" for d, p, _ in ALL_PLANTED])
def test_planted_entity_matches_its_recorded_outcome(doc_id, planted, span):
    """A regression guard that fires in both directions.

    A "miss" that starts being caught means someone patched a regex and this
    note no longer tests what it claims. A "partial" that becomes a full catch
    means the `_NAME` boundary bug is fixed and the leak demonstration is gone.
    Either way the set needs revisiting, so neither should pass quietly.
    """
    note = next(n for n in ADVERSARIAL_NOTES if n.doc_id == doc_id)
    got, n_covered = baseline_outcome(span, covered_chars(RuleRedactor(), note.text))
    assert got == planted.expect, (
        f"{planted.entity!r}: expected {planted.expect}, got {got} "
        f"({n_covered}/{len(span)} chars). Rule gap targeted: "
        f"{planted.vulnerability}"
    )


def test_truncated_name_captures_are_character_leaks():
    """The three partials, scored by the real metrics.

    Each is a partial-match true positive and a strict-match false positive:
    same prediction, opposite verdicts, because the boundary is wrong. That
    disagreement is the signature the strict/partial split exists to surface,
    and the leaked characters are a surname going out the door.
    """
    redactor = RuleRedactor()
    partials = [(d, p, s) for d, p, s in ALL_PLANTED if p.expect == "partial"]
    assert len(partials) == 3

    for doc_id, planted, span in partials:
        note = next(n for n in ADVERSARIAL_NOTES if n.doc_id == doc_id)
        pred = redactor.find(note.text)
        report = Report()
        score((span,), tuple(p for p in pred if p.overlaps(span)),
              len(note.text), report)

        assert report.partial.tp == 1, "span-level: detected"
        assert report.strict.tp == 0, "boundary is wrong"
        assert report.strict.fp == 1
        assert 0.0 < report.leak_rate < 1.0, "characters published anyway"
        assert report.fully_missed_spans == 0


def test_baseline_leaks_nearly_everything_on_this_set():
    """The set's reason to exist, stated as a number.

    The published baseline figures are 20.81% on synth and 16.00% on heldout.
    If this set ever scores in that range it has stopped being adversarial.
    """
    report = Report()
    redactor = RuleRedactor()
    for note in ADVERSARIAL_NOTES:
        score(note.spans, redactor.find(note.text), len(note.text), report)

    assert report.gold_spans == 74
    assert report.leak_rate > 0.95, f"only {report.leak_rate:.2%} leaked"
    assert report.leak_rate > 0.2081, "no worse than the synthetic baseline"
    assert report.partial.recall < 0.1
    assert report.hallucinated == 0


def test_every_category_is_represented():
    """A gap here means a whole category's failure modes went untested."""
    seen = {s.category.value for _d, s in ALL_SPANS}
    assert seen == {"NAME", "LOCATION", "ID", "DATE", "AGE", "CONTACT",
                    "PROFESSION"}


# --- contamination --------------------------------------------------------

def test_phi_values_are_absent_from_the_training_vocabulary():
    """No span here may be a string the transformer trained on.

    Otherwise a good score is lexical recall rather than evidence that the
    model read the context, which is the entire question this set asks. Two-
    letter state codes are exempt: there are fifty of them and `OR` and `ID`
    collide with ordinary clinical words.
    """
    training = {v for lst in (DEFAULT.first_names, DEFAULT.last_names,
                              DEFAULT.doctor_last, DEFAULT.hospitals,
                              DEFAULT.cities, DEFAULT.streets,
                              DEFAULT.professions) for v in lst}
    text = "\n".join(n.text for n in ADVERSARIAL_NOTES)
    hits = sorted(v for v in training if re.search(rf"\b{re.escape(v)}\b", text))
    assert hits == [], f"training vocabulary reused: {hits}"


def test_notes_are_not_members_of_the_existing_corpora():
    """These are new notes, not re-annotated synth or heldout ones."""
    existing = {n.text for n in generate_corpus(200)}
    existing |= {n.text for n in generate_heldout_corpus(50)}
    for note in ADVERSARIAL_NOTES:
        assert note.text not in existing
    ids = {n.doc_id for n in generate_corpus(200)}
    ids |= {n.doc_id for n in generate_heldout_corpus(50)}
    assert {n.doc_id for n in ADVERSARIAL_NOTES} & ids == set()
