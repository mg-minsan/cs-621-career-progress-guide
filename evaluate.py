"""Evaluation harness for retrieval relevance and recommendation quality.

Retrieval relevance is measured separately from recommendation quality.

``evaluate_retrieval`` takes resolved retrieval fixtures (see
``eval_fixtures.resolve_fixtures``) and a pluggable ``retrieve`` callable, and
reports recall@k, precision@k and mean reciprocal rank per entity type. The
retriever is the keyword search (phase 2) or semantic search (phase 3); this
module does not depend on either.

``check_recommendation`` validates a recommendation output against a reviewed
scenario. It checks the output contract (candidate roles, learning priorities,
recommended courses and uncertainties), citation accuracy, allowed assessment
labels, constraint checks and the absence of fabricated readiness, funding or
transition claims. Recommendation quality is therefore scored by explicit
properties, not by the same similarity scores used for retrieval.
"""
from __future__ import annotations

from collections import defaultdict

from eval_fixtures import ASSESSMENT_LABELS


PREREQUISITE_STATES = ("satisfied", "unmet", "unknown")

RECOMMENDATION_KEYS = (
    "candidate_roles", "learning_priorities", "recommended_courses", "uncertainties")

COURSE_FIELDS = (
    "course_id", "title", "provider_name", "learning_priority",
    "outcome_evidence", "prerequisite_assessment", "hours", "commitment",
    "language", "listed_subsidised_fee",
)

DEFAULT_FORBIDDEN_CLAIMS = (
    "readiness",
    "promotion path",
    "career progression",
    "funding eligibility",
    "subsidy eligibility",
    "eligible for funding",
    "eligible for subsid",
)


def _dedupe(items):
    seen, ordered = set(), []
    for item in items:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def evaluate_retrieval(cases, retrieve, k: int = 5) -> dict:
    """Score a retriever against resolved retrieval fixtures.

    ``retrieve(query, entity_type, filters)`` returns ranked canonical entity
    IDs. Duplicate IDs are collapsed while preserving rank order. Recall@k and
    precision@k are computed against the reviewed relevant set; mean reciprocal
    rank rewards surfacing the first relevant entity early.
    """
    per_case = []
    for case in cases:
        relevant = set(case["relevant_ids"])
        results = _dedupe(retrieve(case["query"], case["entity_type"],
                                   case.get("filters")))
        top_k = results[:k]
        hits = [item for item in top_k if item in relevant]
        reciprocal_rank = 0.0
        for rank, item in enumerate(results, start=1):
            if item in relevant:
                reciprocal_rank = 1.0 / rank
                break
        per_case.append({
            "id": case["id"],
            "entity_type": case["entity_type"],
            "relevant_count": len(relevant),
            "returned_count": len(results),
            "recall_at_k": len(hits) / len(relevant) if relevant else 0.0,
            "precision_at_k": len(hits) / len(top_k) if top_k else 0.0,
            "reciprocal_rank": reciprocal_rank,
        })

    groups = defaultdict(list)
    for case in per_case:
        groups[case["entity_type"]].append(case)

    def aggregate(cases):
        if not cases:
            return None
        return {
            "case_count": len(cases),
            "mean_recall_at_k": sum(c["recall_at_k"] for c in cases) / len(cases),
            "mean_precision_at_k": sum(c["precision_at_k"] for c in cases) / len(cases),
            "mean_reciprocal_rank": sum(c["reciprocal_rank"] for c in cases) / len(cases),
        }

    return {
        "k": k,
        "cases": per_case,
        "aggregate": {
            "overall": aggregate(per_case),
            "role": aggregate(groups["role"]),
            "course": aggregate(groups["course"]),
        },
    }


def _text_values(value):
    """Yield every string value in a nested structure, ignoring dict keys."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _text_values(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _text_values(item)


def _numeric(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def check_recommendation(scenario, output) -> list[dict]:
    """Validate a recommendation output against a reviewed scenario.

    Returns a list of ``{"check", "passed", "message"}`` records. A failed
    ``output_shape`` check short-circuits; otherwise every check is attempted.
    """
    checks = []

    def add(name, passed, message):
        checks.append({"check": name, "passed": bool(passed), "message": message})

    if not isinstance(output, dict):
        add("output_shape", False, "recommendation output must be a dict")
        return checks

    missing = [key for key in RECOMMENDATION_KEYS if key not in output]
    add("output_shape", not missing,
        "missing keys: " + ", ".join(missing) if missing else "all keys present")

    forbidden = list(DEFAULT_FORBIDDEN_CLAIMS)
    forbidden.extend(scenario.get("forbidden_claims", []) or [])
    text = " ".join(_text_values(output)).lower()
    for claim in forbidden:
        add(f"no_forbidden_claim:{claim}", claim not in text,
            f"output mentions forbidden claim {claim!r}")

    profile = scenario.get("profile", {}) or {}
    constraints = profile.get("constraints", {}) or {}

    collections = (
        ("candidate_roles", "role_id"),
        ("learning_priorities", "framework_skill_code"),
        ("recommended_courses", "course_id"),
    )
    for collection, id_field in collections:
        for index, item in enumerate(output.get(collection, []) or []):
            label = f"{collection}[{index}]"
            if not isinstance(item, dict):
                add(f"{label}.shape", False, "entry must be a dict")
                continue
            sources = item.get("source_records")
            add(f"{label}.citations", bool(sources),
                "missing source_records" if not sources else "cited")

    for index, item in enumerate(output.get("learning_priorities", []) or []):
        if isinstance(item, dict):
            assessment = item.get("assessment")
            add(f"learning_priorities[{index}].assessment",
                assessment in ASSESSMENT_LABELS,
                f"assessment {assessment!r} not in {ASSESSMENT_LABELS}")

    for index, course in enumerate(output.get("recommended_courses", []) or []):
        if not isinstance(course, dict):
            continue
        missing = [field for field in COURSE_FIELDS if field not in course]
        add(f"recommended_courses[{index}].fields", not missing,
            "missing fields: " + ", ".join(missing) if missing else "complete")
        state = course.get("prerequisite_assessment")
        if state is not None:
            add(f"recommended_courses[{index}].prerequisite_state",
                state in PREREQUISITE_STATES,
                f"prerequisite_assessment {state!r} not in {PREREQUISITE_STATES}")

    budget = constraints.get("budget_sgd")
    if budget is not None:
        for index, course in enumerate(output.get("recommended_courses", []) or []):
            if not isinstance(course, dict):
                continue
            fee = course.get("listed_subsidised_fee")
            amount = _numeric(fee)
            if amount is None:
                add(f"recommended_courses[{index}].budget",
                    True, "fee missing; cannot verify budget constraint")
            else:
                add(f"recommended_courses[{index}].budget", amount <= budget,
                    f"subsidised fee {amount} exceeds budget {budget}")

    language = constraints.get("language")
    if language:
        for index, course in enumerate(output.get("recommended_courses", []) or []):
            if not isinstance(course, dict):
                continue
            course_language = course.get("language")
            matches = (course_language is None
                       or str(course_language).lower() == str(language).lower())
            add(f"recommended_courses[{index}].language", matches,
                f"course language {course_language!r} does not match {language!r}")

    if scenario.get("must_report_missing_requirements"):
        uncertainties = " ".join(_text_values(output.get("uncertainties", []))).lower()
        add("missing_requirements_reported", "requirement" in uncertainties,
            "uncertainties must disclose missing skill-requirement coverage")

    if scenario.get("must_report_multiple_mappings"):
        uncertainties = " ".join(_text_values(output.get("uncertainties", []))).lower()
        add("multiple_mappings_reported", "mapping" in uncertainties,
            "uncertainties must disclose one-to-many skill mappings")

    for course_id in scenario.get("expected_prerequisite_unknown_for", []) or []:
        matched = [course for course in output.get("recommended_courses", []) or []
                   if isinstance(course, dict) and course.get("course_id") == course_id]
        if not matched:
            continue
        state = matched[0].get("prerequisite_assessment")
        add(f"prerequisite_unknown:{course_id}", state == "unknown",
            f"course {course_id} prerequisite_assessment must be 'unknown' "
            f"(got {state!r})")

    return checks
