# Human check (Fix 5)

One person, blind to the AI labels. Sample: 25 E2 pairs (stratified), 10 E1 labels. Unsure answers are excluded and counted.

## E2: does the course teach the skill? (person vs AI-judge majority)

| Stratum | in all 186 | checked | agree | agreement |
|---|---|---|---|---|
| unanimous_Y | 85% | 8 | 8 | 100% |
| unanimous_N | 9% | 8 | 8 | 100% |
| split | 6% | 3 | 2 | 67% |

- **Re-weighted agreement (estimate for all 186 pairs): 98%**
- Raw agreement on the sample: 18/19; Cohen's kappa 0.89 (kappa is low when one answer dominates, so read it with the table)
- Unsure: 6
- Person said Y on 8/19; AI majority said Y on 9/19 of the same rows

| Judge | agrees with the person |
|---|---|
| gpt-mini-5 | 19/19 |
| deepseek:deepseek-v4-pro | 17/19 |
| anthropic:claude-sonnet-5-5 | 17/19 |

Disagreements (person vs AI majority):

- row 185: *Workplace Safety and Health* / Practise Workplace Safety & Health for Signalling and Rigging : person **N**, AI Y (split)

## E1: rule-made labels (person agrees?)

| Label kind | checked | agree | disagree | unsure |
|---|---|---|---|---|
| current | 3 | 3 | 0 | 0 |
| acceptable_next | 4 | 4 | 0 | 0 |
| must_not | 3 | 3 | 0 | 0 |

- **Overall: 10/10 rule labels agreed with**
