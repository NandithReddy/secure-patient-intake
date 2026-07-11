"""Loader for the n2c2 2014 de-identification corpus.

The corpus is NOT in this repository and never will be. Its Data Use Agreement
states that "under no circumstances are copies of any data files to be provided
to additional individuals or posted to other websites, including GitHub."

Get your own copy:
  1. Register at https://portal.dbmi.hms.harvard.edu/
  2. Request the n2c2 2014 De-identification track and sign the DUA
  3. Unpack the XML files somewhere outside this repo (or under ./data/, which
     is gitignored)

Format: one XML file per record.

    <deIdi2b2>
      <TEXT><![CDATA[ ...note text... ]]></TEXT>
      <TAGS>
        <NAME id="P0" start="16" end="29" text="Nandith Reddy" TYPE="PATIENT" />
        ...
      </TAGS>
    </deIdi2b2>

Offsets index into the CDATA text. We validate every one of them against the
text rather than trusting the file — a silently misaligned gold span would
corrupt every metric downstream, and it is much better to crash here.
"""

from __future__ import annotations

import warnings
import xml.etree.ElementTree as ET
from pathlib import Path

from ..types import N2C2_SUBTYPE_MAP, Note, PhiSpan


def load_note(path: Path, *, strict: bool = False) -> Note:
    root = ET.parse(path).getroot()

    text_el = root.find("TEXT")
    if text_el is None or text_el.text is None:
        raise ValueError(f"{path.name}: no <TEXT> element")
    text = text_el.text

    spans: list[PhiSpan] = []
    tags_el = root.find("TAGS")
    for tag in [] if tags_el is None else list(tags_el):
        subtype = (tag.get("TYPE") or tag.tag).upper()
        category = N2C2_SUBTYPE_MAP.get(subtype)
        if category is None:
            msg = f"{path.name}: unmapped PHI subtype {subtype!r}"
            if strict:
                raise ValueError(msg)
            warnings.warn(msg, stacklevel=2)
            continue

        start, end = int(tag.get("start", -1)), int(tag.get("end", -1))
        if start < 0 or end <= start or end > len(text):
            raise ValueError(f"{path.name}: bad offsets {start}:{end} for {subtype}")

        declared = tag.get("text", "")
        actual = text[start:end]
        if declared and declared != actual:
            raise ValueError(
                f"{path.name}: offset misalignment — tag says {declared!r}, "
                f"text[{start}:{end}] is {actual!r}. Refusing to build a corpus "
                f"whose gold labels do not match its text."
            )

        spans.append(
            PhiSpan(start=start, end=end, category=category,
                    text=actual, subtype=subtype)
        )

    return Note(doc_id=path.stem, text=text, spans=tuple(sorted(spans)))


def load_n2c2(directory: str | Path, *, strict: bool = False) -> list[Note]:
    d = Path(directory)
    if not d.is_dir():
        raise FileNotFoundError(
            f"{d} not found. The n2c2 corpus is not distributed with this repo — "
            f"see the module docstring for how to obtain it."
        )
    files = sorted(d.rglob("*.xml"))
    if not files:
        raise FileNotFoundError(f"No .xml files under {d}")
    return [load_note(f, strict=strict) for f in files]
