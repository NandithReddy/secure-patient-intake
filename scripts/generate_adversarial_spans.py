#!/usr/bin/env python
"""Adversarial evaluation set: notes engineered to maximize rule-baseline FNs.

Five synthetic clinical notes whose PHI is placed specifically to fall through
documented gaps in the twenty regexes of `deid/redactors/rules.py`, annotated
as `PhiSpan` objects so the existing scorer can read them with no adapter:

    from deid.eval import evaluate
    from scripts.generate_adversarial_spans import ADVERSARIAL_NOTES
    report = evaluate(RuleRedactor(), ADVERSARIAL_NOTES)

Why this file rather than a JSON fixture
----------------------------------------
`deid/eval/metrics.py` scores `PhiSpan` character intervals, so a fixture that
stores only PHI strings has to be re-located at load time with `str.find()` --
which silently picks the wrong occurrence whenever a value repeats, and
repeated values are exactly what a de-identification test set is full of.

Offsets are computed here, by one function, from one `(entity, occurrence)`
declaration per span. That mirrors `deid/synth.py`, where every PHI value goes
through `_Builder.phi()` for the same reason: an offset bug does not raise, it
quietly poisons every metric downstream, and one code path is far easier to
keep correct than literal integers scattered through a table. `Note.__post_init__`
then re-derives every span from the raw text and raises on any mismatch, so an
incorrect offset cannot survive importing this module.

The annotations are deliberately non-overlapping. `_greedy_match` pairs gold to
predicted one-to-one, so a nested gold span (`Van Oorschot` inside `Ignatia Van
Oorschot`) would manufacture a false negative that no detector could ever
clear.

All PHI is invented: unassignable SSN prefixes, reserved 555 exchanges and
`.invalid` domains. No PHI value here appears in `synth.DEFAULT`, the
vocabulary the transformer trains on, so a score on this set cannot be lexical
recall of a memorised training string. Two-letter state codes are the one
exception: there are only fifty, and `OR` and `ID` collide with ordinary words.

The vocabulary does overlap `synth.HELDOUT` -- `Quillfeather`, `Duskwater` and
`Pellingford` are drawn from it on purpose, to keep the two out-of-vocabulary
sets stylistically comparable. Both are evaluation-only, so that costs nothing
*provided neither is ever trained on*. Fine-tuning on this set would move
HELDOUT's vocabulary into the training data and silently void the
held-out-vocabulary result the README reports.

    python scripts/generate_adversarial_spans.py               # span inventory
    python scripts/generate_adversarial_spans.py --check       # assert the FNs
    python scripts/generate_adversarial_spans.py --score \
        --json-out results/adversarial_rules.json
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

# PhiSpan and PhiCategory are re-exported by deid.eval.metrics, but they are
# defined in deid.types -- importing them from their canonical home keeps this
# file working if metrics.py ever changes which names it pulls in.
from deid.types import N2C2_SUBTYPE_MAP, Note, PhiCategory, PhiSpan


@dataclass(frozen=True)
class Planted:
    """One PHI value placed in a note, plus the rule gap it was placed to hit.

    `occurrence` disambiguates repeated values: `773410` appears both as the
    record number and inside the device serial, and only the first is this
    span. `expect` records what the rule baseline does with it today --
    "miss" for zero predicted overlap, "partial" for a truncated capture that
    span-level recall scores as a hit while characters leak.
    """

    entity: str
    occurrence: int
    category: PhiCategory
    subtype: str
    expect: str
    vulnerability: str

_NOTE_1 = """\
ED DICTATION / UNPROOFED TRANSCRIPT / BED 14
PATIENT: Quillfeather, Rosalind       SEX: F
FACILITY: WRAITHMOOR VALLEY MEDICAL CENTRE
Medical Record No. 30088120455    Account 7741902
Presented 11-04-2021 at 0247 via EMS from the group home on Marrowbone Terrace.

pt is 91 years old, retired kill-floor hand at the Pellingford packing plant,
brought in after a witnessed syncopal episode with brief tonic posturing. per
EMS, FSBG 44 on scene, 1 amp D50 given, GCS back to 15 by arrival. afebrile,
HR 38 then 52 after atropine, BP 78/41 -> 102/60, RR 20, SpO2 94% RA. ECG
shows 2:1 AV block, rate 38, QTc 498. trop-I 0.08 -> 0.31 -> 0.44. K 6.1, Cr
2.4 (baseline 1.1 per outside records), BUN 58, bicarb 17, lactate 3.2. dig
level 2.9. held digoxin and lisinopril.
hx: HFrEF EF 30%, CKD3b, afib on apixaban, 2 prior PCIs.
Spoke with DR. KETTLEBURN, cardiology, who will take to cath lab once the K
is corrected. Daughter Perpetua at bedside, reachable 939.555.0148, she has
the healthcare proxy paperwork. Pt was last admitted here 14 Feb for the same
thing and left AMA.
Transcribed by vendor; dictator ID qfeath07."""

_NOTE_2 = """\
PROGRESS NOTE -- RHEUMATOLOGY -- same-day add-on, dictated between patients
Patient Name: Ignatia Van Oorschot      sex F      aged 72
Seen at Duskwater Hollow Infirmary, pod 3B, as a courtesy for Dr. de Vrieze
whose panel we absorbed in Sep 2019. Referral packet came through
www.pellingford-cardiology.invalid/referrals/vanoorschot-i and is scanned to
the chart.
Reason: 6-week f/u seropositive RA, on MTX 20 mg weekly SC + folate, started
March 3rd, 2019 by Dr. MacAlester before she moved out of the valley.
Interval hx: morning stiffness now 25 min (was 2 h). Swollen joint count 3
(bil MCP2, R wrist), tender 5, CDAI 9.2 -> low disease activity. No oral
ulcers, no pleuritic pain, no Raynaud phenomena. ESR 22, CRP 8.4, Hgb 11.8,
MCV 88, ALT 19, AST 22, Cr 0.9, albumin 3.9. CXR clear. QuantiFERON negative
prior to the biologic discussion.
Van Oorschot asks about tapering before her granddaughter's wedding and
declined a steroid bridge. Three nights a week she is still on the line
stripping tobacco at the leaf barn, which is why the MCP pain matters to her
more than the labs do.
Contact preference: she does not answer the phone, so write to
ignatia dot vanoorschot at duskwater-mail dot invalid or call the barn office
and ask for her by name.
Plan reviewed with Dr. O'Brannigan (attending). Co-signature pending."""

_NOTE_3 = """\
HOME HEALTH / REMOTE MONITORING ENROLLMENT -- telephone encounter, charted late
Patient:
 Mortlake-Grieve, Thaddeus
M.R.N. 773410     SSN 907 44 1183     plan ID 907.44.1183A
84 y/o, enrolled in cardiac RPM after a third HF decompensation this year
(last discharge 20210314 from Wexley Valley Hosp.).
Lives alone at 18 Thistledown Way, Elmsbury, zip 2139. His son's place in
Ravenshollow is the mailing address; he will not give out the street.
Ran a crew laying rail ties for the county road department for 31 years,
retired on disability. Still does small engine repair in the barn for cash.
Weights transmit from a Bluetooth scale, gateway address fd7a:0b19:4c2e::118,
device serial RPM-773410-C7. Cuff is a loaner, asset tag 4471-908823.
Vitals trend: dry weight 79 kg, today 82.6 kg, up 3.1 kg over four days. BP
96/58, HR 74, SpO2 92% on 2 L. Takes torsemide 40 mg daily, metolazone 2.5 mg
Mon/Thu, spironolactone 25 mg, sacubitril-valsartan 97/103 BID, empagliflozin
10 mg. K 4.2 and Cr 1.6 were drawn at the kitchen table on the mobile
phlebotomy run.
Instructed on 2 g sodium and 1.5 L fluid restriction, teach-back adequate.
Escalated to the HF pharmacist; torsemide increased to 60 mg for three days.
Dictated by B. Fenwicke, RN. Reviewed with Mx. Larkspur, the patient's
designated health care agent, who lives in the adjoining county."""

_NOTE_4 = """\
BEHAVIORAL HEALTH / SOCIAL WORK CONSULT -- bedside, no interpreter needed
Consult requested by nursing for capacity concerns. Pt is a nonagenarian, in
her 97th year, admitted from an unlicensed board-and-care in Duskwater, VT
after neighbors called a welfare check. The chart lists her as
Perpetua Quillhaven-Arbogast but she corrects everyone to Birdie and signs
documents that way.
She minded the switchboard at the Elmsbury woolen mill for thirty-one years
and still describes herself that way before anything else.
Last outpatient contact was the fourteenth of March, 2020, then nothing until
a walk-in visit 02/14. Her portal account birdie.q has not been accessed since.
Mental status: alert, oriented to person and place, not to date or situation.
MoCA 14/30 with marked recall and orientation loss, clock drawing distorted.
Denies SI/HI, no psychosis, no hallucinations. Appetite poor with 6 kg weight
loss since the admission weight. Mild hyperactive delirium overnight that
resolved once diphenhydramine was stopped.
Labs: TSH 2.1, B12 318, folate within range, RPR nonreactive, ammonia 22, UA
with few WBC and no nitrites. Head CT shows age-related atrophy and no acute
process.
Collateral from Rev. Pennywhistle at her parish, who has driven her to
appointments for years and holds a key to the house up on Gallows Hill.
Capacity for discharge planning: lacks. Surrogate decision-making to proceed
per statute; no advance directive on file.
Note entered /s/ P.Q.-A., LICSW, after discussion with the attending."""

_NOTE_5 = """\
DISCHARGE SUMMARY -- VASCULAR SURGERY -- auto-populated header, hand-edited body
MRN: 10022847193   alt MRN 56-860991 (duplicate chart, merge pending)
SSN 906228741      license OP-4471908      postcode V6B 1A1 (home in Canada)
Facility: Thornfield Health System, west campus
Admit 4-Mar-21, to the OR Mar 4 2021, discharged to rehab on day five.
Pt aged ninety-one, a former ferry pilot on the strait, brought in with a
6.9 cm infrarenal AAA found incidentally on a CT for flank pain. Not a
candidate for open repair given FEV1 38% predicted and a prior sternotomy, so
EVAR with bilateral iliac limbs. Estimated blood loss 150 mL, fluoro time
24 min, contrast 70 mL. Post-op creatinine bumped 1.2 to 1.9 then recovered to
1.3 by discharge with bicarbonate and holding the ACE-I.
Course: brief ICU stay on the permissive hypotension protocol, extubated the
same day, groin hematoma managed conservatively, no limb ischemia, ABIs 0.84 R
and 0.79 L at discharge. Hgb nadir 9.1 with 1 unit PRBC. Started ASA 81 and
clopidogrel 75 for one month, atorvastatin 80.
Lives at 412, Ambergate Avenue with a daughter who works nights.
Callback 939 555 0172 (daughter's mobile, needs the +1 prefix from the
island), FAX 939 555 0199 for records. Spoke with the rehab intake nurse at
the Pellingford VA.
Follow-up with Dr. Halloran Briscoe in vascular clinic in two weeks, duplex in
one month.
Electronically signed: Lundgren-Marsh, MD, FACS
Authenticated by RESIDENT: Fenwicke-Dunmore on behalf of the attending."""

_TEXTS: dict[str, str] = {
    "adv-0001": _NOTE_1,
    "adv-0002": _NOTE_2,
    "adv-0003": _NOTE_3,
    "adv-0004": _NOTE_4,
    "adv-0005": _NOTE_5,
}

# (entity, occurrence, category, subtype, expect, vulnerability)
_RAW: dict[str, list[tuple]] = {
    "adv-0001": [
        ('Quillfeather, Rosalind', 0, 'NAME', 'PATIENT', 'miss',
         "`\\bPatient:[ \\t]*(_NAME(?:[ \\t]_NAME)+)` is compiled without re.I, "
         "so the all-caps field label `PATIENT:` never matches the literal; "
         "independently, the EHR `Last, First` order breaks the "
         "whitespace-joined `(?:[ \\t]_NAME)+` tail because a comma follows the "
         "first token."),
        ('WRAITHMOOR VALLEY MEDICAL CENTRE', 0, 'LOCATION', 'HOSPITAL', 'miss',
         "HOSPITAL rule's trailing alternation `(?:Hospital|Medical "
         "Center|Regional|General|Memorial|Clinic)` is both case-sensitive and "
         "spelling-closed: the Commonwealth spelling `CENTRE` is not `Center`, "
         "and the all-caps letterhead form defeats the un-flagged literal."),
        ('30088120455', 0, 'ID', 'MEDICALRECORD', 'miss',
         "`\\bMRN[:#]?\\s*(\\d{6,10})\\b` keys on the literal `MRN`, absent from "
         "`Medical Record No.`; the 11-digit value also exceeds `\\d{6,10}` and "
         "every backtrack leaves a digit where the trailing `\\b` must be."),
        ('7741902', 0, 'ID', 'ACCOUNT', 'miss',
         "`\\bAcct[:#]?\\s*(\\d{6,12})` -- `Acct` is a prefix of the spelled-out "
         "word `Account`, so after consuming it the engine sits on `ount` "
         "where `[:#]?\\s*` then `\\d` is required, and the match dies."),
        ('11-04-2021', 0, 'DATE', 'DATE', 'miss',
         "Hyphenated month-first dates fall in the gap between "
         "`\\d{4}-\\d{2}-\\d{2}` (ISO, year-first) and `\\d{1,2}/\\d{1,2}/\\d{2,4}` "
         "(slash-delimited). No pattern pairs hyphen delimiters with "
         "day/month-first ordering."),
        ('Marrowbone Terrace', 0, 'LOCATION', 'STREET', 'miss',
         "STREET rule mandates a leading `\\d{1,5}\\s+` house number and a "
         "suffix from a closed list; a named thoroughfare with no number and "
         "the unlisted type `Terrace` fails on both counts."),
        ('91', 0, 'AGE', 'AGE', 'miss',
         "`(\\d{1,3})[-\\s]year[-\\s]old` requires `year` adjacent to `old`. The "
         "plural `years old` puts `s` exactly where `[-\\s]` is demanded, so "
         "the single most common spoken age form is invisible."),
        ('kill-floor hand', 0, 'PROFESSION', 'PROFESSION', 'miss',
         "No PROFESSION rule exists (recall 0.000). The occupation is also "
         "periphrastic -- a trade named by its work surface, not by an "
         "occupational noun -- so the obvious lexicon patch would not reach it "
         "either."),
        ('Pellingford packing plant', 0, 'LOCATION', 'ORGANIZATION', 'miss',
         "ORGANIZATION maps to LOCATION, but the only organization-shaped rule "
         "is the HOSPITAL pattern, whose closed keyword list contains "
         "care-facility nouns only; an employer with a lowercase industrial "
         "head noun matches nothing."),
        ('KETTLEBURN', 0, 'NAME', 'DOCTOR', 'miss',
         "The honorific rule `\\b(?:Mr|Mrs|Ms|Dr|Doctor)\\.?\\s+(_NAME)` is the "
         "one name rule with no re.I flag, and `_NAME`'s tail is `[a-z'’]+`. "
         "All-caps transcription breaks the honorific literal and the surname "
         "class at once."),
        ('939.555.0148', 0, 'CONTACT', 'PHONE', 'miss',
         "Dot-delimited phones fall between `\\(\\d{3}\\)\\s*\\d{3}-\\d{4}` and "
         "`\\d{3}-\\d{3}-\\d{4}`, and escape IPADDR because `(?:\\d{1,3}\\.){3}` "
         "needs three dot-terminated groups and a final group of at most 3 "
         "digits."),
        ('14 Feb', 0, 'DATE', 'DATE', 'miss',
         "`\\b\\d{1,2}\\s+(?:Jan|...|Dec)\\s+\\d{2,4}\\b` makes the year mandatory; "
         "a day-month with the year implied by the encounter context never "
         "matches."),
        ('qfeath07', 0, 'NAME', 'USERNAME', 'miss',
         "USERNAME maps to NAME, but there is no rule of any kind for logins "
         "or dictator IDs, and the lowercase-plus-digits token matches no "
         "`_NAME` form."),
        ('Perpetua', 0, 'NAME', 'PATIENT', 'miss',
         "A relative's given name in running prose. The only NAME anchors are "
         "honorifics, the `Patient:` label, and `signed by`; a kinship term "
         "(`Daughter`) is not among them."),
    ],
    "adv-0002": [
        ('Ignatia Van Oorschot', 0, 'NAME', 'PATIENT', 'miss',
         "`\\bPatient:` requires the colon immediately after the word "
         "`Patient`. The near-universal EHR header `Patient Name:` inserts a "
         "token before the colon, so the anchor never fires and the full name "
         "is published."),
        ('72', 0, 'AGE', 'AGE', 'miss',
         "The AGE rule is a single post-posed construction "
         "`N[-\\s]year[-\\s]old`. The pre-posed `aged N` form contains no "
         "`year`/`old` material to anchor on."),
        ('Duskwater Hollow Infirmary', 0, 'LOCATION', 'HOSPITAL', 'miss',
         "HOSPITAL's final-keyword alternation is a closed six-item list. "
         "`Infirmary` -- like Institute, Pavilion, Health System, Hospice, "
         "Sanatorium -- is outside it, so an otherwise textbook capitalized "
         "facility name is invisible."),
        ('de Vrieze', 0, 'NAME', 'DOCTOR', 'miss',
         "`_NAME` opens with `[A-Z]`, so an honorific followed by a lowercase "
         "nobiliary particle (`Dr. de Vrieze`) is a total miss rather than a "
         "partial one: the capture group never participates and the span is "
         "skipped."),
        ('Sep 2019', 0, 'DATE', 'DATE', 'miss',
         "The month-year rule `(?:January|...|December)\\s+\\d{4}` admits full "
         "month names only; the abbreviated `_MON` list is wired exclusively "
         "into the day-first pattern, so abbreviated month-year pairs are "
         "unreachable."),
        ('www.pellingford-cardiology.invalid/referrals/vanoorschot-i', 0, 'CONTACT', 'URL', 'miss',
         "The URL rule is anchored on `https?://`. A scheme-less host -- how "
         "URLs are actually typed and dictated -- has no matching pattern, and "
         "the path segment here carries the patient's name."),
        ('March 3rd, 2019', 0, 'DATE', 'DATE', 'miss',
         "The long-date rule needs `\\d{1,2},` directly after the month, so an "
         "ordinal suffix puts letters between day and comma; the month-year "
         "fallback needs a 4-digit year directly after the month name and sees "
         "`3rd` instead."),
        ('MacAlester', 0, 'NAME', 'DOCTOR', 'partial',
         "`_NAME = [A-Z][a-z'’]+(?:-[A-Z]?[a-z'’]+)?` has a lowercase-only "
         "tail that halts at an internal capital. `Dr. MacAlester` captures "
         "`Mac` and publishes `Alester`: span-level recall scores a hit while "
         "characters leak -- exactly the failure the character-level leak_rate "
         "exists to catch."),
        ('Van Oorschot', 1, 'NAME', 'PATIENT', 'miss',
         "A space-separated compound surname in running prose. The honorific "
         "rule needs `Mr|Mrs|Ms|Dr|Doctor` in front of it, and the only "
         "multi-token name rule is the `Patient:` label, whose anchor the "
         "`Patient Name:` header already defeated. Pinned to the prose "
         "mention; the header occurrence is inside the full-name span."),
        ('stripping tobacco at the leaf barn', 0, 'PROFESSION', 'PROFESSION', 'miss',
         "No PROFESSION rule. The occupation is a verb phrase with no "
         "occupational noun at all, so it also defeats a lexicon or gazetteer "
         "remedy."),
        ('ignatia dot vanoorschot at duskwater-mail dot invalid', 0, 'CONTACT', 'EMAIL', 'miss',
         "`[\\w.+-]+@[\\w-]+\\.[\\w.-]+` requires a literal `@` and a dotted "
         "domain. A dictated, spelled-out address has neither while remaining "
         "a fully reconstructible identifier."),
        ("O'Brannigan", 0, 'NAME', 'DOCTOR', 'partial',
         "Same `[a-z'’]+` halt, disguised: on `O'Brannigan` the tail consumes "
         "only the apostrophe, so the rule emits the 2-character span `O'` and "
         "leaves `Brannigan` in the clear while appearing to have fired "
         "correctly."),
    ],
    "adv-0003": [
        ('Mortlake-Grieve, Thaddeus', 0, 'NAME', 'PATIENT', 'miss',
         "`\\bPatient:[ \\t]*` restricts the gap after the colon to spaces and "
         "tabs, so a name wrapped onto the next line is unreachable; the "
         "`Last, First` comma order independently breaks the `(?:[ \\t]_NAME)+` "
         "tail."),
        ('773410', 0, 'ID', 'MEDICALRECORD', 'miss',
         "`\\bMRN` needs the three letters contiguous. The punctuated `M.R.N.` "
         "form inserts dots, so `\\b` + literal fails and the record number is "
         "published verbatim."),
        ('907 44 1183', 0, 'ID', 'SSN', 'miss',
         "`\\b\\d{3}-\\d{2}-\\d{4}\\b` hard-codes hyphen delimiters. "
         "Space-delimited SSNs -- the form a transcriptionist types from "
         "dictation -- match nothing, including the ZIP rule, which needs a "
         "5-digit run."),
        ('907.44.1183A', 0, 'ID', 'HEALTHPLAN', 'miss',
         "A dot-delimited health-plan ID escapes the SSN rule (hyphens) and "
         "IPADDR, which requires three dot-terminated groups and `\\d{1,3}` "
         "last; here the final group is `1183A`."),
        ('84', 0, 'AGE', 'AGE', 'miss',
         "`[-\\s]year[-\\s]old` cannot express the `y/o` abbreviation, which is "
         "how age is written in most real charts. The slash is not in either "
         "character class and `year`/`old` are absent entirely."),
        ('20210314', 0, 'DATE', 'DATE', 'miss',
         "Compact YYYYMMDD has no delimiters for any of the five date patterns "
         "to key on, and the 8-digit run offers no internal `\\b` for the ZIP "
         "rule to latch onto either, so it is missed by the entire pipeline."),
        ('Wexley Valley Hosp.', 0, 'LOCATION', 'HOSPITAL', 'miss',
         "The abbreviation `Hosp.` is not in HOSPITAL's keyword alternation, "
         "and the facility name carries no other listed keyword, so truncation "
         "alone defeats the rule."),
        ('18 Thistledown Way', 0, 'LOCATION', 'STREET', 'miss',
         "STREET's suffix list omits Way, Terrace, Place, Circle, Trail, "
         "Parkway, Highway, Loop, Row and Pike. The house number and "
         "capitalization are textbook; only the thoroughfare type is outside "
         "the closed set."),
        ('2139', 0, 'LOCATION', 'ZIP', 'miss',
         "`\\b\\d{5}(?:-\\d{4})?\\b` fixes the width at 5. A leading-zero-stripped "
         "ZIP -- routine after a spreadsheet round-trip -- is 4 digits and drops "
         "out."),
        ('Ravenshollow', 0, 'LOCATION', 'CITY', 'miss',
         "There is no CITY rule at all. LOCATION coverage is STREET (number + "
         "suffix), ZIP (5 digits) and HOSPITAL (keyword) only, which is the "
         "structural reason LOCATION recall sits at 0.451."),
        ('Ran a crew laying rail ties for the county road department', 0, 'PROFESSION', 'PROFESSION', 'miss',
         "No PROFESSION rule, and the occupation is encoded as a past-tense "
         "narrative clause -- the form dictation actually takes -- with no "
         "nominal job title to match."),
        ('fd7a:0b19:4c2e::118', 0, 'CONTACT', 'IPADDR', 'miss',
         "`\\b(?:\\d{1,3}\\.){3}\\d{1,3}\\b` is IPv4-only. A colon-delimited IPv6 "
         "address for a home gateway shares the category and the disclosure "
         "risk and matches nothing."),
        ('RPM-773410-C7', 0, 'ID', 'DEVICE', 'miss',
         "DEVICE maps to ID, but the only ID patterns are SSN, MRN-labelled "
         "and Acct-labelled digits. An alphanumeric device serial that embeds "
         "the record number is unmatched, so the MRN leaks a second time in a "
         "second shape."),
        ('4471-908823', 0, 'ID', 'IDNUM', 'miss',
         "An unlabelled asset tag has no keyword for the MRN or Acct rules to "
         "anchor on; the 3-2-4 SSN shape does not fit; and the 6-digit "
         "trailing group denies the ZIP rule the `\\b\\d{5}\\b` run it would "
         "otherwise false-positive on."),
        ('B. Fenwicke', 0, 'NAME', 'DOCTOR', 'miss',
         "`\\bsigned by\\s+(?:Dr\\.?\\s+)?(_NAME)` is the only authorship anchor. "
         "`Dictated by` is a different literal, and the initial-plus-surname "
         "form is not an honorific, so the attester's name is published."),
        ('Larkspur', 0, 'NAME', 'PATIENT', 'miss',
         "The honorific alternation is exactly `Mr|Mrs|Ms|Dr|Doctor`. `Mx.` -- "
         "along with Rev., Prof., Sr., Sra., NP, PA-C and CRNA -- is outside "
         "it, so the surname after it is never captured."),
    ],
    "adv-0004": [
        ('nonagenarian', 0, 'AGE', 'AGE', 'miss',
         "The AGE rule requires `(\\d{1,3})`. A lexical age band carries the "
         "same disclosure -- Safe Harbor requires ages over 89 to be aggregated "
         "— while containing no digit for the pattern to capture."),
        ('97th', 0, 'AGE', 'AGE', 'miss',
         "`(\\d{1,3})[-\\s]year[-\\s]old` matches `97` then demands `[-\\s]`; the "
         "ordinal suffix `th` sits there instead. An ordinal age construction "
         "with the word `year` present still misses."),
        ('Duskwater', 0, 'LOCATION', 'CITY', 'miss',
         "There is no CITY rule. LOCATION is covered by STREET (number + "
         "suffix), ZIP (5 digits) and HOSPITAL (keyword) only, so a bare city "
         "name matches nothing -- the structural reason LOCATION recall sits "
         "at 0.451."),
        ('VT', 0, 'LOCATION', 'STATE', 'miss',
         "There is no STATE rule either. A two-letter abbreviation offers no "
         "shape to key on, and the nearest pattern, `\\b\\d{5}(?:-\\d{4})?\\b`, "
         "needs digits."),
        ('Perpetua Quillhaven-Arbogast', 0, 'NAME', 'PATIENT', 'miss',
         "A full name introduced by a narrative clause (`The chart lists her "
         "as`) rather than the `Patient:` label. The three NAME rules are all "
         "anchor-based, so an unanchored full name in prose is structurally "
         "out of reach."),
        ('Birdie', 0, 'NAME', 'PATIENT', 'miss',
         "A self-chosen alias used on signed documents is a NAME under the "
         "project's subtype map, but it appears as a bare capitalized token in "
         "prose -- indistinguishable to a regex from a drug or eponym."),
        ('minded the switchboard', 0, 'PROFESSION', 'PROFESSION', 'miss',
         "No PROFESSION rule exists (recall 0.000), and the trade is named by "
         "the equipment it was worked on rather than by any occupational noun, "
         "so a lexicon patch would not reach it either. The employer is "
         "annotated separately as ORGANIZATION."),
        ('Elmsbury woolen mill', 0, 'LOCATION', 'ORGANIZATION', 'miss',
         "ORGANIZATION maps to LOCATION but only the HOSPITAL keyword rule "
         "could reach it, and an industrial employer has none of the six "
         "care-facility keywords."),
        ('fourteenth of March, 2020', 0, 'DATE', 'DATE', 'miss',
         "Both month-name rules require digits immediately after the month: "
         "the long form needs `\\d{1,2},` and the month-year form needs "
         "`\\s+\\d{4}`, but here a comma follows `March`. A fully written-out "
         "day evades all five patterns."),
        ('02/14', 0, 'DATE', 'DATE', 'miss',
         "`\\d{1,2}/\\d{1,2}/\\d{2,4}` requires three slash-separated components. "
         "A year-less MM/DD -- the dominant shorthand in a visit log -- matches "
         "nothing, yet month and day are the parts Safe Harbor cares about."),
        ('birdie.q', 0, 'NAME', 'USERNAME', 'miss',
         "USERNAME maps to NAME and nothing covers it. The dotted lowercase "
         "token also slips the EMAIL rule, which needs `@`, and the URL rule, "
         "which needs a scheme."),
        ('Pennywhistle', 0, 'NAME', 'PATIENT', 'miss',
         "`(?:Mr|Mrs|Ms|Dr|Doctor)` omits clerical and academic honorifics, so "
         "`Rev. Pennywhistle` -- a named collateral contact, PHI in its own "
         "right -- is never anchored."),
        ('Gallows Hill', 0, 'LOCATION', 'LOCATION-OTHER', 'miss',
         "LOCATION-OTHER maps to LOCATION, but a named landmark that locates "
         "the patient's home has no number, no ZIP and no care keyword, so no "
         "LOCATION rule applies."),
        ('P.Q.-A.', 0, 'NAME', 'DOCTOR', 'miss',
         "`_NAME` requires a `[a-z'’]+` tail, which punctuated initials never "
         "provide, and `/s/` is not the `signed by` literal the authorship "
         "rule keys on."),
    ],
    "adv-0005": [
        ('10022847193', 0, 'ID', 'MEDICALRECORD', 'miss',
         "`\\bMRN[:#]?\\s*(\\d{6,10})\\b` caps the run at 10 digits and then "
         "demands a word boundary. An 11-digit record number is matched by no "
         "backtrack -- every candidate length is followed by another digit -- so "
         "a correctly labelled MRN leaks because it is one digit too long."),
        ('56-860991', 0, 'ID', 'MEDICALRECORD', 'miss',
         "`\\s*(\\d{6,10})` requires the digits contiguous. A hyphen-grouped "
         "record number offers only 2 digits before the break, and the 6-digit "
         "tail also denies the ZIP rule the `\\b\\d{5}\\b` run that would "
         "otherwise cover part of the span."),
        ('906228741', 0, 'ID', 'SSN', 'miss',
         "The SSN rule is the literal 3-2-4 hyphen shape. Nine contiguous "
         "digits -- the form every HL7 and CSV export produces -- matches "
         "nothing, and the digit run has no internal `\\b` for the ZIP rule."),
        ('OP-4471908', 0, 'ID', 'LICENSE', 'miss',
         "LICENSE maps to ID, but the ID rules are SSN plus two "
         "keyword-anchored patterns (`MRN`, `Acct`). A professional or driver "
         "licence number with any other prefix is uncovered."),
        ('V6B 1A1', 0, 'LOCATION', 'ZIP', 'miss',
         "`\\b\\d{5}(?:-\\d{4})?\\b` is US-only. An alphanumeric postal code is a "
         "geographic identifier of equal precision and contains no 5-digit "
         "run."),
        ('Thornfield Health System', 0, 'LOCATION', 'HOSPITAL', 'miss',
         "`Health System` is absent from HOSPITAL's six-keyword alternation, "
         "so the name of the covered entity itself -- the single most "
         "predictable LOCATION in any discharge summary -- is published."),
        ('4-Mar-21', 0, 'DATE', 'DATE', 'miss',
         "`\\b\\d{1,2}\\s+(?:Jan|...)\\s+\\d{2,4}\\b` separates day, month and year "
         "with `\\s+`. The hyphen-delimited DD-Mon-YY variant that spreadsheet "
         "and HL7 exports emit matches on neither side."),
        ('Mar 4 2021', 0, 'DATE', 'DATE', 'miss',
         "Month-first dates are handled only by the two full-month-name rules, "
         "and the long form additionally requires a comma. An abbreviated "
         "month-first date with no comma falls through every one of the five "
         "patterns."),
        ('ninety-one', 0, 'AGE', 'AGE', 'miss',
         "Doubly out of reach: the AGE rule needs a digit, and it needs the "
         "`year-old` frame. A spelled-out age over 89 is the exact case Safe "
         "Harbor singles out for aggregation."),
        ('former ferry pilot on the strait', 0, 'PROFESSION', 'PROFESSION', 'miss',
         "No PROFESSION rule, and the role is identifying precisely because it "
         "is rare and tied to a geography -- a property a pattern cannot "
         "represent."),
        ('412, Ambergate Avenue', 0, 'LOCATION', 'STREET', 'miss',
         "STREET requires `\\d{1,5}\\s+[A-Z]`: a comma between house number and "
         "street name puts a non-whitespace character where `\\s+` must match, "
         "and with the number mandatory the rule cannot fall back to the "
         "street name alone."),
        ('939 555 0172', 0, 'CONTACT', 'PHONE', 'miss',
         "Both phone rules fix their delimiters -- `\\(\\d{3}\\)\\s*\\d{3}-\\d{4}` "
         "keeps a mandatory hyphen even though it tolerates `\\s*` after the "
         "parentheses. Uniform space separation satisfies neither, and the "
         "3-3-4 grouping offers the ZIP rule no 5-digit run."),
        ('939 555 0199', 0, 'CONTACT', 'FAX', 'miss',
         "FAX maps to CONTACT and inherits the same two rigid phone shapes; "
         "the `FAX` label itself anchors nothing, so a records fax number "
         "leaves in the clear."),
        ('Pellingford VA', 0, 'LOCATION', 'HOSPITAL', 'miss',
         "An initialised facility has no keyword from the HOSPITAL "
         "alternation, so the abbreviation style that dominates real referral "
         "language is unmatched."),
        ('Halloran Briscoe', 0, 'NAME', 'DOCTOR', 'partial',
         "`_NAME`'s optional second token is `(?:-[A-Z]?[a-z'’]+)?` -- hyphen "
         "only. A space-separated double-barrelled surname after `Dr.` "
         "captures `Halloran` and publishes `Briscoe`: partial recall counts "
         "this as a true positive while the second half of the name goes out."),
        ('Lundgren-Marsh', 0, 'NAME', 'DOCTOR', 'miss',
         "The authorship rule keys on the literal `signed by`. `Electronically "
         "signed:` -- the string the EHR actually writes -- differs by two "
         "characters and the attending's name is published under it."),
        ('Fenwicke-Dunmore', 0, 'NAME', 'DOCTOR', 'miss',
         "`Authenticated by` is not `signed by`, and `RESIDENT:` is not one of "
         "the five honorifics, so a co-signer attested through any other "
         "workflow verb is unreachable."),
    ],
}


_PLANTED: dict[str, tuple[Planted, ...]] = {
    doc_id: tuple(
        Planted(e, o, PhiCategory(c), s, x, w)
        for e, o, c, s, x, w in rows
    )
    for doc_id, rows in _RAW.items()
}


def _locate(text: str, p: Planted, doc_id: str) -> PhiSpan:
    """The only place an offset is computed. See the module docstring."""
    start = -1
    for _ in range(p.occurrence + 1):
        start = text.find(p.entity, start + 1)
        if start < 0:
            raise ValueError(
                f"{doc_id}: {p.entity!r} has no occurrence #{p.occurrence}"
            )
    if N2C2_SUBTYPE_MAP.get(p.subtype) is not p.category:
        raise ValueError(
            f"{doc_id}: subtype {p.subtype!r} maps to "
            f"{N2C2_SUBTYPE_MAP.get(p.subtype)}, not {p.category}"
        )
    return PhiSpan(start=start, end=start + len(p.entity),
                   category=p.category, text=p.entity, subtype=p.subtype)


def build_notes() -> list[Note]:
    """Resolve every planted entity to a `PhiSpan` and validate the result.

    `Note.__post_init__` checks that each span's text equals the slice its
    offsets name, so this function cannot return a note with a bad offset.
    """
    notes: list[Note] = []
    for doc_id, text in _TEXTS.items():
        spans = sorted(_locate(text, p, doc_id) for p in _PLANTED[doc_id])
        for a, b in zip(spans, spans[1:]):
            if a.overlaps(b):
                raise ValueError(
                    f"{doc_id}: gold spans overlap -- {a.text!r} and {b.text!r}. "
                    f"Nested gold breaks one-to-one matching in _greedy_match."
                )
        notes.append(Note(doc_id=doc_id, text=text, spans=tuple(spans)))
    return notes


ADVERSARIAL_NOTES: list[Note] = build_notes()
SPANS_BY_DOC: dict[str, tuple[PhiSpan, ...]] = {
    n.doc_id: n.spans for n in ADVERSARIAL_NOTES
}
PLANTED_BY_DOC: dict[str, tuple[Planted, ...]] = _PLANTED


def resolved(doc_id: str) -> list[tuple[Planted, PhiSpan]]:
    """Each planted entity paired with the span it resolved to.

    The pairing cannot be recovered from `Note.spans` alone: those are sorted
    by offset and carry no rationale, and two planted entities may share a
    string. Tests and `--check` both read it from here so neither re-derives
    an offset of its own.
    """
    text = _TEXTS[doc_id]
    return [(p, _locate(text, p, doc_id)) for p in _PLANTED[doc_id]]


def baseline_outcome(span: PhiSpan, covered: set[int]) -> tuple[str, int]:
    """Classify one gold span against the characters a redactor covered.

    "partial" is the interesting verdict: the detector fired, span-level
    recall counts a hit, and characters still left the building.
    """
    n = sum(1 for c in range(span.start, span.end) if c in covered)
    if n == 0:
        return "miss", n
    return ("caught" if n == len(span) else "partial"), n


def covered_chars(redactor, text: str) -> set[int]:
    out: set[int] = set()
    for s in redactor.find(text):
        out |= set(range(s.start, s.end))
    return out


def cmd_list() -> int:
    for note in ADVERSARIAL_NOTES:
        print(f"\n{note.doc_id}  ({len(note.text)} chars, {len(note.spans)} gold spans)")
        for s in note.spans:
            print(f"  [{s.start:>5}:{s.end:<5}] {s.category.value:<10} "
                  f"{(s.subtype or ''):<14} {s.text!r}")
    by_cat: dict[str, int] = {}
    for note in ADVERSARIAL_NOTES:
        for s in note.spans:
            by_cat[s.category.value] = by_cat.get(s.category.value, 0) + 1
    total = sum(by_cat.values())
    print(f"\n{len(ADVERSARIAL_NOTES)} notes, {total} gold spans, "
          f"{sum(len(n.text) for n in ADVERSARIAL_NOTES)} chars")
    print("  " + "  ".join(f"{k}={v}" for k, v in sorted(by_cat.items())))
    return 0


def cmd_check() -> int:
    """Assert the baseline still fails the way each entity was designed to.

    This is a regression guard in both directions. A "miss" that starts being
    caught means someone patched a regex and this note no longer tests what it
    claims; a "partial" that becomes a full catch means the boundary bug in
    `_NAME` was fixed and the leak-rate demonstration is gone.
    """
    from deid.redactors.rules import RuleRedactor

    redactor = RuleRedactor()
    failures: list[str] = []
    for note in ADVERSARIAL_NOTES:
        covered = covered_chars(redactor, note.text)
        for p, s in resolved(note.doc_id):
            got, n = baseline_outcome(s, covered)
            mark = "ok  " if got == p.expect else "FAIL"
            if got != p.expect:
                failures.append(
                    f"{note.doc_id} {p.entity!r}: expected {p.expect}, got {got} "
                    f"({n}/{len(s)} chars covered)"
                )
            print(f"  {mark} [{p.category.value:<10}] {got:<7} "
                  f"{n/len(s):>4.0%}  {p.entity!r}")
    print(f"\n{sum(len(n.spans) for n in ADVERSARIAL_NOTES)} spans checked, "
          f"{len(failures)} unexpected")
    for f in failures:
        print("  MISMATCH:", f)
    return 1 if failures else 0


def cmd_score(args) -> int:
    from deid.eval import evaluate

    if args.redactor == "rules":
        from deid.redactors.rules import RuleRedactor
        redactor = RuleRedactor()
    elif args.redactor == "transformer":
        if not args.model_dir:
            raise SystemExit("--redactor transformer requires --model-dir")
        from deid.redactors.transformer import TransformerRedactor
        redactor = TransformerRedactor(args.model_dir,
                                       o_logit_penalty=args.o_logit_penalty)
    else:
        raise SystemExit(
            "--redactor llm is not available here: it transmits note text "
            "off-machine. Use `python -m deid.cli eval` for the LLM arm."
        )

    report = evaluate(redactor, ADVERSARIAL_NOTES)
    payload = {"redactor": redactor.name, "data": "adversarial", **report.as_dict()}
    print(json.dumps(payload, indent=2))
    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2) + "\n")
        print(f"\nwrote {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="assert each planted entity still evades the baseline")
    ap.add_argument("--score", action="store_true",
                    help="run a redactor over the set through deid.eval.evaluate")
    ap.add_argument("--redactor", default="rules",
                    choices=["rules", "transformer", "llm"])
    ap.add_argument("--model-dir", default=None)
    ap.add_argument("--o-logit-penalty", type=float, default=0.0)
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args(argv)

    if args.check:
        return cmd_check()
    if args.score:
        return cmd_score(args)
    return cmd_list()


if __name__ == "__main__":
    sys.exit(main())
