# Career Progress Guide (CS621)

L3 "Consultant" agent: profile in, costed career plan out. The agent does the lookups, retrieval and fee maths;
the user makes three judgement calls (confirm role/goal, choose a path, approve the plan).

    python -m pip install -r requirements.txt
    python -m streamlit run app.py      # CAREERGUIDE_LLM=0 forces the offline rule-based ranker
    python tests/test_agent.py          # property / funding / boundary checks

| Stage | Module | Course-week pattern |
|---|---|---|
| 1 Profile -> framework role | `tools.map_role` | table lookup (wk2 tools) |
| 2 Paths (LLM ranks 2-3) | `tools.candidate_paths`, `llm.rank_paths` | lookup + LLM, rule fallback |
| 3 Gaps | `tools.compute_gaps` | set/level comparison |
| 4 Courses | `tools.search_courses` | RAG over descriptions (wk4); TF-IDF stand-in |
| 5 Plan + cost | `graph.plan_node`, `funding.price_courses` | calculator, exact to the cent |

`graph.py` is the LangGraph (wk6): state record, `trace` reducer, `interrupt()` at the three checkpoints,
loop-back for course swaps / changing path. No tool can enrol, pay, apply or edit a profile.

Assumptions to close: data is a hand-built mock slice (the real Skills Framework and 26,099-course directory
are not loaded yet); funding rates in `funding.py` need hand-verification against the SkillsFuture pages
before the E3 eval; the `[x]` pass marks in the proposal are still open.
