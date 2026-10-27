"""Course agent on its own (offline, BM25). The AI only proposes queries and
picks from code's list; code keeps the strong-match bar and the fees."""
import os
import sys
from pathlib import Path

os.environ["CAREER_FAKE"] = "1"
os.environ["CAREER_SEARCH_MODE"] = "bm25"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import course_agent  # noqa: E402
import llm_steps  # noqa: E402
from llm_steps import CourseChoice, CoursePick, QueryRewrite, SkillQueries  # noqa: E402
from plan_rules import choose_course  # noqa: E402

PERSON = {"residency": "citizen", "age": 41}
SKILL = "Data Governance"


def test_run_contract_pick_is_rule_pick_in_fake_mode():
    out = course_agent.run([SKILL], PERSON)
    r = out["courses"][SKILL]
    assert r["courses"] and all("your_fee" in c for c in r["courses"])
    chosen, alt, why = choose_course(r["courses"])
    assert (r["chosen_ref"], r["pick_reason"]) == (chosen["course_ref"], why)
    assert r["alternative_ref"] == (alt["course_ref"] if alt else None)
    assert out["fallbacks"] == []


def test_ai_pick_off_the_list_is_replaced(monkeypatch):
    fake = CoursePick(picks=[CourseChoice(skill=SKILL, course_ref="NOT-A-COURSE", reason="r")])
    monkeypatch.setattr(llm_steps, "pick_courses", lambda *_: (fake, {"step": "t"}))
    r = course_agent.run([SKILL], PERSON)
    found = r["courses"][SKILL]
    assert found["chosen_ref"] == choose_course(found["courses"])[0]["course_ref"]
    assert r["fallbacks"] == ["pick_courses"]


def test_ai_pick_on_the_list_is_kept_with_its_reason(monkeypatch):
    def pick_last(items):
        it = items[0]
        return CoursePick(picks=[CourseChoice(skill=it["skill"], course_ref=it["candidates"][-1]["course_ref"],
                                              reason="cheaper and just as relevant")]), {"step": "t"}
    monkeypatch.setattr(llm_steps, "pick_courses", pick_last)
    found = course_agent.run([SKILL], PERSON)["courses"][SKILL]
    assert found["chosen_ref"] == found["courses"][-1]["course_ref"]
    assert found["pick_reason"] == "cheaper and just as relevant"
    assert found["alternative_ref"] != found["chosen_ref"]


def _force_miss(monkeypatch):
    def miss(index, skill, description="", n=2):
        return {"skill": skill, "status": "no_strong_match", "query": skill, "courses": [], "message": "none"}
    monkeypatch.setattr(course_agent, "find_courses_for_skill", miss)


def test_rewritten_query_rescues_a_miss(monkeypatch):
    _force_miss(monkeypatch)
    rw = QueryRewrite(rewrites=[SkillQueries(skill=SKILL, queries=["", "data governance framework"]),
                                SkillQueries(skill="Not Asked", queries=["x"])])
    monkeypatch.setattr(llm_steps, "rewrite_queries", lambda *_: (rw, {"step": "t"}))
    found = course_agent.run([SKILL], PERSON)["courses"][SKILL]
    assert found["status"] == "rewritten" and found["query"] == "data governance framework"
    assert found["courses"] and found["chosen_ref"] in {c["course_ref"] for c in found["courses"]}


def test_junk_rewrite_stays_an_honest_miss(monkeypatch):
    _force_miss(monkeypatch)
    rw = QueryRewrite(rewrites=[SkillQueries(skill=SKILL, queries=["   "])])
    monkeypatch.setattr(llm_steps, "rewrite_queries", lambda *_: (rw, {"step": "t"}))
    out = course_agent.run([SKILL], PERSON)
    found = out["courses"][SKILL]
    assert found["status"] == "no_strong_match" and found["courses"] == [] and "chosen_ref" not in found
    assert "no strong match" in out["notes"][-1]


def test_long_gap_list_is_picked_in_chunks(monkeypatch):
    from lookups import skill_gap
    skills = [g["skill"] for g in skill_gap(1056, 1059)]           # 49 gaps (E1 p11 was cut off)
    sizes, real = [], llm_steps.pick_courses

    def spy(items):
        sizes.append(len(items))
        return real(items)
    monkeypatch.setattr(llm_steps, "pick_courses", spy)
    out = course_agent.run(skills, PERSON)
    assert max(sizes) <= course_agent.PICK_CHUNK and len(sizes) > 1
    assert out["fallbacks"] == []
