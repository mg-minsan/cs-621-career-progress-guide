"""Retrieval metrics and recommendation-quality checks."""
import unittest

from evaluate import check_recommendation, evaluate_retrieval


def role_case(identifier, relevant):
    return {"id": identifier, "entity_type": "role", "query": "q",
            "filters": None, "relevant_ids": relevant}


def course_case(identifier, relevant):
    return {"id": identifier, "entity_type": "course", "query": "q",
            "filters": None, "relevant_ids": relevant}


class RetrievalMetricsTests(unittest.TestCase):
    def test_recall_precision_and_reciprocal_rank(self):
        cases = [role_case("r1", ["a", "b"])]
        report = evaluate_retrieval(cases, lambda q, t, f: ["b", "x", "a"], k=5)
        case = report["cases"][0]
        self.assertEqual(case["relevant_count"], 2)
        self.assertEqual(case["returned_count"], 3)
        self.assertEqual(case["recall_at_k"], 1.0)
        self.assertEqual(case["precision_at_k"], 2 / 3)
        self.assertEqual(case["reciprocal_rank"], 1.0)

    def test_metrics_are_reported_per_entity_type(self):
        cases = [
            role_case("r1", ["a"]),
            role_case("r2", ["b"]),
            course_case("c1", ["x"]),
        ]
        report = evaluate_retrieval(cases, lambda q, t, f: [], k=5)
        self.assertEqual(report["aggregate"]["role"]["case_count"], 2)
        self.assertEqual(report["aggregate"]["course"]["case_count"], 1)
        self.assertEqual(report["aggregate"]["overall"]["case_count"], 3)
        self.assertEqual(report["aggregate"]["role"]["mean_recall_at_k"], 0.0)

    def test_duplicate_retrieved_ids_are_deduplicated(self):
        cases = [role_case("r1", ["a"])]
        report = evaluate_retrieval(cases, lambda q, t, f: ["a", "a", "b"], k=5)
        self.assertEqual(report["cases"][0]["returned_count"], 2)

    def test_empty_relevant_set_yields_zero_metrics(self):
        cases = [{"id": "r", "entity_type": "role", "query": "q",
                  "filters": None, "relevant_ids": []}]
        report = evaluate_retrieval(cases, lambda q, t, f: ["a"], k=5)
        self.assertEqual(report["cases"][0]["recall_at_k"], 0.0)


def make_output(**overrides):
    output = {
        "candidate_roles": [
            {"role_id": "a", "role_title": "Software Engineer", "sector": "s",
             "track": "t", "relevance_rationale": "recorded tasks mention design",
             "source_records": [{"source_file": "x", "source_row": 1}]},
        ],
        "learning_priorities": [
            {"framework_skill_code": "ICT-DES-4005-1.1", "required_level": "4",
             "assessment": "unknown", "evidence": "self-reported design docs",
             "source_records": [{"source_file": "x", "source_row": 2}]},
        ],
        "recommended_courses": [
            {"course_id": "TGS-2019503161", "title": "Python Fundamentals",
             "provider_name": "P", "learning_priority": "Programming and Coding",
             "outcome_evidence": "teaches control flow and functions",
             "prerequisite_assessment": "unknown", "hours": 16, "commitment": "16h",
             "language": "English", "listed_subsidised_fee": 375,
             "source_records": [{"source_file": "x", "source_row": 3}]},
        ],
        "uncertainties": ["Missing skill-requirement coverage for target role"],
    }
    output.update(overrides)
    return output


class RecommendationCheckTests(unittest.TestCase):
    def scenario(self, **overrides):
        scenario = {
            "id": "s", "kind": "recommendation",
            "profile": {"constraints": None},
        }
        scenario.update(overrides)
        return scenario

    def check_names(self, checks):
        return {check["check"] for check in checks}

    def test_complete_output_passes_all_checks(self):
        checks = check_recommendation(self.scenario(), make_output())
        self.assertTrue(all(check["passed"] for check in checks), checks)

    def test_non_dict_output_fails_shape_only(self):
        checks = check_recommendation(self.scenario(), "not a dict")
        self.assertEqual(len(checks), 1)
        self.assertFalse(checks[0]["passed"])
        self.assertEqual(checks[0]["check"], "output_shape")

    def test_missing_top_level_keys_are_reported(self):
        checks = check_recommendation(self.scenario(), {"candidate_roles": []})
        failed = [c for c in checks if c["check"] == "output_shape"]
        self.assertTrue(failed)
        self.assertIn("learning_priorities", failed[0]["message"])

    def test_forbidden_claims_are_flagged(self):
        output = make_output(uncertainties=["This course guarantees readiness for the role"])
        checks = check_recommendation(self.scenario(), output)
        self.assertFalse(next(c for c in checks
                              if c["check"] == "no_forbidden_claim:readiness")["passed"])

    def test_items_without_source_records_fail_citation_checks(self):
        output = make_output()
        output["candidate_roles"][0]["source_records"] = []
        checks = check_recommendation(self.scenario(), output)
        failed = next(c for c in checks if c["check"] == "candidate_roles[0].citations")
        self.assertFalse(failed["passed"])

    def test_assessment_labels_are_restricted(self):
        output = make_output()
        output["learning_priorities"][0]["assessment"] = "excellent"
        checks = check_recommendation(self.scenario(), output)
        failed = next(c for c in checks
                      if c["check"] == "learning_priorities[0].assessment")
        self.assertFalse(failed["passed"])

    def test_course_fields_and_prerequisite_states_are_validated(self):
        output = make_output()
        del output["recommended_courses"][0]["outcome_evidence"]
        output["recommended_courses"][0]["prerequisite_assessment"] = "maybe"
        checks = check_recommendation(self.scenario(), output)
        self.assertFalse(next(c for c in checks
                              if c["check"] == "recommended_courses[0].fields")["passed"])
        self.assertFalse(next(c for c in checks if c["check"] ==
                              "recommended_courses[0].prerequisite_state")["passed"])

    def test_budget_constraint_is_enforced(self):
        scenario = self.scenario(profile={"constraints": {"budget_sgd": 400}})
        over_budget = make_output()
        over_budget["recommended_courses"][0]["listed_subsidised_fee"] = 500
        checks = check_recommendation(scenario, over_budget)
        failed = next(c for c in checks
                      if c["check"] == "recommended_courses[0].budget")
        self.assertFalse(failed["passed"])
        within_budget = make_output()
        self.assertTrue(next(c for c in check_recommendation(scenario, within_budget)
                             if c["check"] == "recommended_courses[0].budget")["passed"])

    def test_language_constraint_is_enforced(self):
        scenario = self.scenario(profile={"constraints": {"language": "Mandarin"}})
        checks = check_recommendation(scenario, make_output())
        failed = next(c for c in checks
                      if c["check"] == "recommended_courses[0].language")
        self.assertFalse(failed["passed"])

    def test_missing_requirements_must_be_reported_when_required(self):
        scenario = self.scenario(must_report_missing_requirements=True)
        output = make_output(uncertainties=["Nothing uncertain here"])
        checks = check_recommendation(scenario, output)
        failed = next(c for c in checks
                      if c["check"] == "missing_requirements_reported")
        self.assertFalse(failed["passed"])

    def test_multiple_mappings_must_be_reported_when_required(self):
        scenario = self.scenario(must_report_multiple_mappings=True)
        output = make_output(uncertainties=["Nothing uncertain here"])
        checks = check_recommendation(scenario, output)
        failed = next(c for c in checks
                      if c["check"] == "multiple_mappings_reported")
        self.assertFalse(failed["passed"])
        output = make_output(uncertainties=["Skill code has a one-to-many mapping"])
        passed = next(c for c in check_recommendation(scenario, output)
                      if c["check"] == "multiple_mappings_reported")
        self.assertTrue(passed["passed"])

    def test_expected_prerequisite_unknown_is_enforced(self):
        scenario = self.scenario(expected_prerequisite_unknown_for=["TGS-2019503161"])
        output = make_output()
        output["recommended_courses"][0]["prerequisite_assessment"] = "satisfied"
        checks = check_recommendation(scenario, output)
        failed = next(c for c in checks
                      if c["check"] == "prerequisite_unknown:TGS-2019503161")
        self.assertFalse(failed["passed"])


if __name__ == "__main__":
    unittest.main()
