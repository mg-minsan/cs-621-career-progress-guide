"""Sample-profile discovery demonstration."""
import unittest

from lookup import DEFAULT_DB
from demo_profile import SAMPLE_PROFILES, discover


class SampleProfileTests(unittest.TestCase):
    def test_sample_profiles_are_well_formed(self):
        for name, profile in SAMPLE_PROFILES.items():
            for field in ("skills", "interests", "learning_goal"):
                self.assertIn(field, profile, name)
            self.assertTrue(profile["interests"], name)
            self.assertTrue(profile["learning_goal"].strip(), name)


@unittest.skipUnless(DEFAULT_DB.is_file(), "Run ingest.py --db data/career-ingested.duckdb for snapshot checks")
class SuppliedWorkbookSampleProfileTests(unittest.TestCase):
    def test_data_profile_surfaces_the_data_analyst_role(self):
        result = discover(SAMPLE_PROFILES["data"])
        titles = [candidate["title"] for candidate in result["role_candidates"]]
        self.assertIn("Data Analyst", titles)
        self.assertTrue(result["course_candidates"])

    def test_backend_profile_surfaces_roles_and_courses(self):
        result = discover(SAMPLE_PROFILES["backend"])
        self.assertTrue(result["role_candidates"])
        self.assertTrue(result["course_candidates"])
        self.assertTrue(all(candidate["skill_count"] >= 0
                            for candidate in result["role_candidates"]))


if __name__ == "__main__":
    unittest.main()
