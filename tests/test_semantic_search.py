"""Semantic index and hybrid retrieval behaviour against ingested fixtures."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

import embeddings
from embeddings import embed_text, encode_texts, model_signature, is_compatible_model
from ingest import ingest
from lookup import DEFAULT_DB
from semantic_search import (
    SemanticSearch,
    build_semantic_index,
    load_semantic_index,
)
from eval_fixtures import FIXTURES, resolve_fixtures
from evaluate import evaluate_retrieval
from test_ingest import make_inputs
from test_lookup import extend_inputs


class EmbeddingModelTests(unittest.TestCase):
    def test_embedding_is_deterministic(self):
        first = embed_text("designing data schemas and backend APIs")
        second = embed_text("designing data schemas and backend APIs")
        self.assertTrue(np.array_equal(first, second))

    def test_nonempty_text_is_l2_normalised(self):
        vector = embed_text("python sql apis")
        self.assertAlmostEqual(float(np.linalg.norm(vector)), 1.0, places=5)

    def test_empty_text_is_zero_vector(self):
        for text in ("", "   ", None):
            self.assertFalse(embed_text(text or "").any())

    def test_long_text_is_not_silently_truncated(self):
        head = "a" * 200
        first = embed_text(head + " python")
        second = embed_text(head + " sql")
        # If the model truncated to a fixed window, the trailing tokens would
        # be dropped and the two vectors would be identical.
        self.assertFalse(np.array_equal(first, second))

    def test_encode_texts_shape_and_normalisation(self):
        matrix = encode_texts(["python", "sql", ""])
        self.assertEqual(matrix.shape, (3, embeddings.MODEL_CONFIG["dim"]))
        self.assertFalse(matrix[2].any())
        self.assertAlmostEqual(float(np.linalg.norm(matrix[0])), 1.0, places=5)

    def test_model_signature_is_self_consistent(self):
        self.assertTrue(is_compatible_model(model_signature()))
        changed = model_signature()
        changed["model_id"] = "other-model"
        self.assertFalse(is_compatible_model(changed))


class SemanticIndexFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.folder = Path(cls.temp.name)
        make_inputs(cls.folder)
        extend_inputs(cls.folder)
        cls.db_path = cls.folder / "career.duckdb"
        with redirect_stdout(io.StringIO()):
            ingest(cls.folder, cls.db_path)
        cls.index_dir = cls.folder / "semantic-index"

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        # Rebuild a fresh index before every test so tests never depend on
        # shared state or a prior test's writes.
        build_semantic_index(self.db_path, index_dir=self.index_dir, replace=True)

    def test_build_index_reports_coverage(self):
        report = build_semantic_index(self.db_path, index_dir=self.index_dir,
                                      replace=True)
        self.assertEqual(report["status"], "ok")
        coverage = report["coverage"]
        self.assertEqual(coverage["excluded_empty"], 0)
        self.assertEqual(coverage["by_entity_type"]["role"]["covered_entities"], 4)
        self.assertEqual(coverage["by_entity_type"]["role"]["missing_entities"], 0)
        self.assertEqual(coverage["by_entity_type"]["course"]["covered_entities"], 2)

    def test_build_refuses_to_overwrite_without_replace(self):
        with self.assertRaises(FileExistsError):
            build_semantic_index(self.db_path, index_dir=self.index_dir)
        rebuild = build_semantic_index(self.db_path, index_dir=self.index_dir,
                                       replace=True)
        self.assertEqual(rebuild["status"], "ok")

    def test_load_validates_shape_and_model(self):
        loaded = load_semantic_index(self.index_dir)
        self.assertEqual(loaded["vectors"].shape, (6, embeddings.MODEL_CONFIG["dim"]))
        self.assertEqual(len(loaded["documents"]), 6)
        self.assertEqual(loaded["manifest"]["model_id"], embeddings.MODEL_ID)

    def test_model_mismatch_is_refused(self):
        manifest_path = self.index_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["model_config"]["dim"] = 2048
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "model mismatch"):
            load_semantic_index(self.index_dir)

    def test_missing_index_raises(self):
        with self.assertRaisesRegex(FileNotFoundError, "build_embeddings.py"):
            load_semantic_index(self.folder / "missing-index")

    def test_exact_identifiers_preferred_over_ranking(self):
        with SemanticSearch(self.db_path, index_dir=self.index_dir) as search:
            result = search.search("Analyst", "role")
            self.assertTrue(result["results"])
            self.assertTrue(all(item["exact"] for item in result["results"]))

    def test_hybrid_results_carry_fused_and_evidence(self):
        with SemanticSearch(self.db_path, index_dir=self.index_dir) as search:
            result = search.search("review accounts", "role")
            self.assertEqual(result["status"], "ok")
            for item in result["results"]:
                self.assertFalse(item["exact"])
                self.assertIn("semantic_score", item)
                self.assertIn("keyword_score", item)
                self.assertTrue(item["entity_id"])
                self.assertTrue(item["evidence"])

    def test_sector_filter_is_a_hard_constraint(self):
        with SemanticSearch(self.db_path, index_dir=self.index_dir) as search:
            result = search.search("review accounts", "role", sector="Finance")
            self.assertTrue(result["results"])
            self.assertTrue(all(item["sector"] == "Finance"
                                for item in result["results"]))

    def test_rank_returns_ordered_ids(self):
        with SemanticSearch(self.db_path, index_dir=self.index_dir) as search:
            ids = search.rank("review accounts", "role")
            self.assertEqual(ids, [item["entity_id"] for item in
                                   search.search("review accounts", "role")["results"]])

    def test_empty_query_and_unsupported_type(self):
        with SemanticSearch(self.db_path, index_dir=self.index_dir) as search:
            self.assertEqual(search.search("", "role")["results"], [])
            self.assertEqual(search.search("   ", "course")["results"], [])
            with self.assertRaisesRegex(ValueError, "unsupported entity_type"):
                search.search("x", "skill")


_SUPPLIED_INDEX = DEFAULT_DB.parent / "semantic-index" / "manifest.json"


@unittest.skipUnless(_SUPPLIED_INDEX.is_file(),
                     "Run build_embeddings.py for supplied-workbook semantic checks")
class SuppliedWorkbookSemanticTests(unittest.TestCase):
    def test_index_coverage_matches_supplied_database(self):
        with SemanticSearch() as search:
            coverage = search.coverage()
        self.assertEqual(coverage["by_entity_type"]["role"]["source_entities"], 2030)
        self.assertEqual(coverage["by_entity_type"]["course"]["source_entities"], 26099)
        self.assertEqual(coverage["excluded_empty"], 0)

    def test_exact_identifiers_resolve(self):
        with SemanticSearch() as search:
            role = search.search("Software Engineer", "role",
                                 sector="Infocomm Technology",
                                 track="Software and Applications")
            self.assertEqual(len(role["results"]), 1)
            self.assertTrue(role["results"][0]["exact"])
            course = search.search("TGS-2018500660", "course")
            self.assertEqual(len(course["results"]), 1)
            self.assertEqual(course["results"][0]["title"],
                             "Python Programming (SF) (Synchronous and Asynchronous E-Learning)")

    def test_relevant_roles_surface_for_natural_language_queries(self):
        resolved = resolve_fixtures(FIXTURES, DEFAULT_DB)
        with SemanticSearch() as search:
            for case in resolved["retrieval_cases"]:
                if case["entity_type"] != "role":
                    continue
                ids = search.rank(case["query"], "role",
                                  filters=case.get("filters"), limit=15)
                self.assertTrue(
                    set(ids) & set(case["relevant_ids"]),
                    f"{case['id']}: no relevant role surfaced in top-15")

    def test_semantic_mrr_not_worse_than_keyword(self):
        from search import KeywordSearch
        resolved = resolve_fixtures(FIXTURES, DEFAULT_DB)
        with KeywordSearch() as keyword:
            keyword_report = evaluate_retrieval(
                resolved["retrieval_cases"], keyword.rank, k=5)
        with SemanticSearch() as semantic:
            semantic_report = evaluate_retrieval(
                resolved["retrieval_cases"], semantic.rank, k=5)
        self.assertGreaterEqual(
            semantic_report["aggregate"]["overall"]["mean_reciprocal_rank"],
            keyword_report["aggregate"]["overall"]["mean_reciprocal_rank"])

    def test_sector_filtered_security_query_scores(self):
        resolved = resolve_fixtures(FIXTURES, DEFAULT_DB)
        case = next(c for c in resolved["retrieval_cases"]
                    if c["id"] == "role-discovery-application-security")
        with SemanticSearch() as search:
            ids = search.rank(case["query"], "role", filters=case.get("filters"))
        relevant = set(case["relevant_ids"])
        self.assertGreater(len([item for item in ids[:5] if item in relevant]), 0)


if __name__ == "__main__":
    unittest.main()
