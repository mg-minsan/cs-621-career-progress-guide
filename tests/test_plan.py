"""Step 5 rules: ordering checks, course choice, plan-wide credit, postconditions."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import plan_rules as pr  # noqa: E402
from funding import Person, plan_cost  # noqa: E402

GAPS = [{"skill": "A", "need_level": 3, "status": "missing"},
        {"skill": "B", "need_level": 3, "status": "level up"},
        {"skill": "C", "need_level": 4, "status": "missing"}]


def test_code_order_puts_level_ups_first_within_a_level():
    assert pr.code_order(GAPS) == ["B", "A", "C"]


def test_validate_order_accepts_same_level_reorder():
    assert pr.validate_order(["A", "B", "C"], GAPS) is None


def test_validate_order_rejects_higher_level_first():
    assert "higher-level" in pr.validate_order(["C", "A", "B"], GAPS)


def test_validate_order_rejects_dropped_or_invented_skills():
    assert pr.validate_order(["A", "B"], GAPS)
    assert pr.validate_order(["A", "B", "C", "D"], GAPS)
    assert pr.validate_order(["A", "A", "C"], GAPS)


def test_close_and_cheaper_runner_up_wins():
    first = {"title": "x", "score": 10.0, "your_fee": 2760}
    second = {"title": "y", "score": 9.6, "your_fee": 720}
    chosen, alt, why = pr.choose_course([first, second])
    assert chosen is second and alt is first and "cheaper" in why


def test_clearly_better_match_wins_even_if_pricier():
    first = {"title": "x", "score": 7.0, "your_fee": 2000}
    second = {"title": "y", "score": 2.0, "your_fee": 100}
    assert pr.choose_course([first, second])[0] is first


def test_credit_applied_once_across_plan():
    c = plan_cost(Person("citizen", 30, 500), [300, 300, 300])
    assert c["credit_used"] == 500 and c["out_of_pocket"] == 400


def test_unknown_balance_shows_what_if_and_asks():
    c = plan_cost(Person("citizen", 30, None), [300, 300])
    assert c["needs_user_input"] and c["credit_used"] == 0 and "$100.00" in c["notes"][0]


def test_unknown_fees_are_excluded_and_flagged():
    c = plan_cost(Person("pr", 30), [100, None])
    assert c["total_after_subsidy"] == 100 and c["unknown_cost_courses"] == 1


def test_check_plan_catches_a_bad_total():
    item = lambda s, lv, fee: {"skill": s, "need_level": lv, "course": {"your_fee": fee}}
    plan = {"phases": {"start": [item("B", 3, 100)], "build": [item("A", 3, 100)],
                       "stand_out": [item("C", 4, 100)]},
            "cost": {"total_after_subsidy": 999, "credit_used": 0, "out_of_pocket": 999}}
    assert any("sum" in v for v in pr.check_plan(plan, GAPS))


def test_cheaper_but_mediocre_runner_up_does_not_win():
    """Regression: live run 1 swapped 'Data Mining Techniques' (6.5) for a
    manufacturing course (6.0) because it was cheaper."""
    first = {"title": "Data Mining Techniques", "score": 6.5, "your_fee": 2022}
    second = {"title": "Predictive Maintenance", "score": 6.0, "your_fee": 400}
    assert pr.choose_course([first, second])[0] is first


def test_weak_match_is_labelled():
    assert pr.match_quality({"score": 3.0}) == "weak"
    assert pr.match_quality({"score": 9.0}) == "strong"
    assert pr.match_quality(None) == "none"
