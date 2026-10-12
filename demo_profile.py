#!/usr/bin/env python3
"""Run a sample user profile through the current retrieval stack.

This is a demonstration of role and course *discovery* from a profile. It is
not the recommendation agent (phase 4/5): it does not assess proficiency, map
technologies to framework levels, or check funding eligibility.

Keyword search matches the framework's own vocabulary (competency titles such
as "Software Design", not technology names such as "Python"). The sample
profiles therefore express skills and interests in SkillsFuture skill and role
terms; ``--skills`` / ``--roles`` list the real vocabulary so you can build
your own profiles.

Usage:
    .venv/bin/python demo_profile.py              # run the "backend" sample
    .venv/bin/python demo_profile.py data         # run the "data" sample
    .venv/bin/python demo_profile.py cybersecurity
    .venv/bin/python demo_profile.py --list       # list available samples
    .venv/bin/python demo_profile.py --skills software
    .venv/bin/python demo_profile.py --roles "data analyst"
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

import duckdb

from lookup import CareerLookup, DEFAULT_DB
from search import KeywordSearch


SAMPLE_PROFILES = {
    "backend": {
        "current_role": "Junior Backend Developer",
        "experience_years": 2,
        "skills": ["Software Design", "Applications Development",
                   "System Integration", "Database Administration",
                   "Software Testing"],
        "interests": ["software development", "application integration"],
        "learning_goal": "Python programming",
        "constraints": {"budget_sgd": 500, "hours_per_week": 6, "language": "English"},
    },
    "data": {
        "current_role": None,
        "experience_years": None,
        "skills": ["Data Analytics and Computational Modelling",
                   "Data Storytelling and Visualisation",
                   "Data Mining and Modelling"],
        "interests": ["data analysis", "visualisation"],
        "learning_goal": "data analytics",
        "constraints": {"budget_sgd": 400, "hours_per_week": 4, "language": "English"},
    },
    "cybersecurity": {
        "current_role": "IT Support Executive",
        "experience_years": 3,
        "skills": ["Cyber Risk Management", "Cyber Forensics",
                   "Threat Analysis and Defence", "Security Assessment and Testing"],
        "interests": ["application security", "incident response"],
        "learning_goal": "cybersecurity fundamentals",
        "constraints": None,
    },
}


def framework_skills(query: str = "", limit: int = 30) -> list[dict]:
    """Real framework skill titles from the database, filtered by a term."""
    with duckdb.connect(str(DEFAULT_DB), read_only=True) as db:
        rows = db.execute("""
            SELECT DISTINCT title, sector, category
            FROM core.framework_skills
            WHERE title IS NOT NULL
              AND (? = '' OR lower(title) LIKE '%' || lower(?) || '%')
            ORDER BY title
            LIMIT ?
        """, [query.strip(), query.strip(), limit]).fetchall()
    return [{"title": row[0], "sector": row[1], "category": row[2]} for row in rows]


def framework_roles(query: str = "", limit: int = 30) -> list[dict]:
    """Real role titles from the database, filtered by a term."""
    with duckdb.connect(str(DEFAULT_DB), read_only=True) as db:
        rows = db.execute("""
            SELECT DISTINCT role_title, sector, track
            FROM core.roles
            WHERE (? = '' OR lower(role_title) LIKE '%' || lower(?) || '%')
            ORDER BY role_title
            LIMIT ?
        """, [query.strip(), query.strip(), limit]).fetchall()
    return [{"title": row[0], "sector": row[1], "track": row[2]} for row in rows]


def _profile_query(profile: dict) -> str:
    return " ".join(profile.get("interests", []) + profile.get("skills", []))


def discover(profile: dict, db_path=DEFAULT_DB, role_limit: int = 5,
             course_limit: int = 5) -> dict:
    """Return candidate roles and courses for a profile, plus lookup facts."""
    result = {
        "profile": profile,
        "role_query": _profile_query(profile),
        "role_candidates": [],
        "course_candidates": [],
    }
    with KeywordSearch(db_path) as search, CareerLookup(db_path) as lookup:
        roles = search.search(_profile_query(profile), "role", limit=role_limit)
        for item in roles["results"]:
            role = lookup.get_role(item["entity_id"])["data"]
            result["role_candidates"].append({
                "entity_id": item["entity_id"],
                "title": role["role_title"], "sector": role["sector"],
                "track": role["track"], "score": item["score"],
                "description": (role["description"] or "")[:160],
                "skill_count": len(role["skills"]),
                "task_count": len(role["tasks"]),
                "skills": [skill["source_skill_title"] for skill in role["skills"][:6]],
            })

        courses = search.search(profile.get("learning_goal", "") or
                                _profile_query(profile), "course",
                                limit=course_limit)
        for item in courses["results"]:
            course = lookup.get_course(item["entity_id"])["data"]
            result["course_candidates"].append({
                "entity_id": item["entity_id"],
                "title": course["title"], "provider": course["provider_name"],
                "hours": course["hours"],
                "listed_subsidised_fee": course["listed_subsidised_fee"],
                "language": course["language"],
            })
    return result


def _print(result: dict) -> None:
    profile = result["profile"]
    print("Profile")
    print(f"  current role : {profile.get('current_role') or '(not supplied)'}")
    print(f"  skills       : {', '.join(profile.get('skills', [])) or '(none)'}")
    print(f"  interests    : {', '.join(profile.get('interests', [])) or '(none)'}")
    print(f"  learning goal: {profile.get('learning_goal') or '(none)'}")
    print()

    print(f"Candidate roles (query: {result['role_query']!r})")
    for candidate in result["role_candidates"]:
        print(f"  {candidate['title']}  [{candidate['sector']} / {candidate['track']}]")
        print(f"    skills ({candidate['skill_count']}): "
              f"{', '.join(candidate['skills']) or '(none recorded)'}")
        if candidate["description"]:
            print(f"    {candidate['description']}")
    print()

    print(f"Candidate courses (goal: {profile.get('learning_goal')!r})")
    for course in result["course_candidates"]:
        fee = course["listed_subsidised_fee"]
        print(f"  {course['title'][:64]}")
        print(f"    provider: {course['provider']} | hours: {course['hours']} | "
              f"fee: {fee if fee is not None else 'not listed'} | "
              f"lang: {course['language'] or 'not listed'}")
    print()
    print("This is retrieval only: relevance, not readiness, funding or "
          "proficiency. Fees are listed subsidised prices, not quotes.")


def _print_skills(query: str) -> None:
    print(f"Framework skill titles matching {query!r}:")
    for skill in framework_skills(query):
        print(f"  {skill['title']}  [{skill['sector']}]")


def _print_roles(query: str) -> None:
    print(f"Role titles matching {query!r}:")
    for role in framework_roles(query):
        print(f"  {role['title']}  [{role['sector']} / {role['track']}]")


def main(argv: list[str]) -> int:
    if not DEFAULT_DB.is_file():
        print(f"Career database not found: {DEFAULT_DB}. Run "
              f"`.venv/bin/python ingest.py --db data/career-ingested.duckdb` first.")
        return 1
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("profile", nargs="?", default="backend",
                        choices=list(SAMPLE_PROFILES), help="sample profile to run")
    parser.add_argument("--list", action="store_true", help="list available profiles")
    parser.add_argument("--skills", metavar="TERM", default=None,
                        help="list framework skill titles matching TERM")
    parser.add_argument("--roles", metavar="TERM", default=None,
                        help="list role titles matching TERM")
    args = parser.parse_args(argv)
    if args.list:
        print("Available sample profiles:", ", ".join(SAMPLE_PROFILES))
        return 0
    if args.skills is not None:
        _print_skills(args.skills)
        return 0
    if args.roles is not None:
        _print_roles(args.roles)
        return 0
    _print(discover(SAMPLE_PROFILES[args.profile]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
