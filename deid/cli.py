"""Command line entry point.

    python -m deid.cli eval --redactor rules
    python -m deid.cli eval --redactor transformer --model-dir models/deid-deberta
    python -m deid.cli eval --redactor llm --i-understand-this-transmits-phi
    python -m deid.cli demo
    python -m deid.cli verify-audit --path audit.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .audit import AuditLog
from .redactors.rules import RuleRedactor
from .types import Note, apply_redaction

PHI_WARNING = """\
REFUSING TO RUN.

The `llm` redactor transmits raw note text to a hosted inference API. That is
the exact operation this project exists to make unnecessary.

It is legitimate for one purpose: measuring how well a hosted model redacts,
so the benchmark has an LLM arm. It must never touch a production note.

Before you run this against the n2c2 corpus, read your Data Use Agreement. The
corpus contains surrogate identifiers rather than real patient data, so this is
not a HIPAA disclosure -- but the DUA separately restricts who may receive
copies of the files.

If you understand this, re-run with:
    --i-understand-this-transmits-phi
"""


def _load_notes(args) -> list[Note]:
    if args.data == "n2c2":
        from .loaders.n2c2 import load_n2c2
        notes = load_n2c2(args.n2c2_dir)
        print(f"Loaded {len(notes)} notes from {args.n2c2_dir}")
        return notes[-args.limit :] if args.limit else notes

    if args.data == "heldout":
        from .synth import generate_heldout_corpus
        notes = generate_heldout_corpus(args.limit or 50)
        print(f"Loaded {len(notes)} held-out-vocabulary notes "
              f"(same templates, PHI strings never seen in training)")
        return notes

    from .synth import generate_corpus, split
    _, _, test = split(generate_corpus(args.n_synth))
    if args.limit:
        test = test[: args.limit]
    print(f"Loaded {len(test)} synthetic test notes "
          f"(seeded; not a substitute for the real corpus)")
    return test


def _build_redactor(args):
    if args.redactor == "rules":
        return RuleRedactor()

    if args.redactor == "transformer":
        from .redactors.transformer import TransformerRedactor
        if not args.model_dir:
            raise SystemExit("--redactor transformer requires --model-dir")
        if not Path(args.model_dir).exists():
            raise SystemExit(
                f"{args.model_dir} not found. Train one first:\n"
                f"  python -m deid.train --out {args.model_dir}"
            )
        return TransformerRedactor(args.model_dir,
                                   o_logit_penalty=args.o_logit_penalty)

    if args.redactor == "llm":
        if not args.i_understand_this_transmits_phi:
            raise SystemExit(PHI_WARNING)
        from .redactors.llm import LLMRedactor
        return LLMRedactor(model=args.model, use_batch=not args.no_batch)

    raise SystemExit(f"unknown redactor {args.redactor!r}")


def cmd_eval(args) -> int:
    from .eval import evaluate

    notes = _load_notes(args)
    redactor = _build_redactor(args)
    print(f"\nEvaluating {redactor.name} on {len(notes)} notes\n")
    report = evaluate(redactor, notes)

    d = report.as_dict()
    print(f"\n{'=' * 66}")
    print(f"  {redactor.name}")
    print(f"{'=' * 66}")
    print(f"  LEAK RATE            {report.leak_rate:.2%}   "
          f"<- PHI characters left exposed")
    print(f"  Fully-missed spans   {report.fully_missed_spans} / {report.gold_spans}")
    print(f"  Partial  P/R/F1/F2   {report.partial.precision:.3f} / "
          f"{report.partial.recall:.3f} / {report.partial.f1:.3f} / "
          f"{report.partial.f2:.3f}")
    print(f"  Strict   P/R/F1      {report.strict.precision:.3f} / "
          f"{report.strict.recall:.3f} / {report.strict.f1:.3f}")
    if report.hallucinated:
        print(f"  Hallucinated spans   {report.hallucinated}")
    print(f"  Mean latency         {report.mean_latency_ms:.1f} ms/note")
    if report.total_cost_usd:
        print(f"  Cost                 ${report.total_cost_usd:.4f}")

    print(f"\n  {'CATEGORY':<12} {'RECALL':>8} {'PREC':>8} {'F2':>8}  {'MISSED':>7}")
    print(f"  {'-' * 48}")
    for cat, prf in sorted(d["per_category"].items()):
        missed = d["missed_by_category"].get(cat, 0)
        flag = "  <-- leaking" if prf["recall"] < 0.90 else ""
        print(f"  {cat:<12} {prf['recall']:>8.3f} {prf['precision']:>8.3f} "
              f"{prf['f2']:>8.3f}  {missed:>7}{flag}")
    print()

    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        payload = {"redactor": redactor.name, "notes": len(notes), **d}
        Path(args.json_out).write_text(json.dumps(payload, indent=2))
        print(f"Wrote {args.json_out}")
    return 0


def cmd_demo(args) -> int:
    """Redact one synthetic note and print the before/after."""
    from .synth import generate_corpus

    note = generate_corpus(1)[0]
    redactor = RuleRedactor()
    result = redactor.redact(note)

    # A leak is a gold span with *zero* overlap against any prediction. An
    # exact-boundary comparison would also flag spans that were correctly
    # redacted with slightly different edges, which is a cosmetic problem, not
    # a disclosure. Keep the two straight or the headline number is wrong.
    leaked = [s for s in note.spans if not any(s.overlaps(p) for p in result.spans)]
    partial = [
        s for s in note.spans
        if s not in leaked
        and not any(s.start == p.start and s.end == p.end for p in result.spans)
    ]

    print("=" * 70)
    print("ORIGINAL")
    print("=" * 70)
    print(note.text)
    print("=" * 70)
    print(f"REDACTED BY {redactor.name}")
    print("=" * 70)
    print(result.redacted_text)
    print("=" * 70)
    print(f"LEAKED {len(leaked)} of {len(note.spans)} gold spans "
          f"({len(partial)} more had imperfect boundaries)")
    print("=" * 70)
    for s in sorted(leaked):
        print(f"  {s.category.value:<10} {s.subtype or '':<14} {s.text!r}")
    if leaked:
        print("\nEach line above is a disclosure of protected health information.")
    return 0


def cmd_verify_audit(args) -> int:
    log = AuditLog(args.path)
    result = log.verify()
    if result.ok:
        print(f"OK  {result.entries} entries, hash chain intact.")
        return 0
    print(f"FAIL  chain broken at entry {result.broken_at}: {result.reason}")
    return 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="deid", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("eval", help="score a redactor against gold spans")
    e.add_argument("--redactor", choices=["rules", "transformer", "llm"],
                   default="rules")
    e.add_argument("--data", choices=["synthetic", "heldout", "n2c2"],
                   default="synthetic",
                   help="heldout = same templates, PHI vocabulary the model "
                        "never saw. The honest generalization test.")
    e.add_argument("--n2c2-dir", type=Path)
    e.add_argument("--model-dir", help="checkpoint dir for --redactor transformer")
    e.add_argument("--model", default="claude-opus-4-8",
                   help="model id for --redactor llm")
    e.add_argument("--n-synth", type=int, default=200)
    e.add_argument("--limit", type=int, default=0, help="cap the note count")
    e.add_argument("--o-logit-penalty", type=float, default=0.0,
                   help="Bias the transformer against predicting O. "
                        "Higher = more recall, less precision.")
    e.add_argument("--json-out", help="write the full report as JSON")
    e.add_argument("--i-understand-this-transmits-phi", action="store_true")
    e.add_argument("--no-batch", action="store_true",
                   help="LLM redactor: run synchronously (predictable, full "
                        "price) instead of via the async Batch API (half price).")
    e.set_defaults(func=cmd_eval)

    d = sub.add_parser("demo", help="redact one note and show what leaked")
    d.set_defaults(func=cmd_demo)

    v = sub.add_parser("verify-audit", help="check the audit log hash chain")
    v.add_argument("--path", default="audit.jsonl")
    v.set_defaults(func=cmd_verify_audit)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
