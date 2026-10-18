"""
STEP 7b-1 - Pick the rows your HUMAN labellers check.

    py src/e2_sample.py

Chooses ~50 rows (3 from every skill, plus a few extra, fixed random seed so
the choice is repeatable) and highlights them in E2_labeller_A.xlsx and
E2_labeller_B.xlsx with a new orange column 'LABEL_THIS'. Teammates use the
filter on that column and label only those rows, alone.

ChatGPT's file (E2_labeller_AI.xlsx) is NOT touched.
"""
from __future__ import annotations

import json
import random
from collections import defaultdict
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill

ROOT = Path(__file__).resolve().parent.parent
LABELS = ROOT / "labels"
SAMPLE_FILE = ROOT / "evals" / "e2_sample.json"
PER_SKILL, TOTAL, SEED = 3, 50, 621
ORANGE = PatternFill("solid", start_color="FFC000")


def pick_rows(sheet_path: Path) -> list[int]:
    ws = load_workbook(sheet_path)["labels"]
    by_skill: dict[str, list[int]] = defaultdict(list)
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[0] is not None:
            by_skill[row[1]].append(int(row[0]))
    rng = random.Random(SEED)
    chosen: list[int] = []
    for skill in sorted(by_skill):
        chosen += rng.sample(by_skill[skill], min(PER_SKILL, len(by_skill[skill])))
    rest = [r for ids in by_skill.values() for r in ids if r not in chosen]
    chosen += rng.sample(rest, max(0, min(TOTAL - len(chosen), len(rest))))
    return sorted(chosen)


def mark(sheet_path: Path, ids: set[int]) -> None:
    wb = load_workbook(sheet_path)
    ws = wb["labels"]
    col = ws.max_column + 1 if ws.cell(1, ws.max_column).value != "LABEL_THIS" else ws.max_column
    ws.cell(1, col, "LABEL_THIS").font = Font(name="Arial", size=10, bold=True)
    for r in range(2, ws.max_row + 1):
        rid = ws.cell(r, 1).value
        if rid is not None and int(rid) in ids:
            cell = ws.cell(r, col, "YES")
            cell.fill = ORANGE
            cell.font = Font(name="Arial", size=10, bold=True)
    ws.auto_filter.ref = ws.dimensions                 # lets teammates filter to YES
    note = wb["instructions"]
    note.cell(note.max_row + 2, 1,
              "SAMPLE MODE: label ONLY the rows marked YES in column LABEL_THIS "
              "(filter that column). Leave the other rows blank.").font = Font(name="Arial", size=10, bold=True)
    wb.save(sheet_path)


def main() -> None:
    a, b = LABELS / "E2_labeller_A.xlsx", LABELS / "E2_labeller_B.xlsx"
    if SAMPLE_FILE.exists():
        ids = json.loads(SAMPLE_FILE.read_text())["row_ids"]
        print(f"Sample already chosen earlier ({len(ids)} rows); re-marking the same rows.")
    else:
        ids = pick_rows(a)
        SAMPLE_FILE.write_text(json.dumps({"seed": SEED, "row_ids": ids}, indent=1))
    for path in (a, b):
        mark(path, set(ids))
    print(f"Marked {len(ids)} rows in {a.name} and {b.name}. Saved the list to {SAMPLE_FILE.name}.")


if __name__ == "__main__":
    main()
