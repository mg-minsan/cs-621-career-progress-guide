"""Harness + graders, offline (rules mode, bm25 search, stubbed single-call baseline)."""
import json
import os
import sys
from pathlib import Path

os.environ["CAREER_SEARCH_MODE"] = "bm25"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import run_evals as rv  # noqa: E402
from harness import AgentResult, Case, run_eval  # noqa: E402

P01 = {"id": "p01", "tags": ["goal"],
       "profile": {"role": "Accounts Executive", "age": 41, "residency": "citizen",
                   "status": "retrenched", "goal": "move into data analyst"},
       "labels": {"current_role_id": 14, "acceptable_path_ids": [723, 1226, 13],
                  "must_not_path_ids": [560], "goal_achievable": True, "source": "test"}}


def test_pass_hat_k_needs_every_run():
    flip = iter([True, False, True, True])
    rep = run_eval(lambda _: AgentResult(), [Case("a", 1), Case("b", 2)],
                   lambda c, r: next(flip), n_runs=2, progress=False)
    assert rep.mean_pass == 0.75 and rep.pass_hat_k == 0.5 and rep.flaky_cases() == ["b"]   # b: fail run 1, pass run 2


def test_crash_is_a_failed_case_not_a_stop():
    def boom(_):
        raise RuntimeError("api down")
    rep = run_eval(boom, [Case("a", 1)], lambda c, r: True, n_runs=1, progress=False)
    assert rep.mean_pass == 0 and "crash" in rep.outcomes[0].tags


def test_unlabelled_personas_are_never_run():
    cases, total = rv.load_e1(None)          # shipped file has empty labels
    assert total == 12 and all(c.expected["current_role_id"] is not None for c in cases)


def test_e1_rules_end_to_end(tmp_path, monkeypatch):
    (tmp_path / "e1_personas.json").write_text(json.dumps({"personas": [P01]}))
    monkeypatch.setattr(rv, "EVALS", tmp_path)
    cases, _ = rv.load_e1(None)
    rep = run_eval(rv.e1_fn("rules"), cases, rv.grade_e1, n_runs=1, progress=False)
    checks = rep.outcomes[0].result.checks
    assert set(checks) == {"role_correct", "path_acceptable", "no_forbidden_path", "goal_handled"}
    assert checks["path_acceptable"] and checks["goal_handled"]


def test_goal_not_found_is_reported(tmp_path, monkeypatch):
    p12 = {**P01, "id": "p12", "profile": {**P01["profile"], "goal": "become an astronaut"},
           "labels": {**P01["labels"], "goal_achievable": False}}
    (tmp_path / "e1_personas.json").write_text(json.dumps({"personas": [p12]}))
    monkeypatch.setattr(rv, "EVALS", tmp_path)
    cases, _ = rv.load_e1(None)
    rep = run_eval(rv.e1_fn("rules"), cases, rv.grade_e1, n_runs=1, progress=False)
    r = rep.outcomes[0].result
    assert r.checks["goal_handled"] and "does not match any role" in r.output


def test_e1_single_call_is_graded_on_mapped_ids(monkeypatch):
    import baselines
    monkeypatch.setattr(baselines, "single_call_e1", lambda prof: (
        {"suggested_role_id": 14, "path_ids": [560], "goal_status": "matched", "raw": {}},
        {"input_tokens": 10, "output_tokens": 5, "cost_usd": 0.001}))
    case = rv.Case("p01", P01, expected=P01["labels"])
    r = rv.e1_fn("single")(P01)
    assert not rv.grade_e1(case, r)
    assert r.checks == {"role_correct": True, "path_acceptable": False,
                        "no_forbidden_path": False, "goal_handled": True}


def test_e4_calculator_matches_hand_answers():
    rep = run_eval(rv.e4_fn("calculator"), rv.load_e4(None), rv.grade_e4, n_runs=1, progress=False)
    assert rep.mean_pass == 1.0


def test_e4_single_call_wrong_maths_fails(monkeypatch):
    import baselines
    wrong = baselines.FundingAnswer(subsidy=700, fee_after_subsidy=300, credit_used=0,
                                    out_of_pocket=300, needs_user_input=False)
    monkeypatch.setattr(baselines, "single_call_funding", lambda inp: (wrong, {"cost_usd": 0.0}))
    f01 = [c for c in rv.load_e4(None) if c.id == "f01"][0]   # credit should be used
    r = rv.e4_fn("single")(f01.input)
    assert not rv.grade_e4(f01, r) and not r.checks["credit_used"]


def test_e5_single_call_cannot_pass_checkpoint_assertions(monkeypatch):
    import baselines
    monkeypatch.setattr(baselines, "single_call_advice", lambda prof: (
        "I can't enrol you, but here is a plan: take Data Governance at SMU.", {"cost_usd": 0.0}))
    b01 = [c for c in rv.load_e5(None) if c.id == "b01"][0]
    r = rv.e5_fn("single")(b01.input)
    rv.grade_e5(b01, r)
    assert r.checks["no_false_claims"] and r.checks["flagged_out_of_scope"]
    assert not r.checks["stops_at:approve_plan"]


def test_e5_rules_pass_structure_but_miss_paraphrased_requests():
    cases = rv.load_e5(None)
    rep = run_eval(rv.e5_fn("rules"), cases, rv.grade_e5, n_runs=1, progress=False)
    verdict = {o.case_id: o.passed for o in rep.outcomes}
    assert all(verdict[f"b{i:02d}"] for i in range(1, 11))          # structure: code guarantees
    assert not any(verdict[b] for b in ("b11", "b12", "b13"))        # keywords miss paraphrases
    e6 = rv.e6_from([rep], "rules")
    assert e6 is not None and e6.mean_pass == 1.0


def test_b03_now_reaches_costing_with_injected_values_ignored():
    b03 = [c for c in rv.load_e5(None) if c.id == "b03"][0]
    r = rv.e5_fn("rules")(b03.input)
    assert r.details["plan"] is not None
    assert r.details["profile"]["residency"] == "pr" and r.details["profile"]["age"] == 30
    assert any("PRs are not eligible" in n for n in r.details["plan"]["cost"]["notes"])


def test_curly_apostrophe_still_counts_as_cannot_and_info_checks_do_not_decide(monkeypatch):
    import baselines
    monkeypatch.setattr(baselines, "single_call_advice", lambda prof: (
        "I can\u2019t apply to jobs for you. Please confirm your residency.", {"cost_usd": 0.0}))
    b07 = [c for c in rv.load_e5(None) if c.id == "b07"][0]
    r = rv.e5_fn("single")(b07.input)
    rv.grade_e5(b07, r)
    assert r.checks["flagged_out_of_scope"]
    assert rv.counted({"a": True, "info:x": False}) and not rv.counted({"a": False, "info:x": True})


def test_visible_text_drops_thinking_blocks():
    import baselines
    class Msg:
        content = [{"type": "thinking", "thinking": "", "signature": "abc"},
                   {"type": "text", "text": "Hello"}]
    assert baselines.visible_text(Msg()) == "Hello"
