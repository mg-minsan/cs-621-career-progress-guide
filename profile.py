"""User profile schema definition and validation (phase 4).

Defines and validates the JSON profile accepted by the recommendation
workflow. A profile may contain some or all of:

- ``interests``: preferred activities.
- ``experience_years``: numeric years of experience; per-skill ``evidence``
  carries project/experience detail.
- ``skills``: skill entries with a claimed proficiency (``level``), evidence
  and an assessment method (``assessment_type``). An entry may be a plain
  string (a bare title) or a dict.
- ``current_role`` and optional ``target_role`` (a role reference dict).
- ``constraints``: budget, study time and language preferences.
- ``qualifications``: credentials relevant to course prerequisites.

Validation separates user-stated facts from self-reported proficiency claims
and system-inferred competency matches. It never treats missing evidence as
proof of a missing skill, never equates technology names or years of
experience with a framework level, and never computes a readiness score.

Skill ``assessment_type`` is one of ``self_reported`` (the user claims a
proficiency), ``verified`` (a credential/assessment backs the claim) or
``inferred`` (the system derived the match from evidence; never a user claim).
``verified`` entries are still user-supplied claims, so they are grouped with
``self_reported`` in the evidence split.

Result envelope::

    {
        "schema_version": 1,
        "status": "ok" | "invalid",
        "data": normalized profile dict, or None when invalid,
        "errors": [{"path": "...", "message": "..."}, ...],
        "missing_data": [top-level coverage gaps],
        "evidence": {
            "supplied_facts": {...},
            "self_reported_claims": [skill, ...],
            "inferred_matches": [skill, ...],
        },
        "unknown_fields": [unknown top-level keys, preserved, non-fatal],
    }

``missing_data`` reports coverage gaps (fields that are absent or empty). It
records that evidence is unavailable, not that a skill is missing: an absent
or empty ``skills`` list is kept as an empty list and flagged, never converted
into a claim that the user lacks skills.
"""
from __future__ import annotations

import math

SCHEMA_VERSION = 1

# Per-skill assessment methods. "verified" is still a user-supplied claim; it
# just carries credential/assessment evidence rather than bare self-reporting.
ASSESSMENT_TYPES = ("self_reported", "verified", "inferred")

TARGET_ROLE_TYPES = ("role",)

# User-stated biographical/constraint facts, distinct from proficiency claims
# and system-inferred matches.
FACT_FIELDS = ("current_role", "experience_years", "qualifications", "constraints")

KNOWN_FIELDS = (
    "current_role",
    "experience_years",
    "skills",
    "interests",
    "learning_goal",
    "target_role",
    "constraints",
    "qualifications",
)

def _required_string(value, path, errors):
    if not isinstance(value, str) or not value.strip():
        errors.append({"path": path, "message": "must be a non-empty string"})
        return None
    return value.strip()


def _optional_string(value, path, errors):
    if value is None:
        return None
    if not isinstance(value, str):
        errors.append({"path": path, "message": "must be a string"})
        return None
    if not value.strip():
        errors.append({"path": path, "message": "must not be blank"})
        return None
    return value.strip()


def _number(value, path, errors):
    """A non-negative, finite number; None means not supplied."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        errors.append({"path": path, "message": "must be a number"})
        return None
    if not math.isfinite(value):
        errors.append({"path": path, "message": "must be finite"})
        return None
    if value < 0:
        errors.append({"path": path, "message": "must not be negative"})
        return None
    return value


def _string_list(value, path, errors):
    if value is None:
        return None
    if not isinstance(value, list):
        errors.append({"path": path, "message": "must be a list of strings"})
        return None
    items = []
    for index, entry in enumerate(value):
        if not isinstance(entry, str) or not entry.strip():
            errors.append({"path": f"{path}[{index}]",
                           "message": "must be a non-empty string"})
            continue
        items.append(entry.strip())
    return items


def _validate_skill(skill, path, errors):
    """Normalize one skill entry to a dict; a bare string is a title claim."""
    if isinstance(skill, str):
        name = _required_string(skill, path, errors)
        if name is None:
            return None
        return {
            "name": name,
            "level": None,
            "evidence": None,
            "assessment_type": "self_reported",
            "framework_code": None,
            "framework_level": None,
            "missing_data": ["proficiency_level", "evidence"],
        }
    if not isinstance(skill, dict):
        errors.append({"path": path, "message": "must be a dict or a string"})
        return None

    name = _required_string(skill.get("name"), f"{path}.name", errors)
    if name is None:
        return None
    level = _optional_string(skill.get("level"), f"{path}.level", errors)
    evidence = _optional_string(skill.get("evidence"), f"{path}.evidence", errors)
    assessment_type = skill.get("assessment_type", "self_reported")
    if assessment_type not in ASSESSMENT_TYPES:
        errors.append({"path": f"{path}.assessment_type",
                       "message": f"must be one of {ASSESSMENT_TYPES}"})
        assessment_type = "self_reported"
    framework_code = _optional_string(skill.get("framework_code"),
                                      f"{path}.framework_code", errors)
    framework_level = _optional_string(skill.get("framework_level"),
                                       f"{path}.framework_level", errors)

    missing = []
    if level is None:
        missing.append("proficiency_level")
    if evidence is None:
        missing.append("evidence")
    return {
        "name": name,
        "level": level,
        "evidence": evidence,
        "assessment_type": assessment_type,
        "framework_code": framework_code,
        "framework_level": framework_level,
        "missing_data": missing,
    }


def _validate_target_role(value, path, errors):
    if value is None:
        return None
    if not isinstance(value, dict):
        errors.append({"path": path, "message": "must be a dict"})
        return None
    kind = value.get("type")
    if kind not in TARGET_ROLE_TYPES:
        errors.append({"path": f"{path}.type",
                       "message": f"must be one of {TARGET_ROLE_TYPES}"})
        return None
    title = _required_string(value.get("title"), f"{path}.title", errors)
    sector = _optional_string(value.get("sector"), f"{path}.sector", errors)
    track = _optional_string(value.get("track"), f"{path}.track", errors)
    return {"type": kind, "title": title, "sector": sector, "track": track}


def _validate_constraints(value, path, errors):
    if value is None:
        return None
    if not isinstance(value, dict):
        errors.append({"path": path, "message": "must be a dict"})
        return None
    return {
        "budget_sgd": _number(value.get("budget_sgd"), f"{path}.budget_sgd", errors),
        "hours_per_week": _number(value.get("hours_per_week"),
                                  f"{path}.hours_per_week", errors),
        "language": _optional_string(value.get("language"), f"{path}.language", errors),
    }


def _coverage_gaps(data) -> list[str]:
    """Top-level fields whose evidence is absent or empty.

    These are coverage gaps, never assertions that a skill or fact is false.
    """
    gaps = []
    for field in ("current_role", "experience_years", "learning_goal", "target_role"):
        if data.get(field) is None:
            gaps.append(field)
    for field in ("skills", "interests", "qualifications"):
        if not data.get(field):
            gaps.append(field)
    if not data.get("constraints"):
        gaps.append("constraints")
    return gaps


def validate_profile(profile) -> dict:
    """Validate and normalize a user profile, separating evidence kinds.

    Returns the envelope described in the module docstring. Status is ``ok``
    when every supplied field is well formed (all fields are optional), or
    ``invalid`` with one error record per problem when not. Unknown top-level
    keys are preserved and reported, but do not invalidate the profile.
    """
    result = {
        "schema_version": SCHEMA_VERSION,
        "status": "ok",
        "data": None,
        "errors": [],
        "missing_data": [],
        "evidence": {
            "supplied_facts": {},
            "self_reported_claims": [],
            "inferred_matches": [],
        },
        "unknown_fields": [],
    }
    if not isinstance(profile, dict):
        result["status"] = "invalid"
        result["errors"].append({"path": "", "message": "profile must be a dict"})
        return result

    errors = []
    unknown = [key for key in profile if key not in KNOWN_FIELDS]
    data = {key: profile[key] for key in unknown}

    data["current_role"] = _optional_string(
        profile.get("current_role"), "current_role", errors)
    data["experience_years"] = _number(
        profile.get("experience_years"), "experience_years", errors)
    data["interests"] = _string_list(profile.get("interests"), "interests", errors)
    data["learning_goal"] = _optional_string(
        profile.get("learning_goal"), "learning_goal", errors)
    data["qualifications"] = _string_list(
        profile.get("qualifications"), "qualifications", errors)
    data["target_role"] = _validate_target_role(
        profile.get("target_role"), "target_role", errors)
    data["constraints"] = _validate_constraints(
        profile.get("constraints"), "constraints", errors)

    skills = []
    raw_skills = profile.get("skills")
    if raw_skills is None:
        raw_skills = []
    elif not isinstance(raw_skills, list):
        errors.append({"path": "skills", "message": "must be a list"})
        raw_skills = []
    for index, entry in enumerate(raw_skills):
        skill = _validate_skill(entry, f"skills[{index}]", errors)
        if skill is not None:
            skills.append(skill)
    data["skills"] = skills

    result["errors"] = errors
    result["unknown_fields"] = unknown
    if errors:
        result["status"] = "invalid"
        return result

    result["data"] = data
    result["missing_data"] = _coverage_gaps(data)
    result["evidence"] = {
        "supplied_facts": {field: data[field] for field in FACT_FIELDS},
        "self_reported_claims": [
            skill for skill in skills
            if skill["assessment_type"] in ("self_reported", "verified")
        ],
        "inferred_matches": [
            skill for skill in skills
            if skill["assessment_type"] == "inferred"
        ],
    }
    return result
