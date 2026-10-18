# Secure Patient Intake

**A well-built rule-based PHI redactor leaves 21.28% of protected health information exposed. A fine-tuned token classifier leaves 0.04%, at 100× the speed and zero cost, without any note leaving the machine. On a third set written specifically to attack both, the baseline leaks 98.27% and the model leaks 11.68% — the number that says what the other two are worth.**

Hospitals are sitting on enormous quantities of clinical text and cannot use language models on any of it, because the text identifies patients. Before a note can go near a hosted model, the identifiers have to come out — and someone has to *prove* they came out. That proof is the hard part, and it is what this repository is about.

---

## The result

Same 50 held-out notes, same 1,150 gold spans, same scorer. **Only the detector was swapped.** The evaluation harness, the `PhiSpan` dataclass, and the metrics were not touched between runs — which is the only reason the comparison means anything.

| Category | rules | fine-tuned | Δ recall |
|---|---|---|---|
| CONTACT | 1.000 | 1.000 | · |
| DATE | 1.000 | 1.000 | · |
| ID | 1.000 | 1.000 | · |
| **AGE** | 0.820 ⚠ | **0.980** | **+0.160** |
| **LOCATION** | 0.451 ⚠ | **1.000** | **+0.549** |
| **NAME** | 0.833 ⚠ | **1.000** | **+0.167** |
| **PROFESSION** | 0.000 ⚠ | **1.000** | **+1.000** |

| | rules | fine-tuned |
|---|---|---|
| **Leak rate** | **21.28%** | **0.04%** |
| F2 (recall-weighted) | 0.772 | 0.999 |
| Precision (partial) | 0.944 | 0.998 |
| Spans never detected | 301 / 1150 | 0 / 1150 |
| Latency | 0.2 ms | 35.9 ms |

The baseline's failures are not evenly spread. It has **perfect** recall where a category has one canonical **format**, **partial** recall where a category has many surface forms, and **catastrophic** recall on everything that requires knowing what a word **means**.

An SSN always looks like `123-45-6789`, so a regex catches it every time. Age is the instructive middle case: the baseline implements four forms (`58-year-old`, `58 y/o`, `58 years old`, `aged 58`) and still misses `eighty-five` and `octogenarian`, which is why AGE sits at 0.820 and not 1.000. Every form a pattern can reach is implemented; the remainder needs to know what a word means. But no pattern can tell you that `Whitfield` in *"Whitfield has not been compliant with her medication"* is a surname, while `Furosemide` in the next sentence is not. No pattern knows that `Hyderabad` is a city. No pattern knows that `schoolteacher` is an occupation, which HIPAA Safe Harbor treats as an identifier.

Those are questions about language, which is why the answer is a language model.

### The 100% is suspicious, so we checked it

A perfect score should be treated as a bug report until proven otherwise. The synthetic generator draws PHI from fixed lists — ten cities, eight professions — so **every city and profession in the test set appeared verbatim in training** (100% string overlap; `NAME` 47%). A model that memorised a lexicon would score exactly like a model that understood language.

So we built a **held-out-vocabulary** test set: identical templates, PHI values the model has never seen — *Ravenshollow*, *Pennyworth*, *lighthouse keeper*. Nothing in it overlaps the training vocabulary.

| Category | rules | fine-tuned | precision |
|---|---|---|---|
| AGE | 0.880 ⚠ | **0.940** | 0.979 |
| LOCATION | 0.549 ⚠ | **1.000** | 1.000 |
| NAME | 0.833 ⚠ | **1.000** | 1.000 |
| PROFESSION | 0.000 ⚠ | **1.000** | 0.909 |
| **Leak rate** | **15.67%** | **0.06%** | |

Recall holds at 1.000 on words it has never encountered, except `AGE` at 0.940. Precision slips a little — 0.909 on `PROFESSION`, 0.979 on `AGE` — because it over-redacts unfamiliar occupations and age expressions, which is the *correct* direction of error here: a false positive is a slightly duller note, a false negative is a disclosure.

That is generalization, not lookup. Reproduce it with `--data heldout`; results live in `results/heldout/`.

### The templates were suspicious too, so we attacked them

Swapping the vocabulary answers *"did it memorise a lexicon?"* and leaves a harder question open. The notes still say `Facility: ___` and `The patient is a ___`, and a model can lean on those positions without understanding a word.

So there is a third set: five notes written as rushed dictation — all-caps transcription, `Patient Name:` and `PATIENT:` headers, `Last, First` order, `M.R.N.` with dots, PHI buried in running prose — carrying **74 annotated spans placed to fall through specific regex gaps**. It lives in `scripts/generate_adversarial_spans.py` and scores through the same harness as everything else.

| | rules | fine-tuned |
|---|---|---|
| **Leak rate** | **98.27%** | **11.68%** |
| Spans never detected | 68 / 74 | **1 / 74** |
| Precision (partial) | 1.000 | 0.516 |

**The thesis holds.** 98.27% → 11.68% is the argument of this repository surviving a distribution it was never trained on: recall of 1.000 on `ID`, 0.941 on `LOCATION`, 0.889 on `DATE`, 0.833 on `AGE` and 0.800 on both `NAME` and `PROFESSION`, in notes whose formatting shares almost nothing with the training templates. Exactly one span of seventy-four is missed outright — `P.Q.-A.`, a set of punctuated initials.

**But the 0.04% does not travel, and the reason is instructive.** Precision falls from 0.998 to 0.516: heavy over-redaction on unfamiliar prose, the right direction of error but a long way from the templated figure. The residual 11.68% is now almost entirely *boundary* error rather than missed entities — `stripping tobacco at the leaf barn` is covered for 9 of 34 characters, `Ran a crew laying rail ties for the county road department` for 31 of 58. The model finds the PHI and cannot agree with the annotator where it ends.

### What the frame experiment showed

This set earned its keep by being wrong about why. The first version of the generator emitted one age frame, `The patient is a ___`, and `AGE` recall was **1.000 on the templates and 0.000 here** — every one of `91 years old`, `aged 72`, `84 y/o`, `nonagenarian`, `97th`, `ninety-one` missed.

The obvious fix was more age *formats*. It barely worked: six formats took adversarial `AGE` recall from 0.000 to **0.167**, while templated recall sat at 0.960. The model had learned all six formats inside the one frame it was given.

So the *frames* were varied instead — eight openings differing in capitalization, word order, finite verb, and whether the word "patient" appears at all (`pt is 58 years old, a welder`; `58 y/o welder, presenting with`; `HPI: 58 y/o welder with`). Same six formats, same training budget:

| `AGE` recall | templates | adversarial |
|---|---|---|
| one frame, one format | 1.000 | 0.000 |
| one frame, six formats | 0.960 | 0.167 |
| **eight frames, six formats** | **0.980** | **0.833** |

The cue was never the format. It was the frame — and nothing in the templated or held-out-vocabulary scores could have told us that, because both hold the frames fixed.

Writing notes whose only purpose was to break the thing also drove the one honest fix to the baseline: three age forms it missed (`58 y/o`, `58 years old`, `aged 58`) were plain pattern-matching, so `rules.py` was extended to cover them rather than left weak to flatter the model. Those three spans stay in the set, recorded as catches, guarding the new patterns.

```bash
python scripts/generate_adversarial_spans.py --check     # assert every span's outcome
python scripts/generate_adversarial_spans.py --score \
    --redactor transformer --model-dir models/deid-roberta
```

> **All three numbers are measured on synthetic notes** (see [Data](#data)). The HPI opening varies eight ways, but the header block does not vary at all, so the model can still lean on positional cues like `Facility: ___` that real clinical prose varies freely. Real notes have typos, abbreviations, and transcription noise. Treat 0.04% as evidence that *the pipeline and the harness are sound*, and 11.68% as the closest thing here to a production estimate. The n2c2 corpus is the real exam.

---

## Why leak rate, and not F1

De-identification is not a symmetric classification problem, and scoring it like one hides the thing you actually care about.

- A **false negative** is a disclosure of protected health information.
- A **false positive** is a slightly less useful clinical note.

These are not equally bad. F1 weights precision and recall equally, so it will happily tell you a system is excellent while it publishes surnames. This project reports F1 anyway — the literature does, and you need a comparable figure — but it leads with two numbers that cannot lie to you.

**Leak rate** — the fraction of gold PHI **characters** left un-redacted, ignoring category.

Character-level, not span-level, and that distinction is load-bearing. Span-level recall counts a prediction as correct if it merely *overlaps* the gold span. Under that rule, detecting `Nandith` inside the gold span `Nandith Reddy` scores as a hit — while `Reddy` goes out the door. Only a character metric notices. There is a test for exactly this:

```python
def test_partial_redaction_is_a_leak():
    """Gold 'Nandith Reddy' [0,13); we redact only 'Nandith' [0,7)."""
    score((S(0, 13),), (S(0, 7),), 13, r)
    assert r.partial.tp == 1                       # span-level: "detected"
    assert r.leak_rate == pytest.approx(6 / 13)    # six characters published
```

**F2** — the F-score with recall weighted twice as heavily as precision. The deployment-relevant summary, for the same reason.

Category is deliberately ignored in the leak rate. Redacting a name but labelling it a `DATE` still protects the patient. Getting the label wrong is a quality problem; missing the span is a breach.

---

## Architecture: the boundary is the product

```
┌─ this machine ──────────────────────────┐       ┌─ hosted model ───┐
│                                         │  🛡    │                  │
│  clinical note ─▶ local detector ─▶ redacted ──▶ │  claude-opus-4-8 │
│                        │                │       │                  │
│                        ▼                │       └──────────────────┘
│                 hash-chained audit log  │
└─────────────────────────────────────────┘
```

`EgressGuard` refuses to transmit anything until a **local** detector confirms no PHI remains. It fails closed: a detector that crashes blocks the send, because a monitoring outage must never become a disclosure. It also refuses, at construction, to use a detector that itself transmits off-machine — otherwise you would be shipping the very text you are protecting to the very service you are guarding against.

```python
guard = EgressGuard(detector=RuleRedactor(), audit=AuditLog("audit.jsonl"))
guard.send(raw_note, destination="anthropic:claude-opus-4-8", fn=summarize)
# PhiLeakBlocked: 3 PHI span(s) remain (1×DATE, 1×ID, 1×NAME).
```

The audit log records the SHA-256 of what crossed, never the payload. Writing the payload would make the audit log the largest PHI repository in the system.

---

## The three redactors

All three scored on the same 50 held-out notes, same 1,150 gold spans:

| | runs where | leak rate | precision | latency | cost | hallucinated |
|---|---|---|---|---|---|---|
| `rules` | locally | 21.28% | 0.944 | 0.2 ms | free | 0 |
| `llm` (Claude Opus 4.8) † | **off-machine** | **0.00%** | 0.953 | 4,536 ms | $0.76 | 0 |
| `transformer` (RoBERTa) | **locally** | **0.04%** | **0.998** | 36 ms | free | 0 |

† **The LLM row was measured on the previous corpus generation**, before `AGE` gained six surface forms. Re-running it transmits note text off-machine and costs money, so the figure stands as recorded and is not strictly comparable to the two rows above it. Treat it as evidence that the semantic categories are learnable, which is all it was ever for.

This is the result that makes the architecture argument concrete. **The local fine-tuned model is level with Claude Opus on recall — 0.04% against 0.00% leak — and ahead of it on precision (0.998 vs 0.953), at roughly 125× the speed, zero marginal cost, and without a single byte of note text leaving the machine.** The caveat in the footnote applies: the two were measured on different corpus generations.

Read that carefully, because the honest reading is narrower than the triumphant one:

- The LLM arm is **validation, not a competitor.** It confirms that the semantic categories rules fail on are genuinely learnable — so the baseline's 21.28% is a solvable problem, not an inherent ceiling. Opus solving it the expensive way is what tells you the local model solving it the cheap way isn't a fluke.
- **On this synthetic set, local wins. On real clinical prose it might not.** A 125M-parameter model fine-tuned on templated notes will lean on positional regularities that Opus, with far broader priors, would shrug off on messy real text. The precision gap could easily reverse on n2c2. Do not read "local beats Opus" as a universal claim — read it as "on this benchmark, the local path gives up nothing, and that is the path that keeps data on-premise."
- **Opus hallucinated zero spans.** I predicted it might invent replacement names; on clean synthetic data it did not. That prediction is still worth testing on real notes, where it is more likely to surface — the hallucination counter is built and waiting.

The transformer is the production path, and the reason is architectural rather than about accuracy: it runs on your machine, so no note ever leaves.

It is a RoBERTa token classifier over BIO tags, decoded back to character offsets via the tokenizer's offset mapping. Two levers push it toward over-redaction, because missing a name is a breach and over-redacting is an annoyance:

- **Training:** the `O` class is down-weighted in the loss (`--o-weight 0.3`), so predicting "not PHI" is cheap to get wrong and expensive to get right.
- **Inference:** `--o-logit-penalty` subtracts from the `O` logit before argmax, moving the operating point toward recall **without retraining**. Useful when someone asks for a lower leak rate on a Friday afternoon.

**Why RoBERTa and not DeBERTa-v3.** DeBERTa-v3 produces `NaN` losses under Apple's MPS backend (torch 2.13 / transformers 5.13). The weights corrupt during the first epoch, every token then argmaxes to `O`, and PHI token recall reads exactly `0.000` — a symptom that looks like an undertrained model and is actually a numerically broken one. Whether it trains cleanly on CPU is *unverified*: that probe was still running after 15 minutes, against 24 seconds for RoBERTa on MPS, and was abandoned. RoBERTa trains cleanly and fast, so it is the portable default. The choice lives in `deid/config.py` and is overridable:

```bash
DEID_BASE_MODEL=microsoft/deberta-v3-base python -m deid.train --out models/x --use-cpu
```

The `llm` redactor exists **only to measure** whether a hosted model can do this job. It transmits raw note text, so it is never on the serving path: `EgressGuard` rejects it at construction, the service never imports it, and the CLI refuses to run it without `--i-understand-this-transmits-phi`.

It asks the model for PHI **verbatim**, not for character offsets — models cannot count characters, and an off-by-three offset redacts the wrong text. We locate the strings ourselves. This has a useful side effect: a returned string that appears nowhere in the note was invented, and we count those. **Hallucination rate is something nobody reports for de-identification**, and it matters — a redactor that invents spans will eventually redact real clinical content.

Evaluation sweeps go through the Batch API at half price. An eval has no latency requirement and is embarrassingly parallel; that is what batching is for.

---

## Data

**The n2c2 corpus is not in this repository and never will be.** Its Data Use Agreement states that *"under no circumstances are copies of any data files to be provided to additional individuals or posted to other websites, including GitHub."* `data/` is gitignored, and the loader validates every gold offset against the note text rather than trusting the file.

To use the real benchmark:

1. Register at [portal.dbmi.hms.harvard.edu](https://portal.dbmi.hms.harvard.edu/)
2. Request the **n2c2 2014 De-identification** track and sign the DUA
3. Unpack the XML somewhere under `data/`

Everything here runs **today without it**, against a deterministic synthetic corpus whose gold spans are known by construction. That is what the harness was developed against — you do not want to debug character-offset alignment on data you are not allowed to paste into a GitHub issue.

The n2c2 records contain **surrogate** identifiers: the real PHI was replaced with realistic fakes, which is what makes the corpus usable as a benchmark. Running them through an API is therefore not a HIPAA disclosure. The DUA restricts it independently. Read yours.

---

## Quickstart

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'

python -m deid.cli demo                     # redact one note, see exactly what leaked
python -m deid.cli eval --redactor rules --json-out results/rules.json
pytest                                      # 197 tests, mostly about metric honesty
```

Run the app:

```bash
uvicorn service.main:app --port 8000        # terminal 1
cd frontend && npm install && npm run dev   # terminal 2 → localhost:5173
```

Sign in as `clinician / clinician123` or `admin / admin123`.

Train the local model (~3 minutes on Apple Silicon):

```bash
pip install -e '.[ml]'
python -m deid.train --out models/deid-roberta --n-synth 200 --epochs 6
python -m deid.cli eval --redactor transformer --model-dir models/deid-roberta \
  --n-synth 200 --json-out results/transformer.json

# The honest test: PHI strings the model has never seen.
python -m deid.cli eval --redactor transformer --model-dir models/deid-roberta \
  --data heldout --json-out results/heldout/transformer_heldout.json

python scripts/compare.py results/rules.json results/transformer.json
```

> **`--n-synth` must match between training and evaluation.** `generate_corpus(n)` is a
> deterministic prefix sequence, so training on 600 and evaluating on 200 puts the
> *entire* test split inside the training set and produces a spectacular, worthless
> result. `tests/test_no_contamination.py` asserts this rather than trusting anyone
> to remember it.

Score the LLM arm (this transmits note text — read the warning it prints):

```bash
pip install -e '.[llm]'
export ANTHROPIC_API_KEY=...
python -m deid.cli eval --redactor llm --i-understand-this-transmits-phi \
  --json-out results/llm.json
```

Any report dropped into `results/` appears in the dashboard's comparison chart automatically.

---

## The intake app

The original assignment was a patient-intake CRUD app. It is still here, rebuilt, because it is where de-identification actually gets used — and because its bugs were instructive.

**The audit log never worked.** `auditLog.ts` appended `'\\n'`, which in a normal TypeScript string is an escaped backslash followed by the letter `n` — two literal characters, not a line break. The file accumulated roughly 130 records on one unparseable line, and `wc -l` reported zero. The project's headline compliance feature had never once produced a readable record.

It is now newline-delimited JSON, and each entry carries the SHA-256 of the entry before it. Altering or deleting any record breaks the chain from that point on, and `verify()` reports exactly where.

**Nobody could decide who sees an SSN.** The README said clinicians. The backend gave it to admins and masked it for clinicians. The frontend did the opposite of the backend. In practice nobody ever saw one, and the clinician edit form was unusable because it pre-filled with `***-**-1441` and then failed its own nine-digit validation. Worse, `PUT` had no server-side validation at all, so a direct API call could permanently overwrite a stored SSN with the mask string.

That was not a bug so much as an **absent policy**. The policy now, built on separation of duties and HIPAA's "minimum necessary" principle:

- **admin** — operates the system, manages users, reads the audit log. Never sees PHI. Not a clinician.
- **clinician** — treats patients. Sees masked SSNs by default. May *break glass* to reveal one, must state a reason, and every reveal is written to the audit log.

Nobody sees a full SSN as a side effect of listing patients. SSNs are encrypted at rest with Fernet, so the database file alone discloses nothing.

Also fixed: passwords were stored in plaintext in `data/users.ts` **and** hardcoded a second time inside the React bundle, where `login()` returned a boolean that any user could flip in a debugger. Authentication is now bcrypt plus a signed JWT, server-side. `routes/patients.ts` opened with `// @ts-nocheck`, so the TypeScript in the file most likely to hold security logic was decorative. `middleware/role.ts` imported a symbol that did not exist and was never called by anything.

The original Express backend is preserved untouched in `backend/` as the before-state.

---

## Layout

```
deid/
  types.py            PhiSpan, PhiCategory, span merging, redaction
  synth.py            deterministic synthetic notes with gold spans
  guard.py            EgressGuard — the trust boundary
  audit.py            hash-chained, tamper-evident JSONL
  loaders/n2c2.py     real corpus, with offset validation
  redactors/
    rules.py          the baseline (local)
    transformer.py    the production path (local)
    llm.py            the benchmark arm (transmits off-machine)
  eval/metrics.py     leak rate, F2, strict/partial, per-category
  train.py            recall-weighted fine-tuning
scripts/
  generate_adversarial_spans.py   74 spans built to defeat rules.py
service/              FastAPI: auth, patients, de-id, audit, benchmark
frontend/             React: studio, benchmark, patients, audit trail
tests/                197 tests, mostly about the metrics being honest
```

---

## Known limitations

Stated plainly, because a portfolio project that pretends to be finished is less convincing than one that knows what it is.

1. **Every number comes from synthetic data.** The harness is real and both generalization checks are real, but the corpus is a stand-in until DUA approval. The worry that the model leans on positional cues is no longer hypothetical — it was measured, diagnosed and partly fixed: varying the sentence frames took adversarial `AGE` recall from 0.167 to 0.833, which means the earlier failure was the templates' fault rather than the model's. Eight frames is still eight, and real dictation has unboundedly many. Real notes will score worse than 0.04%. **0.04% is not a production claim; 11.68% is the closer one.**
2. **The LLM arm has been run once, on synthetic data.** 50 notes, Claude Opus 4.8, $0.76. It confirms the semantic categories are learnable and gives the local model something to be measured against — but one run on templated notes is a sanity check, not a characterization. The real comparison is on n2c2.
3. **No checkpoint is committed.** Train your own in ~3 minutes; weights derived from restricted data do not belong in a public repo.
4. **`RECALL_FLOOR = 0.9` is a judgment call**, not a regulatory threshold. HIPAA does not specify a number. It is a defensible bar for a demo, not a compliance certification.
5. **Nothing here is a compliance certification.** A real deployment needs a signed BAA, key management in a KMS rather than an environment variable, penetration testing, and a lawyer.
