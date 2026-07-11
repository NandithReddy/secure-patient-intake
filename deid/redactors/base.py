"""The interface every redactor implements."""

from __future__ import annotations

import time
from typing import Protocol, runtime_checkable

from ..types import Note, PhiSpan, RedactionResult, apply_redaction


@runtime_checkable
class Redactor(Protocol):
    name: str

    def find(self, text: str) -> tuple[PhiSpan, ...]:
        """Locate PHI. The only method a subclass must implement."""
        ...


class BaseRedactor:
    """Shared plumbing: timing, applying the redaction, packaging the result."""

    name: str = "base"
    # Set True only for redactors that transmit note text off-machine. The
    # EgressGuard and the CLI both check this before they will run one.
    transmits_offsite: bool = False

    def find(self, text: str) -> tuple[PhiSpan, ...]:  # pragma: no cover
        raise NotImplementedError

    def redact(self, note: Note) -> RedactionResult:
        t0 = time.perf_counter()
        spans = self.find(note.text)
        elapsed = (time.perf_counter() - t0) * 1000.0
        return RedactionResult(
            doc_id=note.doc_id,
            spans=spans,
            redacted_text=apply_redaction(note.text, spans),
            latency_ms=elapsed,
        )

    def redact_batch(self, notes: list[Note]) -> list[RedactionResult]:
        """Overridden by redactors that can amortize work across notes."""
        return [self.redact(n) for n in notes]
