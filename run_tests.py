#!/usr/bin/env python3
"""Run the project test suite and an optional end-to-end smoke test.

Examples:
    .venv/bin/python run_tests.py                 # full suite
    .venv/bin/python run_tests.py -v              # verbose test names
    .venv/bin/python run_tests.py test_search.py  # one test file
    .venv/bin/python run_tests.py --smoke         # also exercise the real database

The script re-executes itself under ``.venv/bin/python`` when it exists, so
``python3 run_tests.py`` also works as long as the virtualenv has been created
and populated with ``pip install -r requirements.txt``.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"
DEFAULT_DB = ROOT / "data" / "career-ingested.duckdb"


def run_suite(pattern: str, verbose: bool) -> int:
    """Run unittest discover in a subprocess and return its exit code."""
    command = [sys.executable, "-m", "unittest", "discover",
               "-s", "tests", "-p", pattern]
    if verbose:
        command.append("-v")
    print(f"$ {' '.join(command)}", flush=True)
    if not DEFAULT_DB.is_file():
        print("note: data/career-ingested.duckdb is missing; snapshot tests will "
              "be skipped. Run: .venv/bin/python ingest.py --db "
              "data/career-ingested.duckdb", flush=True)
    return subprocess.run(command, cwd=ROOT).returncode


def smoke() -> int:
    """Exercise lookup, search and evaluation against the real database."""
    if not DEFAULT_DB.is_file():
        print(f"smoke test skipped: {DEFAULT_DB} not found", flush=True)
        return 0

    from lookup import CareerLookup
    from search import KeywordSearch
    from eval_fixtures import FIXTURES, resolve_fixtures, run_lookup_cases
    from evaluate import evaluate_retrieval

    with CareerLookup() as lookup:
        role = lookup.resolve_role("Software Engineer", "Infocomm Technology",
                                   "Software and Applications")
        assert role["status"] == "ok", role["status"]
        print(f"lookup:  Software Engineer -> {len(role['data']['skills'])} skills")

    with KeywordSearch() as search:
        courses = search.search("forklift", "course", limit=3)
        assert courses["results"], "forklift search returned no results"
        print("search:  'forklift' ->",
              [course["title"][:38] for course in courses["results"]])

    resolved = resolve_fixtures(FIXTURES, DEFAULT_DB)
    lookup_checks = run_lookup_cases(resolved, DEFAULT_DB)
    assert all(check["passed"] for check in lookup_checks), lookup_checks

    with KeywordSearch() as search:
        report = evaluate_retrieval(resolved["retrieval_cases"], search.rank, k=5)
    assert len(report["cases"]) == len(FIXTURES["retrieval_cases"])
    print(f"eval:    {len(report['cases'])} retrieval cases scored, "
          f"aggregate keys: {sorted(report['aggregate'])}")

    print("smoke test: OK")
    return 0


def main(argv: list[str]) -> int:
    # Re-exec under the project virtualenv so duckdb/pandas/openpyxl resolve.
    # sys.prefix identifies the venv even when .venv/bin/python is a symlink to
    # the same base interpreter, which a sys.executable comparison would miss.
    venv_root = ROOT / ".venv"
    using_venv = Path(sys.prefix).resolve() == venv_root.resolve()
    if venv_root.is_dir() and not using_venv:
        os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), str(ROOT / "run_tests.py"), *argv])

    parser = argparse.ArgumentParser(
        description="Run the project test suite (and optional smoke test).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    parser.add_argument("pattern", nargs="?", default="test_*.py",
                        help="unittest discover pattern (default: test_*.py)")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="print individual test names")
    parser.add_argument("--smoke", action="store_true",
                        help="also exercise lookup/search/evaluation end-to-end")
    args = parser.parse_args(argv)

    code = run_suite(args.pattern, args.verbose)
    if code == 0 and args.smoke:
        code = smoke()
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
