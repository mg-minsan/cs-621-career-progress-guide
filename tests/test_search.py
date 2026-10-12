"""Keyword search behaviour against ingested workbook fixtures."""
from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest

import duckdb

from ingest import ingest
from search import KeywordSearch, _snippet, _terms
from lookup import DEFAULT_DB
from eval_fixtures import FIXTURES, resolve_fixtures
from evaluate import evaluate_retrieval
from test_ingest import make_inputs
from test_lookup import extend_inputs


class SearchTests(unittest.TestCase):
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

    def setUp(self):
        self.search = KeywordSearch(self.db_path)
        self.addCleanup(self.search.close)

    def test_exact_role_title_returns_all_candidates(self):
        result = self.search.search("Analyst", "role")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["results"]), 3)
        self.assertTrue(all(item["exact"] for item in result["results"]))
        titles = {(item["sector"], item["track"]) for item in result["results"]}
        self.assertEqual(titles, {
            ("Finance", "Operations"), ("Finance", "Risk"), ("Technology", "Operations")})

    def test_exact_role_title_honours_sector_and_track_filters(self):
        by_sector = self.search.search("Analyst", "role", sector="Finance")
        self.assertEqual({(r["sector"], r["track"]) for r in by_sector["results"]},
                         {("Finance", "Operations"), ("Finance", "Risk")})
        by_track = self.search.search("Analyst", "role", track="Risk")
        self.assertEqual(len(by_track["results"]), 1)
        self.assertEqual(by_track["results"][0]["sector"], "Finance")

    def test_keyword_role_search_finds_task_and_skill_text(self):
        result = self.search.search("review accounts", "role")
        self.assertTrue(result["results"])
        top = result["results"][0]
        self.assertEqual(top["title"], "Analyst")
        self.assertEqual(top["sector"], "Finance")
        self.assertEqual(top["track"], "Operations")
        self.assertEqual(top["matched_terms"], ["accounts", "review"])
        self.assertTrue(any("accounts" in evidence["snippet"]
                            for evidence in top["evidence"]))

    def test_exact_course_id_and_title_resolve(self):
        for identifier in ("C1", " C1 "):
            result = self.search.search(identifier, "course")
            self.assertEqual(len(result["results"]), 1)
            self.assertEqual(result["results"][0]["entity_id"], "C1")
            self.assertTrue(result["results"][0]["exact"])

    def test_keyword_course_search_finds_outcomes(self):
        result = self.search.search("summarise findings", "course")
        self.assertTrue(result["results"])
        top = result["results"][0]
        self.assertEqual(top["entity_id"], "C1")
        self.assertTrue(any("Summarise" in evidence["snippet"]
                            for evidence in top["evidence"]))
        self.assertIn("summarise", top["matched_terms"])

    def test_unknown_and_empty_queries_return_empty(self):
        self.assertEqual(self.search.search("zzzz not present", "role")["results"], [])
        self.assertEqual(self.search.search("", "course")["results"], [])
        self.assertEqual(self.search.search("   ", "role")["results"], [])

    def test_rank_returns_ordered_ids(self):
        ids = self.search.rank("Analyst", "role")
        self.assertEqual(len(ids), 3)
        self.assertEqual(ids, [item["entity_id"]
                               for item in self.search.search("Analyst", "role")["results"]])

    def test_unsupported_entity_type_raises(self):
        with self.assertRaisesRegex(ValueError, "unsupported entity_type"):
            self.search.search("x", "skill")

    def test_read_only_and_missing_database_protection(self):
        original = self.db_path.read_bytes()
        with KeywordSearch(self.db_path) as searcher:
            with self.assertRaises(duckdb.Error):
                searcher._con.execute("DELETE FROM core.roles")
            searcher.search("Analyst", "role")
        with self.assertRaises(duckdb.Error):
            searcher.search("Analyst", "role")
        self.assertEqual(original, self.db_path.read_bytes())
        with self.assertRaisesRegex(FileNotFoundError, "Run ingest.py first"):
            KeywordSearch(self.folder / "missing.duckdb")


class TokenAndSnippetTests(unittest.TestCase):
    def test_terms_are_lowercase_alphanumeric_tokens(self):
        self.assertEqual(_terms("Python, SQL and R!"), ["python", "sql", "and", "r"])

    def test_snippet_wraps_first_match_with_ellipses(self):
        text = "a" * 200 + "python" + "b" * 200
        snippet = _snippet(text, ["python"], width=20)
        self.assertIn("python", snippet)
        self.assertTrue(snippet.startswith("…"))
        self.assertTrue(snippet.endswith("…"))

    def test_snippet_returns_head_when_no_match(self):
        self.assertEqual(_snippet("short text", ["absent"], width=5), "short")


@unittest.skipUnless(DEFAULT_DB.is_file(), "Run ingest.py --db data/career-ingested.duckdb for snapshot checks")
class SuppliedWorkbookSearchTests(unittest.TestCase):
    def test_exact_identifiers_and_keywords_resolve(self):
        with KeywordSearch() as search:
            role = search.search("Software Engineer", "role", sector="Infocomm Technology",
                                 track="Software and Applications")
            self.assertEqual(len(role["results"]), 1)
            self.assertEqual(role["results"][0]["sector"], "Infocomm Technology")
            course = search.search("TGS-2018500660", "course")
            self.assertEqual(len(course["results"]), 1)
            self.assertEqual(course["results"][0]["title"], "Python Programming (SF) (Synchronous and Asynchronous E-Learning)")
            # "Python Programming" is an exact title shared by three courses.
            exact_title = search.search("Python Programming", "course")
            self.assertEqual(len(exact_title["results"]), 3)
            self.assertTrue(all(item["exact"] for item in exact_title["results"]))
            # A distinctive learning-outcome term surfaces its courses.
            forklift = search.search("forklift", "course", limit=10)
            forklift_titles = [item["title"].lower() for item in forklift["results"]]
            self.assertTrue(any("forklift" in title for title in forklift_titles))
            # Keyword search over required skills surfaces roles with that skill.
            testing = search.search("software testing", "role",
                                    sector="Infocomm Technology", limit=10)
            self.assertTrue(testing["results"])
            self.assertTrue(all(item["sector"] == "Infocomm Technology"
                                for item in testing["results"]))

    def test_keyword_search_scores_the_reviewed_retrieval_fixtures(self):
        resolved = resolve_fixtures(FIXTURES, DEFAULT_DB)
        with KeywordSearch() as search:
            report = evaluate_retrieval(resolved["retrieval_cases"], search.rank, k=5)
        self.assertEqual(report["k"], 5)
        self.assertEqual(len(report["cases"]), len(FIXTURES["retrieval_cases"]))
        for key in ("overall", "role", "course"):
            self.assertIn(key, report["aggregate"])
        self.assertTrue(all(case["returned_count"] > 0 for case in report["cases"]))
        # The sector-filtered security query is keyword-friendly and scores > 0.
        security = next(case for case in report["cases"]
                        if case["id"] == "role-discovery-application-security")
        self.assertGreater(security["recall_at_k"], 0)


if __name__ == "__main__":
    unittest.main()
