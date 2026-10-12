# SkillsFuture Career and Course Recommendation — Implementation Plan

## Goal

Create a guide based on a user's interests, experience, skills and constraints that:

1. Suggests relevant career directions.
2. Explains each role's recorded responsibilities and requirements.
3. Identifies learning priorities and areas needing further assessment.
4. Recommends SkillsFuture courses with supporting learning-outcome evidence.
5. Suggests a practical learning sequence and projects to demonstrate skills.

Recommendations must distinguish source facts from inferred matches. The system must not invent formal career transitions, proficiency assessments or personalised funding eligibility.

## Current status

### Completed

- Verified ingestion of four supplied Excel workbooks using `ingest.py`.
- Preserved raw records, cleaned lookup tables, source row references and file hashes.
- Built retrieval-ready role, course and skill-proficiency text.
- Added role tasks and skill requirements to role search text.
- Generated a quality report and passed eight integrity checks and six fixture tests.
- Exported JSON and Markdown profiles for all 2,030 roles, including the
  Software Engineer profile and all 29 roles without recorded requirements.
- Added an export manifest with canonical IDs, relative paths, output/source
  hashes, counts and missing-data flags; verified full task/requirement coverage.
- Implemented read-only structured lookup and role comparisons in `lookup.py`,
  including explicit title ambiguity, source references and missing-data flags.
- Verified Software Engineer lookup returns all 27 requirements; lookup tests
  cover complete lists, ambiguity, provenance, missing records and read-only access.
- Created a small, reviewed evaluation fixture set (exact lookup, role
  ambiguity, interest-based role discovery, course relevance, evidence versus
  proficiency expectations, missing data and citation accuracy) with a
  retrieval-metric harness and a recommendation-quality checker.
- Implemented the role and course keyword search baseline in `search.py` using
  BM25 over retrieval-ready text, with exact identifiers preferred over ranking
  and sector/track filters for roles; results carry entity IDs and evidence.

### Verified outputs

| Output | Location |
|---|---|
| Fresh database | `data/career-ingested.duckdb` |
| Quality report | `data/career-ingested.quality.json` |
| Ingestion implementation | `ingest.py`, `sql/build_core.sql` |
| Ingestion tests | `tests/test_ingest.py` |
| Read-only structured lookup | `lookup.py` |
| Lookup tests | `tests/test_lookup.py` |
| Role exporter | `export_roles.py` |
| Export tests | `tests/test_export_roles.py` |
| All-role export manifest | `data/role-profiles/manifest.json` |
| Role JSON/Markdown profiles | `data/role-profiles/roles/<role_id>.json`, `.md` |
| Evaluation fixtures | `eval_fixtures.py` |
| Evaluation harness | `evaluate.py` |
| Evaluation tests | `tests/test_eval_fixtures.py`, `tests/test_evaluate.py` |
| Keyword search | `search.py` |
| Search tests | `tests/test_search.py` |

The pre-existing `data/career.duckdb` was not overwritten. Subsequent tools should accept an explicit database path and use the fresh database by default.

### Not yet implemented

- Agent tools (the Python structured lookup API is implemented).
- Embedding indexes and semantic retrieval.
- User profile assessment.
- Validated course-to-skill associations.
- Recommendation agent or generated career guides.

## Architecture

```text
User JSON profile
       |
       v
Validation and clarification
       |
       +--> Known target role --> Exact role lookup
       |
       +--> No target role --> Role keyword/semantic search
                                      |
                                      v
                              Candidate role lookup
                                      |
                                      v
                         Evidence-based learning priorities
                                      |
                                      v
                          Course keyword/semantic search
                                      |
                                      v
                      Exact course lookup and constraint checks
                                      |
                                      v
                         Personalised guide with citations
```

Structured lookup supplies complete facts. Search discovers candidates. The agent explains evidence and asks follow-up questions.

## Phase 1 — Structured lookup and profile exports

### Work

Create a small Python data-access layer with parameterised queries and read-only connections:

```text
search_role_names(query, sector?, track?)
get_role(role_id)
get_role_tasks(role_id)
get_role_skills(role_id)
get_skill(framework_skill_code, level?)
get_course(course_id)
compare_roles(role_id_a, role_id_b)
get_source_records(entity_type, entity_id)
```

- Return stable IDs, source references and explicit missing-data statuses.
- Resolve titles using sector and track when ambiguous.
- Fetch every requirement for complete-list questions.
- Preserve original level labels; do not equate named and numeric scales.
- Do not interpret different framework codes as comparable levels without a validated relationship.
- Export one structured JSON and Markdown document per role using database records.
- Include an export manifest linking role IDs to paths and source hashes.
- Use filesystem-safe paths and collision-resistant names; do not replace database role IDs with slugs.
- Avoid task-by-skill Cartesian joins. Keep work functions/tasks and requirements as separate collections.

### Acceptance criteria

- Software Engineer lookup returns all 27 recorded skill requirements.
- All 2,030 roles can be exported, including roles without requirements.
- Unknown IDs return a clear not-found result.
- Ambiguous role titles do not silently select a role.
- Exports and lookup results retain source references and missing-data flags.
- Tests verify complete lists, source references, ambiguity and missing records.

## Phase 2 — Keyword search baseline

### Work

- Implement keyword search over role descriptions, tasks and requirements.
- Implement keyword search over course titles, descriptions and learning outcomes.
- Return entity IDs, ranked candidates and matching evidence.
- Support explicit filters when the underlying data permits them.
- Prefer direct lookup for exact course references, role IDs and skill codes.
- Keep prerequisites and user preferences available for later checks, rather than treating text similarity as eligibility.

### Acceptance criteria

- Exact titles and identifiers resolve correctly.
- Relevant task and learning-outcome text is discoverable.
- Results can be looked up and cited without parsing generated Markdown.
- A small set of representative queries forms an initial retrieval evaluation set.

## Phase 3 — Semantic search

### Work

- Choose and evaluate an embedding model.
- Build bounded, intentional search representations for roles and courses.
- For role discovery, use descriptions, work functions, tasks and skill titles; avoid embedding every K&A item into one oversized document.
- For course discovery, prioritise titles, descriptions and learning outcomes.
- Preserve prerequisites as structured evidence for constraint checking; prerequisites are not evidence that a course teaches a skill.
- Check model token limits and split content at natural boundaries when needed.
- Store vectors with entity IDs, document IDs, content hashes, model/version and text-construction version.
- Start with local vector files and NumPy ranking; adopt a vector database only if requirements justify it.
- Combine keyword and semantic retrieval; deduplicate chunks by entity before candidate selection.
- Keep search scores separate from suitability or readiness assessments.

### Acceptance criteria

- Identical model/configuration is used for compatible query and document embeddings.
- No silent truncation or incompatible vector mixing occurs.
- Index coverage and excluded/empty records are reported.
- Representative profile and course queries retrieve relevant candidates.
- Every result resolves to an exact record and supporting source evidence.

## Phase 4 — User profile interpretation and learning priorities

### Profile fields

Accept a JSON profile containing some or all of:

- Interests and preferred activities.
- Experience and project evidence.
- Skills, assessment method and claimed proficiency.
- Current role and optional target role.
- Budget, available study time and language preferences.
- Qualifications relevant to course prerequisites.

Do not require unnecessary sensitive personal data. If a hosted model is used, define what profile data may be sent and how consent, storage and retention are handled.

### Work

- Define and validate the profile schema.
- Separate supplied facts, self-reported claims and inferred competency matches.
- Use explicit framework codes where valid; otherwise propose candidate mappings from evidence.
- Retrieve complete role requirements before assessing priorities.
- Compare evidence against level-specific descriptions and K&A.
- Ask follow-up questions when evidence or constraints are insufficient.
- Label requirements as supported, potentially aligned, evidenced gap or unknown.
- Offer several plausible career directions when no target is supplied.
- Inspect management/leadership responsibilities against preferences; vector search does not reliably enforce negation.

### Acceptance criteria

- Missing profile evidence is not treated as proof of a missing skill.
- Technology names and years of experience do not automatically establish framework levels.
- No readiness percentage is generated without a defined and validated method.
- Recommendations include role evidence and uncertainty.
- Formal promotion paths are not inferred from role-title similarity.

## Phase 5 — Course matching and recommendation

### Important source limitation

The supplied course directory has no explicit framework skill code or unique skill ID. Course-to-skill matches must therefore be inferred from descriptions/outcomes, reviewed, or supplied by an authoritative external mapping.

### Work

- Search courses using specific learning priorities rather than only a role title.
- Retrieve exact course records for shortlisted candidates.
- Compare learning outcomes with the relevant competency expectations.
- Record why each course matches and which outcomes support that conclusion.
- Distinguish authoritative mappings, reviewed mappings and model-inferred matches.
- Evaluate prerequisites, language, recorded duration, commitment and cost against supplied constraints.
- Report unknown eligibility or missing prerequisites rather than guessing.
- Use ratings only as supporting signals, with respondent counts where available.
- Avoid redundant recommendations and explain partial coverage.
- Store inferred associations separately from source tables, with evidence, model/configuration and review status.

### Acceptance criteria

Each recommended course includes:

- Course reference, title and provider.
- Learning priority addressed.
- Supporting learning-outcome evidence and source reference.
- Prerequisite assessment: appears satisfied, unmet or unknown.
- Recorded hours, commitment, language and available fees.
- Missing information and required verification.

Completion of a course is not presented as proof of framework proficiency. Availability, current fees and subsidy eligibility must be verified before enrolment. Listed subsidised fees are not personalised quotes.

## Phase 6 — Agent workflow and guide generation

### Work

- Expose narrow lookup/search tools to the agent.
- Define tool-result schemas and consistent errors.
- Use deterministic queries for complete lists, numeric filters and known identifiers.
- Use retrieval for exploratory questions and explanatory evidence.
- Treat retrieved text as data, not instructions.
- Generate a structured guide first, then render Markdown.
- Cite source records for factual claims.
- Explain suggested learning order without claiming it is an official pathway.

### Guide sections

1. User goals and assumptions.
2. Candidate career directions and reasons.
3. Current strengths supported by evidence.
4. Learning priorities and assessment questions.
5. Recommended courses with constraints and evidence.
6. Suggested sequence and practical projects.
7. Uncertainties, verification steps and next actions.

### Acceptance criteria

- An end-to-end profile produces a traceable guide.
- Every recommended course exists in the ingested data.
- Requirements and fees come from lookup, not model memory.
- Unknown information remains explicitly unknown.
- The system asks clarifying questions when an actionable guide cannot be supported.

## Optional layer — Unique skills

The unique-skills list and mapping workbook are already ingested. Use them when they improve cross-sector normalisation or skill-centric discovery; they are not prerequisites for the first end-to-end prototype.

- Use `skill_id` for canonical identity and retain the version-specific transaction ID.
- Preserve all mapping rows, including one-to-many relationships.
- Keep unresolved titles unresolved until reviewed.
- Do not automatically transfer proficiency through a unique-skill match.
- Evaluate unique-skill matching against direct learning-priority-to-course matching.

Adding this layer does not create an authoritative course-to-skill mapping.

## Known data-quality considerations

The verified ingestion report includes:

| Issue | Count | Handling |
|---|---:|---|
| Roles without skill requirements | 29 | Preserve; disclose missing coverage |
| Role requirements without proficiency details | 29 | Do not invent proficiency expectations |
| Framework codes with multiple mappings | 103 | Retain mappings; inspect context |
| Unresolved mapping rows | 67 | Flag for review |
| Courses without entry requirements | 2,817 | Eligibility remains unknown |
| Courses without learning outcomes | 10 | Lower confidence in learning coverage |
| Courses without listed subsidised fees | 44 | Do not substitute zero |
| Duplicate course IDs in raw data | 679 | Preserve variants; use documented row-selection policy |

The cleaned course table contains 26,099 course IDs from 26,782 raw rows. Selected rows are not assumed to be the latest versions.

## Evaluation strategy

Maintain a small, reviewed test set covering:

- Exact lookup and role ambiguity.
- Interest-based role discovery.
- Profile evidence versus proficiency expectations.
- Course relevance and supporting outcomes.
- Prerequisite and budget uncertainty.
- Missing data, multiple mappings and duplicate source records.
- Citation accuracy and unsupported claims.

Measure retrieval relevance separately from recommendation quality. Review outputs with realistic profiles before expanding automation. The reviewed set and harness are implemented in `eval_fixtures.py` and `evaluate.py`; keyword and semantic retrieval score against `retrieval_cases`, while the recommendation agent is checked against `recommendation_scenarios`.

## Immediate next step

Phase 1 lookup and role exports, the reviewed evaluation fixtures and the
role/course keyword search baseline are implemented. Next is the user profile
schema and semantic retrieval, then a small end-to-end example before
investing in embeddings or a full agent.

## Related documents

- [Ingestion README](../README.md)
- [Lookup and semantic search](lookup-and-semantic-search.md)
- [Software Engineer profile](../data/role-profiles/roles/5ad023c4773fd21abc6e010292d435b76a4bca2189f3ad254ff39d836510c314.md)
- [Role export manifest](../data/role-profiles/manifest.json)
