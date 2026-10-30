"""
Skill-gap agent: its own small LangGraph, so it can be evaluated on its own (E3a).

    compute_gaps (code) -> explain_gaps (AI) -> order_skills (AI)

Contract
    run(current_role_id, target_role_id) -> {gaps, skill_order, usage, notes, fallbacks}

  gaps       lookups.skill_gap(), each with importance (core|supporting) + why
  fallbacks  the steps where code replaced the AI's answer (an E3a metric)

The gap LIST is code and never changes. The AI only labels and orders it,
and code checks both: unknown skills are dropped, missing labels get a
default, and an order that breaks validate_order() is replaced by code_order().
"""
from __future__ import annotations

import operator
from typing import Annotated

from typing_extensions import TypedDict
from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

import llm_steps
from lookups import get_role, get_role_tasks, skill_gap
from plan_rules import code_order, validate_order


class GapState(TypedDict, total=False):
    current_role_id: int
    target_role_id: int
    gaps: list[dict]
    skill_order: list[str]
    usage: Annotated[list[dict], operator.add]
    notes: Annotated[list[str], operator.add]
    fallbacks: Annotated[list[str], operator.add]


def compute_gaps(state: GapState) -> dict:
    return {"gaps": skill_gap(state["current_role_id"], state["target_role_id"])}


def explain_gaps(state: GapState) -> dict:
    """[AI] Label each gap. Code keeps the gap list exactly as computed."""
    gaps = state["gaps"]
    if not gaps:
        return {}
    tid = state["target_role_id"]
    try:
        result, usage = llm_steps.explain_gaps(get_role(tid)["role"], get_role_tasks(tid), gaps)
    except ValueError as e:                        # unparseable output: label nothing, say so
        result, usage = None, getattr(e, "usage", None)
        note = f"explain_gaps: AI output unusable ({str(e)[:120]}...); default labels"
    labels = {n.skill: n for n in result.notes} if result else {}
    unlabelled = [g["skill"] for g in gaps if g["skill"] not in labels]
    out_gaps = [{**g, "importance": labels[g["skill"]].importance if g["skill"] in labels else "supporting",
                 "why": labels[g["skill"]].why.strip() if g["skill"] in labels else ""} for g in gaps]
    out = {"gaps": out_gaps, "usage": [usage] if usage else []}
    if result is None:
        out |= {"notes": [note], "fallbacks": ["explain_gaps"]}
    elif unlabelled:
        out |= {"notes": [f"explain_gaps: AI skipped {len(unlabelled)} skill(s); default labels: {unlabelled}"],
                "fallbacks": ["explain_gaps"]}
    return out


def order_skills(state: GapState) -> dict:
    """[AI] Order same-level skills. Code rejects any order that drops, invents
    or repeats a skill, or puts a higher level first."""
    gaps = state["gaps"]
    if len(gaps) <= 1:
        return {"skill_order": code_order(gaps)}
    try:
        result, usage = llm_steps.order_skills(get_role(state["target_role_id"])["role"], gaps)
    except ValueError as e:        # unparseable output (E1 p11: 49 skills, reply cut off). Recover, log it.
        return {"skill_order": code_order(gaps), "fallbacks": ["order_skills"],
                "usage": llm_steps.failed_usage(e),
                "notes": [f"order_skills: AI output unusable ({str(e)[:120]}...); used rule order"]}
    problem = validate_order(result.order, gaps)
    if problem:
        return {"skill_order": code_order(gaps), "usage": [usage], "fallbacks": ["order_skills"],
                "notes": [f"order_skills: AI order rejected ({problem}); used rule order"]}
    return {"skill_order": result.order, "usage": [usage],
            "notes": [f"order_skills: {result.reason}"]}


def build():
    retry = RetryPolicy(max_attempts=3, retry_on=llm_steps.transient_only)   # transient errors only
    b = StateGraph(GapState)
    b.add_node("compute_gaps", compute_gaps)
    b.add_node("explain_gaps", explain_gaps, retry_policy=retry)
    b.add_node("order_skills", order_skills, retry_policy=retry)
    b.add_edge(START, "compute_gaps")
    b.add_edge("compute_gaps", "explain_gaps")
    b.add_edge("explain_gaps", "order_skills")
    b.add_edge("order_skills", END)
    return b.compile()


GRAPH = build()


def run(current_role_id: int, target_role_id: int) -> dict:
    out = GRAPH.invoke({"current_role_id": current_role_id, "target_role_id": target_role_id})
    return {"gaps": out["gaps"], "skill_order": out["skill_order"], "usage": out.get("usage", []),
            "notes": out.get("notes", []), "fallbacks": out.get("fallbacks", [])}
