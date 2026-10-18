"""Run with:  python -m pytest tests -q
These are code checks, not AI checks: if one fails, the data layer is wrong
and every later eval number would be meaningless."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from lookups import ToolError, find_roles, get_role, nearby_roles, skill_gap  # noqa: E402


def test_exact_title_ranks_first():
    top = find_roles("Accounts Executive", 1)[0]
    assert "Accounts Executive" in top["role"]


def test_ambiguous_title_returns_several_sectors():
    sectors = {r["sector"] for r in find_roles("data analyst", 5) if r["score"] >= 0.75}
    assert len(sectors) >= 2  # proves the "confirm role" checkpoint is needed


def test_bad_role_id_fails_loudly():
    with pytest.raises(ToolError):
        get_role(999_999)


def test_gap_is_sorted_lowest_level_first():
    cur = find_roles("Accounts Executive", 1)[0]["role_id"]
    tgt = find_roles("data analyst", 1)[0]["role_id"]
    levels = [g["need_level"] for g in skill_gap(cur, tgt)]
    assert levels == sorted(levels)


def test_gap_to_same_role_is_empty():
    rid = find_roles("Accounts Executive", 1)[0]["role_id"]
    assert skill_gap(rid, rid) == []


def test_nearby_roles_excludes_self():
    rid = find_roles("Accounts Executive", 1)[0]["role_id"]
    assert all(r["role_id"] != rid for r in nearby_roles(rid))
