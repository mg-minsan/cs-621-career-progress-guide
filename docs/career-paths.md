# How career-path search works

The guide maps the user's current job to a SkillsFuture framework role, finds possible next roles, asks an LLM to select suitable options, and lets the user choose a target. A “path” here is a suggested next role, rather than a sequence of jobs through a career ladder.

The lookup and scoring functions are in [lookups.py](../src/lookups.py), the workflow is in [graph.py](../src/graph.py), and the LLM prompts and response schemas are in [llm_steps.py](../src/llm_steps.py).

## Overall flow

1. Search framework role titles using the user's current job title.
2. Ask the LLM to suggest a current-role match and extract target job titles from the user's goal.
3. Pause for the user to confirm or correct the current role and goal titles.
4. Build a next-role shortlist from goal-title matches and shared skills.
5. Ask the LLM to select and explain realistic next roles from that shortlist.
6. Validate the selections and ensure an available goal match is included.
7. Show up to three options with skill-gap counts, then pause for the user's selection.
8. The **skill-gap agent** ([skill_gap_agent.py](../src/skill_gap_agent.py)) calculates the chosen target's skill gaps, labels each as core or supporting with a reason, and orders them. The **course agent** then finds courses for them ([course search](course-search.md)). Both are evaluated on their own in E3.

Unlike course search, role retrieval uses title matching and skill-set overlap. It does not use BM25, embeddings or Reciprocal Rank Fusion.

## Finding the current role

The database `data/careers.db` stores framework roles, their sectors and tracks, and their required skills. `search_roles()` searches this catalogue and returns up to **eight** candidates for the current-role step.

### Title-match score

The underlying `find_roles()` function compares the query against each role title. When a framework role contains alternatives separated by `/`, it scores each alternative and keeps the best score.

```text
title score = 0.5 × character similarity
            + 0.5 × query-word coverage

query-word coverage = number of shared words / number of query words
```

Character similarity uses Python's `SequenceMatcher` on lowercase text. Word matching uses unique alphabetic words, excluding `and`, `of`, `the` and `a`. Scores are rounded to three decimal places. This is a string-match score, not a probability that the role is correct.

`search_roles()` tries the original title and, when different, one variant using these substitutions:

| User wording | Search variant |
|---|---|
| Human resource / human resources | HR |
| AI | Artificial intelligence |
| F&B / food and beverage | Service |
| Restaurant | Outlet |

It keeps each role's best score across variants. If the best title match is at least **0.95**, it returns the highest-scoring matches without adding sector-based matches. Otherwise, queries with at least two words can also match against `sector + role title`, provided a query word matches the sector. This helps find roles whose titles omit their field. Results are sorted by descending score, then role ID.

### LLM interpretation and user confirmation

The LLM sees the profile and the shortlist, including role titles, sectors and match scores. It suggests a current role, gives a confidence and reason, and extracts desired job titles from the user's goal. The prompt asks it to use confidence below 0.6 when candidates are equally plausible. Confidence does not bypass confirmation.

If the model selects an ID outside the shortlist, the code clears that suggestion. The workflow then pauses at `confirm_role`. The user's confirmed role is used for subsequent retrieval, and the user can also correct the extracted goal titles. The backend accepts any existing framework role ID at this checkpoint, including one outside the original shortlist.

## Building the next-role shortlist

The shortlist combines two sources, in this order. The current role is excluded, and duplicate role IDs are removed.

| Source | Retrieval rule |
|---|---|
| Goal matches | For each confirmed goal title, retrieve up to four title matches and retain scores of at least **0.6**. |
| Nearby roles | Add up to eight roles with the highest shared-skill overlap, requiring overlap of at least **0.2**. |

A role found through both sources keeps its `goal` source because goal candidates are inserted first. If there are no candidates, the workflow raises an error rather than inventing a role.

### Shared-skill overlap

`nearby_roles()` compares the current role's skill set with each other role's skill set using **Jaccard overlap**:

```text
overlap = number of skills shared by both roles
          / number of distinct skills across both roles
```

For example, if the current role has `{A, B, C}` and a target has `{B, C, D}`, they share two skills out of four distinct skills:

```text
overlap = 2 / 4 = 0.50
```

This calculation uses framework skill identifiers (`unique_skill`). It ignores proficiency levels when ranking nearby roles and can retrieve roles across sectors.

High overlap suggests transferable skills, but does not establish that a job is a promotion or a realistic next step. Retrieval does not enforce a seniority ladder or use official job-transition edges.

## Selecting and explaining options

The LLM receives the user's profile, confirmed current role, goal titles and candidate roles. Candidate details include sector, retrieval source and overlap where available. The prompt asks for two or three realistic next roles, including the best goal match when one exists, with a short explanation for each.

The structured response allows **one to three** selections, each classified as `goal_match`, `step_up` or `switch`. These classifications and explanations are model judgments; they are not calculated from a validated career ladder. The ranking prompt does not include the detailed skill-gap counts, which are calculated afterwards.

Code applies these checks after the response:

- Drop selections whose role IDs are outside the shortlist.
- If goal candidates exist but none was selected, insert the first retrieved goal candidate at the front with a standard explanation.
- Add skill-gap counts to each displayed option and return at most three options.

There is no fixed weighted formula combining title score, overlap and LLM preference. Title score and overlap build the shortlist; the LLM selects and orders options, followed by the goal-inclusion rule.

## Handling the user's goal

| Status | Meaning |
|---|---|
| `none` | No target job titles were extracted or confirmed. |
| `matched` | At least one goal-title candidate met the retrieval threshold. |
| `not_found` | Goal titles were provided, but none produced a qualifying candidate. Nearby roles are shown with an explanation. |

`matched` means the goal was matched to a framework role. It does not guarantee that the user is qualified, that a vacancy exists, or that the transition is achievable within a particular time.

## Skill gaps and the user's selection

For each displayed target, `skill_gap()` compares its required proficiency levels with those of the confirmed current role. If a skill repeats within a role, the highest recorded level is kept.

A gap is included when the target's required level exceeds the current role's level. Missing or unknown levels are treated as zero for the comparison:

| Situation | Gap label |
|---|---|
| Skill absent from the current role, with a positive target requirement | `missing` |
| Skill present but below the target's required level | `level up` |
| Current level meets or exceeds the target requirement | No gap |

Each option shows the total gap count, number of new skills and number of level-ups separately. Gaps are sorted by required level, then skill identifier.

These are **role-based estimates**: the guide assumes the user's skills match their current framework role. It does not independently assess the user's actual proficiency.

The workflow pauses at `choose_path` for the user to select a target. The backend checks that the selected role exists in the database; it does not restrict this checkpoint to the displayed options. It then computes the target's gaps and searches for courses to address them.
