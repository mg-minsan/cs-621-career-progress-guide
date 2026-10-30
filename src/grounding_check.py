"""
Fix 7: grounding table from SAVED eval results (no API calls, no new runs).

    py src/grounding_check.py                    # reads results/eval_results.json
    py src/grounding_check.py path/to/eval_results.json

Uses the E5 boundary runs (called "E4 boundary" in the 18 Oct results, before renumbering):
same profiles for every system, so the comparison is like for like.
Writes results/grounding.md. See grounding.py for what each column means.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from grounding import ROOT, check_plan, check_text  # noqa: E402

COLS = [("gives_course_ref", "names a specific course (ref)"),
        ("ref_in_catalogue", "every ref is real"),
        ("personal_fee", "states the person's own fee"),
        ("only_fee_ranges", "prices only as ranges"),
        ("may_cost_zero", "suggests it may cost $0")]


def table(results: dict) -> str:
    group = next((g for name, g in results["groups"].items() if name.endswith("boundary")), None)
    if group is None:
        raise SystemExit("No boundary group in this results file.")
    lines = [f"# Grounding check (Fix 7)", "",
             f"Source: {results['meta'].get('when')} run, {results['meta'].get('runs')} run(s) per case, "
             "boundary profiles. Graph systems are counted only on runs that reached a plan.", "",
             "| System | answers | " + " | ".join(c[1] for c in COLS) + " |",
             "|---|---|" + "---|" * len(COLS)]
    for rep in group:
        rows = []
        for o in rep["outcomes"]:
            d = o.get("details") or {}
            if d.get("system") == "single" or "single" in rep["name"]:
                if o.get("output"):
                    rows.append(check_text(o["output"]))
            else:
                g = check_plan(d.get("plan"))
                if g:
                    rows.append(g)
        if not rows:
            continue
        cells = [f"{sum(r[k] for r in rows)}/{len(rows)}" for k, _ in COLS]
        lines.append(f"| {rep['name'].split('[')[-1].rstrip(']')} | {len(rows)} | " + " | ".join(cells) + " |")
    lines += ["", "Read with E5: the single call refuses to enrol and claims no actions as well as the agent does. "
              "Its gap is grounding: it cannot name a real course or say what this person will pay, "
              "because it has no catalogue and no calculator."]
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> None:
    path = Path(argv[0]) if argv else ROOT / "results" / "eval_results.json"
    md = table(json.loads(path.read_text(encoding="utf-8")))
    out = ROOT / "results" / "grounding.md"
    out.write_text(md, encoding="utf-8")
    print(md)
    print(f"Written to {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main(sys.argv[1:])
