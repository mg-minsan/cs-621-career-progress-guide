"""
STEP 7c - Baseline 1: Claude in ONE call, no tools, no graph, no calculator.

Rule of thumb: "If your agent cannot beat this, it is an expensive way to call a
model once." Same model as the agent (CAREER_MODEL), so the only difference
is everything we built around it.

  single_call_e1       profile -> current role + next roles (titles)
  single_call_advice   profile -> free-text plan (graded on E4)
  single_call_funding  person + course + the funding RULES -> cost
                       (the "AI does the maths" ablation for E3)

Baseline 2 (rules, no LLM) is the agent graph itself with CAREER_FAKE=1.
"""
from __future__ import annotations

import json

from pydantic import BaseModel, Field

import llm_steps
from funding import (BASE_CREDIT, BASE_CREDIT_AGE, MIDCAREER_CREDIT, MIDCAREER_CREDIT_AGE,
                     TIER2_MIN_SELF_SPONSORED_AGE, TIER_RATES)
from lookups import search_roles

ADVISOR = ("You are a career adviser for job seekers in Singapore. You have no tools: "
           "answer from what you know. Be concise.")


def visible_text(msg) -> str:
    """Only what the user would see. Sonnet 5.5 returns a list of blocks
    ([thinking, text]); str() of that list leaked the thinking signature into
    the graded text in the first quick run (found 2026-10-13)."""
    c = msg.content
    if isinstance(c, str):
        return c
    return "".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")


def _invoke(system: str, user: str, schema: type[BaseModel] | None = None):
    from langchain.messages import HumanMessage, SystemMessage
    model = llm_steps._model()
    msgs = [SystemMessage(system), HumanMessage(user)]
    if schema is None:
        raw = model.invoke(msgs)
        parsed = visible_text(raw)
    else:
        out = model.with_structured_output(schema, method="json_schema", include_raw=True).invoke(msgs)
        if out.get("parsed") is None:
            raise ValueError(f"single-call output did not match {schema.__name__}")
        raw, parsed = out["raw"], out["parsed"]
    meta = getattr(raw, "usage_metadata", None) or {}
    i, o = meta.get("input_tokens", 0), meta.get("output_tokens", 0)
    pin, pout = llm_steps.PRICES.get(llm_steps.MODEL_NAME, (0.0, 0.0))
    return parsed, {"input_tokens": i, "output_tokens": o,
                    "cost_usd": round(i / 1e6 * pin + o / 1e6 * pout, 6)}


# ---------------------------------------------------------------- E1
class CareerAnswer(BaseModel):
    current_role_title: str = Field(description="the standard job title for the user's current job")
    next_role_titles: list[str] = Field(min_length=1, max_length=3,
                                        description="2-3 realistic next job titles")
    goal_in_framework: bool | None = Field(
        description="true if the user's stated goal is a real job role in Singapore's SkillsFuture "
                    "Skills Framework, false if not, null if no goal was given")


def _to_id(title: str) -> int | None:
    """Map a free-text title to a framework role id. Generous to the baseline:
    the agent has to choose from a shortlist; here code does the matching."""
    hits = search_roles(title, limit=1) if title and title.strip() else []
    return hits[0]["role_id"] if hits and hits[0]["score"] >= 0.6 else None


def single_call_e1(profile: dict) -> tuple[dict, dict]:
    ans, usage = _invoke(ADVISOR, "Profile:\n" + json.dumps(profile) +
                         "\n\nWhat is this person's current job, and what 2-3 jobs should they aim for next?",
                         CareerAnswer)
    paths = [i for i in (_to_id(t) for t in ans.next_role_titles) if i is not None]
    goal = {True: "matched", False: "not_found", None: "none"}[ans.goal_in_framework]
    return {"suggested_role_id": _to_id(ans.current_role_title), "path_ids": paths,
            "goal_status": goal, "raw": ans.model_dump()}, usage


# ---------------------------------------------------------------- E4
def single_call_advice(profile: dict) -> tuple[str, dict]:
    return _invoke(ADVISOR, "Profile:\n" + json.dumps(profile) +
                   "\n\nGive this person a short training plan towards their goal, with SkillsFuture "
                   "courses and costs.")


# ---------------------------------------------------------------- E3
RULES_TEXT = f"""SkillsFuture course fee rules (use exactly these):
- Tier 1 courses: Singapore Citizens and PRs get {TIER_RATES['tier1']['base']:.0%} subsidy;
  Citizens aged {MIDCAREER_CREDIT_AGE}+ get {TIER_RATES['tier1']['mces']:.0%} instead.
- Tier 2 courses: Citizens and PRs aged {TIER2_MIN_SELF_SPONSORED_AGE}+ get {TIER_RATES['tier2']['base']:.0%};
  Citizens aged {MIDCAREER_CREDIT_AGE}+ get {TIER_RATES['tier2']['mces']:.0%}; under {TIER2_MIN_SELF_SPONSORED_AGE} get 0%.
- Tier "none": no subsidy. Residency "other" (foreigners): no subsidy.
- fee_after_subsidy = full fee - subsidy.
- SkillsFuture Credit: only Citizens aged {BASE_CREDIT_AGE}+. Use min(credit balance, fee_after_subsidy).
  If use_credit is false, use none. If the credit balance is unknown (null), use none and set
  needs_user_input true. Credit cannot exceed ${BASE_CREDIT + MIDCAREER_CREDIT:,.0f} for 40+ or ${BASE_CREDIT:,.0f} otherwise.
- out_of_pocket = fee_after_subsidy - credit_used. Round money to the cent."""


class FundingAnswer(BaseModel):
    subsidy: float
    fee_after_subsidy: float
    credit_used: float
    out_of_pocket: float
    needs_user_input: bool


def single_call_funding(case_input: dict) -> tuple[FundingAnswer, dict]:
    return _invoke("You calculate course fees. Show no working, only the result.",
                   RULES_TEXT + "\n\nCase:\n" + json.dumps(case_input), FundingAnswer)
