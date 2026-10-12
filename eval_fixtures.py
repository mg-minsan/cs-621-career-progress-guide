"""Reviewed evaluation fixtures for retrieval and recommendation quality.

This module holds a small, hand-reviewed evaluation set for the SkillsFuture
career and course recommendation workflow. Retrieval relevance and
recommendation quality are measured separately, so the fixtures are split:

* ``retrieval_cases`` pair a natural-language query with the entities a correct
  system should surface. They provide ground truth for recall/precision at
  top-k and mean reciprocal rank. Each case records which side of the system is
  being measured (``entity_type`` is ``role`` or ``course``).
* ``recommendation_scenarios`` pair a realistic user profile with the
  properties a correct recommendation must satisfy: citations on every claim,
  uncertainty for missing evidence, constraint checks, and no invented
  readiness, funding or transition claims.
* ``lookup_cases`` pin down exact-lookup and title-ambiguity behaviour so that
  the structured lookup contract stays stable while search evolves.

Entity references use human-readable keys (sector + track + title for roles,
the SkillsFuture course reference number for courses) so the set can be
reviewed without canonical SHA-256 role IDs. :func:`resolve_fixtures` turns
references into the canonical IDs produced by ``lookup.py`` against a real
database; :func:`validate_fixtures` checks the set is well formed without one.

This is data, not an engine. The keyword/semantic retrieval (phase 2/3) and the
recommendation agent (phase 4/5) consume these fixtures through
``evaluate.evaluate_retrieval`` and ``evaluate.check_recommendation``.
"""
from __future__ import annotations

import copy

from lookup import CareerLookup


SCHEMA_VERSION = 1

ROLE_KINDS = ("role", "course")
ASSESSMENT_LABELS = ("supported", "potentially_aligned", "evidenced_gap", "unknown")


def role_ref(sector: str, track: str, title: str) -> dict:
    """A human-readable role reference resolved to a canonical ID at load time."""
    return {"type": "role", "sector": sector, "track": track, "title": title}


def course_ref(course_id: str) -> dict:
    """A human-readable course reference (SkillsFuture course reference number)."""
    return {"type": "course", "course_id": course_id}


LOOKUP_CASES = [
    {
        "id": "lookup-exact-software-engineer",
        "title": "Software Engineer",
        "sector": "Infocomm Technology",
        "track": "Software and Applications",
        "expected_status": "ok",
        "expected_role": role_ref(
            "Infocomm Technology", "Software and Applications", "Software Engineer"),
        "expected_min_skill_count": 27,
        "notes": ("A unique sector+track+title resolves to one role; the supplied "
                  "workbooks record 27 skill requirements for Software Engineer."),
    },
    {
        "id": "lookup-ambiguous-marketing-manager",
        "title": "Marketing Manager",
        "sector": None,
        "track": None,
        "expected_status": "ambiguous",
        "expected_candidates": [
            role_ref("Energy and Power", "Energy Retail", "Marketing Manager"),
            role_ref("Infocomm Technology", "Sales and Marketing", "Marketing Manager"),
            role_ref("Media", "Media Business Management", "Marketing Manager"),
            role_ref("Retail", "Marketing", "Marketing Manager"),
            role_ref("Tourism",
                     "Business Development, Sales, Sponsorships and Marketing",
                     "Marketing Manager"),
            role_ref("Wholesale Trade",
                     "Marketing, Business Development and Analysis",
                     "Marketing Manager"),
        ],
        "notes": ("A title alone can identify several roles in different sectors and "
                  "tracks. Exact-title resolution must not silently pick one."),
    },
    {
        "id": "lookup-disambiguated-marketing-manager-retail",
        "title": "Marketing Manager",
        "sector": "Retail",
        "track": None,
        "expected_status": "ok",
        "expected_role": role_ref("Retail", "Marketing", "Marketing Manager"),
        "notes": ("Adding the Retail sector disambiguates the shared Marketing Manager "
                  "title to a single role."),
    },
    {
        "id": "lookup-not-found",
        "title": "No Such Role Title",
        "sector": None,
        "track": None,
        "expected_status": "not_found",
        "notes": "Unknown titles return a clear not-found result, never an empty pick.",
    },
    {
        "id": "lookup-exact-account-operations-analyst",
        "title": "Account Operations Analyst",
        "sector": "Financial Services",
        "track": "Operations",
        "expected_status": "ok",
        "expected_role": role_ref(
            "Financial Services", "Operations", "Account Operations Analyst"),
        "notes": "A second exact-lookup example from a different sector/track.",
    },
]

RETRIEVAL_CASES = [
    {
        "id": "role-discovery-backend-python",
        "entity_type": "role",
        "query": ("I build backend APIs with Python, write SQL queries, and enjoy "
                  "designing data schemas."),
        "filters": {"sector": None, "track": None},
        "relevant": [
            role_ref("Infocomm Technology", "Software and Applications",
                     "Software Engineer"),
            role_ref("Infocomm Technology", "Software and Applications",
                     "Associate Software Engineer"),
            role_ref("Financial Services", "Digital and Data Analytics", "Data Engineer"),
        ],
        "notes": ("The two Software and Applications roles list application "
                  "development, software design and data design among their recorded "
                  "tasks/skills; the Financial Services Data Engineer records "
                  "programming, data collection and software configuration. These are "
                  "interest-based candidates, not readiness claims."),
    },
    {
        "id": "role-discovery-data-visualisation",
        "entity_type": "role",
        "query": ("I like turning messy data into dashboards and explaining insights "
                  "to non-technical stakeholders."),
        "filters": {"sector": None, "track": None},
        "relevant": [
            role_ref("Financial Services", "Digital and Data Analytics", "Data Analyst"),
            role_ref("Financial Services", "Digital and Data Analytics", "Data Scientist"),
        ],
        "notes": ("Both roles record Data Storytelling and Visualisation plus Data "
                  "Analytics and Computational Modelling as required skills."),
    },
    {
        "id": "role-discovery-application-security",
        "entity_type": "role",
        "query": "I am interested in application security and responding to incidents.",
        "filters": {"sector": "Infocomm Technology", "track": None},
        "relevant": [
            role_ref("Infocomm Technology", "Cyber Security", "Associate Security Analyst"),
            role_ref("Infocomm Technology", "Cyber Security", "Security Operations Analyst"),
            role_ref("Infocomm Technology", "Cyber Security",
                     "Senior Security Engineer / Security Engineer"),
            role_ref("Infocomm Technology", "Product Development", "Product Security Engineer"),
        ],
        "notes": ("Cyber Security roles record security operations and analysis "
                  "responsibilities; Product Security Engineer applies security within "
                  "product development. The sector filter is an explicit, reviewable "
                  "constraint rather than a similarity artefact."),
    },
    {
        "id": "course-search-python-basics",
        "entity_type": "course",
        "query": "beginner Python programming course for someone new to coding",
        "filters": None,
        "relevant": [
            course_ref("TGS-2018500660"),
            course_ref("TGS-2019503161"),
            course_ref("TGS-2019503784"),
        ],
        "notes": ("Three courses whose titles and learning outcomes teach Python "
                  "programming fundamentals; TGS-2019503161 is explicitly a beginner "
                  "course."),
    },
    {
        "id": "course-search-cybersecurity",
        "entity_type": "course",
        "query": "introduction to cybersecurity for an IT professional",
        "filters": None,
        "relevant": [
            course_ref("TGS-2017505361"),
            course_ref("TGS-2018500229"),
            course_ref("TGS-2018500682"),
        ],
        "notes": ("Preparing for Cybersecurity, a non-IT-professional cybersecurity "
                  "course, and CISSP preparation are all cybersecurity courses with "
                  "matching titles/outcomes."),
    },
    {
        "id": "course-search-workplace-communication",
        "entity_type": "course",
        "query": "effective communication and engagement at the workplace",
        "filters": None,
        "relevant": [
            course_ref("TGS-2011500441"),
            course_ref("TGS-2011500998"),
            course_ref("TGS-2011501038"),
        ],
        "notes": ("Three courses teaching workplace communication/engagement; one "
                  "leads communication at a supervisory level."),
    },
]

RECOMMENDATION_SCENARIOS = [
    {
        "id": "recommend-backend-to-software-engineer",
        "kind": "recommendation",
        "profile": {
            "current_role": "Junior Backend Developer",
            "experience_years": 2,
            "skills": [
                {"name": "Python", "level": "intermediate",
                 "evidence": "Built REST APIs with FastAPI at work",
                 "assessment_type": "self_reported"},
                {"name": "SQL", "level": "intermediate",
                 "evidence": "Writes and tunes PostgreSQL queries",
                 "assessment_type": "self_reported"},
                {"name": "Software Design", "framework_code": "ICT-DES-4005-1.1",
                 "framework_level": "4",
                 "evidence": "Produced design documentation for a small internal service",
                 "assessment_type": "self_reported"},
            ],
            "interests": ["backend development", "system integration"],
            "target_role": role_ref(
                "Infocomm Technology", "Software and Applications", "Software Engineer"),
            "constraints": {"budget_sgd": 1200, "hours_per_week": 6, "language": "English"},
            "qualifications": [],
        },
        "notes": ("A self-reported 'intermediate' Python level and a named framework "
                  "level are supplied as claims, not established proficiency. The "
                  "recommendation must cite source records, label evidence against "
                  "level-4 Software Design expectations, and never convert '2 years' "
                  "or technology names into a framework level or readiness score."),
    },
    {
        "id": "recommend-data-analyst-no-target",
        "kind": "recommendation",
        "profile": {
            "current_role": None,
            "experience_years": None,
            "skills": [
                {"name": "Excel", "level": "advanced",
                 "evidence": "Builds pivot tables and reports for a sales team",
                 "assessment_type": "self_reported"},
            ],
            "interests": ["data analysis", "visualisation", "reporting"],
            "target_role": None,
            "constraints": None,
            "qualifications": [],
        },
        "notes": ("No target role is supplied. The system must offer plausible "
                  "directions (for example the Financial Services Data Analyst) with "
                  "evidence, and must not treat the absence of other profile skills as "
                  "proof that those skills are missing."),
    },
    {
        "id": "recommend-python-with-budget",
        "kind": "recommendation",
        "profile": {
            "current_role": "Administrative Assistant",
            "experience_years": None,
            "skills": [],
            "interests": ["automation", "Python"],
            "target_role": None,
            "constraints": {"budget_sgd": 400, "hours_per_week": 4, "language": "English"},
            "qualifications": [],
        },
        "expected_prerequisite_unknown_for": ["TGS-2018500660"],
        "notes": ("A SGD 400 budget constrains course choice: the subsidised fee of "
                  "TGS-2019503161 (SGD 375) fits while the SGD 500/750 alternatives do "
                  "not. TGS-2018500660 has no recorded entry requirements, so its "
                  "prerequisite assessment must be 'unknown', not assumed satisfied."),
    },
    {
        "id": "recommend-missing-requirements-role",
        "kind": "recommendation",
        "profile": {
            "current_role": None,
            "experience_years": None,
            "skills": [],
            "interests": ["arts", "education"],
            "target_role": role_ref("Arts", "Arts Education", "Arts Educator"),
            "constraints": None,
            "qualifications": [],
        },
        "must_report_missing_requirements": True,
        "notes": ("Arts Educator has no recorded skill requirements in the supplied "
                  "workbooks. The recommendation must disclose that coverage is "
                  "unknown, not claim the role needs no skills."),
    },
    {
        "id": "recommend-multiple-skill-mappings",
        "kind": "recommendation",
        "profile": {
            "current_role": "Digital Transformation Manager",
            "experience_years": 6,
            "skills": [{"name": "Business Environment Analysis",
                        "framework_code": "FSE-ACE-5001-1.1-1",
                        "framework_level": "5",
                        "evidence": "Led market scans for a transformation programme",
                        "assessment_type": "self_reported"}],
            "interests": ["digital transformation", "market analysis"],
            "target_role": role_ref(
                "Financial Services", "Digital and Data Analytics",
                "Digital Transformation Manager"),
            "constraints": None,
            "qualifications": [],
        },
        "must_report_multiple_mappings": True,
        "notes": ("Framework code FSE-ACE-5001-1.1-1 maps to three distinct "
                  "unique-skill titles (Business Environment Analysis, Market "
                  "Evaluation, Market Profiling). A recommendation must preserve "
                  "all mappings and disclose the one-to-many relationship rather "
                  "than silently choosing one."),
    },
    {
        "id": "recommend-no-fabricated-claims",
        "kind": "recommendation",
        "profile": {
            "current_role": "Software Engineer",
            "experience_years": 5,
            "skills": [{"name": "Software Design", "framework_code": "ICT-DES-4005-1.1",
                        "framework_level": "4", "evidence": "Leads design reviews",
                        "assessment_type": "self_reported"}],
            "interests": ["leadership"],
            "target_role": role_ref(
                "Infocomm Technology", "Software and Applications",
                "Software Engineering Manager"),
            "constraints": None,
            "qualifications": [],
        },
        "notes": ("The supplied workbooks do not record a formal Software Engineer -> "
                  "Software Engineering Manager transition. The recommendation must not "
                  "invent a promotion path, readiness percentage, or personalised "
                  "funding eligibility; any such claim is a fabricated claim."),
    },
]

FIXTURES = {
    "schema_version": SCHEMA_VERSION,
    "lookup_cases": LOOKUP_CASES,
    "retrieval_cases": RETRIEVAL_CASES,
    "recommendation_scenarios": RECOMMENDATION_SCENARIOS,
}


def _problem(problems, message):
    problems.append(message)
    return problems


def validate_fixtures(fixtures: dict) -> list[str]:
    """Return every structural problem in a fixture set; empty means valid.

    This checks shape and reference structure only. It does not touch a
    database, so it cannot confirm that references exist or that lookup
    expectations still hold.
    """
    problems = []
    if not isinstance(fixtures, dict):
        return _problem(problems, "fixtures must be a dict")
    if fixtures.get("schema_version") != SCHEMA_VERSION:
        _problem(problems, f"schema_version must be {SCHEMA_VERSION}")

    def require(record, key, collection, seen_ids):
        if not isinstance(record, dict):
            _problem(problems, f"{collection} contains a non-dict entry")
            return None
        if "id" not in record:
            _problem(problems, f"{collection} entry is missing 'id'")
            return None
        if record["id"] in seen_ids:
            _problem(problems, f"duplicate fixture id {record['id']!r}")
            return None
        seen_ids.add(record["id"])
        if key not in record:
            _problem(problems, f"{record['id']!r} is missing {key!r}")
        return record

    def check_reference(ref, owner):
        if not isinstance(ref, dict):
            return _problem(problems, f"{owner}: reference must be a dict")
        kind = ref.get("type")
        if kind == "role":
            for field in ("sector", "track", "title"):
                if not ref.get(field):
                    _problem(problems, f"{owner}: role reference is missing {field!r}")
        elif kind == "course":
            if not ref.get("course_id"):
                _problem(problems, f"{owner}: course reference is missing 'course_id'")
        else:
            _problem(problems, f"{owner}: unknown reference type {kind!r}")

    seen = set()
    for case in fixtures.get("lookup_cases", []):
        if require(case, "title", "lookup_cases", seen) is None:
            continue
        if case.get("expected_status") not in ("ok", "ambiguous", "not_found"):
            _problem(problems, f"{case['id']!r}: invalid expected_status")
        if case.get("expected_role") is not None:
            check_reference(case["expected_role"], case["id"])
        for ref in case.get("expected_candidates", []) or []:
            check_reference(ref, case["id"])

    seen = set()
    for case in fixtures.get("retrieval_cases", []):
        if require(case, "query", "retrieval_cases", seen) is None:
            continue
        if case.get("entity_type") not in ROLE_KINDS:
            _problem(problems, f"{case['id']!r}: invalid entity_type")
        relevant = case.get("relevant", []) or []
        if not relevant:
            _problem(problems, f"{case['id']!r}: 'relevant' must be non-empty")
        for ref in relevant:
            check_reference(ref, case["id"])

    seen = set()
    for scenario in fixtures.get("recommendation_scenarios", []):
        if require(scenario, "profile", "recommendation_scenarios", seen) is None:
            continue
        profile = scenario["profile"]
        if not isinstance(profile, dict):
            _problem(problems, f"{scenario['id']!r}: profile must be a dict")
            continue
        target = profile.get("target_role")
        if target is not None:
            check_reference(target, scenario["id"])
    return problems


def resolve_reference(lookup: CareerLookup, ref: dict) -> str:
    """Return the canonical entity ID for a human-readable reference.

    Role references resolve through exact-title lookup (sector + track remove
    ambiguity); course references resolve through the course reference number.
    Raises ValueError if the reference does not identify exactly one entity.
    """
    kind = ref.get("type")
    if kind == "role":
        result = lookup.resolve_role(ref["title"], ref.get("sector"), ref.get("track"))
        if result["status"] != "ok":
            raise ValueError(f"role reference does not resolve: {ref!r} "
                             f"(status {result['status']})")
        return result["data"]["role_id"]
    if kind == "course":
        result = lookup.get_course(ref["course_id"])
        if result["status"] != "ok":
            raise ValueError(f"course reference does not resolve: {ref!r} "
                             f"(status {result['status']})")
        return result["data"]["course_id"]
    raise ValueError(f"unknown reference type: {ref!r}")


def resolve_fixtures(fixtures: dict, db_path) -> dict:
    """Return a deep copy of the fixture set with canonical IDs resolved.

    Every role/course reference is resolved against ``db_path`` so retrieval
    cases carry ``relevant_ids`` and lookup cases carry ``expected_role_id`` /
    ``expected_candidate_ids``. Any reference that does not identify exactly one
    entity raises ValueError.
    """
    resolved = copy.deepcopy(fixtures)
    with CareerLookup(db_path) as lookup:
        for case in resolved.get("lookup_cases", []):
            if case.get("expected_role") is not None:
                case["expected_role_id"] = resolve_reference(
                    lookup, case["expected_role"])
            candidates = case.get("expected_candidates")
            if candidates is not None:
                case["expected_candidate_ids"] = [
                    resolve_reference(lookup, ref) for ref in candidates]
        for case in resolved.get("retrieval_cases", []):
            case["relevant_ids"] = [
                resolve_reference(lookup, ref) for ref in case["relevant"]]
    return resolved


def run_lookup_cases(fixtures: dict, db_path) -> list[dict]:
    """Verify each lookup case against a real database.

    Returns one record per case with ``id``, ``passed`` and ``message``. This is
    the fixture's self-check: the reviewed expectations must match the current
    lookup behaviour, or the set is stale.
    """
    results = []
    with CareerLookup(db_path) as lookup:
        for case in fixtures.get("lookup_cases", []):
            result = lookup.resolve_role(case["title"], case.get("sector"),
                                         case.get("track"))
            expected = case["expected_status"]
            if result["status"] != expected:
                results.append({"id": case["id"], "passed": False,
                                "message": f"status {result['status']!r} != "
                                           f"{expected!r}"})
                continue
            if expected == "ok":
                expected_id = case.get("expected_role_id")
                if expected_id is not None and result["data"]["role_id"] != expected_id:
                    results.append({"id": case["id"], "passed": False,
                                    "message": "resolved an unexpected role"})
                    continue
                minimum = case.get("expected_min_skill_count")
                if minimum is not None:
                    count = len(result["data"]["skills"])
                    if count < minimum:
                        results.append({"id": case["id"], "passed": False,
                                        "message": f"{count} skills < {minimum}"})
                        continue
            elif expected == "ambiguous":
                candidate_ids = set(case.get("expected_candidate_ids", []))
                actual_ids = {candidate["role_id"] for candidate in result["data"]}
                if candidate_ids and candidate_ids != actual_ids:
                    results.append({"id": case["id"], "passed": False,
                                    "message": "ambiguous candidates differ from "
                                               "the reviewed set"})
                    continue
            results.append({"id": case["id"], "passed": True, "message": "ok"})
    return results
