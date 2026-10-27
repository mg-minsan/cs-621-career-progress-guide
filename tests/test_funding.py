"""Run with:  python -m pytest tests -q"""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from funding import FundingError, Person, course_cost, infer_tier  # noqa: E402

CASES = json.loads((ROOT / "evals" / "e4_funding.json").read_text())["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_e4_hand_computed_cases(case):
    """E4: calculator must match the hand-worked answers to the cent."""
    got = course_cost(Person(**case["person"]), case["full_fee"], case["tier"], case["use_credit"])
    for key, want in case["expected"].items():
        assert getattr(got, key) == pytest.approx(want, abs=0.005), f"{case['id']} {key}"


def test_matches_listed_fees_for_whole_directory():
    """Second-source check: for a citizen under 40, our after-subsidy
    fee must equal the fee the course directory itself lists."""
    con = sqlite3.connect(ROOT / "data" / "careers.db")
    rows = con.execute("SELECT full_fee, fee_after_subsidy FROM courses "
                       "WHERE full_fee > 0 AND fee_after_subsidy IS NOT NULL").fetchall()
    person, checked, mismatches = Person("citizen", 30, 0), 0, 0
    for full, listed in rows:
        tier = infer_tier(full, listed)
        if tier == "unknown":
            continue
        checked += 1
        if abs(course_cost(person, full, tier).fee_after_subsidy - listed) > 0.01:
            mismatches += 1
    assert checked > 25_000
    assert mismatches / checked < 0.001


def test_unknown_tier_fails_loudly():
    with pytest.raises(FundingError):
        course_cost(Person("citizen", 30, 0), 1000, "unknown")


def test_bad_residency_fails_loudly():
    with pytest.raises(FundingError):
        course_cost(Person("tourist", 30, 0), 1000, "tier1")


def test_impossible_credit_balance_triggers_ask():
    got = course_cost(Person("citizen", 30, 99_999), 1000, "tier1")
    assert got.needs_user_input and got.credit_used == 0 and got.out_of_pocket == 300
