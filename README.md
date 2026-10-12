# Career data ingestion

Imports the four supplied SkillsFuture Excel workbooks into a local DuckDB
database. This is the data foundation for the career planner; it does not build
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

## Verification

```sh
.venv/bin/python -m unittest discover -s tests -v
```

Tests build small fixture workbooks in a temporary directory. They exercise
one-to-many/unresolved skill mappings, source provenance, duplicate course
selection, null fees, nonnumeric levels, role search text, missing role requirements,
and failed-rebuild protection.

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
