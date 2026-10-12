"""Role export tests using real ingested workbook fixtures and temporary outputs."""
from contextlib import redirect_stdout
from datetime import date, datetime
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import duckdb
from openpyxl import load_workbook

from export_roles import DEFAULT_OUTPUT, _json_bytes, export_roles
from ingest import REQUIRED, SOURCES, ingest
from lookup import CareerLookup, DEFAULT_DB
from test_ingest import make_inputs
from test_lookup import append_rows, extend_inputs


class RoleExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inputs = tempfile.TemporaryDirectory()
        folder = Path(cls.inputs.name)
        make_inputs(folder)
        extend_inputs(folder)
        workbook = load_workbook(folder / next(iter(SOURCES)))
        cls.literal_description = "Literal <script>alert(1)</script>\n# Not a heading\n[click](javascript:alert(1))"
        workbook["Job Role_Description"]["D2"] = cls.literal_description
        cls.hostile_title = "../../CON / λ🔥 [role](https://example.invalid)\n# Injected <img src=x onerror=alert(1)>"
        append_rows(workbook["Job Role_Description"], "roles", [
            {"Sector": "Finance", "Track": "Operations", "Job Role": cls.hostile_title}])
        headers = REQUIRED["framework_skills"]
        workbook["TSC_CCS_Key"].cell(2, headers.index("Latest Update Date") + 1, "2024-03-01")
        workbook.save(folder / next(iter(SOURCES)))
        workbook.close()
        cls.db_path = folder / "career.duckdb"
        with redirect_stdout(io.StringIO()):
            ingest(folder, cls.db_path)
        with CareerLookup(cls.db_path) as lookup:
            cls.role_id = lookup.resolve_role("Analyst", "Finance", "Operations")["data"]["role_id"]
            cls.empty_id = lookup.resolve_role("Trainee")["data"]["role_id"]

    @classmethod
    def tearDownClass(cls):
        cls.inputs.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.output = self.folder / "profiles"

    def run_export(self, output=None, db=None):
        with redirect_stdout(io.StringIO()):
            return export_roles(db or self.db_path, output or self.output)

    def test_all_roles_complete_collections_and_nested_skill_evidence(self):
        manifest = self.run_export()
        self.assertEqual(manifest["role_count"], 5)
        self.assertEqual(len(list((self.output / "roles").glob("*.json"))), 5)
        self.assertEqual(len(list((self.output / "roles").glob("*.md"))), 5)
        self.assertEqual(json.loads((self.output / "manifest.json").read_text()), manifest)
        self.assertEqual(manifest["database_sha256"], hashlib.sha256(self.db_path.read_bytes()).hexdigest())
        with CareerLookup(self.db_path) as lookup:
            for entry in manifest["roles"]:
                profile = json.loads((self.output / entry["json_path"]).read_text())
                self.assertEqual(profile["schema_version"], 1)
                expected = lookup.get_role(entry["role_id"])
                # Only the enrichment is new; all original lookup fields survive.
                for requirement in profile["data"]["skills"]:
                    detail = requirement.pop("skill_details")
                    native = lookup.get_skill(requirement["framework_skill_code"],
                                              requirement["required_level"])
                    self.assertEqual(detail, json.loads(_json_bytes(native)))
                profile.pop("schema_version")
                self.assertEqual(profile, json.loads(_json_bytes(expected)))
                self.assertEqual(entry["task_count"], len(expected["data"]["tasks"]))
                self.assertEqual(entry["skill_requirement_count"], len(expected["data"]["skills"]))
        entry = next(e for e in manifest["roles"] if e["role_id"] == self.role_id)
        profile = json.loads((self.output / entry["json_path"]).read_text())
        self.assertEqual(len(profile["data"]["tasks"]), 2)
        self.assertEqual(len(profile["data"]["skills"]), 5)
        requirement = next(s for s in profile["data"]["skills"]
                           if s["framework_skill_code"] == "F-3" and s["required_level"] == "Intermediate")
        self.assertIsNone(requirement["required_level_numeric"])
        detail = requirement["skill_details"]
        self.assertEqual(detail["data"]["updated_date"], "2024-03-01")
        self.assertEqual(len(detail["data"]["proficiencies"][0]["knowledge_abilities"]), 2)
        self.assertEqual(len(requirement["source_records"]), 2)
        for source in profile["source_records"]:
            self.assertEqual(entry["source_hashes"][source["source_file"]], source["file_sha256"])

    def test_missing_data_is_explicit_in_json_markdown_and_manifest(self):
        manifest = self.run_export()
        entry = next(e for e in manifest["roles"] if e["role_id"] == self.empty_id)
        profile = json.loads((self.output / entry["json_path"]).read_text())
        self.assertEqual(profile["status"], "ok")
        self.assertEqual(profile["data"]["skills"], [])
        self.assertEqual(profile["data"]["tasks"], [])
        self.assertIn("skill_requirements", profile["missing_data"])
        self.assertIn("tasks", entry["missing_data"])
        self.assertTrue(profile["source_records"])
        markdown = (self.output / entry["markdown_path"]).read_text()
        self.assertIn("No skill requirement records are available. Coverage is unknown.", markdown)
        self.assertIn("No task records are available. Coverage is unknown.", markdown)
        self.assertIn("Not recorded", markdown)
        other = json.loads((self.output / f"roles/{self.role_id}.json").read_text())
        missing = next(s for s in other["data"]["skills"] if s["framework_skill_code"] == "M-1")
        self.assertIn("active_definition", missing["missing_data"])
        self.assertIn("requested_proficiency", missing["skill_details"]["missing_data"])
        self.assertEqual(missing["skill_details"]["data"]["proficiencies"], [])

    def test_filenames_are_safe_unique_and_titles_remain_source_data(self):
        manifest = self.run_export()
        self.assertEqual(len([e for e in manifest["roles"] if e["role_title"] == "Analyst"]), 3)
        paths = [e[key] for e in manifest["roles"] for key in ("json_path", "markdown_path")]
        self.assertEqual(len(paths), len(set(paths)))
        for path in paths:
            self.assertRegex(path, r"^roles/[0-9a-f]{64}\.(json|md)$")
            self.assertTrue((self.output / path).is_file())
            self.assertTrue((self.output / path).resolve().is_relative_to(self.output.resolve()))
        entry = next(e for e in manifest["roles"] if e["role_title"] == self.hostile_title)
        profile = json.loads((self.output / entry["json_path"]).read_text())
        self.assertEqual(profile["data"]["role_title"], self.hostile_title)
        markdown = (self.output / entry["markdown_path"]).read_text()
        self.assertNotIn("<img", markdown)
        self.assertNotIn("\n# Injected", markdown)
        normal = json.loads((self.output / f"roles/{self.role_id}.json").read_text())
        self.assertEqual(normal["data"]["description"], self.literal_description)
        markdown = (self.output / f"roles/{self.role_id}.md").read_text()
        self.assertIn("&lt;script&gt;", markdown)
        self.assertNotIn("<script>", markdown)
        self.assertIn("> \\# Not a heading", markdown)
        self.assertIn(r"\[click\]\(javascript:alert\(1\)\)", markdown)

    def test_markdown_lists_every_requirement_and_has_resolvable_citations(self):
        self.run_export()
        markdown = (self.output / f"roles/{self.role_id}.md").read_text()
        self.assertEqual(len(re.findall(r"^### Task \d+$", markdown, re.MULTILINE)), 2)
        self.assertEqual(len(re.findall(r"^### Requirement \d+:", markdown, re.MULTILINE)), 5)
        self.assertIn("Summarise findings", markdown)
        self.assertIn("Read accounts", markdown)
        self.assertIn("Intermediate", markdown)
        references = set(re.findall(r"\[\^(s\d+)\](?!:)", markdown))
        definitions = re.findall(r"^\[\^(s\d+)\]:", markdown, re.MULTILINE)
        self.assertTrue(references)
        self.assertTrue(references.issubset(set(definitions)))
        self.assertEqual(len(definitions), len(set(definitions)))
        self.assertIn("row: 2; SHA-256:", markdown)
        self.assertIn("different framework codes are not assumed", markdown)

    def test_output_hashes_and_repeatable_exports_without_database_writes(self):
        original = self.db_path.read_bytes()
        first = self.run_export()
        other = self.folder / "repeat"
        second = self.run_export(other)
        self.assertEqual(first, second)
        self.assertEqual(original, self.db_path.read_bytes())
        for entry in first["roles"]:
            for path_key, hash_key in (("json_path", "json_sha256"),
                                       ("markdown_path", "markdown_sha256")):
                content = (self.output / entry[path_key]).read_bytes()
                self.assertEqual(content, (other / entry[path_key]).read_bytes())
                self.assertEqual(hashlib.sha256(content).hexdigest(), entry[hash_key])
        self.assertEqual((self.output / "manifest.json").read_bytes(),
                         (other / "manifest.json").read_bytes())
        self.assertEqual(list(self.folder.glob(".role-export-*")), [])

    def test_existing_outputs_and_symlinks_are_protected(self):
        self.run_export()
        original = (self.output / "manifest.json").read_bytes()
        with self.assertRaises(FileExistsError):
            self.run_export()
        self.assertEqual(original, (self.output / "manifest.json").read_bytes())
        for name in ("empty", "file", "dangling"):
            path = self.folder / name
            if name == "empty":
                path.mkdir()
            elif name == "file":
                path.write_text("existing user data")
            else:
                path.symlink_to(self.folder / "does-not-exist")
            with self.subTest(name=name), self.assertRaises(FileExistsError):
                self.run_export(path)
        self.assertEqual((self.folder / "file").read_text(), "existing user data")
        self.assertTrue((self.folder / "dangling").is_symlink())

    def test_missing_database_and_failed_export_leave_no_partial_output(self):
        missing = self.folder / "missing.duckdb"
        with self.assertRaises(FileNotFoundError):
            self.run_export(db=missing)
        self.assertFalse(missing.exists())
        self.assertFalse(self.output.exists())
        # Let one role finish, then fail while rendering the next one.
        from export_roles import render_role_markdown
        calls = 0

        def fail_second(profile):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("simulated write failure")
            return render_role_markdown(profile)

        with patch("export_roles.render_role_markdown", side_effect=fail_second):
            with self.assertRaisesRegex(OSError, "simulated write failure"):
                self.run_export()
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.folder.glob(".role-export-*")), [])
        self.assertEqual(self.run_export()["role_count"], 5)

    def test_database_changes_and_invalid_ids_fail_before_publication(self):
        with patch("export_roles._file_hash", side_effect=["initial", "changed"]):
            with self.assertRaisesRegex(ValueError, "Database changed"):
                self.run_export()
        self.assertFalse(self.output.exists())
        invalid_db = self.folder / "invalid.duckdb"
        shutil.copyfile(self.db_path, invalid_db)
        with duckdb.connect(str(invalid_db)) as db:
            db.execute("UPDATE core.roles SET role_id = '../escape' WHERE role_id = ?", [self.empty_id])
        with self.assertRaisesRegex(ValueError, "Invalid canonical role ID"):
            self.run_export(db=invalid_db)
        self.assertFalse(self.output.exists())
        self.assertFalse((self.folder / "escape.json").exists())
        self.assertEqual(list(self.folder.glob(".role-export-*")), [])

    def test_missing_or_conflicting_source_hashes_fail_without_publication(self):
        for kind in ("missing", "conflicting"):
            invalid_db = self.folder / f"{kind}.duckdb"
            shutil.copyfile(self.db_path, invalid_db)
            with duckdb.connect(str(invalid_db)) as db:
                if kind == "missing":
                    db.execute("UPDATE audit.sources SET file_sha256 = NULL")
                else:
                    db.execute("UPDATE audit.sources SET file_sha256 = ? WHERE raw_table = 'role_tasks'",
                               ["f" * 64])
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "source hash"):
                self.run_export(db=invalid_db)
            self.assertFalse(self.output.exists())
            self.assertEqual(list(self.folder.glob(".role-export-*")), [])

    def test_output_created_during_export_is_not_overwritten(self):
        from export_roles import render_role_markdown

        def create_destination(profile):
            if not self.output.exists():
                self.output.mkdir()
                (self.output / "user-data.txt").write_text("keep me")
            return render_role_markdown(profile)

        with patch("export_roles.render_role_markdown", side_effect=create_destination):
            with self.assertRaisesRegex(FileExistsError, "Output appeared"):
                self.run_export()
        self.assertEqual((self.output / "user-data.txt").read_text(), "keep me")
        self.assertFalse((self.output / "manifest.json").exists())
        self.assertEqual(list(self.folder.glob(".role-export-*")), [])

    def test_json_scalar_serialisation_is_lossless_and_explicit(self):
        value = {"fee": Decimal("123.456789"), "date": date(2024, 3, 1),
                 "timestamp": datetime(2024, 3, 1, 12, 30), "missing": None}
        self.assertEqual(json.loads(_json_bytes(value)), {
            "fee": "123.456789", "date": "2024-03-01",
            "timestamp": "2024-03-01T12:30:00", "missing": None})
        with self.assertRaises(TypeError):
            _json_bytes({"unsupported": object()})
        with self.assertRaises(ValueError):
            _json_bytes({"invalid": float("nan")})

    def test_cli_exports_and_reports_errors_without_tracebacks(self):
        script = Path(__file__).resolve().parents[1] / "export_roles.py"
        args = [sys.executable, str(script), "--db", str(self.db_path),
                "--output-dir", str(self.output)]
        result = subprocess.run(args, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Exported 5 roles", result.stdout)
        self.assertTrue((self.output / "manifest.json").is_file())
        result = subprocess.run(args, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("Output already exists", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(DEFAULT_OUTPUT, script.parent / "data/role-profiles")
        self.assertEqual(DEFAULT_DB, script.parent / "data/career-ingested.duckdb")


@unittest.skipUnless(DEFAULT_DB.is_file() and (DEFAULT_OUTPUT / "manifest.json").is_file(),
                     "Run export_roles.py for supplied-workbook export checks")
class SuppliedWorkbookExportTests(unittest.TestCase):
    def test_manifest_covers_all_roles_and_software_engineer_requirements(self):
        manifest = json.loads((DEFAULT_OUTPUT / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["role_count"], 2030)
        self.assertEqual(len(manifest["roles"]), 2030)
        self.assertEqual(len({entry["role_id"] for entry in manifest["roles"]}), 2030)
        self.assertEqual(sum(entry["task_count"] for entry in manifest["roles"]), 40379)
        self.assertEqual(sum(entry["skill_requirement_count"] for entry in manifest["roles"]), 44535)
        self.assertEqual(sum("skill_requirements" in entry["missing_data"]
                             for entry in manifest["roles"]), 29)
        for entry in manifest["roles"]:
            self.assertTrue((DEFAULT_OUTPUT / entry["json_path"]).is_file())
            self.assertTrue((DEFAULT_OUTPUT / entry["markdown_path"]).is_file())
        engineer = next(entry for entry in manifest["roles"]
                        if entry["role_title"] == "Software Engineer"
                        and entry["sector"] == "Infocomm Technology")
        profile = json.loads((DEFAULT_OUTPUT / engineer["json_path"]).read_text(encoding="utf-8"))
        self.assertEqual(len(profile["data"]["skills"]), 27)
        self.assertTrue(profile["source_records"])
        markdown = (DEFAULT_OUTPUT / engineer["markdown_path"]).read_text(encoding="utf-8")
        self.assertIn("## Skill requirements (27)", markdown)
        self.assertIn("## Source references", markdown)


if __name__ == "__main__":
    unittest.main()
