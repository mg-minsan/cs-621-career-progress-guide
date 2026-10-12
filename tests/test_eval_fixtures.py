"""Evaluation fixture structure, resolution and lookup self-checks."""
from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest

from ingest import ingest
from lookup import CareerLookup, DEFAULT_DB
from eval_fixtures import (
    FIXTURES, SCHEMA_VERSION, course_ref, resolve_fixtures, resolve_reference,
    role_ref, run_lookup_cases, validate_fixtures,
)
from test_ingest import make_inputs
from test_lookup import extend_inputs


class FixtureStructureTests(unittest.TestCase):
    def test_schema_version_matches(self):
        self.assertEqual(FIXTURES["schema_version"], SCHEMA_VERSION)

    def test_reviewed_fixture_set_is_valid(self):
        self.assertEqual(validate_fixtures(FIXTURES), [])

    def test_each_retrieval_case_has_review_notes_and_relevant(self):
        for case in FIXTURES["retrieval_cases"]:
            self.assertTrue(case["relevant"])
            self.assertTrue(case["notes"].strip())

    def test_invalid_fixtures_are_reported(self):
        problems = validate_fixtures({
            "schema_version": SCHEMA_VERSION,
            "lookup_cases": [{"id": "x"}, "not-a-dict"],
            "retrieval_cases": [
                {"id": "bad-type", "query": "q", "entity_type": "unknown",
                 "relevant": [{"type": "course", "course_id": "C"}]},
                {"id": "dup", "query": "q", "entity_type": "role", "relevant": []},
                {"id": "dup", "query": "q", "entity_type": "role", "relevant": []},
                {"id": "bad-ref", "query": "q", "entity_type": "role",
                 "relevant": [{"type": "role", "sector": "S"}]},
            ],
            "recommendation_scenarios": ["not-a-dict"],
        })
        self.assertIn("'x' is missing 'title'", problems)
        self.assertIn("lookup_cases contains a non-dict entry", problems)
        self.assertIn("recommendation_scenarios contains a non-dict entry", problems)
        self.assertIn("duplicate fixture id 'dup'", problems)
        self.assertTrue(any("invalid entity_type" in p for p in problems))
        self.assertTrue(any("'relevant' must be non-empty" in p for p in problems))
        self.assertTrue(any("missing 'track'" in p for p in problems))
        self.assertTrue(any("missing 'title'" in p for p in problems))


class ResolverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.folder = Path(cls.temp.name)
        make_inputs(cls.folder)
        extend_inputs(cls.folder)
        cls.db_path = cls.folder / "career.duckdb"
        with redirect_stdout(io.StringIO()):
            ingest(cls.folder, cls.db_path)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_role_and_course_references_resolve_to_canonical_ids(self):
        with CareerLookup(self.db_path) as lookup:
            analyst = lookup.resolve_role("Analyst", "Finance", "Operations")["data"]
            self.assertEqual(
                resolve_reference(lookup, role_ref("Finance", "Operations", "Analyst")),
                analyst["role_id"])
            self.assertEqual(
                resolve_reference(lookup, course_ref("C1")), "C1")

    def test_unresolvable_references_raise(self):
        with CareerLookup(self.db_path) as lookup:
            with self.assertRaisesRegex(ValueError, "does not resolve"):
                resolve_reference(lookup, role_ref("Finance", "Operations", "Nobody"))
            with self.assertRaisesRegex(ValueError, "does not resolve"):
                resolve_reference(lookup, course_ref("MISSING"))

    def test_resolve_fixtures_adds_canonical_ids(self):
        fixtures = {
            "schema_version": SCHEMA_VERSION,
            "lookup_cases": [
                {"id": "exact", "title": "Analyst", "sector": "Finance",
                 "track": "Operations", "expected_status": "ok",
                 "expected_role": role_ref("Finance", "Operations", "Analyst"),
                 "expected_min_skill_count": 5},
                {"id": "ambiguous", "title": "Analyst", "sector": None,
                 "track": None, "expected_status": "ambiguous",
                 "expected_candidates": [
                     role_ref("Finance", "Operations", "Analyst"),
                     role_ref("Finance", "Risk", "Analyst"),
                     role_ref("Technology", "Operations", "Analyst")]},
                {"id": "missing", "title": "Nobody", "sector": None,
                 "track": None, "expected_status": "not_found"},
            ],
            "retrieval_cases": [
                {"id": "roles", "entity_type": "role", "query": "analyse accounts",
                 "filters": None,
                 "relevant": [role_ref("Finance", "Operations", "Analyst")]},
                {"id": "courses", "entity_type": "course", "query": "precision",
                 "filters": None, "relevant": [course_ref("C1")]},
            ],
            "recommendation_scenarios": [],
        }
        resolved = resolve_fixtures(fixtures, self.db_path)
        with CareerLookup(self.db_path) as lookup:
            analyst_id = resolve_reference(
                lookup, role_ref("Finance", "Operations", "Analyst"))
        self.assertEqual(resolved["lookup_cases"][0]["expected_role_id"], analyst_id)
        self.assertEqual(len(resolved["lookup_cases"][1]["expected_candidate_ids"]), 3)
        self.assertEqual(resolved["retrieval_cases"][0]["relevant_ids"], [analyst_id])
        self.assertEqual(resolved["retrieval_cases"][1]["relevant_ids"], ["C1"])

    def test_run_lookup_cases_verify_expectations_against_database(self):
        fixtures = {
            "schema_version": SCHEMA_VERSION,
            "lookup_cases": [
                {"id": "exact", "title": "Analyst", "sector": "Finance",
                 "track": "Operations", "expected_status": "ok",
                 "expected_role": role_ref("Finance", "Operations", "Analyst"),
                 "expected_min_skill_count": 5},
                {"id": "ambiguous", "title": "Analyst", "sector": None,
                 "track": None, "expected_status": "ambiguous",
                 "expected_candidates": [
                     role_ref("Finance", "Operations", "Analyst"),
                     role_ref("Finance", "Risk", "Analyst"),
                     role_ref("Technology", "Operations", "Analyst")]},
            ],
        }
        resolved = resolve_fixtures(fixtures, self.db_path)
        results = run_lookup_cases(resolved, self.db_path)
        self.assertTrue(all(result["passed"] for result in results), results)
        # A stale expectation is detected.
        resolved["lookup_cases"][0]["expected_min_skill_count"] = 99
        stale = run_lookup_cases(resolved, self.db_path)
        self.assertFalse(stale[0]["passed"])


@unittest.skipUnless(DEFAULT_DB.is_file(), "Run ingest.py --db data/career-ingested.duckdb for snapshot checks")
class SuppliedWorkbookFixtureTests(unittest.TestCase):
    def test_reviewed_fixtures_resolve_and_lookup_cases_pass(self):
        resolved = resolve_fixtures(FIXTURES, DEFAULT_DB)
        for case in resolved["retrieval_cases"]:
            self.assertTrue(case["relevant_ids"])
            self.assertEqual(len(case["relevant_ids"]), len(set(case["relevant_ids"])),
                             f"duplicate relevant IDs in {case['id']}")
        results = run_lookup_cases(resolved, DEFAULT_DB)
        self.assertTrue(all(result["passed"] for result in results), results)


if __name__ == "__main__":
    unittest.main()
