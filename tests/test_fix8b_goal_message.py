"""Fix 8b, found by the held-out set (h01): the goal message must not contradict the paths shown."""
import os
import sys
import uuid
from pathlib import Path

os.environ["CAREER_FAKE"] = "1"
os.environ["CAREER_SEARCH_MODE"] = "bm25"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from langgraph.types import Command  # noqa: E402

import llm_steps  # noqa: E402
from graph import build, config  # noqa: E402
from llm_steps import PathRanking, ProfileReading, RankedPath  # noqa: E402

NURSE = {"role": "Enrolled Nurse", "age": 29, "residency": "citizen", "status": "employed",
         "goal": "become a registered nurse"}


def _choose_path_payload(monkeypatch, kind):
    monkeypatch.setattr(llm_steps, "read_profile", lambda profile, cands: (ProfileReading(
        role_id=1084, role_confidence=0.9, role_reason="r", goal_target_titles=["Registered Nurse"]), {"step": "t"}))
    monkeypatch.setattr(llm_steps, "rank_paths", lambda profile, cur, cands, titles: (PathRanking(paths=[
        RankedPath(role_id=cands[0]["role_id"], kind=kind, reason="r")]), {"step": "t"}))
    g, cfg = build(), config(uuid.uuid4().hex)
    g.invoke({"profile": NURSE}, cfg)
    return g.invoke(Command(resume={"role_id": 1084}), cfg)["__interrupt__"][0].value


def test_ai_goal_match_without_a_title_match_is_explained_not_contradicted(monkeypatch):
    p = _choose_path_payload(monkeypatch, "goal_match")
    assert p["goal_status"] == "matched"
    assert "closest match" in p["goal_message"] and "does not match any role" not in p["goal_message"]


def test_no_goal_match_still_says_not_found(monkeypatch):
    p = _choose_path_payload(monkeypatch, "step_up")
    assert p["goal_status"] == "not_found" and "does not match any role" in p["goal_message"]
