"""Small workbook fixtures exercising ingestion behaviour, not live data counts."""
from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest

import duckdb
from openpyxl import Workbook, load_workbook

from ingest import REQUIRED, SOURCES, column_name, ingest


def make_inputs(folder: Path):
    """Create only the columns promised by each source contract."""
    data = {
        "roles": [dict(Sector="Finance", Track="Operations", **{"Job Role": "Analyst", "Job Role Description": "Analyse accounts"})],
        "role_tasks": [dict(Sector="Finance", Track="Operations", **{"Job Role": "Analyst", "Critical Work Function": "Report", "Key Tasks": "Review accounts"})],
        "role_skills": [dict(Sector="Finance", Track="Operations", **{"Job Role": "Analyst", "TSC_CCS Code": "F-3", "TSC_CCS Title": "Analysis", "TSC_CCS Type": "tsc", "Proficiency Level": "Intermediate"})],
        "framework_skills": [dict(**{"TSC Code": "F-3", "Sector": "Finance", "TSC_CCS Title": "Analysis", "TSC_CCS Type": "tsc"})],
        "retired_skills": [],
        "knowledge_abilities": [dict(**{"TSC_CCS Code": "F-3", "Proficiency Level": "Intermediate", "Proficiency Description": "Analyse records", "Knowledge / Ability Items": "Summarise findings", "Knowledge / Ability Classification": "ability"})],
        "unique_skills": [dict(skill_id="U1", skill_transaction_id="T1", skill_title="Analysis"),
                          dict(skill_id="U2", skill_transaction_id="T2", skill_title="Reporting")],
        "skill_mappings": [dict(skills_framework_skill_code="F-3", skills_framework_skill_pl="Intermediate", **{"Unique skill_updated_skill_title": title})
                           for title in ["Analysis", "Reporting", "Unrecognised skill"]],
        "courses": [dict(coursereferencenumber="C1", coursetitle="Analysis course", full_course_fee=100,
                         course_fee_after_subsidies=None, number_of_hours=8, about_this_course="Learn analysis"),
                    dict(coursereferencenumber="C1", coursetitle="Analysis course", full_course_fee=100,
                         course_fee_after_subsidies=None, number_of_hours=8, about_this_course="Learn analysis",
                         what_you_learn="Summarise_x000D_\nfindings", minimum_entry_requirement="None")],
    }
    for filename, sheets in SOURCES.items():
        workbook = Workbook()
        workbook.remove(workbook.active)
        for sheet_name, table in sheets.items():
            sheet = workbook.create_sheet(sheet_name)
            headers = REQUIRED[table]
            sheet.append(headers)
            for row in data[table]:
                sheet.append([row.get(h) for h in headers])
        workbook.save(folder / filename)
        workbook.close()


class IngestionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        make_inputs(self.folder)
        self.db_path = self.folder / "career.duckdb"

    def tearDown(self):
        self.temp.cleanup()

    def run_ingest(self, replace=False):
        with redirect_stdout(io.StringIO()):
            return ingest(self.folder, self.db_path, replace)

    def test_source_preservation_and_course_selection(self):
        self.run_ingest()
        with duckdb.connect(str(self.db_path), read_only=True) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM raw.courses").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT count(*) FROM core.courses").fetchone()[0], 1)
            row = db.execute("SELECT selected_source_row, learning_outcomes, listed_subsidised_fee FROM core.courses").fetchone()
            self.assertEqual(row, (3, "Summarise\nfindings", None))
            self.assertEqual(db.execute("SELECT what_you_learn FROM raw.courses WHERE source_row=3").fetchone()[0], "Summarise_x000D_\nfindings")
            self.assertEqual(db.execute("SELECT count(*) FROM core.source_records WHERE entity_type='course'").fetchone()[0], 2)

    def test_mapping_and_original_level_labels(self):
        self.run_ingest()
        with duckdb.connect(str(self.db_path), read_only=True) as db:
            mappings = db.execute("SELECT mapped_title, skill_id, mapping_status FROM core.skill_mappings ORDER BY mapping_id").fetchall()
            self.assertEqual(mappings, [("Analysis", "U1", "matched"), ("Reporting", "U2", "matched"), ("Unrecognised skill", None, "unresolved_title")])
            self.assertEqual(db.execute("SELECT required_level, required_level_numeric FROM core.role_skills").fetchone(), ("Intermediate", None))
            self.assertEqual(db.execute("SELECT count(*) FROM core.career_transitions").fetchone()[0], 0)

    def test_role_search_text_contains_tasks_and_requirements(self):
        self.run_ingest()
        with duckdb.connect(str(self.db_path), read_only=True) as db:
            text, content_hash = db.execute("""
                SELECT text, content_hash FROM core.search_documents
                WHERE entity_type = 'role'
            """).fetchone()
            self.assertIn("Role: Analyst", text)
            self.assertIn("Report: Review accounts", text)
            self.assertIn("Analysis | Required level: Intermediate | Code: F-3", text)
            self.assertEqual(len(content_hash), 64)

    def test_roles_without_requirements_are_preserved_and_reported(self):
        filename = next(iter(SOURCES))
        workbook = load_workbook(self.folder / filename)
        sheet = workbook["Job Role_Description"]
        row = {"Sector": "Finance", "Track": "Operations", "Job Role": "Trainee"}
        sheet.append([row.get(h) for h in REQUIRED["roles"]])
        workbook.save(self.folder / filename)
        workbook.close()
        report = self.run_ingest()
        self.assertEqual(report["quality_warnings"]["roles_without_skill_requirements"], 1)
        self.assertEqual(report["quality_warnings"]["roles_without_tasks"], 1)
        with duckdb.connect(str(self.db_path), read_only=True) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM core.search_documents WHERE entity_type='role'").fetchone()[0], 2)

    def test_existing_database_and_failed_rebuild_are_protected(self):
        self.run_ingest()
        original = self.db_path.read_bytes()
        with self.assertRaises(FileExistsError):
            self.run_ingest()
        # Break a role foreign-key relationship, forcing validation to fail.
        filename = next(iter(SOURCES))
        workbook = load_workbook(self.folder / filename)
        workbook["Job Role_TSC_CCS"]["C2"] = "Unknown role"
        workbook.save(self.folder / filename)
        workbook.close()
        with self.assertRaisesRegex(ValueError, "Integrity checks failed"):
            self.run_ingest(replace=True)
        self.assertEqual(self.db_path.read_bytes(), original)
        self.assertEqual(list(self.folder.glob(".ingest-*")), [])

    def test_successful_rebuild_keeps_stable_ids_and_counts(self):
        first = self.run_ingest()
        with duckdb.connect(str(self.db_path), read_only=True) as db:
            original_ids = db.execute("SELECT role_id FROM core.roles").fetchall()
        second = self.run_ingest(replace=True)
        self.assertEqual(first, second)
        with duckdb.connect(str(self.db_path), read_only=True) as db:
            self.assertEqual(db.execute("SELECT role_id FROM core.roles").fetchall(), original_ids)


if __name__ == "__main__":
    unittest.main()
