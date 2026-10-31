"""
STEP 3 - The agent as a LangGraph graph.

    validate -> (ask_missing)* -> read_profile -> confirm_role*
             -> rank_paths -> choose_path* -> skill_gap_agent -> course_agent -> plan
             -> approve_plan* -> finish                (* = interrupt, the user decides)

The two agents are their own small graphs (skill_gap_agent.py, course_agent.py)
with a fixed run() contract, so each can be evaluated on its own (E3).

Design ideas used (cite these in the report):
  - rules in code = edges; the model only decides inside nodes
  - resume rule: a node re-runs from line 1 on resume, so every AI call
      sits in its OWN node, never above an interrupt() (no double billing,
      no different answer on resume)
  - RetryPolicy on AI nodes: retry the node, not the whole run
  - tools and resume values are validated; bad ids fail loudly
  - the final message is a code template, so it cannot claim the agent
      enrolled, paid or applied (E5 b01/b07)
"""
from __future__ import annotations

import functools
import operator
from typing import Annotated, Any

from typing_extensions import TypedDict
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy, interrupt

import course_agent
import llm_steps
import skill_gap_agent

from course_agent import get_index  # noqa: F401  (app.py and run_evals.py warm the index via graph)
from funding import Person, credit_entitlement, plan_cost
from plan_rules import check_plan, choose_course, match_quality, split_phases
from lookups import ToolError, get_role, get_role_tasks, nearby_roles, search_roles, skill_gap

RESIDENCY_ALIASES = {"citizen": "citizen", "sc": "citizen", "singaporean": "citizen",
                     "singapore citizen": "citizen", "pr": "pr", "spr": "pr",
                     "permanent resident": "pr", "other": "other", "foreigner": "other"}
MAX_ASKS = 3


class State(TypedDict, total=False):
    profile: dict
    missing: list[str]
    role_candidates: list[dict]
    reading: dict                 # ProfileReading as dict
    current_role_id: int
    path_candidates: list[dict]
    paths: list[dict]
    goal_status: str             # matched | not_found | none  (E1 p12)
    goal_message: str
    target_role_id: int
    gaps: list[dict]
    courses: dict
    skill_order: list[str]
    plan: dict
    decision: dict
    final_message: str
    checkpoints: Annotated[list[str], operator.add]   # E5 asserts on this
    usage: Annotated[list[dict], operator.add]        # tokens + cost per AI call
    notes: Annotated[list[str], operator.add]
    fallbacks: Annotated[list[str], operator.add]     # agent steps where code replaced the AI
    spend_capped: bool                                # Fix 3: the budget stopped at least one AI call


# --------------------------------------------------------------------------
# 0. Validate the profile (code) and ask for anything missing (human)
# --------------------------------------------------------------------------
def validate(state: State) -> dict:
    p = dict(state["profile"])
    missing = []
    if not str(p.get("role") or "").strip():
        missing.append("role")
    res = RESIDENCY_ALIASES.get(str(p.get("residency") or "").strip().lower())
    if res is None:
        missing.append("residency (citizen, pr or other)")
    else:
        p["residency"] = res
    try:
        age = int(p.get("age"))
        if not 16 <= age <= 100:
            raise ValueError
        p["age"] = age
    except (TypeError, ValueError):
        missing.append("age (a number from 16 to 100)")
    bal = p.get("credit_balance")
    if bal is not None:                            # "abc" or -100 used to crash later (fix 1)
        try:
            bal = float(bal)
            if bal < 0:
                raise ValueError
            p["credit_balance"] = bal
        except (TypeError, ValueError):
            missing.append("credit_balance (a dollar amount, 0 or more; leave it out if unsure)")
            bal = None
    if bal is not None and res and "age (a number from 16 to 100)" not in missing:
        if bal > credit_entitlement(Person(res, p["age"])):
            missing.append("credit_balance (higher than anyone this age can have; please check)")
    return {"profile": p, "missing": missing}


def route_after_validate(state: State) -> str:
    return "ask_missing" if state["missing"] else "read_profile"


def ask_missing(state: State) -> dict:
    asks = state.get("checkpoints", []).count("ask_missing_info")
    if asks >= MAX_ASKS:
        raise ToolError(f"Still missing after {MAX_ASKS} asks: {state['missing']}. Stopping.")
    answer = interrupt({"checkpoint": "ask_missing_info", "missing": state["missing"],
                        "message": "I need a few details before I can plan: " + ", ".join(state["missing"])})
    # NOTE: resume with a NON-EMPTY dict. LangGraph reads an empty dict as
    # "no answer" and pauses again. Use {"credit_balance": None} for "I don't know".
    if not isinstance(answer, dict):
        raise ToolError("Resume ask_missing_info with a dict of field -> value.")
    profile = {**state["profile"], **answer}
    if "credit_balance" in str(state["missing"]) and "credit_balance" not in answer:
        profile.pop("credit_balance", None)   # user did not confirm it: treat as unknown
    return {"profile": profile, "checkpoints": ["ask_missing_info"]}


# --------------------------------------------------------------------------
# 1. Read the profile: role + goal (AI), then the user confirms (human)
# --------------------------------------------------------------------------
def read_profile(state: State) -> dict:
    cands = search_roles(state["profile"]["role"], limit=8)
    extra = {}
    try:
        reading, usage = llm_steps.read_profile(state["profile"], cands)
        usage = [usage]
    except ValueError as e:                        # unusable reply: degrade to the rules, never crash
        reading, usage = llm_steps.rules_read_profile(state["profile"], cands), llm_steps.failed_usage(e)
        extra = {"fallbacks": ["read_profile"],
                 "notes": [f"read_profile: AI output unusable ({str(e)[:120]}...); used rules"]}
    r = reading.model_dump()
    if r["role_id"] is not None and r["role_id"] not in {c["role_id"] for c in cands}:
        r["role_id"] = None   # model picked off the menu: ignore it, user will choose
        r["role_reason"] += " (model choice was not in the shortlist; ignored)"
    return {"role_candidates": cands, "reading": r, "usage": usage, **extra}


def confirm_role(state: State) -> dict:
    r, cands = state["reading"], state["role_candidates"]
    payload = {"checkpoint": "confirm_role", "suggested_role_id": r["role_id"],
               "confidence": r["role_confidence"], "reason": r["role_reason"],
               "candidates": [{k: c[k] for k in ("role_id", "sector", "role", "score")} for c in cands],
               "goal_titles": r["goal_target_titles"], "cannot_do": r["out_of_scope"]}
    for _ in range(MAX_ASKS):                     # multiple interrupts in one node are fine
        answer = interrupt(payload)
        try:
            role_id = int(answer["role_id"])
            get_role(role_id)                      # raises on a bad id
            goal = answer.get("goal_titles", r["goal_target_titles"])
            return {"current_role_id": role_id,
                    "reading": {**r, "goal_target_titles": goal},
                    "checkpoints": ["confirm_role"]}
        except (KeyError, TypeError, ValueError, ToolError) as e:
            payload = {**payload, "error": f"Invalid answer ({e}). Reply with a valid role_id."}
    raise ToolError("No valid role confirmed.")


# --------------------------------------------------------------------------
# 2. Paths: shortlist (code), rank (AI), user picks (human)
# --------------------------------------------------------------------------
def gap_counts(cur: int, target: int) -> dict:
    """'3 new + 16 level-ups' is honest; '19 skills to close' is not (Step 3 finding)."""
    g = skill_gap(cur, target)
    new = sum(1 for x in g if x["status"] == "missing")
    return {"gap_size": len(g), "new_skills": new, "level_ups": len(g) - new}


def rank_paths(state: State) -> dict:
    cur = state["current_role_id"]
    seen, cands = {cur}, []
    for title in state["reading"]["goal_target_titles"]:
        for c in search_roles(title, limit=4):
            if c["score"] >= 0.6 and c["role_id"] not in seen:
                seen.add(c["role_id"])
                cands.append({**c, "source": "goal"})
    for c in nearby_roles(cur, limit=8):
        if c["role_id"] not in seen:
            seen.add(c["role_id"])
            cands.append({**c, "source": "skill overlap"})
    if not cands:
        raise ToolError("No candidate paths found for this role.")
    paths, notes, fallbacks = [], [], []
    try:
        ranking, usage = llm_steps.rank_paths(state["profile"], get_role(cur), cands,
                                              state["reading"]["goal_target_titles"])
        usage = [usage]
    except ValueError as e:                        # unusable reply: degrade to the rules, never crash
        ranking, usage = llm_steps.rules_rank_paths(cands), llm_steps.failed_usage(e)
        fallbacks.append("rank_paths")
        notes.append(f"rank_paths: AI output unusable ({str(e)[:120]}...); used rules")
    by_id = {c["role_id"]: c for c in cands}
    for p in ranking.paths:
        if p.role_id in by_id:                     # code enforces the menu
            paths.append({**by_id[p.role_id], "kind": p.kind, "reason": p.reason,
                          **gap_counts(cur, p.role_id)})
        else:
            notes.append(f"rank_paths: model returned role {p.role_id} not in shortlist; dropped")
    goal_ids = [c["role_id"] for c in cands if c["source"] == "goal"]
    if goal_ids and not any(p["role_id"] in goal_ids for p in paths):   # rule in code, not prompt
        g = by_id[goal_ids[0]]
        paths.insert(0, {**g, "kind": "goal_match", "reason": "Matches the goal you stated.",
                         **gap_counts(cur, g["role_id"])})
        notes.append("rank_paths: goal match was missing; added by rule")
    titles = state["reading"]["goal_target_titles"]
    if not titles:
        status, msg = "none", ""
    elif goal_ids:
        status, msg = "matched", ""
    else:                                          # say so, never quietly drop a goal
        status = "not_found"
        msg = (f"Your goal ({', '.join(titles)}) does not match any role in the SkillsFuture "
               "Skills Framework, so these are nearby roles instead.")
    return {"path_candidates": cands, "paths": paths[:3], "usage": usage, "notes": notes,
            "fallbacks": fallbacks, "goal_status": status, "goal_message": msg}


def choose_path(state: State) -> dict:
    payload = {"checkpoint": "choose_path", "paths": state["paths"],
               "goal_status": state.get("goal_status", "none"),
               "goal_message": state.get("goal_message", "")}
    for _ in range(MAX_ASKS):
        answer = interrupt(payload)
        try:
            rid = int(answer["role_id"])
            get_role(rid)
            if rid == state["current_role_id"]:    # a 0-skill, $0 "plan" helps nobody (fix 1)
                raise ValueError("that is your current role; pick a different one")
            return {"target_role_id": rid, "checkpoints": ["choose_path"]}
        except (KeyError, TypeError, ValueError, ToolError) as e:
            payload = {**payload, "error": f"Invalid answer ({e}). Reply with a valid role_id."}
    raise ToolError("No valid path chosen.")


# --------------------------------------------------------------------------
# 3-5. Skill-gap agent, course agent, plan (code), approval (human)
#      Wrappers map fields explicitly: adding the compiled subgraphs as nodes
#      would hand back their usage/notes lists and the reducers would count them twice.
# --------------------------------------------------------------------------
def skill_gap_agent_node(state: State) -> dict:
    out = skill_gap_agent.run(state["current_role_id"], state["target_role_id"])
    return {"gaps": out["gaps"], "skill_order": out["skill_order"], "usage": out["usage"],
            "notes": out["notes"], "fallbacks": out["fallbacks"]}


def course_agent_node(state: State) -> dict:
    out = course_agent.run([g["skill"] for g in state["gaps"]], state["profile"],
                           target_role=get_role(state["target_role_id"])["role"])   # Fix 2
    return {"courses": out["courses"], "usage": out["usage"], "notes": out["notes"],
            "fallbacks": out["fallbacks"]}


def picked(found: dict) -> tuple[dict | None, dict | None, str]:
    """The course agent's pick, or the rule pick if it has none."""
    by_ref = {c["course_ref"]: c for c in found.get("courses", [])}
    if found.get("chosen_ref") in by_ref:
        return by_ref[found["chosen_ref"]], by_ref.get(found.get("alternative_ref")), found.get("pick_reason", "")
    return choose_course(found.get("courses", []))


def plan(state: State) -> dict:
    """Stage 5b [code]: pick one course per skill, split into phases, cost it,
    then check postconditions. A plan that breaks a rule is never shown."""
    gap_by_skill = {g["skill"]: g for g in state["gaps"]}
    phases = {}
    for name, skills in split_phases(state["skill_order"]).items():
        items = []
        for sk in skills:
            found = state["courses"].get(sk, {})
            chosen, alt, why = picked(found)
            items.append({**gap_by_skill[sk], "course": chosen, "alternative": alt,
                          "why_this_course": why, "match_quality": match_quality(chosen), "search_status": found.get("status"),
                          "message": found.get("message")})
        phases[name] = items
    chosen = [it["course"] for ph in phases.values() for it in ph if it["course"]]
    p = state["profile"]
    cost = plan_cost(Person(p["residency"], p["age"], p.get("credit_balance")),
                     [c.get("your_fee") for c in chosen])
    new = sum(1 for g in state["gaps"] if g["status"] == "missing")
    target_role = get_role(state["target_role_id"])
    result = {"current_role": get_role(state["current_role_id"])["role"],
              "target_role": target_role["role"],
              "target_role_description": target_role.get("description") or "",
              "target_role_tasks": get_role_tasks(state["target_role_id"]),
              "gap_summary": {"new_skills": new, "level_ups": len(state["gaps"]) - new},
              "phases": phases, "cost": cost,
              "total_hours": round(sum(c.get("hours") or 0 for c in chosen), 1),
              "spend": {"ai_cost_usd": round(spent(state), 4), "cap_usd": llm_steps.MAX_RUN_USD,
                        "capped": bool(state.get("spend_capped"))}}
    violations = check_plan(result, state["gaps"])
    if violations:                                 # postcondition: fail loudly
        raise ToolError(f"Plan failed its checks: {violations}")
    return {"plan": result}


def approve_plan(state: State) -> dict:
    answer = interrupt({"checkpoint": "approve_plan", "plan": state["plan"]})
    approved = bool(answer.get("approved")) if isinstance(answer, dict) else False
    return {"decision": {"approved": approved,
                         "feedback": answer.get("feedback", "") if isinstance(answer, dict) else ""},
            "checkpoints": ["approve_plan"]}


def finish(state: State) -> dict:
    """Code template, not AI: it cannot claim actions the agent never took."""
    p, cannot = state["plan"], state["reading"].get("out_of_scope", [])
    c = p["cost"]
    lines = [f"Your plan: {p['current_role']} -> {p['target_role']}.",
             f"Estimated cost after subsidies and credit: ${c['out_of_pocket']:,.2f} "
             f"(rules checked {c['rules_checked_on']})."]
    if state.get("goal_message"):
        lines.append(state["goal_message"])
    if state.get("spend_capped"):
        lines.append(f"To stay within the ${llm_steps.MAX_RUN_USD:.2f} AI budget for one plan, "
                     "some steps used the simpler rule-based version.")
    lines.append("You approved this plan." if state["decision"]["approved"]
                 else "You did not approve this plan, so nothing has been saved.")
    if cannot:
        lines.append("I can't do these for you: " + "; ".join(cannot)
                     + ". I only advise; enrolling, paying and applying are up to you.")
    return {"final_message": " ".join(lines)}


# --------------------------------------------------------------------------
# Fix 3: spend cap per plan (week 8: "a budget per run, held by the loop")
# --------------------------------------------------------------------------
def spent(state: State) -> float:
    return sum(u.get("cost_usd", 0) for u in state.get("usage", []))


def with_budget(node):
    """Run an AI step inside the plan's budget. A call that could go past the cap is
    never sent; that step uses its rules version, and the user is told."""
    @functools.wraps(node)
    def run(state: State):
        with llm_steps.budget(spent(state)) as ledger:
            out = node(state)
        if ledger["capped"] and isinstance(out, dict):
            out = {**out, "spend_capped": True}
        return out
    return run


# --------------------------------------------------------------------------
def build(checkpointer=None):
    retry = RetryPolicy(max_attempts=3, retry_on=llm_steps.transient_only)   # transient errors only
    b = StateGraph(State)
    b.add_node("validate", validate)
    b.add_node("ask_missing", ask_missing)
    b.add_node("read_profile", with_budget(read_profile), retry_policy=retry)
    b.add_node("confirm_role", confirm_role)
    b.add_node("rank_paths", with_budget(rank_paths), retry_policy=retry)
    b.add_node("choose_path", choose_path)
    b.add_node("skill_gap_agent", with_budget(skill_gap_agent_node))    # AI retries live inside each agent
    b.add_node("course_agent", with_budget(course_agent_node))
    b.add_node("plan", plan)
    b.add_node("approve_plan", approve_plan)
    b.add_node("finish", finish)
    b.add_edge(START, "validate")
    b.add_conditional_edges("validate", route_after_validate,
                            {"ask_missing": "ask_missing", "read_profile": "read_profile"})
    b.add_edge("ask_missing", "validate")
    for a, z in [("read_profile", "confirm_role"), ("confirm_role", "rank_paths"),
                 ("rank_paths", "choose_path"), ("choose_path", "skill_gap_agent"),
                 ("skill_gap_agent", "course_agent"), ("course_agent", "plan"), ("plan", "approve_plan"), ("approve_plan", "finish"),
                 ("finish", END)]:
        b.add_edge(a, z)
    return b.compile(checkpointer=checkpointer or InMemorySaver())


def config(thread_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id}, "recursion_limit": 40}
