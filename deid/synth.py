"""Synthetic clinical notes with gold-standard PHI spans.

Why this exists
---------------
The n2c2 corpus sits behind a Data Use Agreement that forbids redistributing
it — it can never be committed to this repo, and approval takes weeks. So the
evaluation harness is developed and debugged against notes we generate, where
we know every PHI offset by construction because we placed it.

This is not a substitute for the real benchmark. Synthetic prose is easier than
real clinical prose: no typos, no abbreviations, no transcription noise. Scores
here are an *upper bound* on real-corpus performance. Treat them as a smoke
test for the harness, not as a result.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from .types import Note, PhiCategory, PhiSpan

FIRST_NAMES = [
    "Nandith", "Aarav", "Marcus", "Elena", "Priya", "Thomas", "Chen", "Amara",
    "Rosa", "Yusuf", "Ingrid", "Kofi", "Lucia", "Dmitri", "Fatima", "Soren",
    "Wei", "Isabel", "Tariq", "Nadia", "Emeka", "Astrid", "Rafael", "Hana",
]
LAST_NAMES = [
    "Reddy", "Okonkwo", "Vasquez", "Lindqvist", "Nakamura", "Aldridge",
    "Bergström", "Castellanos", "Mwangi", "Petrov", "Silva", "Whitfield",
    "Haddad", "Novak", "Ferreira", "Osei", "Kowalski", "Rahman", "Duarte",
]
DOCTOR_LAST = [
    "Halloway", "Ferreira", "Bhatt", "Lindgren", "Oyelaran", "Castellano",
    "Werner", "Ngozi", "Salcedo", "Marchetti", "Abrahamsen", "Thorne",
]
HOSPITALS = [
    "St. Mary's Regional", "Beth Israel Deaconess", "Cedar Hollow General",
    "Lakeview Methodist", "Mercy General", "Northfield Memorial",
    "Presbyterian Medical Center", "Ravenswood Community Hospital",
]
CITIES = [
    "Hyderabad", "Northfield", "Cedar Rapids", "Brookline", "Ashford",
    "Fairhaven", "Millbrook", "Kingsport", "Danvers", "Winslow",
]
STATES = ["MA", "IA", "OH", "TX", "OR", "NC", "MN", "AZ"]
STREETS = [
    "142 Alder Lane", "88 Whitmore Street", "1401 Kensington Ave",
    "27 Bellevue Court", "990 Hartwell Road", "16 Pinecrest Drive",
]
PROFESSIONS = [
    "welder", "schoolteacher", "long-haul trucker", "commercial fisherman",
    "textile mill worker", "accountant", "roofer", "flight attendant",
]
MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
COMPLAINTS = [
    ("substernal chest pain", "radiating to the left arm"),
    ("progressive dyspnea on exertion", "worse when supine"),
    ("intermittent palpitations", "unrelated to activity"),
    ("epigastric burning", "worse after meals"),
    ("bilateral lower-extremity edema", "pitting to mid-shin"),
]
MEDS = [
    "metformin 500 mg BID", "lisinopril 10 mg daily", "atorvastatin 40 mg qHS",
    "aspirin 81 mg daily", "carvedilol 6.25 mg BID", "furosemide 20 mg daily",
]


@dataclass(frozen=True)
class Vocab:
    """The PHI values the generator draws from.

    Kept separate from the templates so we can hold the templates fixed and
    swap the vocabulary. That distinction is the whole point of `HELDOUT`
    below: a model that memorised "Hyderabad is a CITY" scores perfectly on a
    test set drawn from the same ten cities, and learns nothing. Swapping the
    vocabulary asks the only question that matters — did it learn the *context*
    a city appears in?
    """

    first_names: list[str]
    last_names: list[str]
    doctor_last: list[str]
    hospitals: list[str]
    cities: list[str]
    states: list[str]
    streets: list[str]
    professions: list[str]


DEFAULT = Vocab(FIRST_NAMES, LAST_NAMES, DOCTOR_LAST, HOSPITALS,
                CITIES, STATES, STREETS, PROFESSIONS)

# Entirely disjoint from DEFAULT. Nothing here was ever seen in training.
HELDOUT = Vocab(
    first_names=[
        "Ingeborg", "Casimir", "Perpetua", "Anselm", "Zerlina", "Bartholomew",
        "Clementine", "Fionnuala", "Ignatius", "Rosalind", "Thaddeus", "Wilhelmina",
    ],
    last_names=[
        "Ashdown", "Fairweather", "Greengrass", "Halloran", "Kettleburn",
        "Larkspur", "Mortimer", "Pennyworth", "Quillfeather", "Ravensworth",
    ],
    doctor_last=[
        "Blackwood", "Coriander", "Everhart", "Fenwick", "Grimsby", "Hawthorne",
    ],
    hospitals=[
        "Thornfield General", "Wexley Memorial", "Ashgrove Regional",
        "Bramblewood Clinic", "Copperfield Medical Center",
    ],
    cities=["Ravenshollow", "Duskwater", "Elmsbury", "Pellingford", "Wraithmoor"],
    states=["VT", "NM", "WY", "ID", "DE"],
    streets=[
        "73 Quillon Way", "506 Marrowbone Street", "18 Thistledown Road",
        "241 Ambergate Avenue",
    ],
    professions=[
        "farrier", "cartographer", "lighthouse keeper", "glassblower",
        "stonemason", "millwright",
    ],
)


@dataclass
class _Builder:
    """Accumulates text while recording the exact offset of every PHI value.

    Every PHI string in the note goes through `phi()`, which is the only place
    an offset is ever computed. That is deliberate: an offset bug here would
    silently poison every metric in the project, and one code path is far
    easier to keep correct than offsets scattered through templates.
    """

    parts: list[str]
    spans: list[PhiSpan]
    length: int

    def __init__(self) -> None:
        self.parts, self.spans, self.length = [], [], 0

    def lit(self, s: str) -> "_Builder":
        self.parts.append(s)
        self.length += len(s)
        return self

    def phi(self, value: str, category: PhiCategory, subtype: str) -> "_Builder":
        start = self.length
        self.parts.append(value)
        self.length += len(value)
        self.spans.append(
            PhiSpan(start=start, end=self.length, category=category,
                    text=value, subtype=subtype)
        )
        return self

    def build(self, doc_id: str) -> Note:
        return Note(doc_id=doc_id, text="".join(self.parts),
                    spans=tuple(sorted(self.spans)))


def _date(rng: random.Random) -> tuple[str, str]:
    """Return a date string in one of several real-world formats.

    Format variety is the point. A regex tuned to MM/DD/YYYY silently misses
    "March 3, 2019" and "3-Mar-19", and that miss is a HIPAA violation.
    """
    y, m, d = rng.randint(2015, 2023), rng.randint(1, 12), rng.randint(1, 28)
    style = rng.randint(0, 4)
    if style == 0:
        return f"{m:02d}/{d:02d}/{y}", "numeric"
    if style == 1:
        return f"{MONTHS[m - 1]} {d}, {y}", "long"
    if style == 2:
        return f"{d} {MONTHS[m - 1][:3]} {str(y)[2:]}", "short"
    if style == 3:
        return f"{y}-{m:02d}-{d:02d}", "iso"
    return f"{MONTHS[m - 1]} {y}", "month-year"


_TENS = {2: "twenty", 3: "thirty", 4: "forty", 5: "fifty",
         6: "sixty", 7: "seventy", 8: "eighty", 9: "ninety"}
_UNITS = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
# Latinate bands, only for the decades where clinicians actually write them.
# Below sixty the decade form ("in their 40s") is used instead; nobody charts
# a "quinquagenarian".
_AGE_BANDS = {6: "sexagenarian", 7: "septuagenarian", 8: "octogenarian"}


def _number_words(n: int) -> str:
    """Spell out 20-99. This generator never produces an age below 28."""
    tens, unit = divmod(n, 10)
    return f"{_TENS[tens]}-{_UNITS[unit]}" if unit else _TENS[tens]


def _hpi_opening(rng: random.Random, profession: str, complaint: str,
                 qualifier: str) -> tuple[list[tuple[str, str]], str]:
    """Segments for the HPI's opening clause, as (kind, value) pairs.

    `kind` is "lit", "age" or "prof"; the caller feeds each through
    `_Builder.lit()` or `.phi()`, so this stays off the offset path.

    Eight openings, varying the *frame* and not just the age format. That
    distinction is the whole reason this function exists. An earlier version
    varied six age formats inside one fixed frame -- "The patient is a ___" --
    and the model learned all six formats and still missed `91` in
    `pt is 91 years old, retired kill-floor hand`: AGE recall 0.960 on these
    templates against 0.167 on dictation-style prose. Varying the frames
    instead, at the same training budget, took that 0.167 to 0.833. The format
    was never the cue; the frame was. So these vary in capitalization, in
    age/profession order, and in whether there is a finite verb at all.
    """
    n = rng.randint(28, 89)
    words = _number_words(n)
    band = _AGE_BANDS.get(n // 10)
    decade = f"{n // 10}0s"
    tail = f" who presented with {complaint}, {qualifier}. "
    style = rng.randint(0, 7)

    if style == 0:
        return [("lit", "The patient is a "), ("age", str(n)),
                ("lit", "-year-old "), ("prof", profession),
                ("lit", tail)], "canonical"
    if style == 1:
        return [("lit", "pt is "), ("age", str(n)),
                ("lit", " years old, a "), ("prof", profession),
                ("lit", f", and presented with {complaint}, {qualifier}. ")], "dictated"
    if style == 2:
        return [("age", str(n)), ("lit", " y/o "), ("prof", profession),
                ("lit", f", presenting with {complaint}, {qualifier}. ")], "telegraphic"
    if style == 3:
        return [("lit", "This is a "), ("age", words), ("lit", "-year-old "),
                ("prof", profession), ("lit", tail)], "written-out"
    if style == 4:
        return [("lit", "HPI: "), ("age", str(n)), ("lit", " y/o "),
                ("prof", profession),
                ("lit", f" with {complaint}, {qualifier}. ")], "headed"
    if style == 5:
        return [("lit", "The patient, a "), ("prof", profession),
                ("lit", " aged "), ("age", str(n)),
                ("lit", f", presented with {complaint}, {qualifier}. ")], "prof-first"
    if style == 6 and band is not None:
        return [("lit", "An otherwise well "), ("age", band), ("lit", " "),
                ("prof", profession),
                ("lit", f", brought in with {complaint}, {qualifier}. ")], "band"
    return [("lit", "Patient is in their "), ("age", decade),
            ("lit", ", works as a "), ("prof", profession),
            ("lit", f", and presented with {complaint}, {qualifier}. ")], "decade"


def generate_note(rng: random.Random, doc_id: str, vocab: Vocab = DEFAULT) -> Note:
    b = _Builder()

    first, last = rng.choice(vocab.first_names), rng.choice(vocab.last_names)
    patient = f"{first} {last}"
    # Annotate the surname only, not the honorific — this is the i2b2 convention,
    # and it keeps the rule baseline's capture groups comparable to gold.
    doctor = rng.choice(vocab.doctor_last)
    hospital = rng.choice(vocab.hospitals)
    city, state = rng.choice(vocab.cities), rng.choice(vocab.states)
    mrn = f"{rng.randint(1000000, 9999999)}"
    ssn = f"{rng.randint(100, 899)}-{rng.randint(10, 99)}-{rng.randint(1000, 9999)}"
    phone = f"({rng.randint(200, 989)}) {rng.randint(200, 999)}-{rng.randint(1000, 9999)}"
    email = f"{first.lower()}.{last.lower()}@example-health.org"
    profession = rng.choice(vocab.professions)
    admit, _ = _date(rng)
    followup, _ = _date(rng)
    dob, _ = _date(rng)
    complaint, qualifier = rng.choice(COMPLAINTS)
    med = rng.choice(MEDS)
    opening, _opening_style = _hpi_opening(rng, profession, complaint, qualifier)

    # --- Header -------------------------------------------------------------
    b.lit("ADMISSION NOTE\n")
    b.lit("Facility: ").phi(hospital, PhiCategory.LOCATION, "HOSPITAL")
    b.lit(", ").phi(city, PhiCategory.LOCATION, "CITY")
    b.lit(", ").phi(state, PhiCategory.LOCATION, "STATE").lit("\n")
    b.lit("Patient: ").phi(patient, PhiCategory.NAME, "PATIENT")
    b.lit("   MRN: ").phi(mrn, PhiCategory.ID, "MEDICALRECORD").lit("\n")
    b.lit("DOB: ").phi(dob, PhiCategory.DATE, "DATE")
    b.lit("   SSN: ").phi(ssn, PhiCategory.ID, "SSN").lit("\n")
    b.lit("Admitted: ").phi(admit, PhiCategory.DATE, "DATE").lit("\n\n")

    # --- HPI ----------------------------------------------------------------
    # Names appear here in prose, unmarked by any surrounding delimiter. This
    # is precisely what a rule-based redactor cannot reach.
    b.lit("HISTORY OF PRESENT ILLNESS\n")
    for kind, value in opening:
        if kind == "lit":
            b.lit(value)
        elif kind == "age":
            b.phi(value, PhiCategory.AGE, "AGE")
        else:
            b.phi(value, PhiCategory.PROFESSION, "PROFESSION")
    male = rng.random() < 0.5
    honorific, subj, obj = ("Mr. ", "He", "him") if male else ("Ms. ", "She", "her")
    b.lit(honorific)
    b.phi(last, PhiCategory.NAME, "PATIENT")
    b.lit(" reports the symptoms began approximately three days prior to ")
    b.lit(f"admission. {subj} was last seen at ")
    b.phi(hospital, PhiCategory.LOCATION, "HOSPITAL")
    b.lit(" on ").phi(followup, PhiCategory.DATE, "DATE")
    b.lit(" by Dr. ").phi(doctor, PhiCategory.NAME, "DOCTOR")
    b.lit(f", who started {obj} on {med}. ")
    # A bare surname in running prose, with no honorific and no field label to
    # anchor on. No regex can reach this without a list of every surname on
    # earth; it is the single clearest demonstration of why rules are not enough.
    b.phi(last, PhiCategory.NAME, "PATIENT")
    b.lit(f" has not been compliant with {obj} medication regimen.\n\n")

    # --- Social -------------------------------------------------------------
    b.lit("SOCIAL HISTORY\n")
    b.lit("Lives at ").phi(rng.choice(vocab.streets), PhiCategory.LOCATION, "STREET")
    b.lit(" in ").phi(city, PhiCategory.LOCATION, "CITY")
    b.lit(". Reachable at ").phi(phone, PhiCategory.CONTACT, "PHONE")
    b.lit(" or ").phi(email, PhiCategory.CONTACT, "EMAIL").lit(".\n\n")

    # --- Plan ---------------------------------------------------------------
    b.lit("ASSESSMENT AND PLAN\n")
    b.lit(f"Continue {med}. Obtain serial troponins and a 12-lead ECG. ")
    b.lit("Follow up with Dr. ").phi(doctor, PhiCategory.NAME, "DOCTOR")
    b.lit(" on ").phi(followup, PhiCategory.DATE, "DATE").lit(".\n\n")
    b.lit("Electronically signed by Dr. ")
    b.phi(doctor, PhiCategory.NAME, "DOCTOR")
    b.lit(", ").phi(hospital, PhiCategory.LOCATION, "HOSPITAL").lit("\n")

    return b.build(doc_id)


def generate_corpus(n: int = 200, seed: int = 20260709,
                    vocab: Vocab = DEFAULT) -> list[Note]:
    """Deterministic corpus. The seed is fixed so benchmark runs are comparable.

    Note this is a *prefix sequence*: the first 200 notes of `generate_corpus(600)`
    are exactly `generate_corpus(200)`. Convenient, and a loaded gun — training
    and evaluation must pass the same `n`, or the eval's test split lands inside
    the training set. See tests/test_no_contamination.py.
    """
    rng = random.Random(seed)
    return [generate_note(rng, f"synth-{i:04d}", vocab) for i in range(n)]


def generate_heldout_corpus(n: int = 50, seed: int = 31337) -> list[Note]:
    """Fresh notes whose PHI *strings* the model has never seen.

    Same templates, disjoint vocabulary. Scoring on this instead of the in-vocab
    test set separates "learned that a surname follows an honorific" from
    "memorised the nineteen surnames in LAST_NAMES".
    """
    return [
        Note(doc_id=f"ood-{i:04d}", text=nt.text, spans=nt.spans)
        for i, nt in enumerate(generate_corpus(n, seed=seed, vocab=HELDOUT))
    ]


def split(notes: list[Note], train_frac: float = 0.6, dev_frac: float = 0.15
          ) -> tuple[list[Note], list[Note], list[Note]]:
    """Deterministic train/dev/test split. Never shuffle this with a fresh seed."""
    n_train = int(len(notes) * train_frac)
    n_dev = int(len(notes) * dev_frac)
    return notes[:n_train], notes[n_train : n_train + n_dev], notes[n_train + n_dev :]
