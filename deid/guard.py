"""The trust boundary.

Everything else in this project measures how well we find PHI. This module is
what makes that measurement load-bearing: nothing reaches an external service
unless a local detector has confirmed there is no PHI left in it.

    guard = EgressGuard(detector=RuleRedactor(), audit=AuditLog("audit.jsonl"))
    summary = guard.send(redacted_note, destination="anthropic:claude-opus-4-8",
                         fn=lambda safe: llm.summarize(safe))

If the detector still finds PHI, `send` raises `PhiLeakBlocked` and the call
never happens. The attempt is written to the audit log either way — a blocked
egress is more interesting to an auditor than a successful one.

This is deliberately fail-closed. A detector that crashes, or a detector whose
output we cannot interpret, blocks the send. The alternative — failing open on
a detector error — converts a monitoring outage into a disclosure.
"""

from __future__ import annotations

from collections import Counter
from typing import Callable, TypeVar

from .audit import AuditLog
from .redactors.base import BaseRedactor
from .types import PhiSpan

T = TypeVar("T")


class PhiLeakBlocked(RuntimeError):
    """Raised when text bound for an external service still contains PHI."""

    def __init__(self, destination: str, spans: tuple[PhiSpan, ...]) -> None:
        self.destination = destination
        self.spans = spans
        by_cat = Counter(s.category.value for s in spans)
        detail = ", ".join(f"{n}×{c}" for c, n in sorted(by_cat.items()))
        super().__init__(
            f"Blocked egress to {destination}: {len(spans)} PHI span(s) remain "
            f"({detail}). Redact before transmitting."
        )


class EgressGuard:
    def __init__(self, detector: BaseRedactor, audit: AuditLog) -> None:
        if getattr(detector, "transmits_offsite", False):
            # Using the LLM redactor as the guard's detector would ship the very
            # text we are trying to protect to the very service we are guarding
            # against. Refuse at construction.
            raise ValueError(
                f"Detector {detector.name!r} transmits text off-machine and "
                f"cannot be used to guard an egress boundary."
            )
        self.detector = detector
        self.audit = audit

    def inspect(self, text: str) -> tuple[PhiSpan, ...]:
        return self.detector.find(text)

    def send(
        self,
        text: str,
        *,
        destination: str,
        fn: Callable[[str], T],
        actor_id: int | None = None,
        actor_role: str | None = None,
    ) -> T:
        try:
            residual = self.inspect(text)
        except Exception as e:
            self.audit.record(
                "EGRESS_BLOCKED", actor_id=actor_id, actor_role=actor_role,
                destination=destination, reason=f"detector error: {e!r}",
            )
            raise PhiLeakBlocked(destination, ()) from e

        if residual:
            self.audit.record(
                "EGRESS_BLOCKED", actor_id=actor_id, actor_role=actor_role,
                destination=destination, reason="residual PHI",
                residual=dict(Counter(s.category.value for s in residual)),
            )
            raise PhiLeakBlocked(destination, residual)

        self.audit.record_egress(
            destination=destination, payload=text, redactions={},
            actor_id=actor_id, actor_role=actor_role,
        )
        return fn(text)
