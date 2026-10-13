#!/usr/bin/env python3
"""Evaluate keyword and hybrid semantic retrieval against the reviewed fixtures.

Runs ``evaluate.evaluate_retrieval`` on ``eval_fixtures.RETRIEVAL_CASES`` twice
— once with the phase-2 keyword retriever and once with the phase-3 hybrid
semantic retriever — and prints the aggregate metrics side by side so the
embedding model's contribution is measurable, not assumed.

Examples:
    .venv/bin/python evaluate_semantic.py
    .venv/bin/python evaluate_semantic.py --index-dir data/semantic-index
"""
from __future__ import annotations

import argparse

from eval_fixtures import FIXTURES, resolve_fixtures
from evaluate import evaluate_retrieval
from search import KeywordSearch
from semantic_search import SemanticSearch
from lookup import DEFAULT_DB


def _aggregate_line(report: dict, entity_type: str) -> str:
    aggregate = report["aggregate"].get(entity_type)
    if aggregate is None:
        return "(no cases)"
    return (f"recall@{report['k']}={aggregate['mean_recall_at_k']:.3f} "
            f"precision@{report['k']}={aggregate['mean_precision_at_k']:.3f} "
            f"MRR={aggregate['mean_reciprocal_rank']:.3f}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default=str(DEFAULT_DB),
                        help=f"source database (default: {DEFAULT_DB})")
    parser.add_argument("--index-dir", default=None,
                        help="semantic index directory (default: <db dir>/semantic-index)")
    parser.add_argument("-k", type=int, default=5,
                        help="top-k used for recall/precision (default: 5)")
    args = parser.parse_args(argv)

    resolved = resolve_fixtures(FIXTURES, args.db)

    with KeywordSearch(args.db) as keyword:
        keyword_report = evaluate_retrieval(
            resolved["retrieval_cases"], keyword.rank, k=args.k)

    with SemanticSearch(args.db, index_dir=args.index_dir) as semantic:
        semantic_report = evaluate_retrieval(
            resolved["retrieval_cases"], semantic.rank, k=args.k)
        coverage = semantic.coverage()

    print("Semantic index coverage:")
    for entity_type, stats in coverage["by_entity_type"].items():
        print(f"  {entity_type}: {stats['covered_entities']}/"
              f"{stats['source_entities']} covered, "
              f"{stats['excluded_empty']} empty, "
              f"{stats['duplicated_entities']} duplicated")
    print()
    print(f"{'metric':8s} {'keyword':>44s} {'semantic':>44s}")
    for entity_type in ("overall", "role", "course"):
        print(f"{entity_type:8s} "
              f"{_aggregate_line(keyword_report, entity_type):>44s}   "
              f"{_aggregate_line(semantic_report, entity_type):>44s}")

    print()
    print("Per-case recall@k:")
    for keyword_case, semantic_case in zip(keyword_report["cases"], semantic_report["cases"]):
        print(f"  {keyword_case['id']:38s} keyword={keyword_case['recall_at_k']:.2f} "
              f"semantic={semantic_case['recall_at_k']:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
