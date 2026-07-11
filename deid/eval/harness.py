"""Run a redactor over a corpus and score it."""

from __future__ import annotations

from ..redactors.base import BaseRedactor
from ..types import Note
from .metrics import Report, score


def evaluate(redactor: BaseRedactor, notes: list[Note],
             progress: bool = True) -> Report:
    report = Report()
    results = redactor.redact_batch(notes)

    if len(results) != len(notes):
        raise RuntimeError(
            f"{redactor.name} returned {len(results)} results for {len(notes)} notes"
        )

    for note, result in zip(notes, results):
        if result.doc_id != note.doc_id:
            raise RuntimeError(
                f"result/note misalignment: {result.doc_id!r} vs {note.doc_id!r}"
            )
        score(note.spans, result.spans, len(note.text), report)
        report.hallucinated += result.hallucinated
        report.total_latency_ms += result.latency_ms
        report.total_cost_usd += result.cost_usd

    if progress:
        print(
            f"  {redactor.name:<28} leak={report.leak_rate:7.2%}  "
            f"partial-F2={report.partial.f2:.3f}  "
            f"missed={report.fully_missed_spans}/{report.gold_spans}"
        )
    return report
