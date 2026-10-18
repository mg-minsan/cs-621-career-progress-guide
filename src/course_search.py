"""
STEP 4 - Course search: find SkillsFuture courses that teach a missing skill.

Why this design (retrieval lessons + what we learned from Dumpling):
  * Courses are NOT tagged with skills, so we search their text.
  * Keyword search (BM25) catches exact terms ("Python", "SQL").
    Meaning search (embeddings) catches different wording
    ("data visualisation" vs "dashboarding") - the vocabulary-gap problem.
  * We merge both lists (Reciprocal Rank Fusion), then a re-ranker reads
    each (skill, course) pair and scores how well they match.
  * Fallback chain, all in CODE, no extra AI calls:
        1. search the skill title
        2. broaden: title + the framework's description of the skill
        3. widen: look at 3x more candidates
        4. give up honestly: "no strong course found - search for it yourself"
    Dumpling ended with a web search; we do NOT, because random web pages
    carry wrong fees and unofficial courses.
  * Near-duplicate courses (same title, different run) are collapsed.

Modes (also your ablations in Step 8):
    bm25 | dense | hybrid | hybrid_rerank (default)

Build the meaning index ONCE (downloads ~2 small models, ~10-20 min on a laptop):
    py src/course_search.py --build
Try a search:
    py src/course_search.py "Data Governance"
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from rank_bm25 import BM25Okapi

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "careers.db"
INDEX_DIR = ROOT / "data" / "index"
VECTORS = INDEX_DIR / "course_vectors.npy"
VECTOR_IDS = INDEX_DIR / "course_vector_ids.json"

EMBED_MODEL = os.getenv("CAREER_EMBED_MODEL", "BAAI/bge-small-en-v1.5")
RERANK_MODEL = os.getenv("CAREER_RERANK_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "  # bge convention
# Re-ranker score a course must reach to count as a "strong" match.
# PLACEHOLDER: tune this on your E2 labels (Step 7). Report the value you chose.
RERANK_GOOD = float(os.getenv("CAREER_RERANK_GOOD", "0.0"))

STOP = {"and", "of", "the", "a", "an", "to", "in", "for", "on", "with", "by", "or", "is",
        "are", "be", "this", "that", "you", "your", "will", "course", "learn", "learners"}


def tokenize(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if w not in STOP]


def _norm_title(t: str) -> str:
    """'Ethical Culture (Synchronous E-Learning)' == 'Ethical Culture': same course, other format."""
    return " ".join(tokenize(re.sub(r"\(.*?\)", " ", t or "")))


class SearchError(Exception):
    """Raised loudly with a message saying how to fix it."""


@dataclass
class CourseIndex:
    mode: str = "hybrid_rerank"
    encoder: object | None = None      # callable(list[str]) -> np.ndarray (unit vectors)
    reranker: object | None = None     # callable(list[(query, doc)]) -> list[float]
    vectors: np.ndarray | None = None
    courses: list[dict] = field(default_factory=list)

    def __post_init__(self):
        if self.mode not in {"bm25", "dense", "hybrid", "hybrid_rerank"}:
            raise SearchError(f"Unknown mode {self.mode}")
        con = sqlite3.connect(DB)
        con.row_factory = sqlite3.Row
        self.courses = [dict(r) for r in con.execute(
            "SELECT course_ref, title, provider, rating, full_fee, fee_after_subsidy, hours, "
            "language, search_text FROM courses ORDER BY course_ref")]
        con.close()
        self._bm25 = BM25Okapi([tokenize(c["search_text"]) for c in self.courses])
        if self.mode != "bm25":
            if self.vectors is None:
                self.vectors = self._load_vectors()
            if self.encoder is None:
                self.encoder = _st_encoder()
        if self.mode == "hybrid_rerank" and self.reranker is None:
            self.reranker = _st_reranker()

    def _load_vectors(self) -> np.ndarray:
        if not VECTORS.exists():
            raise SearchError("Meaning index not built. Run: py src/course_search.py --build "
                              "(or use mode='bm25').")
        ids = json.loads(VECTOR_IDS.read_text())
        if ids != [c["course_ref"] for c in self.courses]:
            raise SearchError("Index is out of date with careers.db. Re-run --build.")
        return np.load(VECTORS)

    # ---- the three retrievers -------------------------------------------
    def bm25_top(self, query: str, k: int) -> list[int]:
        scores = self._bm25.get_scores(tokenize(query))
        top = np.argsort(-scores)[:k]
        return [int(i) for i in top if scores[i] > 0]

    def dense_top(self, query: str, k: int) -> list[int]:
        q = self.encoder([QUERY_PREFIX + query])[0]
        return [int(i) for i in np.argsort(-(self.vectors @ q))[:k]]

    def candidates(self, query: str, pool: int) -> list[int]:
        if self.mode == "bm25":
            return self.bm25_top(query, pool)
        if self.mode == "dense":
            return self.dense_top(query, pool)
        fused: dict[int, float] = {}                  # Reciprocal Rank Fusion
        for ranked in (self.bm25_top(query, pool), self.dense_top(query, pool)):
            for rank, i in enumerate(ranked):
                fused[i] = fused.get(i, 0.0) + 1.0 / (60 + rank)
        return sorted(fused, key=fused.get, reverse=True)[:pool]

    def search(self, query: str, k: int = 5, pool: int = 30) -> list[dict]:
        """Top-k distinct courses. 'score' is the re-ranker score in hybrid_rerank
        mode; in other modes it is None (no notion of 'strong enough')."""
        idxs = self.candidates(query, pool)
        if not idxs:
            return []
        scores: list[float | None]
        if self.mode == "hybrid_rerank":
            docs = [self.courses[i]["search_text"][:1000] for i in idxs]
            scores = [float(s) for s in self.reranker([(query, d) for d in docs])]
            order = sorted(range(len(idxs)), key=lambda j: scores[j], reverse=True)
            idxs, scores = [idxs[j] for j in order], [scores[j] for j in order]
        else:
            scores = [None] * len(idxs)
        out, seen = [], set()
        for i, s in zip(idxs, scores):
            c = self.courses[i]
            key = _norm_title(c["title"])
            if key in seen:                           # collapse repeat runs of one course
                continue
            seen.add(key)
            out.append({k2: c[k2] for k2 in ("course_ref", "title", "provider", "rating", "full_fee",
                                             "fee_after_subsidy", "hours", "language")}
                       | {"score": s})
            if len(out) == k:
                break
        return out


def find_courses_for_skill(index: CourseIndex, skill: str, description: str = "",
                           n: int = 2) -> dict:
    """The fallback chain. Returns which step found the courses, so the
    eval can report how often each fallback is needed."""
    attempts = [("title", skill, 30), ("broadened", f"{skill}. {description}".strip(), 30),
                ("widened", f"{skill}. {description}".strip(), 90)]
    for status, query, pool in attempts:
        if status != "title" and not description:
            continue
        hits = index.search(query, k=n, pool=pool)
        strong = [h for h in hits if h["score"] is None or h["score"] >= RERANK_GOOD]
        if strong:
            return {"skill": skill, "status": status, "query": query, "courses": strong[:n]}
    return {"skill": skill, "status": "no_strong_match", "query": skill, "courses": [],
            "message": f"No strong SkillsFuture course found for '{skill}'. "
                       "Search MySkillsFuture for this skill yourself."}


# ---- real models (sentence-transformers), loaded only when needed ----------
def _st_encoder():
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as e:
        raise SearchError("pip install sentence-transformers  (or use mode='bm25')") from e
    model = SentenceTransformer(EMBED_MODEL)
    return lambda texts: model.encode(texts, normalize_embeddings=True, batch_size=64,
                                      show_progress_bar=len(texts) > 100)


def _st_reranker():
    try:
        from sentence_transformers import CrossEncoder
    except ImportError as e:
        raise SearchError("pip install sentence-transformers  (or use mode='hybrid')") from e
    model = CrossEncoder(RERANK_MODEL)
    return lambda pairs: model.predict(pairs)


def build_vectors() -> None:
    con = sqlite3.connect(DB)
    rows = con.execute("SELECT course_ref, search_text FROM courses ORDER BY course_ref").fetchall()
    con.close()
    print(f"Embedding {len(rows)} courses with {EMBED_MODEL} (one-off, ~10-20 min)...")
    vecs = _st_encoder()([t[:1000] for _, t in rows]).astype(np.float32)
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    np.save(VECTORS, vecs)
    VECTOR_IDS.write_text(json.dumps([r for r, _ in rows]))
    print(f"Saved {vecs.shape} to {VECTORS}")


if __name__ == "__main__":
    if "--build" in sys.argv:
        build_vectors()
    else:
        q = " ".join(a for a in sys.argv[1:] if not a.startswith("--")) or "Data Governance"
        mode = os.getenv("CAREER_SEARCH_MODE", "hybrid_rerank")
        idx = CourseIndex(mode=mode)
        print(f"mode={mode}  query={q!r}")
        for h in idx.search(q, k=5):
            s = "" if h["score"] is None else f"{h['score']:6.2f}  "
            print(f"  {s}{h['title'][:70]}  (${h['full_fee']:,.0f}, {h['provider']})")
