#!/usr/bin/env python3
"""End-to-end career/course walkthrough from a profile (retrieval + lookup).

This chains the implemented pieces — keyword search and structured lookup —
into one flow:

    profile -> candidate roles -> role requirements -> courses -> cited summary

Steps that belong to the not-yet-built recommendation agent (proficiency
assessment, learning-priority ranking, prerequisite/budget checks) are out of
scope here. The script reports recorded facts and source references, marks
profile mentions literally (not as an assessment), and labels anything it
cannot assess as unknown. It never emits readiness scores or funding
eligibility.

Usage:
    .venv/bin/python guide.py
    .venv/bin/python guide.py --profile data
    .venv/bin/python guide.py --profile backend --role "Software Engineer"
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from demo_profile import SAMPLE_PROFILES, _profile_query
from lookup import CareerLookup, DEFAULT_DB
from search import KeywordSearch


def _citations(sources: list[dict]) -> list[str]:
    seen, ordered = set(), []
    for source in sources:
        key = (source.get("source_file"), source.get("source_sheet"),
               source.get("source_row"))
        if key in seen:
            continue
        seen.add(key)
        ordered.append(f"{source.get('source_file')} · {source.get('source_sheet')} "
                       f"row {source.get('source_row')}")
    return ordered


def _mentioned(skill_title: str, profile: dict) -> bool:
    terms = {term.lower() for term in profile.get("skills", []) +
             profile.get("interests", [])}
    title = (skill_title or "").lower()
    return title in terms or any(term in title for term in terms)


def run(profile: dict, role_title: str | None = None, db_path=DEFAULT_DB,
        role_limit: int = 5, course_limit: int = 4) -> dict:
    """Walk the flow and return a structured, citation-backed result."""
    with KeywordSearch(db_path) as search, CareerLookup(db_path) as lookup:
        candidates = []
        for item in search.search(_profile_query(profile), "role",
                                  limit=role_limit)["results"]:
            role = lookup.get_role(item["entity_id"])["data"]
            candidates.append({
                "role_id": role["role_id"], "title": role["role_title"],
                "sector": role["sector"], "track": role["track"],
                "skill_count": len(role["skills"]),
                "task_count": len(role["tasks"]),
            })

        focus_result = None
        if role_title:
            resolved = lookup.resolve_role(role_title)
            if resolved["status"] == "ambiguous":
                return {"error": "ambiguous",
                        "candidates": [{"title": c["role_title"],
                                        "sector": c["sector"], "track": c["track"]}
                                       for c in resolved["data"]]}
            if resolved["status"] == "not_found":
                return {"error": "not_found", "role_title": role_title}
            focus_result = resolved
        elif candidates:
            focus_result = lookup.get_role(candidates[0]["role_id"])

        result = {"profile": profile, "candidates": candidates,
                  "focus_role": None, "requirements": [], "courses": [],
                  "role_sources": []}
        if focus_result is None or focus_result.get("data") is None:
            return result
        focus = focus_result["data"]

        result["focus_role"] = {
            "role_id": focus["role_id"], "title": focus["role_title"],
            "sector": focus["sector"], "track": focus["track"],
            "description": (focus["description"] or "")[:220],
        }
        result["role_sources"] = _citations(focus_result["source_records"])

        requirements = lookup.get_role_skills(focus["role_id"])["data"]
        for requirement in requirements:
            mentioned = _mentioned(requirement["source_skill_title"], profile)
            result["requirements"].append({
                "title": requirement["source_skill_title"],
                "code": requirement["framework_skill_code"],
                "level": requirement["required_level"],
                "mentioned_in_profile": mentioned,
                "sources": _citations(requirement["source_records"]),
            })

        # Candidate learning priorities: required skills not literally mentioned.
        priorities = [r for r in result["requirements"]
                      if not r["mentioned_in_profile"]]
        priorities = priorities or result["requirements"]
        for priority in priorities[:3]:
            title = priority["title"]
            course_hits = search.search(title, "course", limit=course_limit)["results"]
            for hit in course_hits:
                course = lookup.get_course(hit["entity_id"])["data"]
                result["courses"].append({
                    "learning_priority": title,
                    "course_id": course["course_id"], "title": course["title"],
                    "provider": course["provider_name"], "hours": course["hours"],
                    "listed_subsidised_fee": course["listed_subsidised_fee"],
                    "language": course["language"],
                    "entry_requirements": course["entry_requirements"],
                    "sources": _citations(course["selected_source_records"]),
                })
    return result


def _print(result: dict) -> None:
    if result.get("error"):
        if result["error"] == "ambiguous":
            print("Role title is ambiguous. Narrow with --profile's sector/track, or:")
            for candidate in result["candidates"]:
                print(f"  - {candidate['title']} [{candidate['sector']} / {candidate['track']}]")
        else:
            print(f"Role not found: {result['role_title']}")
        return

    profile = result["profile"]
    print("=== 1. Profile ===")
    print(f"  skills: {', '.join(profile.get('skills', [])) or '(none)'}")
    print(f"  interests: {', '.join(profile.get('interests', [])) or '(none)'}")
    print()

    print("=== 2. Candidate roles (keyword search) ===")
    for candidate in result["candidates"]:
        print(f"  {candidate['title']}  [{candidate['sector']} / {candidate['track']}]"
              f"  ({candidate['skill_count']} skills, {candidate['task_count']} tasks)")
    print()

    focus = result["focus_role"]
    if focus is None:
        print("No focus role found.")
        return
    print(f"=== 3. Focus role: {focus['title']} [{focus['sector']} / {focus['track']}] ===")
    print(f"  {focus['description']}")
    print(f"  sources: {result['role_sources'][0] if result['role_sources'] else 'none'}")
    print()

    print("=== 4. Recorded requirements (mentions are literal, not assessment) ===")
    for requirement in result["requirements"]:
        flag = "mentioned" if requirement["mentioned_in_profile"] else "priority"
        print(f"  [{flag}] {requirement['title']} (level {requirement['level']}, "
              f"{requirement['code']})")
    print()

    print("=== 5. Candidate courses for top learning priorities ===")
    for course in result["courses"]:
        fee = course["listed_subsidised_fee"]
        print(f"  [{course['learning_priority']}] {course['title'][:60]}")
        print(f"    provider: {course['provider']} | hours: {course['hours']} | "
              f"fee: {fee if fee is not None else 'not listed'} | "
              f"lang: {course['language'] or 'not listed'}")
        if course["entry_requirements"]:
            print(f"    entry requirements: {course['entry_requirements'][:120]}")
        print(f"    source: {course['sources'][0] if course['sources'] else 'none'}")
    print()
    print("Proficiency, readiness, course-to-skill mapping and funding eligibility "
          "are NOT assessed here (phases 4-6). Listed fees are subsidised prices, "
          "not quotes.")


def main(argv: list[str]) -> int:
    if not DEFAULT_DB.is_file():
        print(f"Career database not found: {DEFAULT_DB}. Run "
              f"`.venv/bin/python ingest.py --db data/career-ingested.duckdb` first.")
        return 1
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--profile", default="backend", choices=list(SAMPLE_PROFILES))
    parser.add_argument("--role", default=None,
                        help="target role title (default: top search candidate)")
    args = parser.parse_args(argv)
    _print(run(SAMPLE_PROFILES[args.profile], role_title=args.role))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
