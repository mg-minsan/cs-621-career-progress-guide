"""
Fix 5: a small, BLIND human check of the labels every score depends on (week 3: check the grader).

    py src/make_human_check.py          # writes labels/human_check.xlsx (fixed seed, no API)
    (one person fills column F on both sheets, ~20-30 min)
    py src/score_human_check.py         # agreement with the AI judges and the E1 rules

E2 (25 course-skill pairs): the AI judges said "relevant" unanimously for 158 of 186 pairs (85%),
so a check of only random rows would mostly see easy yeses. Sampling is stratified:
10 unanimous-Y, 8 unanimous-N, 7 split votes; the score re-weights to the real mix.
E1 (10 rule-made labels): 3 "current job", 4 "acceptable next move", 3 "clearly wrong move",
from both the dev and the held-out personas.

Blind: the sheet shows the same evidence the judges saw (skill description and the first 600
characters of course text) but NOT their votes or reasons, so the person is not anchored.
The answer key stays in labels/e2_llm_judges.json and evals/*.json, read only by the scorer.
"""
from __future__ import annotations

import json
import random
import sqlite3
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "labels" / "human_check.xlsx"
SEED = 621
E2_PLAN = {"unanimous_Y": 10, "unanimous_N": 8, "split": 7}
E1_PLAN = {"current": 3, "acceptable_next": 4, "must_not": 3}
E2_CHOICES = ["Y", "N", "Unsure"]
E1_CHOICES = ["Agree", "Disagree", "Unsure"]


def e2_strata() -> dict[str, list[dict]]:
    data = json.loads((ROOT / "labels" / "e2_llm_judges.json").read_text(encoding="utf-8"))
    votes = {n: {int(k): v["relevant"] for k, v in j["labels"].items()} for n, j in data["judges"].items()}
    out: dict[str, list[dict]] = {k: [] for k in E2_PLAN}
    for r in data["rows"]:
        y = sum(v[r["row_id"]] == "Y" for v in votes.values())
        key = "unanimous_Y" if y == len(votes) else "unanimous_N" if y == 0 else "split"
        out[key].append(r)
    return out


def e2_sample(rng: random.Random) -> list[dict]:
    rows = []
    for key, n in E2_PLAN.items():
        pool = sorted(e2_strata()[key], key=lambda r: r["row_id"])
        rows += rng.sample(pool, min(n, len(pool)))
    rng.shuffle(rows)                                  # strata mixed, so order gives nothing away
    return rows


def _roles() -> dict[int, dict]:
    con = sqlite3.connect(ROOT / "data" / "careers.db")
    return {rid: {"role": role, "sector": sector, "description": desc or ""}
            for rid, role, sector, desc in con.execute("SELECT role_id, role, sector, description FROM roles")}


def e1_sample(rng: random.Random) -> list[dict]:
    personas = []
    for f in ("e1_personas.json", "e1_heldout.json"):
        personas += json.loads((ROOT / "evals" / f).read_text(encoding="utf-8"))["personas"]
    items = {"current": [], "acceptable_next": [], "must_not": []}
    for p in personas:
        lab = p.get("labels") or {}
        if lab.get("current_role_id") is None:
            continue
        items["current"].append((p, lab["current_role_id"]))
        items["acceptable_next"] += [(p, r) for r in lab["acceptable_path_ids"] if r != lab["current_role_id"]]
        items["must_not"] += [(p, r) for r in lab.get("must_not_path_ids", [])]
    out = []
    for kind, n in E1_PLAN.items():
        pool = sorted(items[kind], key=lambda x: (x[0]["id"], x[1]))
        picked, seen = [], set()
        for p, r in rng.sample(pool, len(pool)):        # at most one item per persona per kind
            if p["id"] not in seen:
                picked.append((p, r))
                seen.add(p["id"])
            if len(picked) == n:
                break
        out += [{"kind": kind, "persona": p, "role_id": r} for p, r in picked]
    rng.shuffle(out)
    return out


QUESTION = {"current": "Is this the right framework job for the person's CURRENT job title?",
            "acceptable_next": "Is this a realistic NEXT move for them (a step up or their goal)?",
            "must_not": "Is this CLEARLY WRONG as a next move (far too senior or unrelated)?"}

HEAD = Font(bold=True, color="FFFFFF")
FILL = PatternFill("solid", fgColor="1F4E5A")
ANSWER = PatternFill("solid", fgColor="FFF2CC")
WRAP = Alignment(wrap_text=True, vertical="top")


def _sheet(ws, headers, widths, rows, choices, answer_col):
    ws.append(headers)
    for c in ws[1]:
        c.font, c.fill, c.alignment = HEAD, FILL, WRAP
    for r in rows:
        ws.append(r)
    for i, w in enumerate(widths):
        ws.column_dimensions[chr(65 + i)].width = w
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = WRAP
        row[answer_col].fill = ANSWER
    dv = DataValidation(type="list", formula1='"' + ",".join(choices) + '"', allow_blank=True)
    col = chr(65 + answer_col)
    dv.add(f"{col}2:{col}{len(rows) + 1}")
    ws.add_data_validation(dv)
    ws.freeze_panes = "A2"


def main() -> None:
    rng = random.Random(SEED)
    wb = Workbook()
    info = wb.active
    info.title = "Read me"
    for line in [
        "Human check (Fix 5). About 20-30 minutes. One person, on your own, without looking anything up in the repo.",
        "",
        "Fill ONLY the yellow column on the two sheets, using its dropdown. Leave nothing blank; use Unsure if you cannot tell.",
        "",
        "Sheet 'E2 courses' (25 rows): does completing this course teach a MEANINGFUL part of the skill?",
        "   Y = yes, a meaningful part of the skill.   N = a different subject, only a passing mention, or not enough evidence.",
        "   Judge the topic only. Ignore price, provider, eligibility and course level. Don't give credit for a promising title alone.",
        "   (This is the exact rule the AI judges were given.)",
        "",
        "Sheet 'E1 roles' (10 rows): each row states a label our rules made. Agree or Disagree with the question shown.",
        "",
        "You will NOT see what the AI said. That is on purpose: we are checking the AI, so your answer must be your own.",
        "When done: save, then run   py src/score_human_check.py",
    ]:
        info.append([line])
    info.column_dimensions["A"].width = 130

    e2 = wb.create_sheet("E2 courses")
    rows = [[i + 1, r["row_id"], r["skill"], r["skill_description"] or "(no description)",
             f"{r['course_title']}\n\n{r['course_text']}", None, None]
            for i, r in enumerate(e2_sample(rng))]
    _sheet(e2, ["#", "row_id", "Skill", "Skill description", "Course title + text (what the judges saw)",
                "Teaches the skill? (Y/N/Unsure)", "Note (optional)"],
           [4, 7, 22, 40, 90, 16, 30], rows, E2_CHOICES, answer_col=5)

    roles = _roles()
    e1 = wb.create_sheet("E1 roles")
    rows = []
    for i, it in enumerate(e1_sample(rng)):
        p, role = it["persona"]["profile"], roles[it["role_id"]]
        person = (f"{p['role']}, age {p['age']}, {p['residency']}, {p['status']}"
                  + (f". Goal: {p['goal']}" if p.get("goal") else ". No goal given"))
        rows.append([i + 1, f"{it['persona']['id']}|{it['kind']}|{it['role_id']}", person,
                     QUESTION[it["kind"]],
                     f"{role['role']}  ({role['sector']})\n\n{role['description'][:500]}", None, None])
    _sheet(e1, ["#", "id", "Person", "Question", "Framework job (sector) + description",
                "Your answer (Agree/Disagree/Unsure)", "Note (optional)"],
           [4, 18, 34, 34, 80, 16, 30], rows, E1_CHOICES, answer_col=5)

    OUT.parent.mkdir(exist_ok=True)
    wb.save(OUT)
    print(f"Wrote {OUT.name}: 25 E2 rows, 10 E1 rows (seed {SEED}).")


if __name__ == "__main__":
    main()
