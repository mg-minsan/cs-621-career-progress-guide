"""
E1 answer key WITHOUT hand labelling: derived from the Skills Framework itself.

    py src/e1_auto_labels.py            # writes labels into evals/e1_personas.json + labels/E1_auto_audit.xlsx
    py src/e1_auto_labels.py audit      # after ONE person fills the audit sheet: prints agreement

Idea: the framework lists, for every job, the skills it needs and at what
proficiency level (1-6). The average level is a seniority score, and on each
track it puts jobs in career order, e.g.
    Accounts Executive 2.96 -> Accountant 3.50 -> Finance Manager 4.29 -> Financial Controller 5.22

Rules (fixed BEFORE the agent is run on E1; never tuned on agent output):
  current          = the framework role whose name matches the job title (score >= CURRENT_MIN).
                     Several equally good matches in different sectors (e.g. "Marketing Executive"
                     exists in 4 sectors) -> all of them count as correct.
  acceptable_next  = (1) on the same track, the NEXT_RUNGS roles that are a step UP
                         (seniority between current + MIN_STEP and current + BIG_JUMP) and share
                         the MOST skills with the current job (at least MIN_OVERLAP), and
                     (2) roles matching the stated goal, unless they are a jump of more than BIG_JUMP.
  must_not         = (a) same-track roles more than BIG_JUMP above the current job (too senior),
                     (b) goal-matching roles that are a jump of more than BIG_JUMP.
                     Kept conservative on purpose: must_not means CLEARLY wrong.
                     Roles in neither list are not graded either way.
  goal_achievable  = True if the goal matches a framework role (score >= GOAL_MIN), else False.

TITLE_MAP: four personas word their job/goal differently from the framework
(it writes "HR", "Artificial Intelligence", "Outlet Manager"). One mapping line
each, listed below. These are OUR assumptions: report them, and the audit checks them.

TRIED AND DROPPED (for the report): a "name confuser" rule (name matches the job but shares
almost no skills, e.g. sales "Key Accounts Executive" for an Accounts Executive). Cross-sector
skill overlap cannot tell those apart from the SAME job in another sector: Key Accounts sales vs
Accounts Executive share 0% of skill ids / 14% of skill-title words, but Customer Service
Executive (Energy) vs Senior Customer Service Officer (Logistics) also share 0% / 9%. So the
rule would have marked reasonable moves as forbidden.

Nothing here reads the agent, Claude, or nearby_roles (which the agent uses).
Labels are "silver" (rule-made), not expert labels. Say so in the report.
"""
from __future__ import annotations

import json
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
AUDIT = ROOT / "labels" / "E1_auto_audit.xlsx"
SOURCE = "auto-v1: framework seniority ladder (src/e1_auto_labels.py)"

CURRENT_MIN = 0.95        # name match needed to call a role "the current job"
GOAL_MIN = 0.70           # name match needed for a goal to count as a framework role
GOAL_BAND = 0.05          # goal roles within this of the best goal score all count
NEXT_RUNGS = 2            # how many steps up the ladder are "next"
MIN_STEP = 0.10           # smaller seniority differences are sideways, not up
MIN_OVERLAP = 0.15        # Jaccard skill overlap for a same-track step to count
BIG_JUMP = 2.0            # seniority jump that is unrealistic as a next move

# persona id -> how to find its current job / goal when the wording differs from the framework
TITLE_MAP = {
    "p03": {"goal_query": "relationship manager", "goal_sector": "Financial Services"},
    "p05": {"goal_query": "artificial intelligence engineer"},
    "p10": {"current_sector": "Human Resource", "current_prefix": "Executive,",
            "goal_query": "HR business partner"},
    "p11": {"current_sector": "Food Services", "current_query": "service supervisor",
            "goal_query": "outlet manager", "goal_sector": "Food Services"},
}
FILLER = ("move into ", "become an ", "become a ", "a ", "an ")


# ------------------------------------------------------------------ data
def _load():
    con = sqlite3.connect(DB)
    level = dict(con.execute("SELECT role_id, AVG(level_num) FROM role_skills GROUP BY role_id"))
    skills: dict[int, set] = {}
    for rid, sk in con.execute("SELECT role_id, unique_skill FROM role_skills WHERE unique_skill IS NOT NULL"):
        skills.setdefault(rid, set()).add(sk)
    roles = {r[0]: {"role_id": r[0], "sector": r[1], "track": r[2], "role": r[3]}
             for r in con.execute("SELECT role_id, sector, track, role FROM roles")}
    con.close()
    return level, skills, roles


LEVEL, SKILLS, ROLES = _load()


def overlap(a: int, b: int) -> float:
    sa, sb = SKILLS.get(a, set()), SKILLS.get(b, set())
    return len(sa & sb) / len(sa | sb) if sa | sb else 0.0


def tracks(rid: int) -> set[str]:
    return {t.strip() for t in ROLES[rid]["track"].split("/")}


def same_track(a: int, b: int) -> bool:
    return ROLES[a]["sector"] == ROLES[b]["sector"] and bool(tracks(a) & tracks(b))


def clean_goal(goal: str) -> str:
    g = goal.lower().strip()
    for f in FILLER:
        if g.startswith(f):
            g = g[len(f):]
    return g.removesuffix(" role").strip()


# ------------------------------------------------------------------ rules
def current_ids(pid: str, title: str) -> list[int]:
    m = TITLE_MAP.get(pid, {})
    if "current_prefix" in m:
        return sorted(r for r, x in ROLES.items()
                      if x["sector"] == m["current_sector"] and x["role"].startswith(m["current_prefix"]))
    hits = find_roles(m.get("current_query", title), limit=10)
    if "current_sector" in m:
        hits = [h for h in hits if h["sector"] == m["current_sector"]]
    return [h["role_id"] for h in hits if h["score"] >= CURRENT_MIN]


def goal_ids(pid: str, goal: str | None) -> tuple[list[int], list[dict]]:
    """(roles that ARE the goal, the raw name matches)."""
    if not goal:
        return [], []
    m = TITLE_MAP.get(pid, {})
    hits = find_roles(m.get("goal_query", clean_goal(goal)), limit=8)
    if "goal_sector" in m:
        hits = [h for h in hits if h["sector"] == m["goal_sector"]] or hits
    if not hits or hits[0]["score"] < GOAL_MIN:
        return [], hits
    best = hits[0]["score"]
    return [h["role_id"] for h in hits
            if h["score"] >= max(GOAL_MIN, best - GOAL_BAND) and h["role_id"] in LEVEL], hits


def label(p: dict) -> dict:
    pid, prof = p["id"], p["profile"]
    why: dict[int, str] = {}
    cur = current_ids(pid, prof["role"])
    if not cur:
        raise ValueError(f"{pid}: no framework role matches {prof['role']!r}; add a TITLE_MAP line")
    for c in cur:
        why[c] = "current: name match" + (" (TITLE_MAP)" if pid in TITLE_MAP and "current_sector" in TITLE_MAP[pid] else "")
    goals, _ = goal_ids(pid, prof.get("goal"))

    ok, bad = set(), set()
    for c in cur:
        lv = LEVEL[c]
        up = sorted((r for r in ROLES if r not in cur and r in LEVEL and same_track(c, r)
                     and lv + MIN_STEP < LEVEL[r] <= lv + BIG_JUMP and overlap(c, r) >= MIN_OVERLAP),
                    key=lambda r: (-overlap(c, r), LEVEL[r], r))
        for r in up[:NEXT_RUNGS]:
            ok.add(r)
            why.setdefault(r, f"acceptable: step up the same track, {overlap(c, r):.0%} shared skills "
                              f"({lv:.2f} -> {LEVEL[r]:.2f})")
        for r in ROLES:
            if r not in cur and r in LEVEL and same_track(c, r) and LEVEL[r] > lv + BIG_JUMP:
                bad.add(r)
                why.setdefault(r, f"must_not: too senior ({lv:.2f} -> {LEVEL[r]:.2f}, jump > {BIG_JUMP})")

    lv0 = min(LEVEL[c] for c in cur)
    for g in goals:
        if LEVEL[g] > lv0 + BIG_JUMP:
            bad.add(g)
            why[g] = f"must_not: matches the goal but too senior ({lv0:.2f} -> {LEVEL[g]:.2f})"
        else:
            ok.add(g)
            why[g] = "acceptable: matches the stated goal" + (" (TITLE_MAP)" if "goal_query" in TITLE_MAP.get(pid, {}) else "")

    bad -= ok
    primary = cur[0]
    if goals and len(cur) > 1:          # ambiguous sector: the one closest to the goal
        primary = max(cur, key=lambda c: (max(overlap(c, g) for g in goals), -c))
    return {"current_role_id": primary,
            "current_role_alternatives": [c for c in cur if c != primary],
            "acceptable_path_ids": sorted(ok),
            "must_not_path_ids": sorted(bad),
            "goal_achievable": (bool(goals) if prof.get("goal") else "n/a"),
            "source": SOURCE,
            "_why": {str(k): v for k, v in why.items()}}


# ------------------------------------------------------------------ outputs
def write_audit(rows: list[list]) -> None:
    wb = Workbook()
    g = wb.active
    g.title = "instructions"
    lines = [
        "E1 AUTO-LABEL AUDIT  (one person, about 10-15 minutes)",
        "",
        "The E1 answer key was made by rules from the Skills Framework (no person, no AI). See src/e1_auto_labels.py.",
        "Your job is only to CHECK it: for each row, would a sensible careers adviser agree with this label?",
        "  agree = Y  -> the label is fine",
        "  agree = N  -> the label is wrong; write why in 'comment' (e.g. 'too big a jump', 'unrelated job')",
        "Do not change anything else. Do not use ChatGPT/Claude. Do not run the agent first.",
        "",
        "label meanings:",
        "  current           the persona's current job (several = the title exists in several sectors; all count)",
        "  acceptable_next   a realistic next job",
        "  must_not          a job that would be clearly wrong to suggest",
        "  goal              whether the stated goal exists as a framework job",
        "'seniority' = average skill level the job needs (1-6). 'rule' says why the row got its label.",
        "",
        "When done: save, then  py src/e1_auto_labels.py audit",
    ]
    for i, t in enumerate(lines, 1):
        g.cell(i, 1, t).font = Font(name="Arial", size=10, bold=(i == 1))
    g.column_dimensions["A"].width = 110
    ws = wb.create_sheet("audit")
    heads = ["persona", "persona_summary", "label", "role_id", "sector", "track", "role", "seniority",
             "rule", "agree", "comment"]
    for c, h in enumerate(heads, 1):
        ws.cell(1, c, h).font = Font(name="Arial", size=10, bold=True)
        ws.cell(1, c).fill = PatternFill("solid", start_color="D9D9D9")
    yn = DataValidation(type="list", formula1='"Y,N"', allow_blank=True)
    ws.add_data_validation(yn)
    band = PatternFill("solid", start_color="EEF3FA")
    yellow = PatternFill("solid", start_color="FFFF00")
    last, n = None, 0
    for r, row in enumerate(rows, 2):
        if row[0] != last:
            last, n = row[0], n + 1
        for c, v in enumerate(row + [None, None], 1):
            cell = ws.cell(r, c, v)
            cell.font = Font(name="Arial", size=10)
            cell.alignment = Alignment(vertical="top", wrap_text=c in (2, 7, 9, 11))
            cell.fill = yellow if c >= 10 else (band if n % 2 else PatternFill(None))
    yn.add(f"J2:J{len(rows) + 1}")
    for col, w in zip("ABCDEFGHIJK", [8, 34, 15, 8, 20, 24, 44, 9, 46, 7, 30]):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "D2"
    ws.auto_filter.ref = ws.dimensions
    AUDIT.parent.mkdir(exist_ok=True)
    wb.save(AUDIT)


def summary(prof: dict) -> str:
    return (f"{prof['role']}, {prof['age']}, {prof['residency']}, {prof['status']}"
            + (f" | goal: {prof['goal']}" if prof.get("goal") else " | no goal"))


def make(force: bool = False) -> None:
    data = json.loads(PERSONAS.read_text(encoding="utf-8"))
    human = [p["id"] for p in data["personas"]
             if p.get("labels", {}).get("current_role_id") is not None
             and not str(p["labels"].get("source", "")).startswith("auto")]
    if human and not force:
        sys.exit(f"Personas {human} already have human labels. Not overwriting. Use --force to replace them.")
    if AUDIT.exists() and not force:
        sys.exit(f"{AUDIT.name} exists (maybe already audited). Not overwriting. Use --force.")
    rows = []
    for p in data["personas"]:
        lab = label(p)
        why = lab.pop("_why")
        p["labels"] = lab
        s = summary(p["profile"])
        for rid in [lab["current_role_id"]] + lab["current_role_alternatives"]:
            rows.append([p["id"], s, "current", rid, *_role_cols(rid), why[str(rid)]])
        for kind, ids in (("acceptable_next", lab["acceptable_path_ids"]), ("must_not", lab["must_not_path_ids"])):
            for rid in ids:
                rows.append([p["id"], s, kind, rid, *_role_cols(rid), why[str(rid)]])
        if p["profile"].get("goal"):
            rows.append([p["id"], s, "goal", None, None, None,
                         f"goal '{p['profile']['goal']}' is {'IN' if lab['goal_achievable'] else 'NOT in'} the framework",
                         None, "goal: name match" + (" (TITLE_MAP)" if "goal_query" in TITLE_MAP.get(p["id"], {}) else "")])
        print(f"{p['id']}: current {lab['current_role_id']} (+{len(lab['current_role_alternatives'])} alt), "
              f"{len(lab['acceptable_path_ids'])} acceptable, {len(lab['must_not_path_ids'])} must_not, "
              f"goal {lab['goal_achievable']}")
    PERSONAS.write_text(json.dumps(data, indent=1), encoding="utf-8")
    write_audit(rows)
    print(f"Wrote labels into {PERSONAS.name} and {len(rows)} rows to {AUDIT.relative_to(ROOT)}")


def _role_cols(rid: int) -> list:
    x = ROLES[rid]
    return [x["sector"], x["track"], x["role"], round(LEVEL[rid], 2)]


def audit() -> None:
    ws = load_workbook(AUDIT)["audit"]
    rows = [r for r in ws.iter_rows(min_row=2, values_only=True) if r[0]]
    done = [r for r in rows if str(r[9] or "").strip().upper() in ("Y", "N")]
    if not done:
        sys.exit("No Y/N in the 'agree' column yet.")
    by: dict[str, list] = {}
    for r in done:
        by.setdefault(r[2], []).append(str(r[9]).strip().upper() == "Y")
    agree = sum(sum(v) for v in by.values())
    print(f"Audited {len(done)} of {len(rows)} rows. Reviewer agreed with {agree}/{len(done)} "
          f"= {agree / len(done):.0%} of the auto labels.")
    for k, v in by.items():
        print(f"  {k:16} {sum(v)}/{len(v)} agreed")
    for r in done:
        if str(r[9]).strip().upper() == "N":
            print(f"  DISAGREE {r[0]} {r[2]} [{r[3]}] {r[6]}: {r[10] or '(no comment)'}")
    print("Report this number. If many N's, fix the rule (not single labels), re-run, re-audit.")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["audit"]:
        audit()
    else:
        make(force="--force" in args)
