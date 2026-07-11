#!/usr/bin/env python
"""Tabulate every redactor report in results/ into one matrix.

Reads the JSON the harness wrote; computes nothing. Rows are PHI categories,
columns are redactors, cells are recall. This is the terminal twin of the
dashboard's comparison chart and the source for the README's headline table.

    python scripts/report.py                 # all of results/*.json
    python scripts/report.py --dir results/heldout
    python scripts/report.py --markdown
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

CATEGORY_ORDER = ["AGE", "CONTACT", "DATE", "ID", "LOCATION", "NAME", "PROFESSION"]
SEMANTIC = {"NAME", "LOCATION", "PROFESSION"}  # what rules structurally cannot reach


def load(directory: Path) -> list[dict]:
    reports = []
    for path in sorted(directory.glob("*.json")):
        try:
            reports.append(json.loads(path.read_text()))
        except json.JSONDecodeError:
            print(f"skipping unparseable {path}")
    # Order columns by leak rate, worst first — the story reads left to right.
    return sorted(reports, key=lambda r: -r["leak_rate"])


def short(name: str) -> str:
    return name.split(":", 1)[1] if ":" in name else name


def recall(report: dict, cat: str) -> float:
    return report["per_category"].get(cat, {}).get("recall", 0.0)


def render_text(reports: list[dict]) -> None:
    names = [short(r["redactor"]) for r in reports]
    notes = reports[0]["notes"]
    spans = reports[0]["gold_spans"]
    same = all(r["notes"] == notes and r["gold_spans"] == spans for r in reports)

    print(f"\n  {notes} notes, {spans} gold spans"
          + ("  (identical across all redactors)" if same
             else "  ⚠ NOT the same test set — comparison invalid"))
    print()

    w = 17
    header = f"  {'RECALL':<12}" + "".join(f"{n[: w - 1]:>{w}}" for n in names)
    print(header)
    print(f"  {'-' * (12 + w * len(names))}")

    cats = [c for c in CATEGORY_ORDER if any(c in r["per_category"] for r in reports)]
    for c in cats:
        star = "*" if c in SEMANTIC else " "
        row = f" {star}{c:<12}" + "".join(f"{recall(r, c):>{w}.3f}" for r in reports)
        print(row)

    print(f"  {'-' * (12 + w * len(names))}")
    print(f"  {'LEAK RATE':<12}" + "".join(f"{r['leak_rate']:>{w}.2%}" for r in reports))
    print(f"  {'F2':<12}" + "".join(f"{r['partial']['f2']:>{w}.3f}" for r in reports))
    print(f"  {'Precision':<12}" + "".join(f"{r['partial']['precision']:>{w}.3f}" for r in reports))
    print(f"  {'Latency ms':<12}" + "".join(f"{r['mean_latency_ms']:>{w}.1f}" for r in reports))
    cost = "".join(
        (f"${r['total_cost_usd']:>{w-1}.2f}" if r.get("total_cost_usd") else f"{'free':>{w}}")
        for r in reports
    )
    print(f"  {'Cost':<12}{cost}")
    hall = "".join(f"{r.get('hallucinated_spans', 0):>{w}}" for r in reports)
    print(f"  {'Hallucd':<12}{hall}")
    print(f"\n  * categories a rule system structurally cannot reach\n")


def render_markdown(reports: list[dict]) -> None:
    names = [short(r["redactor"]) for r in reports]
    print("| Category | " + " | ".join(names) + " |")
    print("|" + "---|" * (len(names) + 1))
    cats = [c for c in CATEGORY_ORDER if any(c in r["per_category"] for r in reports)]
    for c in cats:
        cells = []
        for r in reports:
            v = recall(r, c)
            cells.append(f"**{v:.3f}**" if (c in SEMANTIC and v >= 0.9) else f"{v:.3f}")
        print(f"| {c} | " + " | ".join(cells) + " |")
    print()
    print("| | " + " | ".join(names) + " |")
    print("|" + "---|" * (len(names) + 1))
    print("| **Leak rate** | " + " | ".join(f"{r['leak_rate']:.2%}" for r in reports) + " |")
    print("| F2 | " + " | ".join(f"{r['partial']['f2']:.3f}" for r in reports) + " |")
    print("| Latency | " + " | ".join(f"{r['mean_latency_ms']:.0f} ms" for r in reports) + " |")
    print("| Cost | " + " | ".join(
        (f"${r['total_cost_usd']:.2f}" if r.get("total_cost_usd") else "free") for r in reports) + " |")
    print("| Hallucinated | " + " | ".join(
        str(r.get("hallucinated_spans", 0)) for r in reports) + " |")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", type=Path, default=Path("results"))
    ap.add_argument("--markdown", action="store_true")
    args = ap.parse_args()

    reports = load(args.dir)
    if not reports:
        print(f"No reports in {args.dir}/ — run an eval with --json-out first.")
        return 1
    (render_markdown if args.markdown else render_text)(reports)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
