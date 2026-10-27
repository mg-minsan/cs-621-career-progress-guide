# E2 AI label provenance

- Date: 2026-10-18 (Asia/Singapore).
- Labeller: Codex assistant in this conversation, reviewing each supplied course–skill pair; these are AI judgments, not human annotations.
- File: `labels/E2_labeller_gpt-mini-5.xlsx` (formerly `E2_labeller_AI.xlsx`; renamed using the user's supplied model name), sheet `labels`, 186 rows. Each row has a `Y`/`N` relevance judgment and a reason in `notes`. The filename change does not independently verify the generating model or change the annotation provenance recorded above.
- Evidence: the existing sheet's skill name, skill description, course title and course text. Course text is the generator's 600-character excerpt; no external course pages were consulted.
- Rule: `Y` when the supplied text establishes that the course teaches a meaningful part of the described skill. `N` for a different subject, a passing mention, or insufficient evidence. Topic match only; ignore price, reputation, course level and eligibility/accreditation restrictions.
- Interpretations: Ethical Culture is assessed against the supplied financial-market-conduct description; generic professional ethics alone is insufficient. Generic dashboards or financial accounts alone do not establish sustainability impact reporting. Generic AI tool use alone does not establish technical AI integration.
- Missing input: rows 43–53 have no skill description for Data-mining and Modelling. These judgments use the skill title and explicit data-mining/modelling content; each reason flags this limitation.
- Labels were assigned before inspecting the resulting search-mode scores and were not revised to improve any mode's results.
- A and B human relevance cells remain blank. The existing 50-row sample was marked using `src/e2_sample.py`; two independent reviewers still need to fill those rows without seeing the AI answers.
- `src/score_e2.py` completed successfully and saved `results/e2_results.json`. Current metrics use AI judgments only; human agreement is unavailable until those labels exist.
