"""Rule-based redactor — the baseline this project exists to beat.

This is a good-faith generalization of the `maskSSN` function from the original
Express backend:

    export function maskSSN(ssn: string): string {
      return `***-**-${ssn.slice(-4)}`;
    }

That function assumed someone had already told it which field was an SSN. Here
we do the harder and more realistic thing: find PHI in free text with no field
labels to lean on.

The baseline is deliberately *strong*. It handles five date formats, two phone
formats, honorific-anchored names, labelled fields, street addresses, and
hospital names. Beating a strawman proves nothing; the point is to show
precisely where a well-built rule system hits a wall that no additional rules
can climb.

Where it hits the wall: a surname in running prose. "Reddy has not been
compliant" contains PHI. No pattern distinguishes it from "Fever has not been
compliant" without knowing that Reddy is a name and fever is not. Neither can
any pattern know that "Hyderabad" is a city and "Furosemide" is not. Those are
questions about language, and that is why the next redactor is a language
model.
"""

from __future__ import annotations

import re

from ..types import PhiCategory, PhiSpan
from .base import BaseRedactor

_MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|"
    "November|December"
)
_MON = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"

# A name token is Capitalized, not ALLCAPS. Requiring the lowercase tail is
# what stops "Patient: Soren Whitfield   MRN:" from capturing the literal field
# label MRN into the name span.
_NAME = r"[A-Z][a-z'’]+(?:-[A-Z]?[a-z'’]+)?"

# (compiled pattern, category, subtype, capture group).
# Group 0 means "the whole match is the PHI"; a positive int narrows to that
# capture group, which is how we tag "Thorne" out of "Dr. Thorne" and the
# digits out of "MRN: 5686099".
_RULES: list[tuple[re.Pattern[str], PhiCategory, str, int]] = [
    # --- Identifiers -------------------------------------------------------
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), PhiCategory.ID, "SSN", 0),
    (re.compile(r"\bMRN[:#]?\s*(\d{6,10})\b", re.I), PhiCategory.ID, "MEDICALRECORD", 1),
    (re.compile(r"\bAcct[:#]?\s*(\d{6,12})\b", re.I), PhiCategory.ID, "ACCOUNT", 1),

    # --- Contact -----------------------------------------------------------
    (re.compile(r"\(\d{3}\)\s*\d{3}-\d{4}"), PhiCategory.CONTACT, "PHONE", 0),
    (re.compile(r"\b\d{3}-\d{3}-\d{4}\b"), PhiCategory.CONTACT, "PHONE", 0),
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), PhiCategory.CONTACT, "EMAIL", 0),
    (re.compile(r"https?://[^\s,;)]+"), PhiCategory.CONTACT, "URL", 0),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), PhiCategory.CONTACT, "IPADDR", 0),

    # --- Dates: five formats, because one format is a liability -------------
    (re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b"), PhiCategory.DATE, "DATE", 0),
    (re.compile(r"\b\d{4}-\d{2}-\d{2}\b"), PhiCategory.DATE, "DATE", 0),
    (re.compile(rf"\b(?:{_MONTHS})\s+\d{{1,2}},\s*\d{{4}}\b"), PhiCategory.DATE, "DATE", 0),
    (re.compile(rf"\b(?:{_MONTHS})\s+\d{{4}}\b"), PhiCategory.DATE, "DATE", 0),
    (re.compile(rf"\b\d{{1,2}}\s+(?:{_MON})\s+\d{{2,4}}\b"), PhiCategory.DATE, "DATE", 0),

    # --- Age ---------------------------------------------------------------
    (re.compile(r"\b(\d{1,3})[-\s]year[-\s]old\b", re.I), PhiCategory.AGE, "AGE", 1),

    # --- Names: only where an honorific or a field label anchors them -------
    (re.compile(rf"\b(?:Mr|Mrs|Ms|Dr|Doctor)\.?\s+({_NAME})"),
     PhiCategory.NAME, "DOCTOR", 1),
    (re.compile(rf"\bPatient:[ \t]*({_NAME}(?:[ \t]{_NAME})+)"),
     PhiCategory.NAME, "PATIENT", 1),
    (re.compile(rf"\bsigned by\s+(?:Dr\.?\s+)?({_NAME})", re.I),
     PhiCategory.NAME, "DOCTOR", 1),

    # --- Location ----------------------------------------------------------
    (
        re.compile(r"\b\d{1,5}\s+[A-Z][\w'’-]*(?:\s+[A-Z][\w'’-]*)*\s+"
                   r"(?:Street|St|Avenue|Ave|Road|Rd|Lane|Ln|Drive|Dr|Court|Ct|"
                   r"Boulevard|Blvd)\b"),
        PhiCategory.LOCATION, "STREET", 0,
    ),
    (re.compile(r"\b\d{5}(?:-\d{4})?\b"), PhiCategory.LOCATION, "ZIP", 0),
    # No leading `\s?` atom here. An optional leading-whitespace atom silently
    # pulls the preceding space into the span, so "seen at Mercy General"
    # redacts to "seen at[**LOCATION**]" — a boundary bug that also depresses
    # strict F1 for reasons that look like a model problem and are not.
    (
        re.compile(r"\b(?:St\.\s)?[A-Z][\w'’]+(?:\s+[A-Z][\w'’]+)*\s+"
                   r"(?:Hospital|Medical Center|Regional|General|Memorial|Clinic)\b"),
        PhiCategory.LOCATION, "HOSPITAL", 0,
    ),
]


class RuleRedactor(BaseRedactor):
    name = "rules"
    transmits_offsite = False

    def find(self, text: str) -> tuple[PhiSpan, ...]:
        spans: list[PhiSpan] = []
        for pattern, category, subtype, group in _RULES:
            for m in pattern.finditer(text):
                # A capture group that didn't participate in the match yields
                # (-1, -1) from span(); skip rather than emit a degenerate span.
                start, end = m.span(group)
                if start < 0 or end <= start:
                    continue
                spans.append(
                    PhiSpan(start=start, end=end, category=category,
                            text=text[start:end], subtype=subtype)
                )
        return tuple(sorted(spans))
