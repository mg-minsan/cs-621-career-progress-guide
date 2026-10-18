"""The agent: five LangGraph stages, three human checkpoints (week 6 patterns).

  profile -> [confirm role & goal] -> paths -> [choose path] -> gaps -> courses -> plan -> [approve]

* Compute nodes are pure and re-runnable; only the `confirm_*`/`approve` nodes call interrupt(),
  and they do nothing with side effects before it (the resume rule).
* State is a record with a reducer on `trace` so every node leaves its working behind.
* The approve step can also swap a course or change the path, which loops back and replans.
* Nothing here enrols, pays, applies or edits a profile -- there is no tool that could.
"""
from __future__ import annotations

import operator
from typing import Annotated, Any
from typing_extensions import TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from . import tools
from .funding import price_courses
from .llm import rank_paths

PHASES = ("start", "build", "stand_out")


class State(TypedDict, total=False):
    profile: dict
    status: str                       # ok | needs_info | approved
    problems: list[str]
    notices: list[str]
    role_candidates: list[dict]
    role_id: str
    goal: str
    goal_reading: str
    paths: list[dict]
    used_llm: bool
    chosen_id: str
    gaps: list[dict]
    options: dict                     # skill -> ranked course candidates
    swaps: dict                       # skill -> course_id picked by the user
    selection: dict                   # skill -> course_id actually used
    plan: dict
    last_action: str
    trace: Annotated[list, operator.add]


def _log(stage: str, msg: str) -> list[dict]:
    return [{"stage": stage, "msg": msg}]


# ------------------------------------------------------------------ 1 · profile
def profile_node(state: State):
    p = state["profile"]
    problems = tools.check_profile(p)
    if problems:
        return {"status": "needs_info", "problems": problems, "trace": _log("profile", "; ".join(problems))}
    goal = (p.get("goal") or "").strip()
    cands = tools.map_role(p["role"])
    top = [tools.ROLES[r].title for r, sc in sorted(tools.goal_scores(goal).items(), key=lambda x: -x[1])[:2] if sc > 0]
    reading = ("No goal given: I'll suggest realistic roles near yours." if not goal else
               "I read your goal as: " + ", ".join(top) if top else
               "I couldn't tie your goal to a framework role, so I'll suggest nearby roles.")
    return {"status": "ok", "problems": [], "role_candidates": cands, "goal": goal, "goal_reading": reading,
            "notices": tools.boundary_notices(goal),
            "trace": _log("profile", f"'{p['role']}' -> {cands[0]['title']} ({cands[0]['score']})")}


def after_profile(state: State):
    return "confirm_profile" if state["status"] == "ok" else END


def confirm_profile(state: State):                                       # CHECKPOINT 1
    answer = interrupt({"stage": "profile", "candidates": state["role_candidates"],
                        "goal": state["goal"], "goal_reading": state["goal_reading"],
                        "notices": state["notices"]})
    return {"role_id": answer["role_id"], "goal": answer.get("goal", state["goal"]),
            "trace": _log("profile", f"user confirmed role {answer['role_id']}")}


# ------------------------------------------------------------------ 2 · paths
def paths_node(state: State):
    cands = tools.candidate_paths(state["role_id"], state["goal"])
    ranked, used = rank_paths(state["profile"], tools.ROLES[state["role_id"]].title, state["goal"], cands)
    return {"paths": ranked, "used_llm": used,
            "trace": _log("paths", f"{len(cands)} shortlisted, kept {len(ranked)} "
                                   f"({'LLM ranked' if used else 'rule-ranked'})")}


def choose_path(state: State):                                           # CHECKPOINT 2
    answer = interrupt({"stage": "paths", "paths": state["paths"], "used_llm": state["used_llm"]})
    return {"chosen_id": answer["role_id"], "swaps": {},
            "trace": _log("paths", f"user chose {tools.ROLES[answer['role_id']].title}")}


# ------------------------------------------------------------------ 3 · gaps
def gaps_node(state: State):
    gaps = tools.compute_gaps(state["role_id"], state["chosen_id"])
    return {"gaps": gaps, "trace": _log("gaps", f"{len(gaps)} skills to close: "
                                                 + ", ".join(f"{g['skill']} (L{g['need']})" for g in gaps))}


# ------------------------------------------------------------------ 4 · courses
def courses_node(state: State):
    options, selection = {}, {}
    chosen_ids: list[str] = []
    for g in state["gaps"]:                                              # lowest level first
        hits = tools.search_courses(g["skill"], k=5)
        options[g["skill"]] = hits
        pick = (state.get("swaps") or {}).get(g["skill"])
        if not pick and hits:
            top = hits[0]["score"]
            reuse = next((h["course_id"] for h in hits[:3]
                          if h["course_id"] in chosen_ids and h["score"] >= 0.8 * top), None)
            pick = reuse or hits[0]["course_id"]
        if pick:
            selection[g["skill"]] = pick
            if pick not in chosen_ids:
                chosen_ids.append(pick)
    return {"options": options, "selection": selection,
            "trace": _log("courses", f"{len(set(selection.values()))} courses cover {len(selection)} gaps")}


# ------------------------------------------------------------------ 5 · plan
def split_phases(gaps: list[dict]) -> dict[str, list[dict]]:
    """Three consecutive slices of the level-sorted gaps: every gap placed, simpler levels first."""
    n = len(gaps)
    a, b = -(-n // 3), -(-2 * n // 3)
    return {"start": gaps[:a], "build": gaps[a:b], "stand_out": gaps[b:]}


def plan_node(state: State):
    profile, role = state["profile"], tools.ROLES
    phases = split_phases(state["gaps"])
    unique: list[str] = []
    gap_rows = []
    for g in state["gaps"]:
        cid = state["selection"].get(g["skill"])
        gap_rows.append({**g, "course_id": cid})
        if cid and cid not in unique:
            unique.append(cid)
    # courses in the order the phases reach them, each priced once
    order = [r["course_id"] for ph in PHASES for g in phases[ph]
             for r in gap_rows if r["skill"] == g["skill"] and r["course_id"]]
    seen: list[str] = []
    for cid in order:
        if cid not in seen:
            seen.append(cid)
    priced = price_courses([{"id": c.id, "title": c.title, "fee": c.fee, "subsidised": c.subsidised}
                            for c in (tools.COURSES[i] for i in seen)], profile)
    plan = {
        "profile": profile,
        "current_role": role[state["role_id"]].title,
        "target_role": role[state["chosen_id"]].title,
        "paths_considered": [{"role": p["title"], "why": p.get("why", "")} for p in state["paths"]],
        "skill_gaps": gap_rows,
        "courses": [{"id": i, "title": tools.COURSES[i].title, "provider": tools.COURSES[i].provider,
                     "full_fee": tools.COURSES[i].fee, "hours": tools.COURSES[i].hours,
                     "teaches": [s for s, c in state["selection"].items() if c == i]} for i in seen],
        "direction": {ph: [{"skill": g["skill"], "level": g["need"],
                            "course": state["selection"].get(g["skill"])} for g in phases[ph]]
                      for ph in PHASES},
        "cost": priced,
        "approved": False,
    }
    return {"plan": plan, "trace": _log("plan", f"{len(seen)} courses, you pay ${priced['you_pay']:,.2f} "
                                                f"after ${priced['subsidy'] + priced['skillsfuture_credit'] + priced['mid_career_credit']:,.2f} funding")}


def approve(state: State):                                               # CHECKPOINT 3
    answer = interrupt({"stage": "plan", "plan": state["plan"], "options": state["options"],
                        "selection": state["selection"]})
    act = answer.get("action")
    if act == "swap":
        return {"last_action": "swap", "swaps": {**(state.get("swaps") or {}), answer["skill"]: answer["course_id"]},
                "trace": _log("plan", f"user swapped {answer['skill']} -> {answer['course_id']}")}
    if act == "change_path":
        return {"last_action": "change_path", "trace": _log("plan", "user went back to choose another path")}
    return {"status": "approved", "plan": {**state["plan"], "approved": True},
            "trace": _log("plan", "user approved the plan")}


def after_approve(state: State):
    if state.get("status") == "approved":
        return END
    return "plan" if state.get("last_action") == "swap" else "choose_path"


def build_graph(checkpointer=None):
    b = StateGraph(State)
    for name, fn in [("profile", profile_node), ("confirm_profile", confirm_profile), ("paths", paths_node),
                     ("choose_path", choose_path), ("gaps", gaps_node), ("courses", courses_node),
                     ("plan", plan_node), ("approve", approve)]:
        b.add_node(name, fn)
    b.add_edge(START, "profile")
    b.add_conditional_edges("profile", after_profile, {"confirm_profile": "confirm_profile", END: END})
    b.add_edge("confirm_profile", "paths")
    b.add_edge("paths", "choose_path")
    b.add_edge("choose_path", "gaps")
    b.add_edge("gaps", "courses")
    b.add_edge("courses", "plan")
    b.add_edge("plan", "approve")
    b.add_conditional_edges("approve", after_approve, {"plan": "courses", "choose_path": "choose_path", END: END})
    return b.compile(checkpointer=checkpointer or InMemorySaver())


class Session:
    """Thin wrapper the UI and the tests share: start, see what's pending, answer."""

    def __init__(self, thread_id: str = "t1"):
        self.graph = build_graph()
        self.cfg: dict[str, Any] = {"configurable": {"thread_id": thread_id}, "recursion_limit": 40}

    def start(self, profile: dict):
        return self.graph.invoke({"profile": profile, "trace": []}, self.cfg)

    def answer(self, value: dict):
        return self.graph.invoke(Command(resume=value), self.cfg)

    def pending(self) -> dict | None:
        snap = self.graph.get_state(self.cfg)
        for t in snap.tasks:
            if t.interrupts:
                return t.interrupts[0].value
        return None

    @property
    def state(self) -> dict:
        return self.graph.get_state(self.cfg).values
