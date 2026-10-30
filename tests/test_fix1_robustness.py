"""Fix 1 (week 2: fail loudly, retry only what is transient, degrade instead of crash).

Each test is a bug found by probing the agent before the fix:
  - credit_balance "abc"  -> ValueError crash in validate
  - credit_balance -100   -> ran the whole (paid) pipeline, then crashed at the plan check
  - an unusable AI reply in read_profile / rank_paths -> the whole run crashed
  - ToolError (a wrong call) was retried 3 times like a timeout
  - choosing your current role as the target -> a 0-skill, $0 "plan"
All offline: CAREER_FAKE=1 or a patched model call. No API key, no cost.
"""
import os
import sys
import uuid
from pathlib import Path

os.environ["CAREER_FAKE"] = "1"
os.environ["CAREER_SEARCH_MODE"] = "bm25"   # no model downloads in tests
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from langgraph.types import Command  # noqa: E402

import llm_steps  # noqa: E402
from graph import build, config  # noqa: E402
from lookups import ToolError  # noqa: E402

BASE = {"role": "Accounts Executive", "age": 30, "residency": "citizen",
        "status": "employed", "goal": "move into data analyst"}


def first_pause(profile):
    g, cfg = build(), config(uuid.uuid4().hex)
    out = g.invoke({"profile": profile}, cfg)
    return out["__interrupt__"][0].value


def test_text_credit_balance_asks_instead_of_crashing():
    p = first_pause({**BASE, "credit_balance": "abc"})
    assert p["checkpoint"] == "ask_missing_info"
    assert any("credit_balance" in m for m in p["missing"])


def test_negative_credit_balance_asks_before_any_paid_step():
    p = first_pause({**BASE, "credit_balance": -100})
    assert p["checkpoint"] == "ask_missing_info"
    assert any("credit_balance" in m for m in p["missing"])


def test_numeric_string_credit_balance_is_accepted():
    p = first_pause({**BASE, "credit_balance": "250"})
    assert p["checkpoint"] == "confirm_role"


def test_current_role_cannot_be_chosen_as_target():
    g, cfg = build(), config(uuid.uuid4().hex)
    g.invoke({"profile": {**BASE, "credit_balance": 0}}, cfg)
    g.invoke(Command(resume={"role_id": 14}), cfg)              # confirm: Accounts Executive
    out = g.invoke(Command(resume={"role_id": 14}), cfg)        # try to "move" to the same role
    payload = out["__interrupt__"][0].value
    assert payload["checkpoint"] == "choose_path"
    assert "current role" in payload["error"]


def _unusable(*args, **kwargs):
    raise llm_steps.OutputParseError("Model output did not match", {"step": "x", "cost_usd": 0.01})


def test_unusable_ai_reply_falls_back_to_rules(monkeypatch):
    monkeypatch.setenv("CAREER_FAKE", "0")                    # take the AI branch...
    monkeypatch.setattr(llm_steps, "_call", _unusable)        # ...whose reply cannot be parsed
    g, cfg = build(), config(uuid.uuid4().hex)
    out = g.invoke({"profile": {**BASE, "credit_balance": 0}}, cfg)
    assert out["__interrupt__"][0].value["checkpoint"] == "confirm_role"
    out = g.invoke(Command(resume={"role_id": 14}), cfg)
    assert out["__interrupt__"][0].value["checkpoint"] == "choose_path"
    state = g.get_state(cfg).values
    assert {"read_profile", "rank_paths"} <= set(state["fallbacks"])
    assert sum(u.get("cost_usd", 0) for u in state["usage"]) > 0     # billed failures still counted


def test_only_transient_errors_are_retried():
    import anthropic
    import httpx
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")

    def api_error(cls, code):
        return cls("x", response=httpx.Response(code, request=req), body=None)
    # the world was busy: retry
    assert llm_steps.transient_only(api_error(anthropic.InternalServerError, 529)) is True
    assert llm_steps.transient_only(api_error(anthropic.RateLimitError, 429)) is True
    assert llm_steps.transient_only(anthropic.APIConnectionError(request=req)) is True
    # the call was wrong: retrying fails the same way, and is billed again
    assert llm_steps.transient_only(api_error(anthropic.BadRequestError, 400)) is False
    assert llm_steps.transient_only(ToolError("no such role")) is False
    assert llm_steps.transient_only(llm_steps.OutputParseError("bad", {})) is False
