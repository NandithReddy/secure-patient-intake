"""LLM-based redactor.

⚠️  THIS REDACTOR TRANSMITS RAW NOTE TEXT OFF-MACHINE.

It exists to *measure* whether a hosted language model can de-identify clinical
text. It is never on the serving path. `EgressGuard` and the FastAPI service
both refuse to instantiate it, and the CLI requires an explicit
`--i-understand-this-transmits-phi` flag before it will run.

Before pointing this at the n2c2 corpus, read your Data Use Agreement. The
corpus contains surrogate (resynthesized) identifiers rather than real patient
data, so this is not a HIPAA disclosure — but the DUA independently restricts
who may receive copies of the files, and an inference API is a recipient.

Design note: why we ask for strings, not offsets
------------------------------------------------
The obvious prompt is "return the character offsets of each PHI span." Language
models are bad at that — they cannot count characters reliably, and an
off-by-three offset silently redacts the wrong text. Instead we ask for the
PHI *verbatim*, then locate it ourselves with an exact string search.

This has a useful side effect. If the model returns a string that does not
appear anywhere in the note, it invented it. We count those. Hallucination rate
is a number nobody reports for de-identification, and it turns out to matter:
a redactor that invents spans is one that will eventually redact real clinical
content.
"""

from __future__ import annotations

import json
import os
import re
import time

from ..types import Note, PhiCategory, RedactionResult, PhiSpan, apply_redaction
from .base import BaseRedactor

# USD per million tokens. Cached from Anthropic's pricing page (2026-06-24);
# verify before quoting these in a writeup.
PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-4-8": (5.00, 25.00),
    "claude-opus-4-7": (5.00, 25.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-fable-5": (10.00, 50.00),
}

_SCHEMA = {
    "type": "object",
    "properties": {
        "spans": {
            "type": "array",
            "description": "Every span of protected health information in the note.",
            "items": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": (
                            "The PHI exactly as it appears in the note, "
                            "character for character. Do not normalize, "
                            "reformat, correct, or paraphrase it."
                        ),
                    },
                    "category": {
                        "type": "string",
                        "enum": PhiCategory.values(),
                    },
                },
                "required": ["text", "category"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["spans"],
    "additionalProperties": False,
}

SYSTEM = """\
You are a de-identification system for clinical text, operating under HIPAA \
Safe Harbor.

Find every span of protected health information in the note. Categories:

  NAME        patients, doctors, nurses, relatives, usernames
  PROFESSION  the patient's occupation
  LOCATION    hospitals, clinics, employers, streets, cities, states, \
countries, ZIP codes
  AGE         any age
  DATE        any date or date fragment, in any format
  CONTACT     phone, fax, email, URL, IP address
  ID          SSN, medical record number, account, license, device, any \
other identifier

Rules:

1. Return each PHI string exactly as it appears in the note. Copy it \
character for character. Never normalize a date, expand an abbreviation, or \
fix a typo.
2. If a name appears more than once, return it once. The caller locates every \
occurrence.
3. Report a surname in running prose. "Reddy has not been compliant" contains \
a name.
4. Do not report clinical content: diagnoses, medications, dosages, lab \
values, symptoms, and anatomy are not PHI.
5. Do not report relative time references ("three days prior to admission").

Missing PHI discloses a patient's identity. Over-reporting only degrades the \
note. When a span is genuinely ambiguous, report it.\
"""


class LLMRedactor(BaseRedactor):
    name = "llm"
    transmits_offsite = True

    def __init__(
        self,
        model: str = "claude-opus-4-8",
        api_key: str | None = None,
        max_tokens: int = 4096,
        effort: str = "high",
        use_batch: bool = True,
    ) -> None:
        try:
            import anthropic
        except ImportError as e:  # pragma: no cover
            raise ImportError(
                "The LLM redactor needs the anthropic SDK: pip install -e '.[llm]'"
            ) from e

        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        # A bare client() also resolves an `ant auth login` profile, so an unset
        # env var is not by itself an error. Let the SDK decide.
        self._client = anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()
        self._anthropic = anthropic
        self.model = model
        self.max_tokens = max_tokens
        self.effort = effort
        # Batch API halves the cost but is asynchronous and can queue. Disable
        # for a predictable, watch-it-happen synchronous run.
        self.use_batch = use_batch
        self.name = f"llm:{model}"

    # -- cost -----------------------------------------------------------------
    def _cost(self, usage, *, batch: bool) -> float:
        inp, out = PRICING.get(self.model, (0.0, 0.0))
        cost = (usage.input_tokens / 1e6) * inp + (usage.output_tokens / 1e6) * out
        return cost * 0.5 if batch else cost  # Batch API is half price

    # -- request construction -------------------------------------------------
    def _params(self, text: str) -> dict:
        return {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": SYSTEM,
            "thinking": {"type": "adaptive"},
            "output_config": {
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": _SCHEMA},
            },
            "messages": [{"role": "user", "content": f"<note>\n{text}\n</note>"}],
        }

    # -- response -> spans ----------------------------------------------------
    def _locate(self, text: str, payload: dict) -> tuple[tuple[PhiSpan, ...], int]:
        """Turn the model's verbatim strings into character spans.

        Every occurrence of each returned string is marked, because a name the
        model mentioned once may appear five times in the note and all five
        must be redacted. Strings that do not occur are counted as
        hallucinations and discarded.
        """
        spans: list[PhiSpan] = []
        hallucinated = 0
        seen: set[tuple[int, int]] = set()

        for item in payload.get("spans", []):
            raw = item.get("text", "")
            if not raw or not raw.strip():
                continue
            try:
                category = PhiCategory(item["category"])
            except (KeyError, ValueError):
                hallucinated += 1
                continue

            hits = list(re.finditer(re.escape(raw), text))
            if not hits:
                hallucinated += 1
                continue
            for m in hits:
                key = (m.start(), m.end())
                if key in seen:
                    continue
                seen.add(key)
                spans.append(
                    PhiSpan(start=m.start(), end=m.end(), category=category,
                            text=raw, subtype=None)
                )
        return tuple(sorted(spans)), hallucinated

    @staticmethod
    def _payload(message) -> dict:
        """Pull the structured JSON out of the response.

        `parsed_output` is populated when the SDK could validate the response
        against the schema; fall back to parsing the text block for older SDKs
        and for the Batch API path, which does not run the client-side parser.
        """
        parsed = getattr(message, "parsed_output", None)
        if isinstance(parsed, dict):
            return parsed
        for block in message.content:
            if getattr(block, "type", None) == "text":
                try:
                    return json.loads(block.text)
                except json.JSONDecodeError:
                    continue
        return {"spans": []}

    # -- single note ----------------------------------------------------------
    def redact(self, note: Note) -> RedactionResult:
        t0 = time.perf_counter()
        message = self._client.messages.create(**self._params(note.text))
        elapsed = (time.perf_counter() - t0) * 1000.0

        if message.stop_reason == "refusal":
            # A safety classifier declined. Not a bug — record it and move on,
            # rather than crashing a 500-note sweep on note 312.
            return RedactionResult(
                doc_id=note.doc_id, spans=(), redacted_text=note.text,
                latency_ms=elapsed, cost_usd=self._cost(message.usage, batch=False),
                meta={"refused": True},
            )

        spans, hallucinated = self._locate(note.text, self._payload(message))
        return RedactionResult(
            doc_id=note.doc_id,
            spans=spans,
            redacted_text=apply_redaction(note.text, spans),
            latency_ms=elapsed,
            cost_usd=self._cost(message.usage, batch=False),
            hallucinated=hallucinated,
        )

    # -- batch ----------------------------------------------------------------
    def redact_batch(self, notes: list[Note], poll_seconds: int = 20
                     ) -> list[RedactionResult]:
        """Score a whole corpus through the Batch API at half price.

        An evaluation sweep has no latency requirement and is embarrassingly
        parallel, which is exactly what batching is for. On a 500-note test set
        this is the difference between roughly $12 and roughly $6 per pass.
        """
        if not self.use_batch or len(notes) < 2:
            return [self.redact(n) for n in notes]

        from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
        from anthropic.types.messages.batch_create_params import Request

        batch = self._client.messages.batches.create(
            requests=[
                Request(
                    custom_id=n.doc_id,
                    params=MessageCreateParamsNonStreaming(**self._params(n.text)),
                )
                for n in notes
            ]
        )

        t0 = time.perf_counter()
        while True:
            status = self._client.messages.batches.retrieve(batch.id)
            if status.processing_status == "ended":
                break
            time.sleep(poll_seconds)
        wall_ms = (time.perf_counter() - t0) * 1000.0
        per_note_ms = wall_ms / len(notes)

        by_id = {n.doc_id: n for n in notes}
        results: dict[str, RedactionResult] = {}

        # Batch results arrive in arbitrary order — key by custom_id, never
        # by position.
        for entry in self._client.messages.batches.results(batch.id):
            note = by_id[entry.custom_id]
            if entry.result.type != "succeeded":
                results[note.doc_id] = RedactionResult(
                    doc_id=note.doc_id, spans=(), redacted_text=note.text,
                    latency_ms=per_note_ms,
                    meta={"batch_error": entry.result.type},
                )
                continue

            message = entry.result.message
            if message.stop_reason == "refusal":
                results[note.doc_id] = RedactionResult(
                    doc_id=note.doc_id, spans=(), redacted_text=note.text,
                    latency_ms=per_note_ms,
                    cost_usd=self._cost(message.usage, batch=True),
                    meta={"refused": True},
                )
                continue

            spans, hallucinated = self._locate(note.text, self._payload(message))
            results[note.doc_id] = RedactionResult(
                doc_id=note.doc_id,
                spans=spans,
                redacted_text=apply_redaction(note.text, spans),
                latency_ms=per_note_ms,
                cost_usd=self._cost(message.usage, batch=True),
                hallucinated=hallucinated,
            )

        return [results[n.doc_id] for n in notes]
