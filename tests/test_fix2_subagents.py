"""Fix 2 (week 7: does each agent earn its place, and is anything withheld?).

Before: explain_gaps (a paid Claude call per plan) labelled every gap core/supporting
with a reason, and nothing used it; the course agent picked courses without knowing
the target job. After: the labels steer the AI's skill order and are shown to the
user; the target job reaches the course agent. The rules baseline is unchanged.
All offline: CAREER_FAKE=1 or a patched model call. No API key, no cost.
"""
import os
import sys
import uuid
from pathlib import Path

os.environ["CAREER_FAKE"] = "1"
os.environ["CAREER_SEARCH_MODE"] = "bm25"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from langgraph.types import Command  # noqa: E402

import course_agent  # noqa: E402
import llm_steps  # noqa: E402
from graph import build, config  # noqa: E402
from llm_steps import CoursePick, SkillOrder  # noqa: E402
from plan_rules import code_order  # noqa: E402

PERSON = {"residency": "citizen", "age": 41}
SKILL = "Data Governance"
GAPS = [{"skill": "B", "need_level": 3, "status": "missing", "importance": "supporting", "why": "x"},
        {"skill": "A", "need_level": 3, "status": "missing", "importance": "core", "why": "y"}]


def _capture(monkeypatch, reply):
    """Take the AI branch, record the prompt text, return a fixed parsed reply."""
    sent = []
    monkeypatch.setenv("CAREER_FAKE", "0")
    monkeypatch.setattr(llm_steps, "_call", lambda schema, text: (sent.append(text), (reply, {"step": "t"}))[1])
    return sent


def test_order_prompt_carries_core_labels(monkeypatch):
    sent = _capture(monkeypatch, SkillOrder(order=["A", "B"], reason="core first"))
    llm_steps.order_skills("Data Analyst", GAPS)
    assert "A (level 3, missing, core)" in sent[0]
    assert "core skills" in sent[0] and "before supporting" in sent[0]


def test_rules_order_is_unchanged_by_labels():
    # baseline 2 must not move: code_order ignores importance (level, then level-ups first)
    plain = [{k: v for k, v in g.items() if k not in ("importance", "why")} for g in GAPS]
    assert code_order(GAPS) == code_order(plain)


def test_pick_prompt_names_the_target_job(monkeypatch):
    def first_candidate(schema, text):
        sent.append(text)
        return CoursePick(picks=[]), {"step": "t"}
    sent = []
    monkeypatch.setenv("CAREER_FAKE", "0")
    monkeypatch.setattr(llm_steps, "_call", first_candidate)
    course_agent.run([SKILL], PERSON, target_role="Data Analyst")
    assert "preparing for this job: Data Analyst" in sent[-1]
    assert "as that job uses it" in sent[-1]


def test_without_a_target_job_the_prompt_is_as_before(monkeypatch):
    sent = []
    monkeypatch.setenv("CAREER_FAKE", "0")
    monkeypatch.setattr(llm_steps, "_call", lambda s, t: (sent.append(t), (CoursePick(picks=[]), {"step": "t"}))[1])
    course_agent.run([SKILL], PERSON)                          # E3b calls it like this
    assert "preparing for this job" not in sent[-1]


def test_graph_passes_target_job_and_plan_keeps_labels(monkeypatch):
    seen = {}
    real = course_agent.run

    def spy(skills, person, target_role=""):
        seen["role"] = target_role
        return real(skills, person, target_role=target_role)
    monkeypatch.setattr(course_agent, "run", spy)
    g, cfg = build(), config(uuid.uuid4().hex)
    g.invoke({"profile": {"role": "Accounts Executive", "age": 41, "residency": "citizen",
                          "status": "employed", "goal": "move into data analyst", "credit_balance": 0}}, cfg)
    g.invoke(Command(resume={"role_id": 14}), cfg)
    out = g.invoke(Command(resume={"role_id": 723}), cfg)     # Data Analyst (financial services)
    plan = out["__interrupt__"][0].value["plan"]
    assert "Data Analyst" in seen["role"]
    items = [it for ph in plan["phases"].values() for it in ph]
    assert items and all(it["importance"] in ("core", "supporting") and it.get("why") for it in items)
