"""Skill-gap agent on its own (offline). Code keeps the gap list; bad AI labels
or orders are replaced, and the replacement is recorded as a fallback."""
import os
import sys
from pathlib import Path

os.environ["CAREER_FAKE"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import llm_steps  # noqa: E402
import skill_gap_agent  # noqa: E402
from llm_steps import GapExplanation, GapNote, SkillOrder  # noqa: E402
from lookups import skill_gap  # noqa: E402
from plan_rules import code_order  # noqa: E402

CUR, TGT = 14, 723          # Accounts Exec -> FS Data Analyst: 12 gaps


def test_run_contract_gaps_unchanged_and_labelled():
    out = skill_gap_agent.run(CUR, TGT)
    keys = ("skill", "type", "need_level", "have_level", "status")
    assert [{k: g[k] for k in keys} for g in out["gaps"]] == skill_gap(CUR, TGT)
    assert all(g["importance"] in ("core", "supporting") and g["why"] for g in out["gaps"])
    assert sorted(out["skill_order"]) == sorted(g["skill"] for g in out["gaps"])
    assert out["fallbacks"] == []


def test_skipped_and_invented_labels_get_defaults(monkeypatch):
    gaps = skill_gap(CUR, TGT)
    notes = [GapNote(skill=g["skill"], importance="core", why="needed") for g in gaps[1:]]
    notes.append(GapNote(skill="Invented Skill", importance="core", why="x"))
    monkeypatch.setattr(llm_steps, "explain_gaps", lambda *_: (GapExplanation(notes=notes), {"step": "t"}))
    out = skill_gap_agent.run(CUR, TGT)
    assert [g["skill"] for g in out["gaps"]] == [g["skill"] for g in gaps]   # nothing invented
    first = out["gaps"][0]
    assert first["importance"] == "supporting" and first["why"] == ""
    assert "explain_gaps" in out["fallbacks"]


def test_unparseable_labels_fall_back(monkeypatch):
    def boom(*_):
        raise ValueError("Model output did not match GapExplanation")
    monkeypatch.setattr(llm_steps, "explain_gaps", boom)
    out = skill_gap_agent.run(CUR, TGT)
    assert "explain_gaps" in out["fallbacks"] and "unusable" in out["notes"][0]


def test_invalid_order_replaced_by_rule_order(monkeypatch):
    gaps = skill_gap(CUR, TGT)
    bad = list(reversed(code_order(gaps)))           # higher levels first: breaks the hard rule
    monkeypatch.setattr(llm_steps, "order_skills", lambda *_: (SkillOrder(order=bad, reason="r"), {"step": "t"}))
    out = skill_gap_agent.run(CUR, TGT)
    assert out["skill_order"] == code_order(gaps)
    assert "order_skills" in out["fallbacks"]
