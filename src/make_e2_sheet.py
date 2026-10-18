"""
STEP 7a - Build the E2 labelling sheets (course relevance).

    py src/make_e2_sheet.py            # all 4 search modes (needs the meaning index)
    py src/make_e2_sheet.py --modes bm25

POOLING (standard trick in search evaluation): nobody can judge all 26,099
courses for a skill. Instead we collect the top 5 from EVERY search mode,
merge them, and humans label only that pool. Any course a system returns is
then labelled, so every mode can be scored fairly (precision@k).

Writes
  labels/E2_labeller_A.xlsx, labels/E2_labeller_B.xlsx   two identical sheets,
      rows shuffled the same way, with NO hint of which mode found each course
      (so labellers cannot favour a system)
  evals/e2_pool.json   which mode found which course at which rank (for scoring)

Two people label SEPARATELY. Their agreement (Cohen's kappa) goes in the report.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

sys.path.insert(0, str(Path(__file__).resolve().parent))
from course_search import CourseIndex  # noqa: E402
from lookups import skill_description  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SKILLS = [  # 15 skills: data path, business, sustainability, AI, plus two known-hard ones
    "Data Collection and Analysis", "Data Governance", "Data Storytelling and Visualisation",
    "Data-mining and Modelling", "Programming and Coding", "Stakeholder Management",
    "Ethical Culture", "Impact Indicators, Measurement and Reporting", "Project Management",
    "Budgeting", "Cybersecurity", "Artificial Intelligence Application",
    "Digital Marketing Management", "Customer Experience Management", "Workplace Safety and Health",
]
ALL_MODES = ["bm25", "dense", "hybrid", "hybrid_rerank"]
TOP_K = 5
FONT, BOLD = Font(name="Arial", size=10), Font(name="Arial", size=10, bold=True)
INPUT_FILL = PatternFill("solid", start_color="FFFF00")

GUIDE = [
    "HOW TO LABEL (read before starting)",
    "",
    "Fill ONLY the yellow column 'relevant' with Y or N. Use 'notes' for anything unsure.",
    "Y = a person who completes this course would gain a MEANINGFUL PART of the skill",
    "    as described in 'skill_description' (not just a passing mention).",
    "N = the course is mainly about something else, or only touches the skill.",
    "Unsure? Mark N and write why in 'notes'. Do not guess Y.",
    "Ignore price, provider reputation and course level: judge topic match only.",
    "",
    "RULES",
    "1. Label alone. Do not look at the other labeller's sheet until both are finished.",
    "2. Do not run the agent on these skills before labelling.",
    "3. Do not change any other column or the row order.",
    "",
    "EXAMPLE ROW (format only - the real rows are on the 'labels' sheet)",
]


def build_pool(modes: list[str]) -> dict[str, list[dict]]:
    base = CourseIndex(mode=modes[-1]) if modes[-1] != "bm25" else None
    indexes = {}
    for m in modes:
        if m == "bm25":
            indexes[m] = CourseIndex(mode="bm25")
        else:
            indexes[m] = CourseIndex(mode=m, encoder=base.encoder, vectors=base.vectors,
                                     reranker=base.reranker if m == "hybrid_rerank" else None)
    pool: dict[str, list[dict]] = {}
    for skill in SKILLS:
        found: dict[str, dict] = {}
        for m, idx in indexes.items():
            for rank, hit in enumerate(idx.search(skill, k=TOP_K), start=1):
                entry = found.setdefault(hit["course_ref"], {"course_ref": hit["course_ref"],
                                                             "title": hit["title"],
                                                             "provider": hit["provider"],
                                                             "found_by": {}})
                entry["found_by"][m] = rank
        pool[skill] = list(found.values())
    return pool


def write_sheet(path: Path, rows: list[dict]) -> None:
    wb = Workbook()
    guide = wb.active
    guide.title = "instructions"
    for r, line in enumerate(GUIDE, start=1):
        guide.cell(r, 1, line).font = BOLD if line.isupper() and line else FONT
    ex_row = len(GUIDE) + 1
    example = ["(example)", "Budgeting", "Plan and monitor budgets...", "TGS-0000000",
               "Budgeting Essentials for Managers", "Example Provider", "Learn to build...",
               "Y", "covers budget planning"]
    for c, v in enumerate(example, start=1):
        guide.cell(ex_row, c, v).font = FONT
    guide.cell(ex_row, 8).fill = INPUT_FILL
    guide.column_dimensions["A"].width = 95

    ws = wb.create_sheet("labels")
    headers = ["row_id", "skill", "skill_description", "course_ref", "course_title",
               "provider", "course_text", "relevant", "notes"]
    for c, h in enumerate(headers, start=1):
        ws.cell(1, c, h).font = BOLD
    dv = DataValidation(type="list", formula1='"Y,N"', allow_blank=True)
    ws.add_data_validation(dv)
    for r, row in enumerate(rows, start=2):
        for c, h in enumerate(headers, start=1):
            cell = ws.cell(r, c, row.get(h, ""))
            cell.font = FONT
            cell.alignment = Alignment(wrap_text=h in {"skill_description", "course_text"},
                                       vertical="top")
        ws.cell(r, 8).fill = INPUT_FILL
        dv.add(ws.cell(r, 8))
    for col, width in zip("ABCDEFGHI", [8, 26, 45, 16, 45, 24, 70, 10, 30]):
        ws.column_dimensions[col].width = width
    ws.freeze_panes = "A2"
    wb.save(path)


def main() -> None:
    modes = ALL_MODES
    if "--modes" in sys.argv:
        modes = sys.argv[sys.argv.index("--modes") + 1].split(",")
    pool = build_pool(modes)
    text = {c["course_ref"]: c["search_text"] for c in CourseIndex(mode="bm25").courses}
    rows, rng = [], random.Random(621)
    for skill, entries in pool.items():
        desc = skill_description(skill)
        entries = entries[:]
        rng.shuffle(entries)                      # hide which system ranked it first
        for e in entries:
            rows.append({"skill": skill, "skill_description": desc, "course_ref": e["course_ref"],
                         "course_title": e["title"], "provider": e["provider"],
                         "course_text": text[e["course_ref"]].replace("\r", "")[:600]})
    for i, row in enumerate(rows, start=1):
        row["row_id"] = i
    (ROOT / "labels").mkdir(exist_ok=True)
    for who in ("A", "B"):
        write_sheet(ROOT / "labels" / f"E2_labeller_{who}.xlsx", rows)
    (ROOT / "evals" / "e2_pool.json").write_text(json.dumps(
        {"modes": modes, "top_k": TOP_K, "skills": pool}, indent=1))
    sizes = [len(v) for v in pool.values()]
    print(f"{len(rows)} rows to label ({min(sizes)}-{max(sizes)} per skill), modes={modes}")
    print("wrote labels/E2_labeller_A.xlsx, labels/E2_labeller_B.xlsx, evals/e2_pool.json")


if __name__ == "__main__":
    main()
