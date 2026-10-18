"""Step 8 fixes found by the full E1 run (2026-10-18). Offline, no API."""
import os
import sys
from pathlib import Path

os.environ["CAREER_FAKE"] = "1"
os.environ["CAREER_SEARCH_MODE"] = "bm25"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import graph  # noqa: E402
import llm_steps  # noqa: E402
from lookups import find_roles, search_roles, skill_gap  # noqa: E402


def ids(rows):
    return [r["role_id"] for r in rows]


def test_hr_executive_found_via_sector_name():               # E1 p10
    assert not {1195, 1201, 1205} & set(ids(find_roles("Human Resource Executive", 8)))
    assert ids(search_roles("Human Resource Executive", 8))[0] in (1195, 1201, 1205)


def test_food_and_beverage_and_restaurant_wording():         # E1 p11
    assert ids(search_roles("Food and Beverage Supervisor", 8))[0] == 1056
    assert ids(search_roles("Restaurant Manager", 4))[0] in (1059, 1703)
    assert 18 not in ids(search_roles("Restaurant Manager", 4))      # Treasury Manager (was a goal match)


def test_plain_titles_unchanged():
    for t in ["Accounts Executive", "Software Engineer", "Security Officer", "Bank Teller", "Data Analyst"]:
        assert ids(search_roles(t, 1)) == ids(find_roles(t, 1))


def test_unparseable_skill_order_falls_back_instead_of_crashing(monkeypatch):
    def boom(*_):
        raise ValueError("Model output did not match SkillOrder: reason Field required")
    monkeypatch.setattr(llm_steps, "order_skills", boom)
    gaps = skill_gap(1056, 1059)
    assert len(gaps) > 40                                     # the case that broke: 49 skills
    out = graph.order_skills({"gaps": gaps, "target_role_id": 1059})
    assert sorted(out["skill_order"]) == sorted(g["skill"] for g in gaps)
    assert "unusable" in out["notes"][0]
