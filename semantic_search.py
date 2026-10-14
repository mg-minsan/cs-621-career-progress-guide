"""Hybrid keyword + semantic retrieval over role and course documents.

Phase 3 builds bounded, intentional search representations for roles and
courses and stores their embeddings so queries can be ranked by meaning as
well as by keyword match. This module:

* builds a local vector index from ``core.search_documents`` (roles:
  descriptions, tasks and required-skill titles; courses: titles, descriptions
  and learning outcomes), storing entity IDs, document IDs, content hashes and
  the embedding model/configuration and text-construction version alongside the
  vectors;
* loads an index and refuses to mix it with a different embedding model or
  configuration (no incompatible vector mixing);
* reports index coverage, excluded empty records and duplicated entities;
* fuses BM25 keyword scores (``search.KeywordSearch``) with cosine similarity
  scores (``embeddings``) using reciprocal rank fusion, deduplicating chunks by
  entity before ranking.

Search scores are relevance signals, never readiness or suitability. Results
carry canonical entity IDs and evidence snippets so callers fetch complete
facts and source records through ``lookup.CareerLookup``.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import shutil
from pathlib import Path
import tempfile

import duckdb
import numpy as np

from embeddings import (
    MODEL_CONFIG,
    embed_text,
    encode_texts,
    is_compatible_model,
    model_signature,
)
from lookup import DEFAULT_DB
from search import KeywordSearch


INDEX_SCHEMA_VERSION = 1
# Describes which core.search_documents sections/schema the index was built
# from. Bump when the text construction changes so stale indexes are visible.
TEXT_VERSION = "core.search_documents.v1"

# Reciprocal rank fusion constant; ranks are scale-free so semantic (cosine)
# and keyword (BM25) scores can be combined without normalising either scale.
RRF_K = 60

# Only roles and courses are indexed; skill proficiency text is not part of
# role/course discovery and is deliberately out of scope for phase 3.
INDEXED_ENTITY_TYPES = ("role", "course")

_SNIPPET_WIDTH = 240


def _head_snippet(text: str, width: int = _SNIPPET_WIDTH) -> str:
    """The head of a document's text, used as semantic evidence."""
    text = text or ""
    return text[:width] + ("…" if len(text) > width else "")


def _query(con, sql, params=()):
    cursor = con.execute(sql, params)
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def default_index_dir(db_path=DEFAULT_DB) -> Path:
    return Path(db_path).resolve().parent / "semantic-index"


def _load_documents(con) -> list[dict]:
    """One record per role/course search document, enriched for ranking.

    Empty or blank text is returned as-is so the caller can report and exclude
    it rather than silently embedding an empty string.
    """
    roles = _query(con, """
        SELECT d.document_id, d.entity_type, d.entity_id, d.section, d.text,
               d.content_hash, r.sector, r.track, r.role_title AS title,
               NULL AS provider_name
        FROM core.search_documents d
        JOIN core.roles r ON r.role_id = d.entity_id
        WHERE d.entity_type = 'role'
    """)
    courses = _query(con, """
        SELECT d.document_id, d.entity_type, d.entity_id, d.section, d.text,
               d.content_hash, NULL AS sector, NULL AS track, c.title AS title,
               c.provider_name
        FROM core.search_documents d
        JOIN core.courses c ON c.course_id = d.entity_id
        WHERE d.entity_type = 'course'
    """)
    return roles + courses


def _coverage(con, documents, excluded_empty) -> dict:
    """Report indexed/covered counts per entity type and excluded records."""
    def stats(total_entities, docs, excluded):
        counts = Counter(d["entity_id"] for d in docs)
        duplicates = sum(1 for count in counts.values() if count > 1)
        return {
            "source_entities": total_entities,
            "indexed_documents": len(docs),
            "covered_entities": len(counts),
            "missing_entities": total_entities - len(counts),
            "duplicated_entities": duplicates,
            "excluded_empty": excluded,
        }

    total_roles = _query(con, "SELECT count(*) AS n FROM core.roles")[0]["n"]
    total_courses = _query(con, "SELECT count(*) AS n FROM core.courses")[0]["n"]

    excluded_by_type = Counter(r["entity_type"] for r in excluded_empty)
    return {
        "entity_types_indexed": list(INDEXED_ENTITY_TYPES),
        "excluded_entity_types": ["skill_proficiency"],
        "total_documents": len(documents),
        "excluded_empty": len(excluded_empty),
        "by_entity_type": {
            "role": stats(total_roles, [d for d in documents
                                        if d["entity_type"] == "role"],
                          excluded_by_type.get("role", 0)),
            "course": stats(total_courses, [d for d in documents
                                            if d["entity_type"] == "course"],
                            excluded_by_type.get("course", 0)),
        },
    }


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db_sha256(db_path: Path) -> str:
    digest = hashlib.sha256()
    with db_path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_semantic_index(db_path=DEFAULT_DB, index_dir=None, replace=False) -> dict:
    """Build (or rebuild) the local vector index and return its report.

    The index is written atomically: vectors and manifest are assembled in a
    temporary sibling directory and then renamed into place, so a failed build
    leaves no partial index. An existing index directory is protected unless
    ``replace`` is true.
    """
    db_path = Path(db_path).resolve()
    if not db_path.is_file():
        raise FileNotFoundError(
            f"Career database not found: {db_path}. Run ingest.py first.")
    index_dir = Path(index_dir).resolve() if index_dir else default_index_dir(db_path)
    if index_dir.exists() and not replace:
        raise FileExistsError(
            f"Index already exists at {index_dir}; pass replace=True to rebuild.")

    source_db_sha256 = _db_sha256(db_path)

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        rows = _load_documents(con)
        kept = [row for row in rows if row["text"] and row["text"].strip()]
        excluded_empty = [{
            "document_id": row["document_id"], "entity_type": row["entity_type"],
            "entity_id": row["entity_id"], "section": row["section"],
        } for row in rows if not (row["text"] and row["text"].strip())]
        coverage = _coverage(con, kept, excluded_empty)
    finally:
        con.close()

    texts = [row["text"] for row in kept]
    documents = [{
        "document_id": row["document_id"],
        "entity_type": row["entity_type"],
        "entity_id": row["entity_id"],
        "section": row["section"],
        "content_hash": row["content_hash"],
        "title": row["title"],
        "sector": row["sector"],
        "track": row["track"],
        "provider_name": row["provider_name"],
        "text_length": len(row["text"]),
    } for row in kept]

    vectors = encode_texts(texts)
    signature = model_signature()
    manifest = {
        "schema_version": INDEX_SCHEMA_VERSION,
        "text_version": TEXT_VERSION,
        **signature,
        "source_db": str(db_path),
        "source_db_sha256": source_db_sha256,
        "built_at": _iso_now(),
        "document_count": len(documents),
        "coverage": coverage,
        "documents": documents,
    }

    index_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".semantic-index-", dir=index_dir.parent))
    try:
        np.save(temporary / "vectors.npy", vectors)
        (temporary / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        if replace and index_dir.exists():
            shutil.rmtree(index_dir)
        temporary.replace(index_dir)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise

    return {
        "status": "ok",
        "index_dir": str(index_dir),
        "source_db_sha256": source_db_sha256,
        "model_id": signature["model_id"],
        "dim": MODEL_CONFIG["dim"],
        "document_count": len(documents),
        "coverage": coverage,
    }


def load_semantic_index(index_dir, verify_model=True) -> dict:
    """Load a built index and validate its model and shape.

    Raises RuntimeError for incompatible schema, text construction or model
    configuration, unreadable files, invalid metadata or nonfinite/misaligned
    vectors. A wholly absent index raises FileNotFoundError.
    """
    index_dir = Path(index_dir).resolve()
    manifest_path = index_dir / "manifest.json"
    if not index_dir.exists():
        raise FileNotFoundError(
            f"Semantic index not found: {index_dir}. Run build_embeddings.py.")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        vectors = np.load(index_dir / "vectors.npy", allow_pickle=False)
    except (OSError, ValueError, EOFError) as exc:
        raise RuntimeError(
            f"Semantic index is corrupt or unreadable at {index_dir}: {exc}. "
            "Rebuild with build_embeddings.py --replace.") from exc
    if not isinstance(manifest, dict):
        raise RuntimeError("Semantic index is corrupt: manifest must be an object.")
    if (manifest.get("schema_version") != INDEX_SCHEMA_VERSION or
            manifest.get("text_version") != TEXT_VERSION):
        raise RuntimeError(
            "Semantic index schema/text version is incompatible. Rebuild the index.")
    signature = {"model_id": manifest.get("model_id"),
                 "model_config": manifest.get("model_config")}
    if verify_model and not is_compatible_model(signature):
        raise RuntimeError(
            f"Semantic index model mismatch: stored {signature!r} is incompatible "
            f"with this process's {model_signature()!r}. Rebuild the index.")
    documents = manifest.get("documents")
    if (not isinstance(documents, list) or
            manifest.get("document_count") != len(documents) or
            any(not isinstance(doc, dict) or
                doc.get("entity_type") not in INDEXED_ENTITY_TYPES or
                any(not isinstance(doc.get(key), str) or not doc[key]
                    for key in ("entity_id", "document_id", "content_hash"))
                for doc in documents)):
        raise RuntimeError("Semantic index is corrupt: invalid document metadata.")
    if (not isinstance(vectors, np.ndarray) or vectors.ndim != 2 or
            not np.issubdtype(vectors.dtype, np.floating) or
            not np.isfinite(vectors).all()):
        raise RuntimeError("Semantic index is corrupt: expected a finite 2D float matrix.")
    if vectors.shape[0] != len(documents):
        raise RuntimeError(
            f"Semantic index is corrupt: {vectors.shape[0]} vectors but "
            f"{len(documents)} documents.")
    if vectors.shape[1] != MODEL_CONFIG["dim"]:
        raise RuntimeError(
            f"Semantic index dimension {vectors.shape[1]} does not match model "
            f"dimension {MODEL_CONFIG['dim']}.")
    return {"manifest": manifest, "vectors": vectors, "documents": documents}


class SemanticSearch:
    """Own a read-only DuckDB connection and a loaded vector index.

    Exact identifiers are preferred over ranking (delegated to
    ``KeywordSearch``); otherwise keyword and semantic scores are fused with
    reciprocal rank fusion after deduplicating chunks by entity. A query that
    embeds to the zero vector (no tokens) or matches nothing returns an empty
    list with status ok.
    """

    def __init__(self, db_path=DEFAULT_DB, index_dir=None, verify_model=True):
        self.db_path = Path(db_path).resolve()
        if not self.db_path.is_file():
            raise FileNotFoundError(
                f"Career database not found: {self.db_path}. Run ingest.py first.")
        self.index_dir = (Path(index_dir).resolve() if index_dir
                          else default_index_dir(self.db_path))
        loaded = load_semantic_index(self.index_dir, verify_model=verify_model)
        self.manifest = loaded["manifest"]
        if self.manifest.get("source_db_sha256") != _db_sha256(self.db_path):
            raise RuntimeError(
                "Semantic index database mismatch: index is stale or belongs to a "
                "different database. Rebuild the index.")
        self.vectors = loaded["vectors"]
        self.documents = loaded["documents"]
        self._con = duckdb.connect(str(self.db_path), read_only=True)
        self._keyword = KeywordSearch(self.db_path)
        self._corpora = {}
        self._type_rows = {"role": [], "course": []}
        self._by_entity = {}
        for index, document in enumerate(self.documents):
            self._type_rows[document["entity_type"]].append(index)
            self._by_entity.setdefault(document["entity_id"], document)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def close(self):
        self._con.close()
        self._keyword.close()

    def _query(self, sql, params=()):
        return _query(self._con, sql, params)

    def coverage(self) -> dict:
        """The index coverage report recorded at build time."""
        return self.manifest.get("coverage", {})

    def _corpus(self, entity_type: str) -> dict:
        """entity_id -> live document text/metadata for evidence snippets."""
        if entity_type not in self._corpora:
            if entity_type == "role":
                rows = self._query("""
                    SELECT d.entity_id, d.section, d.text,
                           r.sector, r.track, r.role_title AS title
                    FROM core.search_documents d
                    JOIN core.roles r ON r.role_id = d.entity_id
                    WHERE d.entity_type = 'role'
                """)
            else:
                rows = self._query("""
                    SELECT d.entity_id, d.section, d.text, c.title, c.provider_name
                    FROM core.search_documents d
                    JOIN core.courses c ON c.course_id = d.entity_id
                    WHERE d.entity_type = 'course'
                """)
            self._corpora[entity_type] = {row["entity_id"]: row for row in rows}
        return self._corpora[entity_type]

    def _semantic_ranked(self, query: str, entity_type: str,
                         sector, track) -> list[dict]:
        """Rank documents by cosine similarity, deduplicating chunks by entity.

        Only positive similarities are retained. For roles, explicit sector and
        track filters are applied as hard, reviewable constraints (never as a
        similarity artefact).
        """
        row_indices = list(self._type_rows[entity_type])
        if entity_type == "role":
            sector_norm = sector.strip().lower() if sector is not None else None
            track_norm = track.strip().lower() if track is not None else None
            kept = []
            for index in row_indices:
                document = self.documents[index]
                if sector_norm is not None and (document["sector"] or "").lower() != sector_norm:
                    continue
                if track_norm is not None and (document["track"] or "").lower() != track_norm:
                    continue
                kept.append(index)
            row_indices = kept
        if not row_indices:
            return []
        query_vector = embed_text(query)
        scores = self.vectors[row_indices] @ query_vector
        order = np.argsort(-scores, kind="stable")
        best: dict = {}
        for offset in order:
            score = float(scores[offset])
            if score <= 0:
                continue
            document = self.documents[row_indices[offset]]
            entity_id = document["entity_id"]
            if entity_id not in best or score > best[entity_id]["semantic_score"]:
                best[entity_id] = {"entity_id": entity_id, "document": document,
                                   "semantic_score": score}
        ranked = sorted(best.values(), key=lambda item: -item["semantic_score"])
        for rank, item in enumerate(ranked, start=1):
            item["semantic_rank"] = rank
        return ranked

    def _keyword_ranked(self, query: str, entity_type: str,
                        sector, track) -> list[dict]:
        """BM25-ranked results, deduplicated by entity (highest score first)."""
        results = self._keyword.keyword_results(query, entity_type, sector, track)
        best: dict = {}
        for result in results:
            best.setdefault(result["entity_id"], result)
        ranked = sorted(best.values(), key=lambda item: -item["score"])
        for rank, item in enumerate(ranked, start=1):
            item["keyword_rank"] = rank
        return ranked

    def _hybrid_results(self, query: str, entity_type: str,
                        sector, track, limit):
        semantic = self._semantic_ranked(query, entity_type, sector, track)
        keyword = self._keyword_ranked(query, entity_type, sector, track)
        if not semantic and not keyword:
            return []

        sem_by_id = {item["entity_id"]: item for item in semantic}
        kw_by_id = {item["entity_id"]: item for item in keyword}
        union = sorted(sem_by_id.keys() | kw_by_id.keys())

        fused = []
        for entity_id in union:
            score = 0.0
            if entity_id in sem_by_id:
                score += 1.0 / (RRF_K + sem_by_id[entity_id]["semantic_rank"])
            if entity_id in kw_by_id:
                score += 1.0 / (RRF_K + kw_by_id[entity_id]["keyword_rank"])
            fused.append((entity_id, score))

        fused.sort(key=lambda pair: (
            -pair[1],
            -(sem_by_id.get(pair[0], {}).get("semantic_score", 0.0)),
            pair[0],
        ))

        corpus = self._corpus(entity_type)
        results = []
        for entity_id, fused_score in fused:
            keyword_item = kw_by_id.get(entity_id)
            semantic_item = sem_by_id.get(entity_id)
            record = corpus.get(entity_id, {})
            document = semantic_item["document"] if semantic_item else self._by_entity.get(entity_id, {})
            title = record.get("title") or document.get("title") or entity_id

            evidence = []
            if keyword_item:
                evidence.extend(keyword_item.get("evidence", []))
            section = record.get("section") or document.get("section")
            snippet = _head_snippet(record.get("text") or "")
            if snippet and not any(ev.get("section") == section for ev in evidence):
                evidence.append({"section": section, "snippet": snippet})

            result = {
                "entity_id": entity_id,
                "title": title,
                "score": fused_score,
                "semantic_score": (semantic_item or {}).get("semantic_score"),
                "keyword_score": (keyword_item or {}).get("score"),
                "matched_terms": (keyword_item or {}).get("matched_terms", []),
                "evidence": evidence,
                "exact": False,
            }
            meta = record or document
            if entity_type == "role":
                result["sector"] = meta.get("sector")
                result["track"] = meta.get("track")
            else:
                result["provider_name"] = meta.get("provider_name")
            results.append(result)
            if limit is not None and len(results) >= limit:
                break
        return results

    def search(self, query: str, entity_type: str, sector: str | None = None,
               track: str | None = None, limit: int | None = 10) -> dict:
        """Ranked candidates with entity IDs, fused scores and evidence.

        Exact identifiers are returned first and marked ``exact`` (same
        behaviour as keyword search). Otherwise keyword and semantic scores are
        fused and returned together, deduplicated by entity.
        """
        if entity_type not in INDEXED_ENTITY_TYPES:
            raise ValueError(f"unsupported entity_type: {entity_type!r}")
        exact = [item for item in self._keyword.search(
            query, entity_type, sector, track, limit=None)["results"]
            if item["exact"]]
        if exact:
            return {"status": "ok", "entity_type": entity_type, "query": query,
                    "results": exact[:limit] if limit is not None else exact}
        results = self._hybrid_results(query, entity_type, sector, track, limit)
        return {"status": "ok", "entity_type": entity_type, "query": query,
                "results": results}

    def rank(self, query: str, entity_type: str, filters: dict | None = None,
             limit: int | None = None) -> list[str]:
        """Ranked canonical entity IDs, suitable for ``evaluate_retrieval``."""
        filters = filters or {}
        result = self.search(query, entity_type, sector=filters.get("sector"),
                             track=filters.get("track"), limit=limit)
        return [item["entity_id"] for item in result["results"]]
