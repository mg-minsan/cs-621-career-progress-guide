"""
Course agent: its own small LangGraph, so it can be evaluated on its own (E3b).

    search (code) -> [rewrite_queries (AI) -> retry_search (code)] -> pick_courses (AI)
                      only when some skill has no strong match

Contract
    run(skills, person) -> {courses, usage, notes, fallbacks}

  courses    {skill: {status, query, courses[+your_fee, schemes], message?,
                      chosen_ref, alternative_ref, pick_reason}}
             status: title | broadened | widened | rewritten | no_strong_match
  fallbacks  the steps where code replaced the AI's answer (an E3b metric)

What the AI may NOT decide: what counts as a strong match (strong_hits() and
RERANK_GOOD, in code) and the fee (funding.py). It proposes queries and picks
from the candidates code found; a course_ref that is not on that skill's list
is replaced by plan_rules.choose_course().

Cost here is before SkillsFuture Credit; credit is applied once across the
whole plan in graph.plan() (otherwise it would be counted per course).
"""
from __future__ import annotations

import operator
import os
from typing import Annotated

from typing_extensions import TypedDict
from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

import llm_steps
from course_search import CourseIndex, find_courses_for_skill, strong_hits
from funding import FundingError, Person, course_cost, infer_tier
from lookups import skill_description
from plan_rules import choose_course

N_CANDIDATES = 4        # what the AI chooses from (choose_course only ever compares the top 2)
MAX_QUERIES = 3
PICK_CHUNK = 12         # skills per pick call, so a long gap list cannot run past max_tokens

_INDEX: CourseIndex | None = None


def get_index() -> CourseIndex:
    """Built once per process (loading 26k courses + models takes a few seconds)."""
    global _INDEX
    if _INDEX is None:
        _INDEX = CourseIndex(mode=os.getenv("CAREER_SEARCH_MODE", "hybrid_rerank"))
    return _INDEX


def reset_index() -> None:
    global _INDEX
    _INDEX = None


class CourseState(TypedDict, total=False):
    skills: list[dict]            # [{skill, description}]
    person: dict                  # {residency, age}
    found: dict
    rewrites: dict                # skill -> [query]
    usage: Annotated[list[dict], operator.add]
    notes: Annotated[list[str], operator.add]
    fallbacks: Annotated[list[str], operator.add]


def add_fees(courses: list[dict], person: Person) -> list[dict]:
    for c in courses:
        tier = infer_tier(c["full_fee"], c["fee_after_subsidy"])
        try:
            cost = course_cost(person, c["full_fee"], tier, use_credit=False)
            c["your_fee"], c["schemes"] = cost.out_of_pocket, cost.schemes
        except FundingError as e:                # unknown tier: say so, never guess
            c["your_fee"], c["schemes"] = None, [str(e)]
    return courses


def _person(state: CourseState) -> Person:
    return Person(state["person"]["residency"], state["person"]["age"])


def search(state: CourseState) -> dict:
    idx, person, found = get_index(), _person(state), {}
    for s in state["skills"]:
        res = find_courses_for_skill(idx, s["skill"], s["description"], n=N_CANDIDATES)
        add_fees(res["courses"], person)
        found[s["skill"]] = res
    return {"found": found}


def route_after_search(state: CourseState) -> str:
    misses = any(r["status"] == "no_strong_match" for r in state["found"].values())
    return "rewrite_queries" if misses else "pick_courses"


def rewrite_queries(state: CourseState) -> dict:
    """[AI] New queries for the misses only. Code trims, dedupes and caps them."""
    desc = {s["skill"]: s["description"] for s in state["skills"]}
    misses = [{"skill": k, "description": desc.get(k, ""), "tried": r["query"]}
              for k, r in state["found"].items() if r["status"] == "no_strong_match"]
    try:
        result, usage = llm_steps.rewrite_queries(misses)
    except ValueError as e:
        return {"rewrites": {}, "fallbacks": ["rewrite_queries"],
                "notes": [f"rewrite_queries: AI output unusable ({str(e)[:120]}...); no rewrites"]}
    wanted, rewrites = {m["skill"] for m in misses}, {}
    for r in result.rewrites:
        if r.skill not in wanted:                  # code enforces the menu
            continue
        qs = list(dict.fromkeys(q.strip() for q in r.queries if q.strip()))
        if qs:
            rewrites[r.skill] = qs[:MAX_QUERIES]
    return {"rewrites": rewrites, "usage": [usage]}


def retry_search(state: CourseState) -> dict:
    """[code] Same strong-match bar as the first search."""
    idx, person, found, rescued = get_index(), _person(state), dict(state["found"]), []
    for skill, queries in state.get("rewrites", {}).items():
        for q in queries:
            strong = strong_hits(idx, q, N_CANDIDATES)
            if strong:
                found[skill] = {"skill": skill, "status": "rewritten", "query": q,
                                "courses": add_fees(strong, person)}
                rescued.append(skill)
                break
    notes = [f"rewrite_queries: rescued {len(rescued)} skill(s): {rescued}"] if rescued else []
    return {"found": found, "notes": notes}


def _alternative(cands: list[dict], chosen: dict) -> dict | None:
    return next((c for c in cands if c["course_ref"] != chosen["course_ref"]), None)


def pick_courses(state: CourseState) -> dict:
    """[AI] One course per skill, from that skill's own list only."""
    found = {k: dict(v) for k, v in state["found"].items()}
    items = [{"skill": k, "candidates": r["courses"]} for k, r in found.items() if r["courses"]]
    if not items:
        return {"found": found}
    picks, out = {}, {"usage": [], "notes": []}
    for i in range(0, len(items), PICK_CHUNK):    # 49 picks in one reply was cut off (E1 p11)
        try:
            result, usage = llm_steps.pick_courses(items[i:i + PICK_CHUNK])
            picks |= {p.skill: p for p in result.picks}
            out["usage"].append(usage)
        except ValueError as e:
            out["notes"].append(f"pick_courses: AI output unusable ({str(e)[:120]}...); rule picks")
    replaced = []
    for it in items:
        cands = it["candidates"]
        by_ref = {c["course_ref"]: c for c in cands}
        p = picks.get(it["skill"])
        if p and p.course_ref in by_ref:
            chosen, why = by_ref[p.course_ref], p.reason
            alt = _alternative(cands, chosen)
        else:                                      # off the menu or skipped: rule pick
            chosen, alt, why = choose_course(cands)
            replaced.append(it["skill"])
        found[it["skill"]] |= {"chosen_ref": chosen["course_ref"],
                               "alternative_ref": alt["course_ref"] if alt else None,
                               "pick_reason": why}
    out["found"] = found
    if replaced:
        out["fallbacks"] = ["pick_courses"]
        if picks:
            out["notes"].append(f"pick_courses: AI pick missing or off the list for {replaced}; used rule pick")
    return out


def build():
    retry = RetryPolicy(max_attempts=3)            # transient API errors
    b = StateGraph(CourseState)
    b.add_node("search", search)
    b.add_node("rewrite_queries", rewrite_queries, retry_policy=retry)
    b.add_node("retry_search", retry_search)
    b.add_node("pick_courses", pick_courses, retry_policy=retry)
    b.add_edge(START, "search")
    b.add_conditional_edges("search", route_after_search,
                            {"rewrite_queries": "rewrite_queries", "pick_courses": "pick_courses"})
    b.add_edge("rewrite_queries", "retry_search")
    b.add_edge("retry_search", "pick_courses")
    b.add_edge("pick_courses", END)
    return b.compile()


GRAPH = build()


def run(skills: list[str], person: dict) -> dict:
    """skills: gap skill names; person: {residency, age}."""
    out = GRAPH.invoke({"skills": [{"skill": s, "description": skill_description(s)} for s in skills],
                        "person": {"residency": person["residency"], "age": person["age"]}})
    found = out["found"]
    misses = [s for s, r in found.items() if r["status"] == "no_strong_match"]
    notes = out.get("notes", [])
    if misses:
        notes = notes + [f"courses: no strong match for {len(misses)} skill(s): {misses}"]
    return {"courses": found, "usage": out.get("usage", []), "notes": notes,
            "fallbacks": out.get("fallbacks", [])}
