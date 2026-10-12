"""End-to-end guide flow tests."""
import unittest

from lookup import DEFAULT_DB
from demo_profile import SAMPLE_PROFILES
from guide import run


@unittest.skipUnless(DEFAULT_DB.is_file(), "Run ingest.py --db data/career-ingested.duckdb for snapshot checks")
class SuppliedWorkbookGuideTests(unittest.TestCase):
    def test_data_profile_flow_reaches_a_focus_role_and_courses(self):
        result = run(SAMPLE_PROFILES["data"])
        self.assertEqual(result["focus_role"]["title"], "Data Analyst")
        self.assertTrue(result["requirements"])
        self.assertTrue(result["courses"])
        self.assertTrue(result["role_sources"])
        self.assertTrue(all(course["sources"] for course in result["courses"]))

    def test_target_role_returns_all_recorded_requirements(self):
        result = run(SAMPLE_PROFILES["backend"], role_title="Software Engineer")
        self.assertEqual(result["focus_role"]["title"], "Software Engineer")
        self.assertEqual(len(result["requirements"]), 27)
        mentioned = [r for r in result["requirements"] if r["mentioned_in_profile"]]
        self.assertTrue(mentioned)
        self.assertLess(len(mentioned), len(result["requirements"]))

    def test_ambiguous_role_title_is_reported_not_picked(self):
        result = run(SAMPLE_PROFILES["backend"], role_title="Marketing Manager")
        self.assertEqual(result["error"], "ambiguous")
        self.assertGreater(len(result["candidates"]), 1)

    def test_unknown_role_title_is_reported(self):
        result = run(SAMPLE_PROFILES["backend"], role_title="No Such Role")
        self.assertEqual(result["error"], "not_found")


if __name__ == "__main__":
    unittest.main()
