"""Lookup contract tests against ingested workbook fixtures, not mocked SQL."""
from contextlib import redirect_stdout
from decimal import Decimal
import io
from pathlib import Path
import tempfile
import unittest

import duckdb
from openpyxl import load_workbook

from ingest import REQUIRED, SOURCES, ingest
from lookup import CareerLookup, DEFAULT_DB
from test_ingest import make_inputs


def append_rows(sheet, table, rows):
    for row in rows:
        sheet.append([row.get(header) for header in REQUIRED[table]])


def extend_inputs(folder):
    workbook = load_workbook(folder / next(iter(SOURCES)))
    identities = {
        "a": {"Sector": "Finance", "Track": "Operations", "Job Role": "Analyst"},
        "b": {"Sector": "Finance", "Track": "Risk", "Job Role": "Analyst"},
        "c": {"Sector": "Technology", "Track": "Operations", "Job Role": "Analyst"},
        "empty": {"Sector": "Finance", "Track": "Operations", "Job Role": "Trainee"},
    }
    append_rows(workbook["Job Role_Description"], "roles", [
        identities[name] for name in ("b", "c", "empty")])
    append_rows(workbook["Job Role_CWF_KT"], "role_tasks", [
        {**identities["a"], "Critical Work Function": "Report", "Key Tasks": "Review accounts"},
        {**identities["a"], "Critical Work Function": "Plan", "Key Tasks": "Plan audits"},
    ])
    requirements = [
        ("a", "F-3", "3", "Analysis"),
        ("a", "S-1", "Basic", "Communication"),
        ("a", "T-3", "3", "Technology"),
        ("a", "M-1", "Advanced", "Missing definition"),
        ("b", "F-3", "4", "Analysis"),
        ("b", "F-3", "Intermediate", "Analysis"),
        ("b", "S-1", "Basic", "Communication"),
        ("b", "T-4", "4", "Technology"),
        # A repeated source row must not duplicate a core requirement.
        ("a", "F-3", "Intermediate", "Analysis"),
    ]
    append_rows(workbook["Job Role_TSC_CCS"], "role_skills", [
        {**identities[role], "TSC_CCS Code": code, "Proficiency Level": level,
         "TSC_CCS Title": title, "TSC_CCS Type": "tsc"}
        for role, code, level, title in requirements])
    append_rows(workbook["TSC_CCS_Key"], "framework_skills", [
        {"TSC Code": code, "Sector": "Finance", "TSC_CCS Title": title,
         "TSC_CCS Description": "Recorded definition", "TSC_CCS Type": "tsc"}
        for code, title in [("S-1", "Communication"), ("T-3", "Technology"),
                            ("T-4", "Technology")]])
    append_rows(workbook["TSC_CCS_K&A"], "knowledge_abilities", [
        {"TSC_CCS Code": code, "Proficiency Level": level,
         "Proficiency Description": "Recorded expectations",
         "Knowledge / Ability Items": text, "Knowledge / Ability Classification": "knowledge"}
        for code, level, text in [("F-3", "Intermediate", "Read accounts"),
                                  ("F-3", "3", "Level three expectations"),
                                  ("F-3", "4", "Level four expectations"),
                                  ("S-1", "Basic", "Listen"),
                                  ("K-ONLY", "Basic", "K&A without active key")]])
    workbook.save(folder / next(iter(SOURCES)))
    workbook.close()

    filename = "MySkillsFutureCourseDirectory.xlsx"
    workbook = load_workbook(folder / filename)
    append_rows(workbook["Sheet2"], "courses", [
        {"coursereferencenumber": "C2", "coursetitle": "Precision course",
         "full_course_fee": "123.456789", "course_fee_after_subsidies": "0",
         "number_of_hours": "0"}])
    workbook.save(folder / filename)
    workbook.close()


class LookupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.folder = Path(cls.temp.name)
        make_inputs(cls.folder)
        extend_inputs(cls.folder)
        cls.db_path = cls.folder / "career.duckdb"
        with redirect_stdout(io.StringIO()):
            ingest(cls.folder, cls.db_path)
        with CareerLookup(cls.db_path) as lookup:
            cls.a = lookup.resolve_role("Analyst", "Finance", "Operations")["data"]["role_id"]
            cls.b = lookup.resolve_role("Analyst", "Finance", "Risk")["data"]["role_id"]
            cls.empty = lookup.resolve_role("Trainee")["data"]["role_id"]

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.lookup = CareerLookup(self.db_path)
        self.addCleanup(self.lookup.close)

    def test_title_search_and_ambiguity(self):
        candidates = self.lookup.search_role_names("  aNaLySt  ")["data"]
        self.assertEqual(len(candidates), 3)
        ambiguous = self.lookup.resolve_role(" ANALYST ")
        self.assertEqual(ambiguous["status"], "ambiguous")
        self.assertEqual(ambiguous["data"], candidates)
        self.assertEqual(len(ambiguous["source_records"]), 3)
        self.assertTrue(all(candidate["source_records"] for candidate in candidates))
        self.assertEqual(self.lookup.resolve_role("Analyst", sector="Finance")["status"], "ambiguous")
        self.assertEqual(self.lookup.resolve_role("Analyst", track="Operations")["status"], "ambiguous")
        resolved = self.lookup.resolve_role(" analyst ", " finance ", " operations ")
        self.assertEqual(resolved["status"], "ok")
        self.assertEqual(resolved["data"]["role_id"], self.a)
        self.assertEqual(self.lookup.resolve_role("Unknown")["status"], "not_found")
        self.assertEqual(len(self.lookup.search_role_names("")["data"]), 4)
        self.assertEqual(len(self.lookup.search_role_names("aly", track="Risk")["data"]), 1)

    def test_inputs_are_parameterised_and_search_wildcards_are_literal(self):
        for query in ("' OR true --", "%", "_", "'; DROP TABLE core.roles; --"):
            with self.subTest(query=query):
                self.assertEqual(self.lookup.search_role_names(query)["data"], [])
                self.assertEqual(self.lookup.resolve_role(query)["status"], "not_found")
                self.assertEqual(self.lookup.get_role(query)["status"], "not_found")
                self.assertEqual(self.lookup.get_skill(query)["status"], "not_found")
                self.assertEqual(self.lookup.get_course(query)["status"], "not_found")
        self.assertEqual(self.lookup.search_role_names("Analyst", sector="' OR true --")["data"], [])
        self.assertEqual(self.lookup.get_source_records("' OR true --", self.a)["data"], [])
        self.assertEqual(len(self.lookup.search_role_names("")["data"]), 4)

    def test_complete_role_lists_and_per_item_provenance(self):
        result = self.lookup.get_role(self.a)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["data"]["tasks"]), 2)
        self.assertEqual(len(result["data"]["skills"]), 5)
        self.assertEqual(result["data"]["tasks"], self.lookup.get_role_tasks(self.a)["data"])
        self.assertEqual(result["data"]["skills"], self.lookup.get_role_skills(self.a)["data"])
        review = next(task for task in result["data"]["tasks"] if task["task_text"] == "Review accounts")
        self.assertEqual(len(review["source_records"]), 2)
        intermediate = next(skill for skill in result["data"]["skills"]
                            if skill["framework_skill_code"] == "F-3"
                            and skill["required_level"] == "Intermediate")
        self.assertIsNone(intermediate["required_level_numeric"])
        self.assertEqual(len(intermediate["source_records"]), 2)
        definition, = intermediate["definition_source_records"]
        self.assertEqual(definition["source_table"], "framework_skills")
        self.assertEqual(len(intermediate["proficiency_source_records"]), 2)
        for skill in result["data"]["skills"]:
            self.assertTrue(skill["source_records"])
            for source in skill["source_records"]:
                self.assertEqual(source["source_table"], "role_skills")
                self.assertEqual(source["source_sheet"], "Job Role_TSC_CCS")
                self.assertEqual(len(source["file_sha256"]), 64)
                self.assertGreaterEqual(source["source_row"], 2)
        self.assertEqual(result["source_records"], self.lookup.get_source_records("role", self.a)["data"])

    def test_missing_collections_are_distinct_from_unknown_roles(self):
        for method, field in ((self.lookup.get_role_tasks, "tasks"),
                              (self.lookup.get_role_skills, "skill_requirements")):
            existing = method(self.empty)
            self.assertEqual(existing["status"], "ok")
            self.assertEqual(existing["data"], [])
            self.assertIn(field, existing["missing_data"])
            unknown = method("unknown")
            self.assertEqual(unknown["status"], "not_found")
            self.assertIsNone(unknown["data"])
        role = self.lookup.get_role(self.empty)
        self.assertEqual(set(role["missing_data"]), {
            "description", "performance_expectation", "tasks", "skill_requirements"})
        self.assertTrue(role["source_records"])
        self.assertEqual(self.lookup.get_role("unknown")["status"], "not_found")

    def test_skill_levels_knowledge_abilities_and_source_keys(self):
        all_levels = self.lookup.get_skill("F-3")
        self.assertEqual([p["level"] for p in all_levels["data"]["proficiencies"]],
                         ["3", "4", "Intermediate"])
        result = self.lookup.get_skill("F-3", "Intermediate")
        proficiency, = result["data"]["proficiencies"]
        self.assertIsNone(proficiency["level_numeric"])
        self.assertEqual(len(proficiency["knowledge_abilities"]), 2)
        self.assertEqual(len(proficiency["source_records"]), 2)
        for source in proficiency["source_records"]:
            self.assertEqual(source["entity_id"], proficiency["proficiency_id"])
            self.assertEqual(source["entity_type"], "skill_proficiency")
        absent = self.lookup.get_skill("F-3", "intermediate")
        self.assertEqual(absent["status"], "ok")
        self.assertEqual(absent["data"]["proficiencies"], [])
        self.assertIn("requested_proficiency", absent["missing_data"])
        self.assertEqual(self.lookup.get_skill("unknown")["status"], "not_found")
        fallback = self.lookup.get_skill("M-1")
        self.assertEqual(fallback["data"]["definition_source"], "role_requirement_fallback")
        self.assertIn("active_definition", fallback["missing_data"])
        self.assertIn("proficiency_details", fallback["missing_data"])
        self.assertTrue(fallback["source_records"])
        ka_only = self.lookup.get_skill("K-ONLY", "Basic")
        self.assertEqual(ka_only["status"], "ok")
        self.assertIn("active_definition", ka_only["missing_data"])
        self.assertTrue(ka_only["data"]["proficiencies"])
        self.assertTrue(ka_only["source_records"])
        ka_absent = self.lookup.get_skill("K-ONLY", "Advanced")
        self.assertIn("requested_proficiency", ka_absent["missing_data"])
        self.assertEqual(ka_absent["data"]["available_levels"], ["Basic"])
        self.assertTrue(ka_absent["source_records"])
        missing_requirement = next(s for s in self.lookup.get_role_skills(self.a)["data"]
                                   if s["framework_skill_code"] == "M-1")
        self.assertIn("active_definition", missing_requirement["missing_data"])
        self.assertIn("proficiency_details", missing_requirement["missing_data"])

    def test_course_selected_source_and_exact_fees(self):
        result = self.lookup.get_course("C1")
        self.assertEqual(result["data"]["selected_source_row"], 3)
        self.assertEqual(len(result["source_records"]), 2)
        selected, = result["data"]["selected_source_records"]
        self.assertEqual(selected["source_row"], 3)
        self.assertIn("listed_subsidised_fee", result["missing_data"])
        self.assertNotIn("entry_requirements", result["missing_data"])
        self.assertIsNone(result["data"]["listed_subsidised_fee"])
        precision = self.lookup.get_course("C2")
        self.assertEqual(precision["data"]["full_fee"], Decimal("123.456789"))
        self.assertEqual(precision["data"]["listed_subsidised_fee"], Decimal("0.000000"))
        self.assertNotIn("listed_subsidised_fee", precision["missing_data"])
        self.assertNotIn("hours", precision["missing_data"])
        self.assertIn("entry_requirements", precision["missing_data"])
        self.assertIn("learning_outcomes", precision["missing_data"])
        self.assertEqual(self.lookup.get_course("unknown")["status"], "not_found")

    def test_comparison_does_not_infer_cross_code_or_level_equivalence(self):
        comparison = self.lookup.compare_roles(self.a, self.b)
        self.assertEqual(comparison["status"], "ok")
        data = comparison["data"]
        self.assertEqual({(p["a"]["framework_skill_code"], p["a"]["required_level"])
                          for p in data["shared_requirements"]},
                         {("F-3", "Intermediate"), ("S-1", "Basic")})
        different, = data["different_levels"]
        self.assertEqual(different["framework_skill_code"], "F-3")
        self.assertEqual(different["comparison_status"], "not_assessed")
        self.assertEqual({s["required_level"] for s in different["a"]}, {"3", "Intermediate"})
        self.assertEqual({s["framework_skill_code"] for s in data["only_a"]}, {"T-3", "M-1"})
        self.assertEqual({s["framework_skill_code"] for s in data["only_b"]}, {"T-4"})
        self.assertTrue(comparison["source_records"])
        with_empty = self.lookup.compare_roles(self.a, self.empty)
        self.assertIn("role_b.skill_requirements", with_empty["missing_data"])
        identical = self.lookup.compare_roles(self.a, self.a)["data"]
        self.assertEqual(len(identical["shared_requirements"]), 5)
        self.assertEqual(identical["different_levels"], [])
        unknown = self.lookup.compare_roles("unknown", self.b)
        self.assertEqual(unknown["status"], "not_found")
        self.assertEqual(unknown["missing_data"], ["role_a"])

    def test_read_only_context_and_missing_database_protection(self):
        original = self.db_path.read_bytes()
        with CareerLookup(self.db_path) as reader:
            with self.assertRaises(duckdb.Error):
                reader._con.execute("DELETE FROM core.roles")
            reader.get_role(self.a)
        with self.assertRaises(duckdb.Error):
            reader.get_role(self.a)
        self.assertEqual(original, self.db_path.read_bytes())
        missing = self.folder / "missing.duckdb"
        with self.assertRaisesRegex(FileNotFoundError, "Run ingest.py first"):
            CareerLookup(missing)
        self.assertFalse(missing.exists())
        self.assertEqual(DEFAULT_DB, Path(__file__).resolve().parents[1] / "data/career-ingested.duckdb")


@unittest.skipUnless(DEFAULT_DB.is_file(), "Run ingest.py --db data/career-ingested.duckdb for snapshot checks")
class SuppliedWorkbookLookupTests(unittest.TestCase):
    def test_software_engineer_has_all_27_recorded_requirements(self):
        with CareerLookup() as lookup:
            result = lookup.resolve_role("Software Engineer", "Infocomm Technology",
                                         "Software and Applications")
            self.assertEqual(result["status"], "ok")
            role = result["data"]
            requirements = lookup.get_role_skills(role["role_id"])["data"]
            self.assertEqual(len(requirements), 27)
            self.assertEqual(requirements, role["skills"])
            self.assertTrue(all(skill["source_records"] for skill in requirements))
            self.assertTrue(all(task["source_records"] for task in role["tasks"]))
            for skill in requirements:
                self.assertTrue(skill["definition_source_records"])
                self.assertTrue(skill["proficiency_source_records"])


if __name__ == "__main__":
    unittest.main()
