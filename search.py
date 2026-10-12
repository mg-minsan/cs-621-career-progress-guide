"""Keyword search over role and course retrieval text.

This is the phase-2 search baseline. It ranks the ``core.search_documents``
text built by ingestion — role descriptions, tasks and required skills for
roles; titles, descriptions and learning outcomes for courses — using BM25 over
lowercased alphanumeric tokens. Inverse document frequency lets discriminative
terms such as "python" outweigh common words, so relevant task and
learning-outcome text is discoverable without an embedding model.

Exact identifiers (course reference numbers, role IDs and exact titles) are
resolved directly before any keyword ranking, so ``TGS-...`` course references
and exact titles always return the right entity. Results carry entity IDs,
scores, matched terms and evidence snippets, so callers can fetch complete
facts and source records through ``lookup.CareerLookup`` without parsing
generated Markdown. Scores are relevance signals, never readiness or
suitability.
"""
from __future__ import annotations

from collections import Counter
import math
import re
from pathlib import Path

import duckdb

from lookup import DEFAULT_DB


_TOKEN = re.compile(r"[a-z0-9]+")

# BM25 parameters (Robertson et al.); standard defaults for short documents.
K1 = 1.2
B = 0.75


def _terms(query: str) -> list[str]:
    return list(dict.fromkeys(_TOKEN.findall(query.lower())))


def _snippet(text: str, terms: list[str], width: int = 100) -> str:
    """A window around the first matched term, or the head of the text."""
    lower = text.lower()
    first = None
    for term in terms:
        index = lower.find(term)
        if index != -1 and (first is None or index < first):
            first = index
    if first is None:
        return text[:width]
    start = max(0, first - width // 2)
    end = min(len(text), first + width // 2)
    snippet = text[start:end]
    if start > 0:
        snippet = "…" + snippet
    if end < len(text):
        snippet += "…"
    return snippet


class KeywordSearch:
    """Own one read-only DuckDB connection; never creates or rebuilds a database.

    Exact identifiers are preferred over keyword ranking: an exact role ID or
    title, or an exact course reference number or title, short-circuits the
    search. Otherwise documents are scored with BM25 and ranked descending, with
    ties broken by title and entity ID for determinism. The tokenized corpus is
    cached per entity type for the lifetime of the instance.
    """

    def __init__(self, db_path=DEFAULT_DB):
        self.db_path = Path(db_path).resolve()
        if not self.db_path.is_file():
            raise FileNotFoundError(
                f"Career database not found: {self.db_path}. Run ingest.py first.")
        self._con = duckdb.connect(str(self.db_path), read_only=True)
        self._corpora = {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def close(self):
        self._con.close()

    def _query(self, sql, params=()):
        cursor = self._con.execute(sql, params)
        columns = [column[0] for column in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def _exact_roles(self, query: str, sector, track) -> list[dict]:
        matches = self._query("""
            SELECT role_id, sector, track, role_title FROM core.roles
            WHERE role_id = ?
               OR lower(role_title) = lower(?)
            ORDER BY sector, track, role_title, role_id
        """, [query.strip(), query.strip()])
        if sector is not None or track is not None:
            matches = [match for match in matches
                       if (sector is None or match["sector"].lower() == sector.strip().lower())
                       and (track is None or match["track"].lower() == track.strip().lower())]
        return [
            {"entity_id": match["role_id"], "title": match["role_title"],
             "sector": match["sector"], "track": match["track"],
             "score": None, "matched_terms": [], "evidence": [], "exact": True}
            for match in matches
        ]

    def _exact_courses(self, query: str) -> list[dict]:
        by_id = self._query("""
            SELECT course_id, title, provider_name FROM core.courses
            WHERE course_id = ?
        """, [query.strip()])
        if by_id:
            return [
                {"entity_id": course["course_id"], "title": course["title"],
                 "provider_name": course["provider_name"], "score": None,
                 "matched_terms": [], "evidence": [], "exact": True}
                for course in by_id
            ]
        matches = self._query("""
            SELECT course_id, title, provider_name FROM core.courses
            WHERE lower(title) = lower(?)
            ORDER BY course_id
        """, [query.strip()])
        return [
            {"entity_id": course["course_id"], "title": course["title"],
             "provider_name": course["provider_name"], "score": None,
             "matched_terms": [], "evidence": [], "exact": True}
            for course in matches
        ]

    def _build_corpus(self, entity_type: str) -> dict:
        if entity_type == "role":
            rows = self._query("""
                SELECT d.entity_id, d.section, d.text,
                       r.sector, r.track, r.role_title AS title
                FROM core.search_documents d
                JOIN core.roles r ON r.role_id = d.entity_id
                WHERE d.entity_type = 'role'
            """)
        elif entity_type == "course":
            rows = self._query("""
                SELECT d.entity_id, d.section, d.text, c.title, c.provider_name
                FROM core.search_documents d
                JOIN core.courses c ON c.course_id = d.entity_id
                WHERE d.entity_type = 'course'
            """)
        else:
            raise ValueError(f"unsupported entity_type: {entity_type!r}")
        docs = []
        document_frequency = Counter()
        total_length = 0
        for row in rows:
            counts = Counter(_TOKEN.findall(row["text"].lower()))
            docs.append({**row, "counts": counts, "length": sum(counts.values())})
            document_frequency.update(counts.keys())
            total_length += docs[-1]["length"]
        count = len(docs)
        return {
            "docs": docs,
            "document_frequency": document_frequency,
            "average_length": total_length / count if count else 0.0,
        }

    def _corpus(self, entity_type: str) -> dict:
        if entity_type not in self._corpora:
            self._corpora[entity_type] = self._build_corpus(entity_type)
        return self._corpora[entity_type]

    @staticmethod
    def _score(document, terms, idfs, average_length) -> float:
        """BM25 score for one document; idfs are precomputed per query term."""
        length = document["length"] or 1
        score = 0.0
        for term in terms:
            idf = idfs.get(term)
            if idf is None:
                continue
            term_frequency = document["counts"].get(term, 0)
            if term_frequency == 0:
                continue
            score += (idf * term_frequency * (K1 + 1)) / (
                term_frequency + K1 * (1 - B + B * length / average_length))
        return score

    def _keyword_results(self, entity_type, query, sector, track, limit):
        terms = _terms(query)
        if not terms:
            return []
        corpus = self._corpus(entity_type)
        count = len(corpus["docs"])
        idfs = {}
        for term in terms:
            frequency = corpus["document_frequency"].get(term, 0)
            if frequency:
                idfs[term] = math.log(
                    1.0 + (count - frequency + 0.5) / (frequency + 0.5))
        filtered = []
        if entity_type == "role":
            sector_norm = sector.strip().lower() if sector is not None else None
            track_norm = track.strip().lower() if track is not None else None
            for document in corpus["docs"]:
                if sector_norm is not None and document["sector"].lower() != sector_norm:
                    continue
                if track_norm is not None and document["track"].lower() != track_norm:
                    continue
                filtered.append(document)
        else:
            filtered = corpus["docs"]
        scored = []
        for document in filtered:
            score = self._score(document, terms, idfs, corpus["average_length"])
            if score <= 0:
                continue
            matched = sorted(term for term in terms if document["counts"].get(term))
            result = {
                "entity_id": document["entity_id"], "title": document["title"],
                "score": score, "matched_terms": matched,
                "evidence": [{"section": document["section"],
                              "snippet": _snippet(document["text"], terms)}],
                "exact": False,
            }
            if entity_type == "role":
                result["sector"] = document["sector"]
                result["track"] = document["track"]
            else:
                result["provider_name"] = document["provider_name"]
            scored.append(result)
        scored.sort(key=lambda item: (-item["score"], item["title"],
                                      item["entity_id"]))
        return scored[:limit] if limit is not None else scored

    def search(self, query: str, entity_type: str, sector: str | None = None,
               track: str | None = None, limit: int | None = 10) -> dict:
        """Ranked candidates with entity IDs and matching evidence.

        Exact identifiers are returned first and marked ``exact``. Keyword
        results carry ``score``, ``matched_terms`` and per-section ``evidence``
        snippets. An empty or unknown query returns an empty list with status ok.
        """
        if entity_type not in ("role", "course"):
            raise ValueError(f"unsupported entity_type: {entity_type!r}")
        exact = (self._exact_roles(query, sector, track) if entity_type == "role"
                 else self._exact_courses(query))
        if exact:
            return {"status": "ok", "entity_type": entity_type, "query": query,
                    "results": exact[:limit] if limit is not None else exact}
        results = self._keyword_results(entity_type, query, sector, track, limit)
        return {"status": "ok", "entity_type": entity_type, "query": query,
                "results": results}

    def rank(self, query: str, entity_type: str, filters: dict | None = None,
             limit: int | None = None) -> list[str]:
        """Ranked canonical entity IDs, suitable for ``evaluate_retrieval``.

        ``filters`` accepts ``sector`` and ``track`` for role searches and is
        ignored for course searches.
        """
        filters = filters or {}
        result = self.search(query, entity_type, sector=filters.get("sector"),
                             track=filters.get("track"), limit=limit)
        return [item["entity_id"] for item in result["results"]]
