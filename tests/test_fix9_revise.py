"""Fix 9: "Not for me" is no longer a dead end. Feedback revises the plan (max 2 times);
the AI only maps feedback onto a fixed menu; code applies it and re-checks the plan.
Offline: rules mode, or a patched model call."""
import os
import sys
import uuid
from pathlib import Path

os.environ["CAREER_FAKE"] = "1"
os.environ["CAREER_SEARCH_MODE"] = "bm25"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from langgraph.types import Command  # noqa: E402

import llm_steps  # noqa: E402
from graph import MAX_REVISIONS, build, config  # noqa: E402
from llm_steps import PlanFeedback, rules_read_feedback  # noqa: E402

PROFILE = {"role": "Accounts Executive", "age": 41, "residency": "citizen",
           "status": "employed", "goal": "move into data analyst", "credit_balance": 0}


def _to_plan():
    g, cfg = build(), config(uuid.uuid4().hex)
    g.invoke({"profile": PROFILE}, cfg)
    g.invoke(Command(resume={"role_id": 14}), cfg)
    out = g.invoke(Command(resume={"role_id": 723}), cfg)
    return g, cfg, out["__interrupt__"][0].value


def _say(g, cfg, feedback):
    return g.invoke(Command(resume={"approved": False, "feedback": feedback}), cfg)


def _items(plan):
    return [it for ph in plan["phases"].values() for it in ph]


def test_rules_reading_of_feedback():
    skills = ["Data Visualisation", "Programming and Coding"]
    assert rules_read_feedback("too expensive", skills).prefer == "cheaper"
    assert rules_read_feedback("I'm busy, less time please", skills).prefer == "shorter"
    assert rules_read_feedback("skip programming and coding, I know it", skills).drop_skills == ["Programming and Coding"]
    assert rules_read_feedback("show me a different job", skills).action == "change_path"
    assert rules_read_feedback("stop", skills).action == "stop"


def test_cheaper_revision_never_costs_more_and_passes_checks():
    g, cfg, first = _to_plan()
    out = _say(g, cfg, "too expensive, something cheaper")
    second = out["__interrupt__"][0].value["plan"]           # plan() ran check_plan again: it passed
    assert second["revision"] == 1 and second["prefer"] == "cheaper"
    assert second["cost"]["total_after_subsidy"] <= first["plan"]["cost"]["total_after_subsidy"]
    first_refs = {it["skill"]: {c["course_ref"] for c in [it["course"], it["alternative"]] if c} for it in _items(first["plan"])}
    for it in _items(second):                                 # no new course can appear
        assert it["course"] is None or it["course"]["course_ref"] in first_refs[it["skill"]] | {
            c["course_ref"] for c in g.get_state(cfg).values["courses"][it["skill"]]["courses"]}


def test_skip_a_skill_then_stop_after_max_revisions():
    g, cfg, first = _to_plan()
    skill = _items(first["plan"])[0]["skill"]
    second = _say(g, cfg, f"skip {skill}, I already know it")["__interrupt__"][0].value["plan"]
    assert second["skipped"] == [skill] and skill not in {it["skill"] for it in _items(second)}
    third = _say(g, cfg, "cheaper please")["__interrupt__"][0].value["plan"]
    assert third["revision"] == MAX_REVISIONS == 2 and third["skipped"] == [skill]   # earlier choice kept
    done = _say(g, cfg, "even cheaper")                       # third request: the loop stops
    assert "__interrupt__" not in done
    assert "I stop after 2 revisions" in done["final_message"] and "nothing has been saved" in done["final_message"]


def test_different_job_goes_back_to_path_choice():
    g, cfg, _ = _to_plan()
    out = _say(g, cfg, "actually show me a different job")
    assert out["__interrupt__"][0].value["checkpoint"] == "choose_path"


def test_stop_and_approve_end_without_revising():
    g, cfg, _ = _to_plan()
    out = g.invoke(Command(resume={"approved": False, "feedback": ""}), cfg)
    assert "__interrupt__" not in out and not out.get("revisions")
    g, cfg, _ = _to_plan()
    out = g.invoke(Command(resume={"approved": True, "feedback": "great"}), cfg)
    assert "You approved this plan." in out["final_message"]


def test_unclear_feedback_says_so():
    g, cfg, _ = _to_plan()
    plan = _say(g, cfg, "hmm")["__interrupt__"][0].value["plan"]
    assert "could not tell what to change" in plan["revision_note"]


def test_ai_reading_is_held_to_the_menu(monkeypatch):
    g, cfg, first = _to_plan()
    real = _items(first["plan"])[0]["skill"]
    monkeypatch.setenv("CAREER_FAKE", "0")
    monkeypatch.setattr(llm_steps, "_call", lambda schema, text: (
        PlanFeedback(action="revise", prefer="shorter", drop_skills=[real, "Rocket Science"], reason="r"),
        {"step": "PlanFeedback", "cost_usd": 0.0}))
    plan = _say(g, cfg, "shorter, and skip things I know")["__interrupt__"][0].value["plan"]
    assert plan["skipped"] == [real] and plan["prefer"] == "shorter"
    assert any("Rocket Science" in n for n in g.get_state(cfg).values["notes"])   # invented skill ignored, logged
