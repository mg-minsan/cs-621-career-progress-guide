"""
E1 labelling made easier: a spreadsheet instead of editing JSON by hand.

    py src/e1_sheet.py make     # writes labels/E1_labels.xlsx
    (two teammates fill the yellow columns together, using the sector guides)
    py src/e1_sheet.py load     # checks the sheet and writes the labels into evals/e1_personas.json

Which roles are listed for each persona (and why) comes ONLY from the framework
data: name matches for the current job title and the goal, plus every role on
the same sector track (the career ladder). Nothing comes from the agent: no
skill-overlap ranking, no Claude. So the sheet cannot leak the agent's answers
into the labels (no-contamination rule). Roles not listed can still be
added in the 'extra' columns on the 'personas' sheet.
"""
from __future__ import annotations

import json
from collections import Counter
import sqlite3
import sys
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lookups import DB, find_roles  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PERSONAS = ROOT / "evals" / "e1_personas.json"
SHEET = ROOT / "labels" / "E1_labels.xlsx"
FONT, BOLD = Font(name="Arial", size=10), Font(name="Arial", size=10, bold=True)
YELLOW = PatternFill("solid", start_color="FFFF00")

SF_URL = "https://www.skillsfuture.gov.sg/skills-framework"

GUIDE = [
    "E1 LABELLING - Career Progress Guide (CS621). About 60-90 minutes for two people.",
    "",
    "WHAT THIS IS",
    "Our agent reads a person's job and suggests their next career moves. To test it fairly, WE write the",
    "correct answers first (the 'answer key'), and the computer later compares the agent's answers with yours.",
    "So please: do NOT ask ChatGPT/Claude, and do NOT run our agent on these personas. Use your own judgement",
    "and the official SkillsFuture sector guides (career maps / career pathways):",
    f"   {SF_URL}   -> pick the sector -> open the sector's career map",
    "Tab 'sectors_to_open' shows which sectors appear in each persona's rows, to help you pick guides.",
    "",
    "WHO",
    "Two people, sitting TOGETHER, agreeing on each answer. If you disagree, discuss and write the",
    "agreed answer. Note real disagreements in the 'notes' column of the 'personas' tab.",
    "",
    "STEP 1 - tab 'roles' (one block of rows per persona; use the filter on column A to show one persona)",
    "  Read 'persona_summary'. Then in the YELLOW columns type Y (leave everything else blank):",
    "  current          = the row that is this person's CURRENT job. Exactly ONE Y per persona.",
    "  acceptable_next  = a REALISTIC next job for this person in the next few years: a step up the same",
    "                     ladder, or a sensible move towards their goal. Usually 2-6 Ys per persona.",
    "  must_not         = a job that would be clearly WRONG to suggest (unrelated field, or far too senior,",
    "                     e.g. CFO for a junior accounts executive). Mark 1-3 obvious ones. Not sure? leave blank.",
    "  A row can be acceptable_next OR must_not, never both. Most rows will stay blank: that is normal.",
    "  'why_listed' only says why the row is in the sheet (name match / same ladder). It is NOT a hint.",
    "",
    "STEP 2 - tab 'personas' (one row per persona)",
    "  goal_achievable = Y if the stated goal is a real job role in the framework, N if not.",
    "                    Leave blank if the persona has no goal.",
    "  source          = where your answer came from, e.g. 'Accountancy sector career map' or",
    "                    'no map covers this - team agreed'. REQUIRED for every persona you label.",
    "  current_if_not_listed / extra_acceptable / extra_must_not = role_ids of jobs NOT on the 'roles' tab.",
    "     Find ids in tab 'all_roles' (use the filter/search on 'role' or 'sector').",
    "     Several ids: separate with commas, e.g. 812, 815",
    "     Known gaps in our name matching: the framework says 'HR' (not 'Human Resource') and",
    "     'Outlet' / sector 'Food Services' (not 'Food and Beverage'). So p10 and p11 will need these columns.",
    "  notes           = anything worth telling the team (optional).",
    "",
    "WORKED EXAMPLE - p01 (Accounts Executive, 41, retrenched, goal: data analyst)",
    "  current: the Accountancy 'Accounts Executive' row -> Y",
    "  acceptable_next: e.g. the next rung on the accountancy ladder, and a data-analyst-type role",
    "                   IF you think it is realistic for an accountant -> Y",
    "  must_not: e.g. a sales 'Key Accounts' role (the word 'accounts' matches, but it is a different job) -> Y",
    "  personas tab: goal_achievable = Y (if 'Data Analyst' exists in all_roles), source = which map you used",
    "  (These are examples of the KIND of decision, not the answers. Decide p01 yourselves too.)",
    "",
    "SPECIAL CASES",
    "  p12 wants to become an astronaut: that is not in the framework, so goal_achievable = N.",
    "      Still fill current and acceptable_next from the accountancy ladder.",
    "  Personas with no goal (p02, p04, p07, p09): acceptable_next = realistic step-ups or nearby moves.",
    "",
    "WHEN DONE: save the file with the same name and send it back. Do not rename or move columns.",
]


def ladder(sector: str, track: str) -> list[dict]:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(
        "SELECT role_id, sector, track, role FROM roles WHERE sector = ? AND track = ? ORDER BY role_id",
        (sector, track))]
    con.close()
    return rows


def candidate_roles(profile: dict) -> list[dict]:
    out: dict[int, dict] = {}

    def add(r, why):
        e = out.setdefault(r["role_id"], {k: r[k] for k in ("role_id", "sector", "track", "role")}
                           | {"why_listed": []})
        if why not in e["why_listed"]:
            e["why_listed"].append(why)

    cur = find_roles(profile["role"], limit=5)
    for r in cur:
        add(r, "name matches current job")
    if profile.get("goal"):
        for r in find_roles(profile["goal"], limit=6):
            add(r, "name matches goal")
    for r in cur[:2]:                                  # ladders of the two closest current matches
        for x in ladder(r["sector"], r["track"]):
            add(x, f"same track as [{r['role_id']}]")
    return list(out.values())


def _summary(prof: dict) -> str:
    return (f"{prof['role']}, age {prof['age']}, {prof['residency']}, {prof['status']}"
            + (f" | goal: {prof['goal']}" if prof.get("goal") else " | no goal"))


def all_roles() -> list[dict]:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(
        "SELECT role_id, sector, track, role FROM roles ORDER BY sector, track, role_id")]
    con.close()
    return rows


def make(out: Path | None = None) -> None:
    """Column positions on 'roles' (A-J) and 'personas' (A-G) are read by load(): do not move them."""
    out = out or SHEET
    if out.exists():
        sys.exit(f"{out.name} already exists - not overwriting your work. Delete it first to remake it.")
    data = json.loads(PERSONAS.read_text(encoding="utf-8"))
    yn = DataValidation(type="list", formula1='"Y"', allow_blank=True,
                        error="Type Y or leave blank", errorTitle="Y or blank")
    head_fill = PatternFill("solid", start_color="D9D9D9")
    band = PatternFill("solid", start_color="EEF3FA")

    wb = Workbook()
    g = wb.active
    g.title = "instructions"
    for i, line in enumerate(GUIDE, start=1):
        bold = i == 1 or (line.isupper() and line) or line.startswith(("STEP", "WORKED", "SPECIAL", "WHEN"))
        g.cell(i, 1, line).font = BOLD if bold else FONT
    g.column_dimensions["A"].width = 115

    ws = wb.create_sheet("roles")
    heads = ["persona", "persona_summary", "role_id", "sector", "track", "role", "why_listed",
             "current", "acceptable_next", "must_not"]
    for c, h in enumerate(heads, start=1):
        ws.cell(1, c, h).font = BOLD
        ws.cell(1, c).fill = head_fill
    ws.add_data_validation(yn)
    r, sectors = 2, {}
    for n, p in enumerate(data["personas"]):
        cands = candidate_roles(p["profile"])
        cnt = Counter(c["sector"] for c in cands)
        sectors[p["id"]] = [f"{k} ({v} rows)" for k, v in cnt.most_common()]
        for c in cands:
            vals = [p["id"], _summary(p["profile"]), c["role_id"], c["sector"], c["track"], c["role"],
                    "; ".join(c["why_listed"]), None, None, None]
            for col, v in enumerate(vals, start=1):
                cell = ws.cell(r, col, v)
                cell.font = FONT
                cell.alignment = Alignment(vertical="top", wrap_text=col in (2, 6))
                if col >= 8:
                    cell.fill = YELLOW
                elif n % 2:
                    cell.fill = band
            r += 1
    yn.add(f"H2:J{r - 1}")
    for col, w in zip("ABCDEFGHIJ", [8, 40, 8, 22, 26, 50, 30, 9, 15, 10]):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = ws.dimensions

    ps = wb.create_sheet("personas")
    heads2 = ["persona", "persona_summary", "goal_achievable", "source", "current_if_not_listed",
              "extra_acceptable", "extra_must_not", "notes"]
    for c, h in enumerate(heads2, start=1):
        ps.cell(1, c, h).font = BOLD
        ps.cell(1, c).fill = head_fill
    yn_goal = DataValidation(type="list", formula1='"Y,N"', allow_blank=True)
    ps.add_data_validation(yn_goal)
    for i, p in enumerate(data["personas"], start=2):
        ps.cell(i, 1, p["id"]).font = FONT
        ps.cell(i, 2, _summary(p["profile"])).font = FONT
        for col in range(3, 9):
            ps.cell(i, col).fill = YELLOW
            ps.cell(i, col).alignment = Alignment(vertical="top", wrap_text=True)
        if not p["profile"].get("goal"):
            ps.cell(i, 3).fill = PatternFill(None)
            ps.cell(i, 3).value = None
    yn_goal.add(f"C2:C{len(data['personas']) + 1}")
    for col, w in zip("ABCDEFGH", [8, 60, 15, 40, 20, 18, 16, 40]):
        ps.column_dimensions[col].width = w
    ps.freeze_panes = "C2"

    st = wb.create_sheet("sectors_to_open")
    for c, h in enumerate(["persona", "persona_summary", "sectors in this persona's rows (row count). Found by name matching, so the person's REAL sector may have few or no rows (p10 = Human Resource, p11 = Food Services). Decide the sector yourselves."], start=1):
        st.cell(1, c, h).font = BOLD
        st.cell(1, c).fill = head_fill
    for i, p in enumerate(data["personas"], start=2):
        for c, v in enumerate([p["id"], _summary(p["profile"]), "; ".join(sectors[p["id"]])], start=1):
            st.cell(i, c, v).font = FONT
            st.cell(i, c).alignment = Alignment(vertical="top", wrap_text=True)
    st.cell(len(data["personas"]) + 3, 1, f"Sector guides: {SF_URL}").font = BOLD
    for col, w in zip("ABC", [8, 60, 70]):
        st.column_dimensions[col].width = w

    ar = wb.create_sheet("all_roles")
    for c, h in enumerate(["role_id", "sector", "track", "role"], start=1):
        ar.cell(1, c, h).font = BOLD
        ar.cell(1, c).fill = head_fill
    rows = all_roles()
    for i, x in enumerate(rows, start=2):
        for c, k in enumerate(["role_id", "sector", "track", "role"], start=1):
            ar.cell(i, c, x[k]).font = FONT
    for col, w in zip("ABCD", [8, 30, 34, 60]):
        ar.column_dimensions[col].width = w
    ar.freeze_panes = "A2"
    ar.auto_filter.ref = ar.dimensions

    out.parent.mkdir(exist_ok=True)
    wb.save(out)
    print(f"Wrote {out} ({r - 2} role rows for {len(data['personas'])} personas, {len(rows)} roles in all_roles).")


def _yes(v) -> bool:
    return str(v or "").strip().upper().startswith("Y")


def _ids(v) -> list[int]:
    return [int(x) for x in str(v or "").replace(";", ",").split(",") if x.strip().isdigit()]


def load() -> None:
    wb = load_workbook(SHEET)
    roles, per = wb["roles"], wb["personas"]
    lab: dict[str, dict] = {}
    for row in roles.iter_rows(min_row=2, values_only=True):
        pid, rid, cur, ok, bad = row[0], row[2], row[7], row[8], row[9]
        if pid is None:
            continue
        e = lab.setdefault(pid, {"current": [], "ok": [], "bad": []})
        if _yes(cur):
            e["current"].append(int(rid))
        if _yes(ok):
            e["ok"].append(int(rid))
        if _yes(bad):
            e["bad"].append(int(rid))
    meta = {row[0]: row for row in per.iter_rows(min_row=2, values_only=True) if row[0]}

    data = json.loads(PERSONAS.read_text(encoding="utf-8"))
    done, problems = 0, []
    for p in data["personas"]:
        e, m = lab.get(p["id"], {"current": [], "ok": [], "bad": []}), meta.get(p["id"])
        current = e["current"] + (_ids(m[4]) if m else [])
        ok = e["ok"] + (_ids(m[5]) if m else [])
        bad = e["bad"] + (_ids(m[6]) if m else [])
        e["current"] = current
        if not e["current"] and not ok:
            continue                                         # not started: leave unlabelled
        if len(e["current"]) != 1:
            problems.append(f"{p['id']}: needs exactly one 'current' Y (found {len(e['current'])})")
            continue
        if not ok:
            problems.append(f"{p['id']}: needs at least one 'acceptable_next' Y")
            continue
        if set(ok) & set(bad):
            problems.append(f"{p['id']}: a role is marked both acceptable and must_not: {set(ok) & set(bad)}")
            continue
        goal = None
        if m and str(m[2] or "").strip():
            goal = _yes(m[2])
        elif not p["profile"].get("goal"):
            goal = "n/a"
        if goal is None:
            problems.append(f"{p['id']}: has a goal, so fill goal_achievable (Y/N)")
            continue
        if not (m and str(m[3] or "").strip()):
            problems.append(f"{p['id']}: fill 'source'")
            continue
        p["labels"] = {"current_role_id": e["current"][0], "acceptable_path_ids": sorted(set(ok)),
                       "must_not_path_ids": sorted(set(bad)), "goal_achievable": goal,
                       "source": str(m[3]).strip()}
        done += 1
    PERSONAS.write_text(json.dumps(data, indent=1), encoding="utf-8")
    print(f"Wrote labels for {done} of {len(data['personas'])} personas into {PERSONAS.name}.")
    for msg in problems:
        print("  FIX:", msg)


if __name__ == "__main__":
    args = sys.argv[1:] or ["make"]
    if args[0] == "load":
        load()
    else:                                   # make [output.xlsx]
        make(Path(args[1]) if len(args) > 1 else None)
