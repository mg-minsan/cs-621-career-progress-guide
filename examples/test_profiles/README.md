# Test profiles

Ten test cases for the agent graph (`src/graph.py`), aimed at role mapping, next-role suggestions,
profile validation, skill gaps and course search. Some cases expect a normal output, some expect an error.

Each case is one JSON file:

| Key | Meaning |
|---|---|
| `description` | What the case tests and why |
| `profile` | The input, in the same shape as `examples/accounts_exec.json` |
| `answers` | Scripted replies to each pause (`ask_missing_info`, `confirm_role`, `choose_path`, `approve_plan`), in order |
| `stop_at` | Optional: stop when the graph reaches this pause instead of answering it |
| `expect.fake` / `expect.real` | What should happen offline (`CAREER_FAKE=1`) and with Claude |

`run_cli.py` cannot script answers, so the cases are played by `src/run_test_profiles.py`.
The list of available checks is in that file's docstring.

## How to run

```
python src/data_prep.py                  # once: builds data/careers.db (git-ignored)

# offline, free, deterministic
CAREER_FAKE=1 CAREER_SEARCH_MODE=bm25 python src/run_test_profiles.py
CAREER_FAKE=1 CAREER_SEARCH_MODE=bm25 python src/run_test_profiles.py 04 07    # only cases starting 04 and 07

# with Claude (about $0.02 a case, needs ANTHROPIC_API_KEY): drop CAREER_FAKE
python src/run_test_profiles.py
```

## The cases and the offline run

Run on 2026-10-19, offline (`CAREER_FAKE=1`, `CAREER_SEARCH_MODE=bm25`). **10 of 10 passed.**

| # | Case | Expected offline | Result |
|---|---|---|---|
| 01 | "Human Resources Executive" (plural), goal HR business partner | Pauses at `confirm_role` with no suggestion, and no Human Resource role in the shortlist. This is today's behaviour, recorded as is: `SYNONYMS` turns it into "hr executive", but the sector fallback needs a word shared with "Human Resource", and "resources" is not "resource". | PASS |
| 02 | "Sales Executive" | The title exists in 4+ sectors, all scoring 1.0. No suggestion, so the user must pick. | PASS |
| 03 | "F&B supervisor" | Role 1056 is the top candidate (1.0), but the runner-up is 0.909, inside the 0.1 margin, so offline there is no suggestion. | PASS |
| 04 | Accounts Executive (14) to Data Analyst (723), full run | Pauses `confirm_role`, `choose_path`, `approve_plan`. `goal_status=matched`, a 12-skill gap, and the run reaches the final message. | PASS |
| 05 | Goal worded "data analyst" (no "into" or "become") | The offline goal regex misses it, so `goal_status=none`. | PASS |
| 06 | Age 22, `credit_balance` 500 (the app's default) | Pauses at `ask_missing_info` (credit entitlement under 25 is $0). Answering `{"credit_balance": 0}` continues to `confirm_role`. | PASS |
| 07 | Same profile, user keeps answering 500 | Error: `Still missing after 3 asks` | PASS |
| 08 | "asdfgh" | No suggestion at `confirm_role`; the best title score is about 0.21. | PASS |
| 09 | Role IDs `999999`, `abc`, `14x` at `confirm_role` | Each reply is re-asked with an "Invalid answer" error. Error: `No valid role confirmed.` | PASS |
| 10 | Arts Educator (role 249, one of 29 roles with no skills data) | Error: `No candidate paths found for this role.` because `nearby_roles` returns nothing and there is no goal. | PASS |

## What these results do and do not show

- The `real` expectations (Claude) have **not** been run. Cases 02, 03 and 05 predict that Claude behaves
  differently from the offline rules (03: suggests 1056; 05: reads the goal as `matched`; 02: confidence under 0.6).
  Those are predictions, not results.
- Cases 01, 05 and 10 record behaviour that may be gaps in the code, not intended design. Each passes because it
  matches what the code does today. If the code is fixed, update `expect`.
- Case 04 checks that a plan is produced and the gap size is right. It does not check course quality or cost.
- Course search never reaches "no strong match" in BM25 mode, so that fallback has no case here.
- These cases do not use the answer keys in `evals/*.json`, which the main README says not to edit.
