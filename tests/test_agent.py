"""Smoke + property tests (a slice of E3/E4/E5). Run:  python -m pytest -q   (or python tests/test_agent.py)"""
import json, os, sys
os.environ["CAREERGUIDE_LLM"] = "0"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from careerguide.data import SAMPLE_PROFILES
from careerguide.funding import price_courses
from careerguide.graph import Session, PHASES
from careerguide import tools


def run(profile, path_index=0):
    s = Session("t")
    s.start(profile)
    p = s.pending()
    s.answer({"role_id": p["candidates"][0]["role_id"], "goal": p["goal"]})
    p = s.pending()
    s.answer({"role_id": p["paths"][path_index]["role_id"]})
    return s


def test_happy_path_plan_properties():
    s = run(SAMPLE_PROFILES["Accounts Executive, 41, retrenched"])
    plan = s.pending()["plan"]
    gaps = [g["skill"] for g in plan["skill_gaps"]]
    placed = [d["skill"] for ph in PHASES for d in plan["direction"][ph]]
    assert sorted(gaps) == sorted(placed)                       # every gap placed once
    levels = [d["level"] for ph in PHASES for d in plan["direction"][ph]]
    assert levels == sorted(levels)                             # simpler levels first
    assert all(g["course_id"] for g in plan["skill_gaps"])
    s.answer({"action": "approve"})
    assert s.state["status"] == "approved"
    json.dumps(s.state["plan"])                                 # valid JSON


def test_funding_exact():
    c = [{"id": "x", "title": "x", "fee": 1000, "subsidised": True}]
    r = price_courses(c, {"age": 41, "residency": "citizen", "status": "employed"})
    assert (r["subsidy"], r["skillsfuture_credit"], r["mid_career_credit"], r["you_pay"]) == (900.0, 100.0, 0.0, 0.0)
    r = price_courses(c, {"age": 30, "residency": "pr", "status": "employed"})
    assert (r["subsidy"], r["you_pay"]) == (700.0, 300.0)
    r = price_courses([{"id": "y", "title": "y", "fee": 6800, "subsidised": False}],
                      {"age": 41, "residency": "citizen", "status": "retrenched"})
    assert r["you_pay"] == 2300.0 and r["skillsfuture_credit"] == 500.0 and r["mid_career_credit"] == 4000.0


def test_boundary_action_goal_does_nothing():
    s = Session("b"); s.start(SAMPLE_PROFILES["Boundary test: goal demands an action"])
    assert s.pending()["notices"]
    assert not any(hasattr(tools, n) for n in ("enrol", "pay", "apply"))


def test_missing_fields_stop():
    s = Session("m"); s.start({"role": "Accounts Executive", "age": 41})
    assert s.state["status"] == "needs_info" and s.pending() is None


def test_swap_replans():
    s = run(SAMPLE_PROFILES["Marketing Executive, 27, upskill for AI"])
    pl = s.pending()
    skill = next(iter(pl["selection"])); alt = pl["options"][skill][-1]["course_id"]
    s.answer({"action": "swap", "skill": skill, "course_id": alt})
    assert s.pending()["selection"][skill] == alt


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"): f(); print("ok", n)
