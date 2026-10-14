"""End-to-end guide flow tests."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import duckdb
import numpy as np
from openpyxl import load_workbook

from ingest import SOURCES, ingest
from lookup import CareerLookup, DEFAULT_DB
from semantic_search import build_semantic_index
from test_ingest import make_inputs
from test_lookup import append_rows, extend_inputs
from demo_profile import SAMPLE_PROFILES
from guide import main, run


class GuideFixtureTests(unittest.TestCase):
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

    def test_suggestion_limit_applies_to_unique_roles_not_document_chunks(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            make_inputs(folder)
            workbook_path = folder / next(iter(SOURCES))
            workbook = load_workbook(workbook_path)
            append_rows(workbook["Job Role_Description"], "roles", [
                {"Sector": f"Sector {i}", "Track": "Operations", "Job Role": "Analyst",
                 "Job Role Description": "Analyse accounts"} for i in range(6)])
            workbook.save(workbook_path)
            workbook.close()
            db_path = folder / "career.duckdb"
            with redirect_stdout(io.StringIO()):
                ingest(folder, db_path)
            # Fixture: chunked index documents for one role must not crowd out
            # distinct recorded roles before the guide's five-role limit.
            with duckdb.connect(str(db_path)) as con:
                con.execute("""
                    INSERT INTO core.search_documents
                    SELECT document_id || '-' || CAST(i AS VARCHAR), entity_type,
                           entity_id, section, text, content_hash
                    FROM core.search_documents CROSS JOIN range(10) chunks(i)
                    WHERE entity_type = 'role'
                """)
            for use_index in (False, True):
                if use_index:
                    build_semantic_index(db_path)
                result = run(SAMPLE_PROFILES["backend"], role_title="accounts",
                             db_path=db_path)
                self.assertEqual(len(result["suggestions"]), 5)
                self.assertEqual(len({c["role_id"] for c in result["suggestions"]}), 5)

    def test_cli_hybrid_suggestions_exact_ambiguity_and_empty_target(self):
        with tempfile.TemporaryDirectory() as folder:
            index_dir = Path(folder) / "index"
            build_semantic_index(self.db_path, index_dir=index_dir)
            cases = [("review accounts", "Hybrid keyword/vector", False),
                     ("Trainee", "=== 3. Focus role: Trainee", True),
                     ("Analyst", "ambiguous", False),
                     ("", "Target role is empty", False),
                     ("!!!", "No matching recorded roles", False)]
            for query, expected, has_focus in cases:
                with self.subTest(query=query):
                    output = io.StringIO()
                    with redirect_stdout(output):
                        status = main(["--db", str(self.db_path), "--index-dir",
                                       str(index_dir), "--role", query])
                    self.assertEqual(status, 0)
                    self.assertIn(expected, output.getvalue())
                    self.assertEqual("=== 3. Focus role" in output.getvalue(), has_focus)
                    if query == "Analyst":
                        self.assertIn("--role-id", output.getvalue())
                        self.assertIn("Finance / Risk", output.getvalue())
                        self.assertIn("Technology / Operations", output.getvalue())
    def test_cli_no_match_and_invalid_id_produce_clear_messages(self):
        for arguments, expected in [(["--role", "qzxv987654321"], "No matching recorded roles"),
                                    (["--role-id", "invalid-id"], "Canonical role ID not found")]:
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(["--db", str(self.db_path), *arguments]), 0)
            self.assertIn(expected, output.getvalue())
            self.assertNotIn("=== 3. Focus role", output.getvalue())

    def test_cli_invalid_index_reports_error_without_traceback_or_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            index_dir = Path(folder) / "index"
            index_dir.mkdir()
            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                status = main(["--db", str(self.db_path), "--index-dir", str(index_dir),
                               "--role", "review accounts"])
        self.assertEqual(status, 1)
        self.assertIn("Semantic index", stderr.getvalue())
        self.assertIn("Rebuild", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())
        self.assertNotIn("keyword fallback", stdout.getvalue())
        self.assertNotIn("Focus role", stdout.getvalue())

    def test_cli_displays_cited_suggestions_and_accepts_explicit_id_selection(self):
        command = [sys.executable, str(Path(__file__).resolve().parents[1] / "guide.py"),
                   "--db", str(self.db_path), "--profile", "backend"]
        output = subprocess.run(command + ["--role", "review accounts"],
                                capture_output=True, text=True)
        self.assertEqual(output.returncode, 0, output.stderr)
        self.assertIn("keyword fallback", output.stdout)
        self.assertIn("relevance signals", output.stdout)
        self.assertIn("readiness", output.stdout)
        self.assertIn("Analyse accounts", output.stdout)
        self.assertIn("row ", output.stdout)
        self.assertIn("--role-id", output.stdout)
        self.assertNotIn("=== 3. Focus role", output.stdout)
        self.assertNotIn("Candidate courses", output.stdout)
        suggested = run(SAMPLE_PROFILES["backend"], role_title="review accounts",
                        db_path=self.db_path)["suggestions"][0]
        self.assertIn(suggested["role_id"], output.stdout)
        self.assertIn("Analyst", output.stdout)
        self.assertIn("Finance", output.stdout)
        self.assertIn("Operations", output.stdout)
        selected = subprocess.run(command + ["--role-id", suggested["role_id"]],
                                  capture_output=True, text=True)
        self.assertEqual(selected.returncode, 0, selected.stderr)
        self.assertIn("=== 3. Focus role: Analyst", selected.stdout)
        self.assertIn("Recorded requirements", selected.stdout)
        self.assertIn("Candidate courses", selected.stdout)

    def test_present_but_invalid_indexes_fail_clearly_without_keyword_fallback(self):
        cases = ("model", "schema", "text_version", "json", "manifest_missing",
                 "vectors_missing", "vector_shape", "nonfinite", "database",
                 "vectors_empty", "metadata", "unknown_role")
        with tempfile.TemporaryDirectory() as folder:
            index_dir = Path(folder) / "index"
            for case in cases:
                with self.subTest(case=case):
                    build_semantic_index(self.db_path, index_dir=index_dir, replace=True)
                    manifest_path = index_dir / "manifest.json"
                    manifest = json.loads(manifest_path.read_text())
                    if case == "model":
                        manifest["model_id"] = "wrong-model"
                    elif case == "schema":
                        manifest["schema_version"] = 999
                    elif case == "text_version":
                        manifest["text_version"] = "old-text"
                    elif case == "database":
                        manifest["source_db_sha256"] = "wrong-database"
                    elif case == "metadata":
                        manifest["documents"] = [{"entity_type": "bogus"}]
                    elif case == "unknown_role":
                        for doc in manifest["documents"]:
                            if doc["entity_type"] == "role":
                                doc["entity_id"] = "f" * 64
                    manifest_path.write_text(json.dumps(manifest))
                    if case == "json":
                        manifest_path.write_text("{broken json")
                    elif case == "manifest_missing":
                        manifest_path.unlink()
                    elif case == "vectors_missing":
                        (index_dir / "vectors.npy").unlink()
                    elif case == "vectors_empty":
                        (index_dir / "vectors.npy").write_bytes(b"")
                    elif case == "vector_shape":
                        np.save(index_dir / "vectors.npy", np.zeros(6))
                    elif case == "nonfinite":
                        vectors = np.load(index_dir / "vectors.npy")
                        vectors[0, 0] = np.nan
                        np.save(index_dir / "vectors.npy", vectors)
                    with self.assertRaisesRegex(RuntimeError, "Semantic index"):
                        run(SAMPLE_PROFILES["backend"], role_title="review accounts",
                            db_path=self.db_path, index_dir=index_dir)
                    # Exact lookup does not depend on an approximate-search index.
                    exact = run(SAMPLE_PROFILES["backend"], role_title="Trainee",
                                db_path=self.db_path, index_dir=index_dir)
                    self.assertEqual(exact["focus_role"]["title"], "Trainee")

    def test_empty_and_no_match_targets_do_not_default_to_profile_role(self):
        for query in ("", "   ", "qzxv987654321"):
            with self.subTest(query=query):
                result = run(SAMPLE_PROFILES["backend"], role_title=query,
                             db_path=self.db_path)
                self.assertIsNone(result["focus_role"])
                self.assertFalse(result["selection_required"])
                self.assertEqual(result["suggestions"], [])
                self.assertTrue(result["message"])
        invalid = run(SAMPLE_PROFILES["backend"], role_id="invalid-id",
                      db_path=self.db_path)
        self.assertEqual(invalid["error"], "not_found")
        self.assertIn("Canonical role ID not found", invalid["message"])
        with self.assertRaisesRegex(ValueError, "either"):
            run(SAMPLE_PROFILES["backend"], role_title="Analyst", role_id="id",
                db_path=self.db_path)

    def test_ambiguous_titles_keep_all_ids_and_each_can_be_explicitly_selected(self):
        ambiguous = run(SAMPLE_PROFILES["backend"], role_title="Analyst",
                        db_path=self.db_path)
        self.assertEqual(ambiguous["error"], "ambiguous")
        self.assertEqual(len(ambiguous["candidates"]), 3)
        identities = set()
        for candidate in ambiguous["candidates"]:
            selected = run(SAMPLE_PROFILES["backend"],
                           role_id=candidate["role_id"], db_path=self.db_path)
            self.assertEqual(selected["focus_role"]["role_id"], candidate["role_id"])
            self.assertEqual(selected["focus_role"]["title"], "Analyst")
            identities.add((selected["focus_role"]["sector"],
                            selected["focus_role"]["track"]))
        self.assertEqual(identities, {("Finance", "Operations"), ("Finance", "Risk"),
                                      ("Technology", "Operations")})
        suggested = run(SAMPLE_PROFILES["backend"], role_title="review accounts",
                        db_path=self.db_path)
        confirmed = run(SAMPLE_PROFILES["backend"], db_path=self.db_path,
                        role_id=suggested["suggestions"][0]["role_id"])
        self.assertTrue(confirmed["requirements"])
        self.assertTrue(confirmed["role_sources"])

    def test_available_index_uses_hybrid_retrieval_and_still_requires_selection(self):
        with tempfile.TemporaryDirectory() as folder:
            index_dir = Path(folder) / "index"
            build_semantic_index(self.db_path, index_dir=index_dir)
            result = run(SAMPLE_PROFILES["backend"], role_title="review accounts",
                         db_path=self.db_path, index_dir=index_dir)
        self.assertEqual(result["retrieval_method"], "hybrid")
        self.assertIn("keyword", result["retrieval_disclosure"].lower())
        self.assertIn("vector", result["retrieval_disclosure"].lower())
        self.assertTrue(result["suggestions"])
        self.assertTrue(result["selection_required"])
        self.assertIsNone(result["focus_role"])
        self.assertTrue(all(item["sources"] and item["evidence"]
                            for item in result["suggestions"]))

    def test_unknown_title_suggests_recorded_roles_without_generating_guide(self):
        result = run(SAMPLE_PROFILES["backend"], role_title="review accounts",
                     db_path=self.db_path)
        self.assertEqual(result["error"], "not_found")
        self.assertEqual(result["retrieval_method"], "keyword")
        self.assertIn("missing", result["retrieval_disclosure"].lower())
        self.assertTrue(result["selection_required"])
        self.assertIsNone(result["focus_role"])
        self.assertEqual(result["requirements"], [])
        self.assertEqual(result["courses"], [])
        self.assertGreater(len(result["suggestions"]), 0)
        self.assertLessEqual(len(result["suggestions"]), 5)
        ids = [item["role_id"] for item in result["suggestions"]]
        self.assertEqual(len(ids), len(set(ids)))
        with CareerLookup(self.db_path) as lookup:
            for item in result["suggestions"]:
                recorded = lookup.get_role(item["role_id"])
                self.assertEqual(item["title"], recorded["data"]["role_title"])
                self.assertEqual(item["sector"], recorded["data"]["sector"])
                self.assertEqual(item["track"], recorded["data"]["track"])
                self.assertEqual(item["description"], recorded["data"]["description"])
                self.assertEqual(item["source_records"], recorded["source_records"])
                self.assertTrue(item["sources"])
                self.assertTrue(item["evidence"])
        self.assertIn("relevance", result["message"].lower())
        self.assertIn("readiness", result["message"].lower())


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

    def test_research_engineer_returns_five_unique_cited_suggestions(self):
        result = run(SAMPLE_PROFILES["backend"], role_title="Research Engineer")
        self.assertEqual(len(result["suggestions"]), 5)
        self.assertEqual(len({item["role_id"] for item in result["suggestions"]}), 5)
        self.assertTrue(all(item["sources"] and item["evidence"]
                            for item in result["suggestions"]))
        self.assertIsNone(result["focus_role"])
        self.assertTrue(result["selection_required"])

    def test_unknown_role_title_is_reported(self):
        result = run(SAMPLE_PROFILES["backend"], role_title="No Such Role")
        self.assertEqual(result["error"], "not_found")


if __name__ == "__main__":
    unittest.main()
