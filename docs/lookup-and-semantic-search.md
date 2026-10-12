# Structured Lookup and Semantic Search for SkillsFuture Role Discovery

## 1. Recommendation

Use **structured lookup for exact facts and completeness**, and **semantic search for discovering relevant roles**. An agent selects the appropriate tool, retrieves evidence, and explains the results.

The workbook `jobsandskills-skillsfuture-skills-framework-dataset.xlsx` contains 2,030 roles across 39 sectors. Its explicit role-to-skill relationships make a lookup-first architecture a good fit.

Generating one Markdown document per role is useful for browsing and documentation. Keep structured JSON or database records alongside those documents; do not make the agent parse Markdown for every exact query.

## 2. What each approach does

### Structured lookup

Lookup fetches known records using identifiers or explicit filters:

- Get a role's description and tasks.
- Get every skill required by a role.
- Get a skill's definition, proficiency description, knowledge and abilities.
- Find roles requiring a particular skill code.
- Compare two roles' requirements.

A lookup for Software Engineer returns all 27 recorded skill requirements. A small set of retrieved text chunks may not contain the complete list.

### Semantic search

Semantic search matches meaning rather than just exact words. It helps when a person describes experience or interests without naming a role:

> I build Python APIs, work with SQL, and enjoy backend systems.

This can retrieve roles whose descriptions mention application development, integration or related responsibilities, even if they do not use the same wording.

Search similarity indicates relevance, **not qualification or readiness**.

### RAG

Retrieval-augmented generation means supplying retrieved evidence to an LLM before it answers. Retrieval can use structured lookup, keyword search or vector search; RAG does not inherently require a vector database.

For this project, distinguish exact data tools from semantic discovery tools rather than treating every question as a vector-search request.

## 3. Choosing the right tool

| Question | Recommended method |
|---|---|
| What skills does Software Engineer require? | Resolve role, then structured lookup |
| What does Software Design level 4 mean? | Exact skill lookup |
| Which roles require a particular skill code? | Structured query |
| Compare Associate Software Engineer and Software Engineer | Lookup both records and compare requirements |
| Which roles suit my backend development interests? | Semantic/keyword search, then lookup candidates |
| Find roles involving threat modelling | Keyword/semantic search, then verify tasks |
| Explain these skill requirements simply | Lookup evidence, then LLM explanation |
| Answer questions using external career-guide PDFs | Document retrieval alongside structured framework data |

## 4. Source relationships and data constraints

The role identifier is the combination of **Sector + Track + Job Role**. Titles alone are not unique.

| Source sheet | Purpose | Join |
|---|---|---|
| `Job Role_Description` | Role identity, description and performance expectation | Role identifier |
| `Job Role_CWF_KT` | Critical work functions and key tasks | Role identifier |
| `Job Role_TSC_CCS` | Required skills and proficiency levels | Role identifier; `TSC_CCS Code` |
| `TSC_CCS_Key` | Current skill definitions | `TSC Code` |
| `TSC_CCS_Key_Retired` | Retired skill definitions | `TSC Code` |
| `TSC_CCS_K&A` | Proficiency descriptions and knowledge/ability items | `TSC_CCS Code` |

Observed constraints in the inspected workbook:

- All 2,030 roles have task records.
- 2,001 roles have skill-requirement records; 29 have none recorded.
- Role requirements reference 29 distinct codes missing from the current catalogue and K&A, and absent from the retired catalogue.
- Individual tasks are not explicitly mapped to individual skills.
- The workbook does not explicitly define career progression links.
- Proficiency values include numeric and named scales. Preserve source values.

Use left joins and report missing information explicitly. Do not invent task-to-skill links, replacement codes or promotion pathways.

## 5. Suggested architecture

```text
Excel workbook
      |
      v
Extraction and validation
      |
      +--> Structured JSON / SQLite
      |       +--> Exact lookup, filters and comparisons
      |
      +--> Markdown role profiles
      |       +--> Human-readable documentation
      |
      +--> Concise role search text
              +--> Keyword index
              +--> Embeddings
                       ^
                       |
                 User profile query
                       |
                       v
                 Candidate role IDs
                       |
                       v
                 Structured lookup
                       |
                       v
               Evidence-based answer
```

A possible SQLite schema separates:

- `roles`: ID, sector, track, title, description, performance expectation.
- `work_functions` and `tasks`: responsibilities attached to roles.
- `skills`: code, catalogue status, sector, category, title, definition and dates.
- `role_skill_requirements`: role ID, referenced code, recorded title/type and required level.
- `skill_proficiencies`: code, level and proficiency description.
- `knowledge_ability_items`: code, classification and item text.

Preserve unresolved references rather than rejecting them through a foreign-key constraint. For example, create an unresolved skill placeholder or retain the source reference separately.

Store workbook, sheet and row references where possible so answers can cite their evidence.

## 6. Working with a JSON user profile

Example input:

```json
{
  "current_role": "Junior Software Developer",
  "experience_years": 2,
  "skills": [
    {
      "name": "Python",
      "level": "intermediate",
      "evidence": "Built backend APIs using FastAPI"
    },
    {
      "name": "Software Testing",
      "framework_code": "ICT-DIT-3015-1.2",
      "framework_level": "3",
      "assessment_type": "self_reported",
      "evidence": "Designed automated tests and investigated failures"
    }
  ],
  "interests": ["backend development", "security"],
  "preferences": {
    "people_management": false
  }
}
```

### When a target role is supplied

1. Validate the profile and resolve the role unambiguously.
2. Fetch all target-role requirements.
3. Map personal skills to candidate framework competencies.
4. Compare evidence with the proficiency descriptions and K&A.
5. Explain strengths, possible gaps and missing evidence.
6. Ask follow-up questions where necessary.

Semantic role discovery is optional in this workflow.

### When no target role is supplied

1. Turn skills, experience and interests into search text.
2. Retrieve candidate roles with keyword and semantic search.
3. Apply explicit filters and examine preferences.
4. Look up each candidate's complete profile and requirements.
5. Compare fit and evidence coverage.
6. Explain recommendations and uncertainties.

Do not equate `intermediate` in a personal profile with a numeric framework level. Using PostgreSQL, for example, does not automatically establish Database Administration level 4.

Suggested assessment categories:

- Evidence supports the requirement.
- Possible alignment; verification needed.
- Evidence indicates a gap.
- Unknown; no evidence provided.

A missing profile entry is not proof that the person lacks the skill. Similarity scores must not be presented as readiness percentages.

## 7. Implementing semantic search

### Step 1: Build concise role search text

For each role, include:

- Sector, track and title.
- Job description.
- Work functions and representative task wording.
- Required skill titles.

Example:

```text
Role: Software Engineer
Sector: Infocomm Technology
Track: Software and Applications

Description:
Leads software design, development, testing and implementation projects.

Responsibilities:
Analyse user and business requirements.
Manage software construction and design.
Oversee security provisions and testing.

Required skills:
Applications Development; Software Design; Software Testing;
System Integration; Solution Architecture.
```

This is an illustrative abbreviated search representation, not the full source record. Keep the complete record available through lookup.

Do not embed all K&A items in the initial role-discovery text. They can be lengthy and duplicated across roles. Retrieve them after identifying candidates.

### Step 2: Embed role texts

An embedding model converts text into a numeric vector. Generate one or more vectors per role, retaining the exact role ID and metadata.

For 2,030 roles, local NumPy similarity search is a reasonable starting point; a vector database is not necessary initially.

### Step 3: Embed the profile query

Convert the profile into a factual narrative:

```text
Experience building backend services and APIs using Python and SQL.
Experience writing automated tests.
Interested in backend development and application security.
```

Use the same embedding model and compatible query/document encoding conventions as the role vectors.

Keep hard constraints separate from the narrative. Apply sector filters explicitly. Preferences such as "no people management" require post-retrieval checks; vector search does not reliably enforce negation.

### Step 4: Rank candidates

For normalized vectors, cosine similarity is their dot product. Return the top candidate IDs and search scores.

Example prototype:

```python
import numpy as np
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("all-MiniLM-L6-v2")

# Replace this illustrative input with generated role search records.
roles = [
    {
        "role_id": "example-role-id",
        "search_text": "Role description, responsibilities and skills..."
    }
]

role_vectors = model.encode(
    [role["search_text"] for role in roles],
    normalize_embeddings=True,
)

query = """
Experience building backend services and APIs using Python and SQL.
Experience writing automated tests.
Interested in backend development and application security.
"""

query_vector = model.encode(query, normalize_embeddings=True)
scores = role_vectors @ query_vector

top_k = min(10, len(roles))
top_indices = np.argsort(scores)[::-1][:top_k]

for index in top_indices:
    print(roles[index]["role_id"], float(scores[index]))
```

Install prototype dependencies with `pip install sentence-transformers numpy`. Model loading typically downloads model files the first time. A local model keeps inference local after downloading; a hosted embedding API would require evaluating privacy and data-sharing implications.

This code is a starting point, not an evaluated production ranking system. Model choice and search quality must be tested against representative profiles.

### Step 5: Look up and assess candidates

```python
# Pseudocode: these functions need project-specific implementations.
candidates = semantic_search(profile, top_k=10)

for candidate in candidates:
    role = get_role(candidate["role_id"])
    requirements = get_role_skills(candidate["role_id"])
    # Compare profile evidence with complete recorded requirements.
```

Search discovers candidates; lookup verifies their recorded facts. The agent then explains relevance and uncertainty.

## 8. Indexing and retrieval considerations

- Save role vectors and their ordered role IDs rather than recomputing them on each request.
- Record the embedding model/version, search-text construction version and source checksum.
- Regenerate affected vectors when source content changes; do not mix incompatible embedding models.
- Check model token limits. Shorten text deliberately or split descriptions, tasks and skills into separate vectors rather than silently truncating.
- If indexing multiple chunks per role, group and deduplicate results by role ID before returning candidates.
- Combine keyword retrieval with semantic retrieval. Exact titles, codes and terminology often benefit from keyword matching.
- If shared skill definitions are indexed, keep them as canonical skill records to avoid many identical chunks crowding out useful results.
- Use exact role lookup for requests for complete lists, not just top-k text retrieval.

For richer document RAG, chunks can follow role overviews, individual work functions and individual skills. Each chunk should contain its role/skill identity in text and metadata.

## 9. Suggested agent tools

```text
search_roles(query, sector?, track?)
get_role(role_id)
get_role_tasks(role_id)
get_role_skills(role_id)
get_skill(skill_code)
find_roles_by_skill(skill_code)
compare_roles(role_id_a, role_id_b)
search_framework_text(query, filters?)
```

The agent should:

1. Resolve ambiguous role names before exact comparisons.
2. Fetch full records when completeness matters.
3. Distinguish source facts from inferred fit or recommendations.
4. Ask for evidence rather than guessing proficiency from technology names.
5. Cite source records and report unresolved data.

## 10. Evaluation and rollout

Start with structured extraction, validation, lookup and keyword search. Then add embeddings and evaluate discovery quality.

Test:

- Exact role-name resolution, including titles appearing in multiple tracks.
- Whether relevant roles appear in the top candidates for representative profiles.
- Whether explicit filters and preferences are respected.
- Completeness of skill lists and comparisons.
- Handling of missing requirements and unresolved codes.
- Whether answers cite evidence and avoid unsupported proficiency claims.

Recommendation:

> Lookup for truth and completeness; semantic search for discovery; the agent coordinates both.

## Related local example

The Software Engineer combined profile is available in:

- [Markdown profile](../data/software-engineer-combined.md)
- [Structured JSON](../data/software-engineer-combined.json)

This document describes a proposed architecture. It does not mean all-role extraction, an embedding index or agent tools have already been implemented.
