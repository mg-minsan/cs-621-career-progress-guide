"""Sample-profile discovery demonstration."""
import unittest

from lookup import DEFAULT_DB
from demo_profile import SAMPLE_PROFILES, discover, framework_roles, framework_skills


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

    def test_backend_profile_surfaces_software_engineer(self):
        result = discover(SAMPLE_PROFILES["backend"])
        titles = [candidate["title"] for candidate in result["role_candidates"]]
        # Framework vocabulary (Software Design, Applications Development, ...)
        # must surface Software Engineer even though the profile uses no
        # technology names.
        self.assertIn("Software Engineer", titles)
        self.assertTrue(result["course_candidates"])

    def test_framework_vocabulary_lookup(self):
        self.assertTrue(framework_skills("software design"))
        self.assertTrue(framework_roles("software engineer"))
        self.assertTrue(all("title" in skill for skill in framework_skills("data")))


if __name__ == "__main__":
    unittest.main()
