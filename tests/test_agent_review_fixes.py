"""Regression coverage for query drift, retries, raw grading and billed parse failures."""
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ["CAREER_FAKE"] = "1"
os.environ["CAREER_SEARCH_MODE"] = "bm25"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import course_agent
import llm_steps
import skill_gap_agent
from course_search import strong_hits
from harness import AgentResult, Case
from run_evals import grade_e3b


def test_rewrite_is_scored_against_original_skill():
    pairs = []
    def rerank(batch):
        pairs.extend(batch)
        return [-10.0, 10.0]
    idx = SimpleNamespace(
        mode="hybrid_rerank", reranker=rerank,
        courses=[{"course_ref": "python", "search_text": "Python basics"},
                 {"course_ref": "people", "search_text": "Managing stakeholders"}],
        search=lambda *a, **kw: [{"course_ref": "python", "score": 20.0},
                                 {"course_ref": "people", "score": 1.0}])
    hits = strong_hits(idx, "Python basics", 4, relevance_query="Stakeholder Management")
    assert [h["course_ref"] for h in hits] == ["people"]
    assert all(q == "Stakeholder Management" for q, _ in pairs)
    assert hits[0]["score"] == 10.0


def test_transient_chunk_retry_does_not_repeat_completed_chunks(monkeypatch):
    monkeypatch.setattr(course_agent, "PICK_CHUNK", 1)
    monkeypatch.setattr(course_agent.time, "sleep", lambda *_: None)
    calls = []
    def pick(items):
        skill = items[0]["skill"]
        calls.append(skill)
        if calls == ["first", "second"]:
            raise ConnectionError("temporary")
        return llm_steps.CoursePick(picks=[llm_steps.CourseChoice(
            skill=skill, course_ref=skill, reason="ok")]), {"step": skill}
    monkeypatch.setattr(llm_steps, "pick_courses", pick)
    found = {s: {"courses": [{"course_ref": s}]} for s in ("first", "second")}
    out = course_agent.pick_courses({"found": found})
    assert calls == ["first", "second", "second"]
    assert out["usage"] == [{"step": "first"}, {"step": "second"}]


@pytest.mark.parametrize("step", ["explain_gaps", "order_skills"])
def test_gap_parse_failures_keep_usage(monkeypatch, step):
    usage = {"step": step, "input_tokens": 100, "output_tokens": 20, "cost_usd": 0.01}
    def fail(*args):
        raise llm_steps.OutputParseError("bad JSON", usage)
    monkeypatch.setattr(llm_steps, step, fail)
    out = skill_gap_agent.run(14, 723)
    assert usage in out["usage"]
    assert step in out["fallbacks"]


def test_call_attaches_raw_usage_on_parse_failure(monkeypatch):
    raw = SimpleNamespace(usage_metadata={"input_tokens": 100, "output_tokens": 20})
    model = SimpleNamespace(invoke=lambda *_: {"raw": raw, "parsed": None, "parsing_error": "bad"})
    monkeypatch.setattr(llm_steps, "_model", lambda: SimpleNamespace(with_structured_output=lambda *a, **k: model))
    with pytest.raises(llm_steps.OutputParseError) as error:
        llm_steps._call(llm_steps.CoursePick, "pick")
    assert error.value.usage["input_tokens"] == 100
    assert error.value.usage["output_tokens"] == 20
    assert error.value.usage["cost_usd"] > 0


def test_e3b_rejects_raw_off_menu_pick_after_repair(monkeypatch):
    import run_evals
    monkeypatch.setattr(run_evals, "e2_gold", lambda: {})
    candidate = {"course_ref": "valid", "full_fee": 100, "fee_after_subsidy": 100}
    result = AgentResult(details={"found": {"courses": [candidate], "status": "title",
        "chosen_ref": "valid", "raw_chosen_ref": "invented"}, "fallbacks": ["pick_courses"]})
    case = Case("test", {"skill": "skill", "person": {"residency": "citizen", "age": 41}})
    assert not grade_e3b(case, result)
    assert not result.checks["pick_in_menu"]
    assert not result.checks["metric_no_fallback"]
    assert "fees_correct" not in result.checks
