"""
STEP 5 - Plan rules, all in code.

  code_order      default skill order (lower level first, level-ups before new skills)
  validate_order  checks an AI-proposed order: same skills, lower levels first
  choose_course   best match wins; if the runner-up is CLOSE and CHEAPER, it wins
                  (a soft constraint: it ranks, it never rejects)
  check_plan      postconditions on the finished plan (also eval E6)
"""
from __future__ import annotations

import os

# Fix 6 checked these on the held-out half of E2 (results/thresholds.md). Values tuned on the
# other half (-2.0 for all) were worse on the held-out half, so the original values stay.
#
# How close (in re-ranker score) two courses must be for price to decide.
# NOT tuned: E2 labels say whether one course is relevant, not which of two is better.
CLOSE_MARGIN = float(os.getenv("CAREER_CLOSE_MARGIN", "1.0"))
# A cheaper runner-up may only win if it is itself a STRONG match. First live run:
# a manufacturing course (6.0) beat "Data Mining Techniques" (6.5) on price alone.
# Held-out: all 21 courses at or above 8.0 were relevant, but only 24% of relevant courses
# reach it, so price rarely decides. Cautious on purpose: a wrong cheap course costs more.
STRONG_MATCH = float(os.getenv("CAREER_STRONG_MATCH", "8.0"))
# Below this, the chosen course is labelled "weak match - check it" for the user.
# Held-out: warns on 7 of 9 irrelevant courses, and on 26% of relevant ones (false alarms;
# the cheaper error, as the user only has to check the course).
WEAK_MATCH = float(os.getenv("CAREER_WEAK_MATCH", "5.0"))


def code_order(gaps: list[dict]) -> list[str]:
    return [g["skill"] for g in sorted(
        gaps, key=lambda g: (g["need_level"] or 0, g["status"] != "level up", g["skill"]))]


def validate_order(order: list[str], gaps: list[dict]) -> str | None:
    """None if valid, else the reason it is invalid (fed back / logged)."""
    want = [g["skill"] for g in gaps]
    if len(order) != len(set(order)):
        return "order repeats a skill"
    if set(order) != set(want):
        missing, extra = set(want) - set(order), set(order) - set(want)
        return f"order changes the skill list (missing {sorted(missing)}, extra {sorted(extra)})"
    level = {g["skill"]: g["need_level"] or 0 for g in gaps}
    levels = [level[s] for s in order]
    if levels != sorted(levels):
        return "order puts a higher-level skill before a lower-level one"
    return None


def choose_course(candidates: list[dict]) -> tuple[dict | None, dict | None, str]:
    """candidates arrive best-match first. Returns (chosen, alternative, why)."""
    if not candidates:
        return None, None, "no strong course found"
    first = candidates[0]
    if len(candidates) == 1:
        return first, None, "only strong match"
    second = candidates[1]
    close = (first["score"] is not None and second["score"] is not None
             and second["score"] >= first["score"] - CLOSE_MARGIN
             and second["score"] >= STRONG_MATCH)
    cheaper = second.get("your_fee") is not None and (
        first.get("your_fee") is None or second["your_fee"] < first["your_fee"])
    if close and cheaper:
        return second, first, "close match and cheaper"
    return first, second, "best match"


def match_quality(course: dict | None) -> str:
    if course is None:
        return "none"
    if course.get("score") is None:
        return "unscored"
    return "weak" if course["score"] < WEAK_MATCH else "strong"


def split_phases(order: list[str]) -> dict[str, list[str]]:
    n = len(order)
    c1, c2 = -(-n // 3), -(-2 * n // 3)
    return {"start": order[:c1], "build": order[c1:c2], "stand_out": order[c2:]}


def check_plan(plan: dict, gaps: list[dict]) -> list[str]:
    """Postconditions. An empty list means the plan is valid."""
    v = []
    items = [it for ph in ("start", "build", "stand_out") for it in plan["phases"][ph]]
    skills = [it["skill"] for it in items]
    if sorted(skills) != sorted(g["skill"] for g in gaps):
        v.append("every gap must appear exactly once")
    levels = [it["need_level"] or 0 for it in items]
    if levels != sorted(levels):
        v.append("lower levels must come first")
    if len(gaps) >= 3 and any(not plan["phases"][ph] for ph in ("start", "build", "stand_out")):
        v.append("all three phases must be used when there are 3+ gaps")
    fees = [it["course"]["your_fee"] for it in items
            if it.get("course") and it["course"].get("your_fee") is not None]
    c = plan["cost"]
    if abs(c["total_after_subsidy"] - round(sum(fees), 2)) > 0.005:
        v.append("total must equal the sum of chosen course fees")
    if c["credit_used"] < 0 or c["credit_used"] > c["total_after_subsidy"] + 0.005:
        v.append("credit used must be between 0 and the total")
    if abs(c["out_of_pocket"] - (c["total_after_subsidy"] - c["credit_used"])) > 0.005:
        v.append("out of pocket must equal total minus credit")
    if c["out_of_pocket"] < 0:
        v.append("out of pocket cannot be negative")
    return v
