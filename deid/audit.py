"""Tamper-evident audit log.

The original implementation had a bug that made it useless:

    fs.appendFileSync(logFilePath, JSON.stringify(logEntry) + '\\n');

In a normal TypeScript string, `'\\n'` is an escaped backslash followed by the
letter n — two literal characters, not a line break. The log file accumulated
~130 records on a single unparseable line. `wc -l` reported zero. The headline
compliance feature of the project had never produced a readable record.

This version fixes that and goes further. Each entry carries the SHA-256 of the
previous entry, so the log is a hash chain: altering or deleting any historical
record invalidates every hash after it, and `verify()` will say so. That is
what makes an audit log evidence rather than a suggestion.

What is never written here
--------------------------
PHI. Not the note, not the spans, not the SSN. We record the SHA-256 of any
transmitted payload, its length, and the count of redactions by category. If
you need to prove later what was sent, you hash the payload you have and
compare. Writing the payload itself would make the audit log the largest PHI
repository in the system.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

GENESIS = "0" * 64


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _canonical(entry: dict[str, Any]) -> str:
    """Stable serialization. Key order must not vary or the chain breaks."""
    return json.dumps(entry, sort_keys=True, separators=(",", ":"))


@dataclass
class VerificationResult:
    ok: bool
    entries: int
    broken_at: int | None = None
    reason: str | None = None


class AuditLog:
    """Append-only, hash-chained JSONL."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _last_hash(self) -> str:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return GENESIS
        with self.path.open("rb") as fh:
            # Walk back from EOF to find the final newline rather than reading
            # the whole file; this log is meant to grow without bound.
            fh.seek(0, os.SEEK_END)
            end = fh.tell()
            size = min(4096, end)
            fh.seek(end - size)
            tail = fh.read(size).decode("utf-8", errors="replace")
        lines = [l for l in tail.splitlines() if l.strip()]
        if not lines:
            return GENESIS
        return _sha256(lines[-1])

    def record(self, action: str, *, actor_id: int | None = None,
               actor_role: str | None = None, **fields: Any) -> dict[str, Any]:
        with self._lock:
            entry = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "action": action,
                "actor_id": actor_id,
                "actor_role": actor_role,
                "prev": self._last_hash(),
                **fields,
            }
            line = _canonical(entry)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")  # a real newline, this time
                fh.flush()
                os.fsync(fh.fileno())
            return entry

    def record_egress(self, *, destination: str, payload: str,
                      redactions: dict[str, int], actor_id: int | None = None,
                      actor_role: str | None = None) -> dict[str, Any]:
        """Record that text crossed the trust boundary.

        `payload` is hashed, never stored. This is the record that answers the
        auditor's only real question: what exactly left the building?
        """
        return self.record(
            "EGRESS",
            actor_id=actor_id,
            actor_role=actor_role,
            destination=destination,
            payload_sha256=_sha256(payload),
            payload_chars=len(payload),
            redactions=dict(sorted(redactions.items())),
        )

    def read(self) -> Iterator[dict[str, Any]]:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    yield json.loads(line)

    def verify(self) -> VerificationResult:
        """Walk the chain. Any edit to any past record shows up here."""
        prev = GENESIS
        count = 0
        if not self.path.exists():
            return VerificationResult(ok=True, entries=0)

        with self.path.open("r", encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                line = line.rstrip("\n")
                if not line.strip():
                    continue
                count += 1
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError as e:
                    return VerificationResult(False, count, i, f"unparseable: {e}")

                if entry.get("prev") != prev:
                    return VerificationResult(
                        False, count, i,
                        f"chain broken: entry claims prev={entry.get('prev')!r}, "
                        f"computed {prev!r}",
                    )
                # Re-canonicalize: catches a record whose fields were edited in
                # place without updating the stored line.
                if _canonical(entry) != line:
                    return VerificationResult(
                        False, count, i, "entry does not match its canonical form"
                    )
                prev = _sha256(line)

        return VerificationResult(ok=True, entries=count)
