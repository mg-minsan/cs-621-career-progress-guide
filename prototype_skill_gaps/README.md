# THROWAWAY: Streamlit skill-coverage POC

**Question:** Can a JSON list such as `{"skills": ["data analysis", "python"]}`
produce a useful, reviewable coverage comparison against a recorded target role?
This is a functional prototype, not a production recommendation engine or a
validated skill/proficiency assessment. Keep it separate until the flow is useful.

## Run

From the repository root, install the isolated POC's dependencies once:

```sh
.venv/bin/python -m pip install -r prototype_skill_gaps/requirements.txt
```

Then start it with one command:

```sh
.venv/bin/python -m streamlit run prototype_skill_gaps/app.py --server.address 127.0.0.1
```

Open **http://localhost:8501**. Stop with Ctrl+C. The app reads the existing career
DuckDB (default `data/career-ingested.duckdb`) and optionally the existing
`semantic-index` beside it. Use the sidebar for another database. If no database
exists, prepare it using the repository's documented ingestion command first.
It never changes the database or builds a persistent index.

## Try the flow

1. Paste JSON or upload a `.json` file. Upload takes precedence. The included
   `sample_profile.json` has `data analysis`, `python`, `SQL`, and `communication`.
   Existing profile-schema dictionaries with `name`, evidence, level, and optional
   exact `framework_code` are accepted as well. Supplied levels are retained,
   **not** compared to required framework levels.
2. Enter a target title/description or canonical ID and click **Find roles**.
   Exact-title ambiguities retain every candidate. Unknown targets reuse the
   guide's hybrid role suggestions, with disclosed keyword fallback if the index
   is absent; corrupt/incompatible indexes produce an error, not a silent fallback.
3. Explicitly choose a recorded role. Inspect its description and source records.
4. Review possible skill mappings and optionally confirm them. Apply confirmations
   to update the report; select “Unconfirmed / not listed” and apply to clear one.
5. Inspect the requirement table and evidence, or download the report as JSON.

## What the labels mean

- **matched**: a case-insensitive exact skill title, exact supplied framework code,
  or a user-confirmed mapping. This is self-reported coverage, not proof of mastery.
- **possible_match**: local keyword/vector retrieval found a candidate mapping,
  but the user has not confirmed it. It is not counted as matched.
- **not_listed**: no confirmed or candidate mapping. A candidate learning gap or
  unknown coverage—not proof the user lacks the skill.
- **proficiency = not_assessed**: names alone cannot establish the recorded required
  level. No readiness percentage, funding eligibility, or course recommendations.

For skill names, the POC ranks only the selected role's requirement titles,
definitions, and recorded proficiency descriptions. It combines word-overlap and
project `hash-ngram-v1` vector rankings using reciprocal rank fusion. Up to three
requirements per profile skill are retained, with a heuristic vector threshold of
0.25; exact matches skip approximate matching. This is **not** a validated skill
ontology, deep semantic model, or the persisted role/course index. Python may
produce irrelevant/no mappings; verify the framework definitions rather than
assuming it satisfies programming or data-analysis requirements.

Profile data and confirmations are session-only. Editing the profile or changing
the selected role/database resets confirmations. Role-query edits require another
search. No profile files are saved automatically, and no external model API is
used. Only Download writes a report at your explicit request. Run on localhost;
there is no authentication or production hardening.

## Boundary / verdict

`skill_coverage.py` is pure prototype comparison logic; `app.py` owns UI and
read-only lookups. Production modules and CLI remain unchanged. No automated test
suite is added for throwaway code; validate the interaction using Streamlit's
AppTest plus a local server smoke check. Decide whether name/code coverage and
manual confirmation are useful before promoting or deleting this folder. Durable
prototype tracking: Beads `career-m5z-n1y`.
