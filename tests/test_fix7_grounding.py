"""Fix 7: the grounding check (no AI, no API) reads advice the way a user would act on it."""
import os
import sys
import uuid
from pathlib import Path

os.environ["CAREER_FAKE"] = "1"
os.environ["CAREER_SEARCH_MODE"] = "bm25"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from langgraph.types import Command  # noqa: E402

import grounding_check  # noqa: E402
from graph import build, config  # noqa: E402
from grounding import check_plan, check_text  # noqa: E402

GENERIC = ("**Power BI fundamentals**: roughly $300-$900 before subsidy. With your credit you could pay "
           "$0-$500 out of pocket. Search MySkillsFuture for 'data analytics'.")


def test_generic_advice_is_not_grounded():
    g = check_text(GENERIC)
    assert not g["gives_course_ref"] and not g["personal_fee"]
    assert g["only_fee_ranges"] and g["may_cost_zero"]


def test_zero_detector_is_not_fooled_by_cents_or_larger_sums():
    for text in ("costs $0.50 per page", "about $10 to $20", "$1,000 after subsidy", "$105.00"):
        assert not check_text(text)["may_cost_zero"], text
    for text in ("$0 out of pocket", "fully covered by your credit", "pay $ 0 - $300"):
        assert check_text(text)["may_cost_zero"], text


def test_refs_are_checked_against_the_catalogue():
    assert check_text("Take TGS-2020513097 (Republic Polytechnic).")["ref_in_catalogue"]
    assert not check_text("Take TGS-0000000001.")["ref_in_catalogue"]       # invented reference


def _plan():
    g, cfg = build(), config(uuid.uuid4().hex)
    g.invoke({"profile": {"role": "Accounts Executive", "age": 41, "residency": "citizen",
                          "status": "employed", "goal": "move into data analyst", "credit_balance": 0}}, cfg)
    g.invoke(Command(resume={"role_id": 14}), cfg)
    return g.invoke(Command(resume={"role_id": 723}), cfg)["__interrupt__"][0].value["plan"]


def test_graph_plan_is_grounded():
    g = check_plan(_plan())
    assert g["gives_course_ref"] and g["ref_in_catalogue"] and g["personal_fee"]
    assert not g["only_fee_ranges"] and not g["may_cost_zero"]
    assert check_plan(None) is None                                      # stopped before a plan


def test_table_reads_old_and_new_group_names():
    plan = _plan()
    for name in ("E4 boundary", "E5 boundary"):                         # 18 Oct results used E4
        results = {"meta": {"when": "x", "runs": 1}, "groups": {name: [
            {"name": f"{name[:2]} [single call (Claude, no tools)]",
             "outcomes": [{"output": GENERIC, "details": {"system": "single"}}]},
            {"name": f"{name[:2]} [agent (Claude)]", "outcomes": [{"output": "", "details": {"plan": plan}}]}]}}
        md = grounding_check.table(results)
        assert "| single call (Claude, no tools) | 1 | 0/1 | 0/1 | 0/1 | 1/1 | 1/1 |" in md
        assert "| agent (Claude) | 1 | 1/1 | 1/1 | 1/1 | 0/1 | 0/1 |" in md
