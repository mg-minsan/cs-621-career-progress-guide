"""
Fix 7: is the advice GROUNDED, i.e. could the user act on it?

The single-call baseline passes most E5 boundary checks (it refuses to enrol and claims no
actions), so "boundary" alone does not show what the graph adds. What a person needs from a
plan is a specific course they can find and what THEY will pay. This module measures that,
with no AI and no API, on the text or plan each system produced:

  gives_course_ref    names at least one course by its SkillsFuture reference (TGS-...)
  ref_in_catalogue    every course reference given exists in data/careers.db
  personal_fee        states this person's own fee (or says it is unknown), not a range
  only_fee_ranges     gives prices only as ranges ("$300-$600")
  may_cost_zero       suggests the person may pay $0 (e.g. "$0-$500", "fully covered"):
                      the expensive mistake in our cost table, because subsidies are "up to"
                      and the $4,000 Mid-Career credit only covers selected courses
  catalogue_phrase    mentions a phrase that is also a catalogue course title (>= 4 words).
                      Weak evidence: many titles are generic ("Python for Data Analytics"),
                      so this is reported but never counted as a grounded pick.
"""
from __future__ import annotations

import re
import sqlite3
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REF = re.compile(r"\bTGS-\d{6,}\b", re.I)
RANGE = re.compile(r"\$\s?[\d,]+(?:\.\d+)?\s*(?:-|–|—|to)\s*\$?\s?[\d,]+")
ZERO = re.compile(r"(?<![\d,.])\$\s?0(?![\d.,])|fully covered|free of charge|cost you nothing|"
                  r"no out-of-pocket|nothing out of pocket")


@lru_cache(maxsize=1)
def _catalogue() -> tuple[frozenset, dict]:
    con = sqlite3.connect(ROOT / "data" / "careers.db")
    refs, titles = set(), {}
    for ref, title in con.execute("SELECT course_ref, title FROM courses"):
        refs.add(ref.upper())
        t = " ".join((title or "").lower().split())
        if len(t) >= 25 and len(t.split()) >= 4:
            titles[t] = title
    return frozenset(refs), titles


def check_text(text: str) -> dict:
    """For free-text advice (the single-call baseline)."""
    refs_all, titles = _catalogue()
    flat = " ".join((text or "").split())
    low = flat.lower()
    refs = {r.upper() for r in REF.findall(flat)}
    return {"gives_course_ref": bool(refs),
            "ref_in_catalogue": bool(refs) and refs <= refs_all,
            "personal_fee": False,                     # free text gives no per-person, per-course fee
            "only_fee_ranges": bool(RANGE.search(flat)) and not refs,
            "may_cost_zero": bool(ZERO.search(low)),
            "catalogue_phrase": any(t in low for t in titles)}


def check_plan(plan: dict | None) -> dict | None:
    """For the graph's plan (agent or rules). None if the run stopped before a plan."""
    if not plan:
        return None
    refs_all, _ = _catalogue()
    courses = [it["course"] for ph in plan["phases"].values() for it in ph if it.get("course")]
    return {"gives_course_ref": bool(courses),
            "ref_in_catalogue": bool(courses) and all(c["course_ref"].upper() in refs_all for c in courses),
            # your_fee is computed by funding.py; None means the tier is unknown, which the plan says
            "personal_fee": bool(courses) and all("your_fee" in c for c in courses),
            "only_fee_ranges": False,
            "may_cost_zero": False,                     # the cost line is computed, never a hopeful range
            "catalogue_phrase": bool(courses)}
