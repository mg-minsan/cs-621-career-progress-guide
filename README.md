# Career data ingestion, lookup and role exports

Imports the four supplied SkillsFuture Excel workbooks into a local DuckDB
database, provides read-only structured lookup, and exports source-backed role
profiles. This is the data foundation for the career planner; it does not build
a chatbot, infer user skills, extract PDF arrows, or calculate funding eligibility.

## Run

Use Python 3.10 or later:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python ingest.py
```

The default input folder is the folder containing `ingest.py`. Outputs:

- `data/career.duckdb`
- `data/career.quality.json`

For another location:

```sh
.venv/bin/python ingest.py --input-dir /path/to/workbooks --db data/career.duckdb
```

An existing database is protected by default. To rebuild, close database readers
and pass `--replace`. The script builds and checks a temporary database before
replacing the destination; failures during loading or validation preserve the
previous database. Rebuild replaces the entire database, including any manually
added transitions. Keep curated transitions in a separate source file before
rebuilding. This is a local, single-writer ingestion script.

## Tables

`raw` contains nine imported data sheets. Column headers are converted to
snake_case, while cell values are stored as source text (Excel cell formatting
is not retained). `source_file`, `source_sheet`, and `source_row` identify the
original Excel location. Formula text, if present, is preserved rather than
executed. Legend sheets are documentation and are not loaded.

`core` contains:

| Table | Key / purpose |
| --- | --- |
| `roles` | Stable SHA-256 ID derived from sector, track and role title |
| `role_skills` | Role, framework skill code and required level |
| `framework_skills` | Framework definitions; missing active definitions explicitly flagged |
| `skill_proficiency` | Framework skill code + original level label |
| `skill_knowledge_abilities` | Knowledge and ability items per code and level |
| `unique_skills` | Common skill IDs and descriptions |
| `skill_mappings` | Every mapping row; multiple mappings retained |
| `role_tasks` | Work functions and tasks per role |
| `courses` | One selected source row per course ID |
| `career_transitions` | Empty table reserved for reviewed PDF transitions |
| `source_records` | Links entity IDs to all contributing source rows |
| `search_documents` | Role descriptions/tasks/requirements, course and skill-proficiency text with IDs and content hashes |

`audit.sources` records source file hashes and row counts. Audit views expose
duplicate courses, one-to-many mappings and quality warnings. The JSON report
contains raw/core counts, integrity checks and warnings. Warnings are not proof
that recommendations are accurate; review them before using affected records.

## Cleaning decisions

- Trim text and remove Excel `_x000D_` escapes only in `core`.
- Do not interpret literal source strings such as `No mapping` as null.
- Keep original proficiency labels; a separate numeric column is populated only
  where conversion is valid. `Basic`, `Intermediate` and `Advanced` are not
  automatically equated with numeric levels.
- Framework skill codes can encode proficiency/version information. Do not
  compare codes alone to find cross-level gaps, or strip code suffixes blindly.
- Resolve mapping titles to unique skill IDs only when a case-insensitive,
  trimmed title has one match. Unresolved mappings have a null ID and status.
- Deduplicate courses by selecting a whole row with the most populated learning
  outcomes, entry requirements and valid subsidised fee; ties use the first
  source row. Keep all variants in `raw.courses`. Conflicting identities or fees
  need review; no assumption is made that the selected row is the newest.
- Fees are `DECIMAL(18,6)`, hours are numeric, and missing values stay null.
  Listed subsidised prices are not personalised quotes. GST is not inferred.
- Ratings and other source fields remain available in raw even when they are
  not used in the initial core course table.
- PDFs and profiles are not loaded. No course-to-skill links are invented.
- `search_documents` is retrieval-ready text, not a search index. Add embeddings
  and keyword retrieval later. Use source links to cite the original records;
  for a deduplicated course, `selected_source_row` identifies the displayed row.

## Query examples

```python
import duckdb

with duckdb.connect("data/career.duckdb", read_only=True) as db:
    print(db.execute("""
        SELECT r.role_title, s.source_skill_title, s.required_level
        FROM core.roles r
        JOIN core.role_skills s USING (role_id)
        WHERE r.sector = ? AND r.role_title = ?
        ORDER BY s.source_skill_title
    """, ["Financial Services", "Account Operations Analyst"]).fetchall())

    print(db.execute("SELECT * FROM audit.quality_summary").fetchall())
```

## Read-only lookup

`lookup.py` provides a `CareerLookup` context manager. It defaults to
`data/career-ingested.duckdb`; pass an explicit path for any other database.
It never creates or rebuilds a database. To prepare the default database:

```sh
.venv/bin/python ingest.py --db data/career-ingested.duckdb
```

```python
from lookup import CareerLookup

with CareerLookup() as lookup:
    result = lookup.resolve_role(
        "Software Engineer", sector="Infocomm Technology",
        track="Software and Applications",
    )
    if result["status"] == "ok":
        role = result["data"]
        print(role["role_id"], len(role["skills"]))  # 27 in supplied workbooks
        print(role["tasks"])  # separate from skills, never a Cartesian join
        requirement = role["skills"][0]
        skill = lookup.get_skill(
            requirement["framework_skill_code"], requirement["required_level"],
        )
        print(skill["data"]["proficiencies"])
    elif result["status"] == "ambiguous":
        print(result["data"])  # candidate IDs, sectors and tracks; ask the user
```

| Method | Result in `data` |
|---|---|
| `search_role_names(query, sector=None, track=None)` | All literal, case-insensitive title substring matches; empty query lists all roles |
| `resolve_role(title, sector=None, track=None)` | Full role on one exact title match, or all candidates on ambiguity |
| `get_role(role_id)` | Description, performance expectation, separate `tasks` and `skills` lists |
| `get_role_tasks(role_id)` | Every recorded task with per-task source rows |
| `get_role_skills(role_id)` | Every requirement, original/numeric level, definition/proficiency text and gap flags |
| `get_skill(framework_skill_code, level=None)` | Definition, available original level labels, selected/all proficiencies and K&A items |
| `get_course(course_id)` | Selected whole course record with exact fees and selected source row references |
| `compare_roles(role_id_a, role_id_b)` | Both full roles, shared requirements, code-only-in-one-role requirements, and unassessed differing level labels |
| `get_source_records(entity_type, entity_id)` | All contributing spreadsheet rows, enriched with file SHA-256 hashes |

### Result contract

All methods return a dictionary with `status`, `data`, `missing_data` and
`source_records`:

- `ok`: the lookup succeeded. Existing roles without recorded tasks or skills
  return empty lists and `tasks` / `skill_requirements` missing-data flags.
  This is not evidence that those roles need no skills.
- `not_found`: unknown role, course or skill identifiers return `data=None`.
  Name search instead returns `ok` with an empty list on no matches. Source
  lookup returns `not_found` with an empty list when no source links exist.
- `ambiguous`: exact-title resolution returns every candidate; use sector and
  track to disambiguate. Substring search never silently selects a role.
- `missing_data`: field names or coverage flags. Inspect nested task,
  requirement and proficiency flags as well as top-level flags. A known skill
  code with an unrecorded requested level remains `ok`, with empty
  `proficiencies` and a `requested_proficiency` flag.
- `source_records`: contributing source file, sheet, row, entity IDs and hash.
  Task/name/requirement entries also retain their own source rows. Requirement
  text has separate `definition_source_records` and
  `proficiency_source_records`. Course `selected_source_records` identifies the
  displayed variant; other variants remain in the top-level source list.

IDs and level labels are exact. Only title search/resolution and sector/track
filters trim input and match case-insensitively; `%` and `_` are literal search
characters. Fees stay `decimal.Decimal` and skill update dates stay Python
`date` objects. When serialising later, use decimal strings and ISO dates rather
than converting fees to floating-point numbers.

Role comparison uses exact framework codes and original level labels. A shared
requirement has the same code and label. `only_a` / `only_b` mean the code is
absent from the other role; `different_levels` retains both sets of labels with
`comparison_status="not_assessed"`. Named levels are not equated to numbers,
code suffixes are not stripped, and no readiness or promotion claim is made.

Missing database files raise `FileNotFoundError`; invalid/incompatible databases
raise DuckDB errors. All queries use bound input parameters and the connection
is opened read-only and closed when the context exits. Close readers before
rebuilding the database.

## Keyword search

`search.py` provides `KeywordSearch`, a read-only BM25 keyword search over the
retrieval-ready `core.search_documents` text: role descriptions, tasks and
required skills for roles; titles, descriptions and learning outcomes for
courses. Exact identifiers are preferred over ranking — an exact role ID or
title, or an exact course reference number or title, short-circuits the search.

```python
from search import KeywordSearch

with KeywordSearch() as search:
    roles = search.search("software testing", "role",
                          sector="Infocomm Technology", limit=10)
    courses = search.search("forklift", "course", limit=10)
    course_ids = search.rank("forklift", "course")  # ids only, for evaluation
```

`search(...)` returns a status envelope whose `results` list carries each
entity's canonical ID, BM25 score, matched query terms and per-section evidence
snippets. Exact matches are flagged `exact` and come first. `rank(...)` returns
just the ranked canonical IDs, matching the `retrieve` contract used by
`evaluate.evaluate_retrieval`. Fetch complete facts and source records with
`CareerLookup` (`get_role` / `get_course`) rather than parsing the snippets.
Scores are relevance signals, never readiness or suitability.

## Role profile exports

`export_roles.py` uses `CareerLookup` to export **every role**, including roles
with no recorded skill requirements. It enriches each requirement with the
matching skill definition, exact recorded proficiency and knowledge/ability
items. Work functions/tasks and skill requirements remain separate lists.

```sh
.venv/bin/python export_roles.py
# Or use another database/output location:
.venv/bin/python export_roles.py --db data/career-ingested.duckdb --output-dir data/role-profiles-new
```

Defaults: database `data/career-ingested.duckdb`, output `data/role-profiles/`.
The output directory contains:

```text
manifest.json
roles/<full-role-id>.json
roles/<full-role-id>.md
```

Full canonical role IDs are used as filenames, not titles or slugs, so duplicate
titles and special characters cannot collide or become filesystem paths. The
manifest retains the title, sector and track for browsing. It links each ID to
relative JSON/Markdown paths, output-file SHA-256 hashes, source-workbook hashes,
list counts and role-level missing-data flags. It also records the source
DuckDB file's SHA-256 hash and the export schema version.

Each JSON document preserves the lookup envelope (`status`, `data`,
`missing_data`, `source_records`) with `schema_version: 1`. In
`data.skills`, each requirement adds `skill_details`, the full result of
`get_skill(code, required_level)`. All nested provenance and missing-data flags
are retained. Dates become ISO strings, decimals become exact decimal strings,
and nulls remain null. Markdown includes the same recorded responsibilities,
requirements, matching proficiency/K&A text, missing-data disclosures, and
source-row/hash footnotes. Source text is escaped rather than interpreted as
Markdown instructions or HTML; JSON retains the original cleaned text.

To find a profile without guessing its filename:

```python
import json
from pathlib import Path

root = Path("data/role-profiles")
manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
entry = next(role for role in manifest["roles"]
             if role["role_title"] == "Software Engineer"
             and role["sector"] == "Infocomm Technology"
             and role["track"] == "Software and Applications")
print(root / entry["markdown_path"])
profile = json.loads((root / entry["json_path"]).read_text(encoding="utf-8"))
print(len(profile["data"]["skills"]))  # 27 in the supplied workbooks
```

Existing output paths (including files, empty directories and symlinks) are
protected. Choose a different `--output-dir` to regenerate. This local tool
assumes one writer per output path. It builds in a temporary sibling directory,
checks that the database did not change, and publishes the completed directory;
a failed export leaves no visible partial output. Identical unchanged database
inputs produce byte-identical documents and manifests. Do not rebuild or replace
the database during export.

The verified full export contains **2,030 JSON and 2,030 Markdown profiles**,
covering all 40,379 task records and 44,535 requirements, with 29 roles explicitly
flagged as lacking recorded requirements. Files under `data/` are gitignored;
regenerate them after a fresh checkout. Full profiles include repeated skill
text and provenance and currently occupy about 1.7 GB; they are browsing/evidence
outputs, not deliberately bounded embedding inputs or an authoritative pathway.

## Evaluation fixtures

`eval_fixtures.py` holds a small, reviewed evaluation set; `evaluate.py` scores
it. Retrieval relevance and recommendation quality are measured separately, so
the set is split:

- `lookup_cases`: exact lookup and title ambiguity pinned against the database
  (`resolve_role` expectations), with a self-check via `run_lookup_cases`.
- `retrieval_cases`: representative natural-language queries (role discovery and
  course search) with the entities a correct system should surface.
- `recommendation_scenarios`: realistic profiles with the properties a correct
  recommendation must satisfy — citations on every claim, uncertainty for
  missing evidence, budget/language constraints, prerequisite handling, and no
  invented readiness, funding or transition claims.

Entity references use human-readable keys (sector + track + title for roles,
SkillsFuture course reference number for courses); `resolve_fixtures` turns them
into the canonical IDs produced by `lookup.py`.

```python
from eval_fixtures import FIXTURES, resolve_fixtures
from evaluate import evaluate_retrieval, check_recommendation

resolved = resolve_fixtures(FIXTURES, "data/career-ingested.duckdb")

# retrieve(query, entity_type, filters) returns ranked canonical IDs.
report = evaluate_retrieval(resolved["retrieval_cases"], retrieve, k=5)

checks = check_recommendation(
    resolved["recommendation_scenarios"][0], recommendation)
```

`evaluate_retrieval` reports recall@k, precision@k and mean reciprocal rank per
entity type (role/course). `check_recommendation` validates a recommendation
output against its scenario: required sections, citation accuracy, allowed
assessment labels, budget/language constraints, prerequisite uncertainty and
absence of fabricated claims.

## Verification

```sh
.venv/bin/python run_tests.py        # full suite
.venv/bin/python run_tests.py --smoke  # + end-to-end smoke test
.venv/bin/python -m unittest discover -s tests -v  # equivalent, verbose
```

Tests build small fixture workbooks in a temporary directory. They exercise
one-to-many/unresolved skill mappings, source provenance, duplicate course
selection, null fees, nonnumeric levels, role search text, missing role requirements,
and failed-rebuild protection. Lookup tests also verify complete lists, title
ambiguity, exact code/level comparisons, parameterised input, fee precision,
per-item provenance, missing records and read-only database protection. Export
fixtures verify complete profiles, K&A evidence, missing-data disclosures,
safe filenames, escaped Markdown, source citations, deterministic output,
file hashes, existing-output protection and failure cleanup.

If `data/career-ingested.duckdb` exists, a snapshot test checks that Software
Engineer returns all 27 requirements with provenance. If the full role export
also exists, another snapshot test checks manifest coverage and the Software
Engineer export. These checks are otherwise skipped. The fixture tests do not
require the supplied large workbooks or generated exports.

## Verified ingestion snapshot

A fresh import of the supplied workbooks is available in
`data/career-ingested.duckdb`, with its report in
`data/career-ingested.quality.json`. The pre-existing `data/career.duckdb` was
not overwritten. Reproduce the fresh import at another path with:

```sh
.venv/bin/python ingest.py --db data/career-ingested.duckdb
# If that output already exists, close readers and add --replace.
```

The verified import contains 2,030 roles, 44,535 role-skill requirements,
26,099 distinct course IDs from 26,782 course rows, and 40,136 retrieval-ready
text records. All eight integrity checks passed; six fixture tests passed.

Source-quality warnings include 29 roles without skill requirements, 29
requirements without proficiency details, 103 codes with multiple skill mappings,
67 unresolved mapping rows, 2,817 courses without entry requirements, 10 without
learning outcomes, and 44 without listed subsidised fees. Raw variants and source
locations remain available for review. No embeddings, course-to-skill mappings,
profile assessments or all-role Markdown exports are generated by this step.
