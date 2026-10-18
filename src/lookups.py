"""
Plain Python lookups over data/careers.db.

These are deliberately NOT AI. A rule in code runs every time;
a rule in a prompt is a request. Later (Step 3) we wrap these as LangChain
@tool functions so the agent can call them, and so the eval harness can call
them directly to build ground truth.

Tools must fail LOUDLY. A wrong role id raises ToolError with
the valid options, instead of quietly returning an empty list.
"""
from difflib import SequenceMatcher
from pathlib import Path
import re
import sqlite3

DB = Path(__file__).resolve().parent.parent / "data" / "careers.db"


class ToolError(Exception):
    """Raised with a message the model can act on (what to feed back)."""


def _con() -> sqlite3.Connection:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z]+", text.lower())) - {"and", "of", "the", "a"}


# --------------------------------------------------------------------------
# Stage 1 - map a free-text job title to framework roles
# --------------------------------------------------------------------------
def find_roles(title: str, limit: int = 5) -> list[dict]:
    """Return the closest framework roles to a free-text job title, with a
    0-1 score. Several sectors can share a name, so the CALLER (agent, then
    user) must pick one - this is your 'You confirm role' checkpoint."""
    if not title or not title.strip():
        raise ToolError("Empty job title. Ask the user for their current job title.")
    query = title.lower().strip()
    qwords = _words(query)
    with _con() as con:
        rows = con.execute("SELECT role_id, sector, track, role FROM roles").fetchall()
    scored = []
    for r in rows:
        # A role name can hold several titles: "Accounts Executive / Accounts Assistant"
        best = 0.0
        for part in r["role"].split("/"):
            part = part.strip().lower()
            ratio = SequenceMatcher(None, query, part).ratio()
            overlap = len(qwords & _words(part)) / max(len(qwords), 1)
            best = max(best, 0.5 * ratio + 0.5 * overlap)
        scored.append({**dict(r), "score": round(best, 3)})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:limit]


# Step 8 fix (found by E1 failure analysis, 2026-10-18): the framework writes some
# job words differently from how people say them. Applied to the AGENT's searches
# only (search_roles). The E1 answer key (e1_auto_labels.py) still uses plain
# find_roles, so this fix cannot change the labels it is scored against.
SYNONYMS = [
    (r"\bhuman resources?\b", "hr"),
    (r"\bai\b", "artificial intelligence"),
    (r"\bf\s*&\s*b\b|\bfood and beverage\b", "service"),
    (r"\brestaurant\b", "outlet"),
]


def expand_title(title: str) -> list[str]:
    """The title itself, plus one variant in framework wording (if any word changes)."""
    import re
    t = title.lower().strip()
    v = t
    for pat, rep in SYNONYMS:
        v = re.sub(pat, rep, v)
    v = re.sub(r"\s+", " ", v).strip()
    return [t] if v == t else [t, v]


def search_roles(title: str, limit: int = 5) -> list[dict]:
    """Agent-side role search. Best score per role over:
    - the title and its framework-wording variant (SYNONYMS), matched on the job name, and
    - ONLY if no job name matches exactly: the same queries matched on "sector + job name",
      because some sectors leave the field out of the name (Human Resource: "Executive,
      Performance and Rewards"). Doing it always crowded exact matches (Logistics Coordinator)."""
    if not title or not title.strip():
        raise ToolError("Empty job title. Ask the user for their current job title.")
    best: dict[int, dict] = {}
    for q in expand_title(title):
        for r in find_roles(q, limit=limit * 3):
            if r["role_id"] not in best or r["score"] > best[r["role_id"]]["score"]:
                best[r["role_id"]] = r
    if best and max(r["score"] for r in best.values()) >= 0.95:
        return sorted(best.values(), key=lambda x: (-x["score"], x["role_id"]))[:limit]   # exact name: done
    with _con() as con:
        rows = con.execute("SELECT role_id, sector, track, role FROM roles").fetchall()
    for q in expand_title(title):
        qwords = _words(q)
        if len(qwords) < 2:                      # one word + a sector name matches too much
            continue
        for r in rows:
            sector = r["sector"].lower()
            if not (qwords & _words(sector)):    # only when the query names the sector
                continue
            s = 0.0
            for part in r["role"].split("/"):
                text = f"{sector} {part.strip().lower()}"
                s = max(s, 0.5 * SequenceMatcher(None, q, text).ratio()
                        + 0.5 * len(qwords & _words(text)) / max(len(qwords), 1))
            s = round(s, 3)
            if r["role_id"] not in best or s > best[r["role_id"]]["score"]:
                best[r["role_id"]] = {**dict(r), "score": s}
    return sorted(best.values(), key=lambda x: (-x["score"], x["role_id"]))[:limit]


def get_role(role_id: int) -> dict:
    with _con() as con:
        row = con.execute("SELECT * FROM roles WHERE role_id = ?", (role_id,)).fetchone()
    if row is None:
        raise ToolError(f"No role with id {role_id}. Use find_roles to get a valid id.")
    return dict(row)


# --------------------------------------------------------------------------
# Stage 2 - nearby roles (candidate paths)
# --------------------------------------------------------------------------
def role_skills(role_id: int) -> dict[str, dict]:
    """unique_skill -> {level, type, title}. Highest level kept if a skill repeats."""
    get_role(role_id)  # raises loudly on a bad id
    with _con() as con:
        rows = con.execute(
            "SELECT unique_skill, skill_title, skill_type, level_num "
            "FROM role_skills WHERE role_id = ?", (role_id,)).fetchall()
    out: dict[str, dict] = {}
    for r in rows:
        prev = out.get(r["unique_skill"])
        if prev is None or (r["level_num"] or 0) > (prev["level"] or 0):
            out[r["unique_skill"]] = {"level": r["level_num"], "type": r["skill_type"],
                                      "title": r["skill_title"]}
    return out


def nearby_roles(role_id: int, limit: int = 10, min_overlap: float = 0.2) -> list[dict]:
    """Roles that share the most skills with this one (Jaccard overlap).
    High overlap = realistic step-up; low overlap = career switch.
    NOTE: overlap is a HEURISTIC, not ground truth for 'realistic next step'
    (see eval E1 - labels must come from sector guides or hand labelling)."""
    mine = set(role_skills(role_id))
    with _con() as con:
        rows = con.execute(
            "SELECT rs.role_id, r.sector, r.track, r.role, rs.unique_skill "
            "FROM role_skills rs JOIN roles r USING(role_id) WHERE rs.role_id != ?",
            (role_id,)).fetchall()
    by_role: dict[int, dict] = {}
    for r in rows:
        entry = by_role.setdefault(r["role_id"], {"role_id": r["role_id"], "sector": r["sector"],
                                                  "track": r["track"], "role": r["role"],
                                                  "skills": set()})
        entry["skills"].add(r["unique_skill"])
    results = []
    for e in by_role.values():
        jac = len(mine & e["skills"]) / len(mine | e["skills"])
        if jac >= min_overlap:
            results.append({k: e[k] for k in ("role_id", "sector", "track", "role")}
                           | {"overlap": round(jac, 3)})
    results.sort(key=lambda x: x["overlap"], reverse=True)
    return results[:limit]


# --------------------------------------------------------------------------
# Stage 3 - skill gap between current role and chosen target role
# --------------------------------------------------------------------------
def skill_gap(current_role_id: int, target_role_id: int) -> list[dict]:
    """Skills the target role needs that the user lacks, or has at a lower
    level. Sorted lowest level first (feeds the start -> build -> stand out
    ordering in Step 5). Deterministic: the eval can recompute it exactly."""
    have = role_skills(current_role_id)
    need = role_skills(target_role_id)
    gaps = []
    for skill, req in need.items():
        cur = have.get(skill)
        cur_level = cur["level"] if cur else 0
        if (req["level"] or 0) > (cur_level or 0):
            gaps.append({"skill": skill, "type": req["type"],
                         "need_level": req["level"], "have_level": cur_level,
                         "status": "missing" if cur is None else "level up"})
    gaps.sort(key=lambda g: (g["need_level"] or 0, g["skill"]))
    return gaps


if __name__ == "__main__":
    # Quick smoke test: run `python src/lookups.py`
    print("find_roles('Accounts Executive'):")
    for r in find_roles("Accounts Executive", 3):
        print(f"  {r['score']:.2f}  [{r['role_id']}] {r['sector']} / {r['role']}")
    print("\nfind_roles('data analyst') - note the same title in several sectors:")
    for r in find_roles("data analyst", 5):
        print(f"  {r['score']:.2f}  [{r['role_id']}] {r['sector']} / {r['role']}")


def skill_description(skill_title: str) -> str:
    """Framework description of a skill (used to broaden course searches)."""
    with _con() as con:
        row = con.execute("SELECT description FROM skills WHERE skill_title = ? "
                          "AND description IS NOT NULL LIMIT 1", (skill_title,)).fetchone()
    return row["description"] if row else ""
