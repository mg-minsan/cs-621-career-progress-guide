#!/usr/bin/env python3
"""Build the local semantic vector index for role and course discovery.

Reads ``core.search_documents`` from a database built by ``ingest.py`` and
writes a NumPy vector index plus a manifest that records the embedding model,
its configuration, the text-construction version, per-document content hashes
and index coverage. Run this once after ingestion, then query with
``semantic_search.SemanticSearch``.

Examples:
    .venv/bin/python build_embeddings.py
    .venv/bin/python build_embeddings.py --db data/career-ingested.duckdb
    .venv/bin/python build_embeddings.py --replace
"""
from __future__ import annotations

import argparse

from semantic_search import build_semantic_index, default_index_dir
from lookup import DEFAULT_DB


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default=str(DEFAULT_DB),
                        help=f"source database (default: {DEFAULT_DB})")
    parser.add_argument("--index-dir", default=None,
                        help="output index directory (default: <db dir>/semantic-index)")
    parser.add_argument("--replace", action="store_true",
                        help="rebuild an existing index in place")
    args = parser.parse_args(argv)

    report = build_semantic_index(args.db, index_dir=args.index_dir,
                                  replace=args.replace)
    coverage = report["coverage"]
    print(f"index:   {report['index_dir']}")
    print(f"model:   {report['model_id']} (dim={report['dim']})")
    print(f"docs:    {report['document_count']} indexed, "
          f"{coverage['excluded_empty']} excluded empty")
    for entity_type, stats in coverage["by_entity_type"].items():
        print(f"  {entity_type}: {stats['covered_entities']}/"
              f"{stats['source_entities']} entities covered, "
              f"{stats['duplicated_entities']} duplicated, "
              f"{stats['excluded_empty']} empty, "
              f"{stats['missing_entities']} missing")
    print(f"source:  {report['source_db_sha256'][:16]}… (sha256)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
