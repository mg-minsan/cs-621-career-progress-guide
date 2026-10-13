"""Tests for the user profile schema and validator (phase 4)."""
import unittest

from profile import (
    ASSESSMENT_TYPES,
    FACT_FIELDS,
    KNOWN_FIELDS,
    SCHEMA_VERSION,
    TARGET_ROLE_TYPES,
    validate_profile,
)


FULL_PROFILE = {
    "current_role": "Junior Backend Developer",
    "experience_years": 2,
    "skills": [
        {"name": "Python", "level": "intermediate",
         "evidence": "Built REST APIs with FastAPI at work",
         "assessment_type": "self_reported"},
        {"name": "Software Design", "framework_code": "ICT-DES-4005-1.1",
         "framework_level": "4",
         "evidence": "Produced design documentation for a small service",
         "assessment_type": "self_reported"},
    ],
    "interests": ["backend development", "system integration"],
    "learning_goal": "Python programming",
    "target_role": {"type": "role", "sector": "Infocomm Technology",
                    "track": "Software and Applications",
                    "title": "Software Engineer"},
    "constraints": {"budget_sgd": 1200, "hours_per_week": 6,
                    "language": "English"},
    "qualifications": ["BSc Computer Science"],
}


class ProfileSchemaTests(unittest.TestCase):
    def test_schema_constants(self):
        self.assertEqual(SCHEMA_VERSION, 1)
        self.assertEqual(ASSESSMENT_TYPES, ("self_reported", "verified", "inferred"))
        self.assertEqual(TARGET_ROLE_TYPES, ("role",))
        self.assertEqual(
            FACT_FIELDS,
            ("current_role", "experience_years", "qualifications", "constraints"))
        self.assertIn("skills", KNOWN_FIELDS)
        self.assertIn("target_role", KNOWN_FIELDS)
        self.assertIn("constraints", KNOWN_FIELDS)

    def test_full_profile_valid(self):
        result = validate_profile(FULL_PROFILE)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["data"]["current_role"], "Junior Backend Developer")
        self.assertEqual(result["data"]["experience_years"], 2)
        self.assertEqual(len(result["data"]["skills"]), 2)
        self.assertEqual(result["data"]["skills"][0]["assessment_type"], "self_reported")
        self.assertEqual(result["data"]["constraints"]["budget_sgd"], 1200)
        self.assertEqual(result["unknown_fields"], [])
        self.assertEqual(result["missing_data"], [])

    def test_empty_profile_is_ok_and_reports_coverage(self):
        result = validate_profile({})
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["skills"], [])
        self.assertEqual(result["data"]["current_role"], None)
        self.assertEqual(result["data"]["constraints"], None)
        # Every top-level field is a coverage gap, not a claim about the user.
        self.assertEqual(set(result["missing_data"]), set(KNOWN_FIELDS))

    def test_string_skill_is_normalised_to_a_claim(self):
        result = validate_profile({"skills": ["Software Design"]})
        self.assertEqual(result["status"], "ok")
        skill = result["data"]["skills"][0]
        self.assertEqual(skill["name"], "Software Design")
        self.assertEqual(skill["assessment_type"], "self_reported")
        self.assertEqual(skill["level"], None)
        self.assertEqual(skill["missing_data"], ["proficiency_level", "evidence"])

    def test_missing_skills_not_treated_as_missing_skill(self):
        result = validate_profile({"skills": [], "interests": ["arts"]})
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["skills"], [])
        self.assertIn("skills", result["missing_data"])
        # Coverage is flagged, but no "user lacks skills" claim or readiness is
        # fabricated anywhere in the result.
        for key in result:
            self.assertNotIn("missing_skill", key.lower())
            self.assertNotIn("readiness", key.lower())
        self.assertNotIn("missing skills", str(result).lower())

    def test_skill_without_evidence_is_kept_not_dropped(self):
        result = validate_profile({"skills": [{"name": "SQL"}]})
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["data"]["skills"]), 1)
        self.assertEqual(result["data"]["skills"][0]["name"], "SQL")
        self.assertIn("proficiency_level", result["data"]["skills"][0]["missing_data"])
        self.assertIn("evidence", result["data"]["skills"][0]["missing_data"])

    def test_no_readiness_generated(self):
        result = validate_profile(FULL_PROFILE)
        self.assertNotIn("readiness", result)
        self.assertNotIn("readiness", result["data"])
        self.assertNotIn("readiness_score", result["data"])

    def test_evidence_split_separates_claims_and_inferences(self):
        profile = {
            "current_role": "Data Analyst",
            "experience_years": 3,
            "qualifications": ["BSc"],
            "constraints": {"budget_sgd": 400, "hours_per_week": 4, "language": "English"},
            "skills": [
                {"name": "SQL", "level": "intermediate", "evidence": "daily reports",
                 "assessment_type": "self_reported"},
                {"name": "Excel", "level": "advanced", "evidence": "certification",
                 "assessment_type": "verified"},
                {"name": "Python", "level": "basic", "evidence": "automation scripts",
                 "assessment_type": "inferred"},
            ],
        }
        result = validate_profile(profile)
        self.assertEqual(result["status"], "ok")
        claims = result["evidence"]["self_reported_claims"]
        inferred = result["evidence"]["inferred_matches"]
        self.assertEqual([skill["name"] for skill in claims], ["SQL", "Excel"])
        self.assertEqual([skill["name"] for skill in inferred], ["Python"])
        facts = result["evidence"]["supplied_facts"]
        self.assertEqual(facts["current_role"], "Data Analyst")
        self.assertEqual(facts["experience_years"], 3)
        self.assertEqual(facts["qualifications"], ["BSc"])
        self.assertEqual(facts["constraints"]["budget_sgd"], 400)

    def test_unknown_top_level_field_is_preserved_nonfatal(self):
        result = validate_profile({"current_role": "Engineer", "custom_field": "x"})
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["unknown_fields"], ["custom_field"])
        self.assertEqual(result["data"]["custom_field"], "x")

    def test_non_dict_profile_invalid(self):
        result = validate_profile(["not", "a", "dict"])
        self.assertEqual(result["status"], "invalid")
        self.assertIsNone(result["data"])
        self.assertTrue(any(error["message"] == "profile must be a dict"
                            for error in result["errors"]))

    def test_negative_experience_years_invalid(self):
        result = validate_profile({"experience_years": -1})
        self.assertEqual(result["status"], "invalid")
        self.assertTrue(any(error["path"] == "experience_years"
                            for error in result["errors"]))

    def test_bool_experience_years_invalid(self):
        result = validate_profile({"experience_years": True})
        self.assertEqual(result["status"], "invalid")

    def test_skills_not_list_invalid(self):
        result = validate_profile({"skills": "Python"})
        self.assertEqual(result["status"], "invalid")
        self.assertTrue(any(error["path"] == "skills" for error in result["errors"]))

    def test_skill_missing_name_invalid(self):
        result = validate_profile({"skills": [{"level": "intermediate"}]})
        self.assertEqual(result["status"], "invalid")
        self.assertTrue(any(error["path"] == "skills[0].name"
                            for error in result["errors"]))

    def test_skill_bad_assessment_type_invalid(self):
        result = validate_profile(
            {"skills": [{"name": "Python", "assessment_type": "guessed"}]})
        self.assertEqual(result["status"], "invalid")
        self.assertTrue(any(error["path"] == "skills[0].assessment_type"
                            for error in result["errors"]))

    def test_negative_budget_invalid(self):
        result = validate_profile({"constraints": {"budget_sgd": -5}})
        self.assertEqual(result["status"], "invalid")
        self.assertTrue(any(error["path"] == "constraints.budget_sgd"
                            for error in result["errors"]))

    def test_negative_hours_invalid(self):
        result = validate_profile({"constraints": {"hours_per_week": -1}})
        self.assertEqual(result["status"], "invalid")

    def test_constraints_none_is_ok(self):
        result = validate_profile({"constraints": None})
        self.assertEqual(result["status"], "ok")
        self.assertIsNone(result["data"]["constraints"])
        self.assertIn("constraints", result["missing_data"])

    def test_target_role_missing_title_invalid(self):
        result = validate_profile({"target_role": {"type": "role"}})
        self.assertEqual(result["status"], "invalid")
        self.assertTrue(any(error["path"] == "target_role.title"
                            for error in result["errors"]))

    def test_target_role_bad_type_invalid(self):
        result = validate_profile({"target_role": {"type": "course", "title": "X"}})
        self.assertEqual(result["status"], "invalid")
        self.assertTrue(any(error["path"] == "target_role.type"
                            for error in result["errors"]))

    def test_numeric_level_label_must_be_string(self):
        # Claimed proficiency is a label, never auto-converted to a number.
        result = validate_profile({"skills": [{"name": "Python", "level": 4}]})
        self.assertEqual(result["status"], "invalid")
        self.assertTrue(any(error["path"] == "skills[0].level"
                            for error in result["errors"]))


class ProfileIntegrationTests(unittest.TestCase):
    """Existing sample profiles and fixtures must conform to the schema."""

    def test_demo_sample_profiles_validate(self):
        from demo_profile import SAMPLE_PROFILES
        for name, profile in SAMPLE_PROFILES.items():
            result = validate_profile(profile)
            self.assertEqual(result["status"], "ok", f"{name}: {result['errors']}")

    def test_recommendation_scenario_profiles_validate(self):
        from eval_fixtures import FIXTURES
        for scenario in FIXTURES["recommendation_scenarios"]:
            result = validate_profile(scenario["profile"])
            self.assertEqual(result["status"], "ok",
                             f"{scenario['id']}: {result['errors']}")


if __name__ == "__main__":
    unittest.main()
