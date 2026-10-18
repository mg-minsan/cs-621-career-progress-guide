"""Course search logic, tested with stand-in models (no downloads):
a hashing 'encoder' and a word-overlap 're-ranker'. The real models are
checked by running  py src/course_search.py "Data Governance"  yourself."""
import sys
import zlib
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import course_search as cs  # noqa: E402


def fake_encoder(texts, dim=512):
    out = np.zeros((len(texts), dim), dtype=np.float32)
    for r, t in enumerate(texts):
        for w in cs.tokenize(t.replace(cs.QUERY_PREFIX, "")):
            out[r, zlib.crc32(w.encode()) % dim] += 1
    norms = np.linalg.norm(out, axis=1, keepdims=True)
    return out / np.where(norms == 0, 1, norms)


def fake_reranker(pairs):
    return [len(set(cs.tokenize(q)) & set(cs.tokenize(d))) - 1.0 for q, d in pairs]


@pytest.fixture(scope="module")
def bm25_index():
    return cs.CourseIndex(mode="bm25")


@pytest.fixture(scope="module")
def full_index(bm25_index):
    vecs = fake_encoder([c["search_text"][:1000] for c in bm25_index.courses])
    return cs.CourseIndex(mode="hybrid_rerank", encoder=fake_encoder,
                          reranker=fake_reranker, vectors=vecs)


def test_bm25_finds_keyword_courses(bm25_index):
    hits = bm25_index.search("data governance", k=5)
    assert len(hits) == 5
    assert any("governance" in h["title"].lower() for h in hits)


def test_results_have_no_duplicate_titles(full_index):
    hits = full_index.search("python programming", k=5)
    titles = [cs._norm_title(h["title"]) for h in hits]
    assert len(titles) == len(set(titles))


def test_reranked_scores_are_sorted(full_index):
    scores = [h["score"] for h in full_index.search("data storytelling visualisation", k=5)]
    assert scores == sorted(scores, reverse=True)


def test_gibberish_falls_through_to_honest_no_match(full_index, monkeypatch):
    monkeypatch.setattr(cs, "RERANK_GOOD", 99.0)      # nothing can be "strong"
    res = cs.find_courses_for_skill(full_index, "Data Governance", "Manage data quality", n=2)
    assert res["status"] == "no_strong_match" and res["courses"] == []
    assert "yourself" in res["message"]


def test_fallback_reports_which_step_succeeded(full_index):
    res = cs.find_courses_for_skill(full_index, "Data Governance", "Manage data quality", n=2)
    assert res["status"] in {"title", "broadened", "widened"} and len(res["courses"]) <= 2


def test_missing_index_fails_loudly(monkeypatch, tmp_path):
    monkeypatch.setattr(cs, "VECTORS", tmp_path / "nope.npy")
    with pytest.raises(cs.SearchError):
        cs.CourseIndex(mode="hybrid", encoder=fake_encoder)
