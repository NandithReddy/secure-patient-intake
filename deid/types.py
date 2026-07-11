"""Core vocabulary: what a PHI span is, what a note is, what a redactor returns."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class PhiCategory(str, Enum):
    """Top-level PHI categories.

    These collapse the i2b2/n2c2 fine-grained tag set into the groups that
    matter for a disclosure decision. The original tag is preserved on the
    span as `subtype`, so nothing is lost for per-tag analysis.
    """

    NAME = "NAME"
    PROFESSION = "PROFESSION"
    LOCATION = "LOCATION"
    AGE = "AGE"
    DATE = "DATE"
    CONTACT = "CONTACT"
    ID = "ID"

    @classmethod
    def values(cls) -> list[str]:
        return [c.value for c in cls]


# Maps the n2c2 2014 fine-grained TYPE attribute onto our top-level categories.
# Anything unmapped is dropped with a warning rather than silently bucketed —
# a mis-bucketed gold span corrupts the per-category recall numbers.
N2C2_SUBTYPE_MAP: dict[str, PhiCategory] = {
    # NAME
    "PATIENT": PhiCategory.NAME,
    "DOCTOR": PhiCategory.NAME,
    "USERNAME": PhiCategory.NAME,
    # PROFESSION
    "PROFESSION": PhiCategory.PROFESSION,
    # LOCATION
    "HOSPITAL": PhiCategory.LOCATION,
    "ORGANIZATION": PhiCategory.LOCATION,
    "STREET": PhiCategory.LOCATION,
    "CITY": PhiCategory.LOCATION,
    "STATE": PhiCategory.LOCATION,
    "COUNTRY": PhiCategory.LOCATION,
    "ZIP": PhiCategory.LOCATION,
    "LOCATION-OTHER": PhiCategory.LOCATION,
    # AGE
    "AGE": PhiCategory.AGE,
    # DATE
    "DATE": PhiCategory.DATE,
    # CONTACT
    "PHONE": PhiCategory.CONTACT,
    "FAX": PhiCategory.CONTACT,
    "EMAIL": PhiCategory.CONTACT,
    "URL": PhiCategory.CONTACT,
    "IPADDR": PhiCategory.CONTACT,
    "IPADDRESS": PhiCategory.CONTACT,
    # ID
    "SSN": PhiCategory.ID,
    "MEDICALRECORD": PhiCategory.ID,
    "HEALTHPLAN": PhiCategory.ID,
    "ACCOUNT": PhiCategory.ID,
    "LICENSE": PhiCategory.ID,
    "VEHICLE": PhiCategory.ID,
    "DEVICE": PhiCategory.ID,
    "BIOID": PhiCategory.ID,
    "IDNUM": PhiCategory.ID,
}


@dataclass(frozen=True, order=True)
class PhiSpan:
    """A half-open character interval [start, end) carrying PHI.

    Offsets are into the *raw* note text. `text` is carried for debugging and
    for the LLM redactor's verbatim-match path; it is never the source of
    truth — the offsets are.
    """

    start: int
    end: int
    category: PhiCategory
    text: str = ""
    subtype: str | None = None

    def __post_init__(self) -> None:
        if self.start < 0 or self.end < self.start:
            raise ValueError(f"degenerate span [{self.start}, {self.end})")

    def __len__(self) -> int:
        return self.end - self.start

    def overlaps(self, other: PhiSpan) -> bool:
        return self.start < other.end and other.start < self.end

    def overlap_chars(self, other: PhiSpan) -> int:
        return max(0, min(self.end, other.end) - max(self.start, other.start))


@dataclass
class Note:
    """A clinical note plus (optionally) its gold PHI annotations."""

    doc_id: str
    text: str
    spans: tuple[PhiSpan, ...] = ()

    def __post_init__(self) -> None:
        # Guard against a loader producing offsets that don't index this text.
        for s in self.spans:
            if s.end > len(self.text):
                raise ValueError(
                    f"{self.doc_id}: span {s.start}:{s.end} exceeds text length {len(self.text)}"
                )
            if s.text and self.text[s.start : s.end] != s.text:
                raise ValueError(
                    f"{self.doc_id}: span text {s.text!r} != slice "
                    f"{self.text[s.start:s.end]!r} at {s.start}:{s.end}"
                )


@dataclass
class RedactionResult:
    """What a redactor produces for one note."""

    doc_id: str
    spans: tuple[PhiSpan, ...]
    redacted_text: str
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    # Spans the model claimed to find but which do not appear verbatim in the
    # note. Only an LLM can do this; it is one of the more interesting things
    # the benchmark measures.
    hallucinated: int = 0
    meta: dict = field(default_factory=dict)


def apply_redaction(text: str, spans: tuple[PhiSpan, ...]) -> str:
    """Replace each span with a category placeholder.

    Applied right-to-left so earlier offsets stay valid. Overlapping spans are
    merged first — otherwise a nested span would corrupt the offsets of its
    parent and produce mangled output.
    """
    merged = merge_spans(spans)
    out = text
    for s in sorted(merged, key=lambda s: s.start, reverse=True):
        out = f"{out[: s.start]}[**{s.category.value}**]{out[s.end :]}"
    return out


import re as _re

# Matches the placeholders apply_redaction() inserts, e.g. "[**NAME**]".
_PLACEHOLDER_RE = _re.compile(r"\[\*\*[A-Z]+\*\*\]")


def placeholder_regions(text: str) -> list[tuple[int, int]]:
    """Character ranges occupied by redaction placeholders like [**NAME**]."""
    return [(m.start(), m.end()) for m in _PLACEHOLDER_RE.finditer(text)]


def residual_phi(text: str, spans: tuple[PhiSpan, ...]) -> tuple[PhiSpan, ...]:
    """Real leaked PHI, excluding false positives inside redaction placeholders.

    Re-running a statistical detector on already-redacted text is unreliable:
    the text is now full of "[**NAME**]" markers the model never saw in
    training, so it can flag a bracket or marker character as PHI. Those hits
    are artifacts of our own placeholders, not leaked identifiers.

    A span counts as a real leak only if it is NOT wholly contained in a
    placeholder. A genuinely missed name sits in ordinary text, outside any
    placeholder, so it still counts — this filter narrows false positives
    without ever hiding a real leak.
    """
    regions = placeholder_regions(text)
    return tuple(
        s for s in spans
        if not any(r0 <= s.start and s.end <= r1 for r0, r1 in regions)
    )


def merge_spans(spans: tuple[PhiSpan, ...] | list[PhiSpan]) -> list[PhiSpan]:
    """Union overlapping/adjacent spans, keeping the longest span's category.

    Two detectors firing on "Mr. Reddy" and "Reddy" must not produce two
    replacements. When categories disagree we keep the one covering more
    characters; the redacted output only needs a defensible label.
    """
    if not spans:
        return []
    ordered = sorted(spans, key=lambda s: (s.start, -len(s)))
    merged: list[PhiSpan] = [ordered[0]]
    for s in ordered[1:]:
        last = merged[-1]
        if s.start <= last.end:  # overlapping or exactly adjacent
            if s.end <= last.end:
                continue  # fully contained
            winner = last if len(last) >= len(s) else s
            merged[-1] = PhiSpan(
                start=last.start,
                end=s.end,
                category=winner.category,
                subtype=winner.subtype,
            )
        else:
            merged.append(s)
    return merged
