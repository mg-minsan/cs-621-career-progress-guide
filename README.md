# Career Progress Guide 🧭

**CS621 Agentic AI project.** Type in your job, age, residency and goal → the agent finds realistic next
roles in Singapore's SkillsFuture framework, the skills you are missing, real courses, and what they cost
**you** after subsidies and SkillsFuture Credit. You decide at every checkpoint (confirm job → choose path
→ approve plan). Built with LangGraph + Claude Sonnet + Streamlit.

---

## Quick start (teammates)

### Option A: Docker (recommended, same on every laptop)

You need [Docker Desktop](https://www.docker.com/products/docker-desktop/) running.

```bash
git clone <this-repo-url>
cd <repo-folder>              # the folder git just created
cp .env.example .env          # Windows PowerShell: copy .env.example .env
# open .env and paste YOUR Anthropic API key (or leave it: the app runs in free offline mode)
docker compose up --build
```

Open **http://localhost:8501**.

- The **first build takes ~5 min** (it installs packages, builds the database and downloads two small models).
  After that, `docker compose up` starts in seconds.
- Stop with `Ctrl + C`. Rebuild after pulling new code: `docker compose up --build`.

### Option B: Python on your laptop (no Docker)

Python 3.12 or 3.13.

```powershell
# Windows
powershell -ExecutionPolicy Bypass -File setup.ps1     # one time, 15-25 min
.\.venv\Scripts\Activate.ps1
streamlit run src/app.py
```
```bash
# Mac / Linux
bash setup.sh                                           # one time
source .venv/bin/activate && streamlit run src/app.py
```

### API key and cost

- Each teammate uses **their own** key from https://console.anthropic.com, in `.env`
  (`ANTHROPIC_API_KEY=sk-ant-...`). `.env` is git-ignored: **never commit it, never paste it in chat.**
- One plan in the app costs about **$0.02**. A full evaluation run costs about **$1.70**.
- No key? Switch on **Offline demo** in the sidebar: the rules-only version, free, no internet needed.

---

## Everyday commands

| What | Docker | Local (venv active) |
|---|---|---|
| Run the app | `docker compose up` | `streamlit run src/app.py` |
| Tests (offline, free, ~1 min) | `docker compose run --rm app pytest -q` | `python -m pytest tests -q` |
| Agent in the terminal | `docker compose run --rm app python src/run_cli.py examples/accounts_exec.json` | `python src/run_cli.py examples/accounts_exec.json` |
| Quick eval (~$0.40) | `docker compose run --rm app python src/run_evals.py --quick` | `python src/run_evals.py --quick` |
| Full eval (~$1.70, 30-40 min) | `docker compose run --rm app python src/run_evals.py` | `python src/run_evals.py` |

Eval reports go to `results/eval_report.md`. **Each run overwrites `results/`**, so rename the folder
(e.g. `results_v3`) before running again if you want to keep the old one.

## Project layout

```
src/
  app.py            Streamlit app (the 4 checkpoints)        ui_art.py   icons + styling
  graph.py          the LangGraph agent (nodes, interrupts)  llm_steps.py  the 3 Claude decisions
  lookups.py        role search, skill gaps                   funding.py  subsidy + credit calculator
  course_search.py  BM25 + embeddings + re-ranker             plan_rules.py  phases, plan checks
  run_evals.py      E1-E5 evaluation harness                  harness.py  run_eval harness
  data_prep.py      builds data/careers.db from data/raw      settings.py loads .env
evals/              test cases (E1 personas, E3 funding, E4 boundary)
results/            evaluation reports
data/raw/           the 4 SkillsFuture spreadsheets
data/index/         course search vectors (in git, so nobody has to rebuild them)
data/careers.db     built automatically from data/raw (not in git: 101 MB, too big)
```

## Troubleshooting

- **"Connection error" in the browser on the first load**: the models are still loading. Wait a few
  seconds and press F5.
- **App says "Meaning search unavailable"**: the search index was not built. Run
  `python src/course_search.py --build` (Docker does this for you). The app still works with keyword search.
- **Windows crash with `OMP: Error #15`**: run `$env:KMP_DUPLICATE_LIB_OK = "TRUE"` before starting.
- **`ANTHROPIC_API_KEY is not set`**: put it in `.env`, or switch on Offline demo.

## Team rules for git

1. Never commit `.env`, API keys or `data/careers.db` (the `.gitignore` already blocks them).
2. Work on a branch and open a pull request. Run `python -m pytest tests -q` before you push.
3. Do not change `evals/*.json` answer keys after seeing agent results (no-contamination rule).

---

# Development log (how it was built, for the report)

## Build roadmap

| Step | What you build | Key idea | Done when |
|---|---|---|---|
| **1. Data layer** ✅ | SQLite DB + lookup functions (`find_roles`, `nearby_roles`, `skill_gap`) | tools fail loudly, rules in code | tests pass |
| **2. Answer keys first** ✅ (E3 + E4 written) | Funding rule engine + eval cases E3 (funding) and E4 (boundary), written *before* any agent | no contamination | 20 + 10 cases with hand-checked answers |
| **3. Agent skeleton** ✅ | LangGraph `StateGraph`: 5 nodes, `interrupt()` at confirm-role, choose-path, approve-plan; Pydantic structured output | graphs, interrupts, schemas | one profile runs end to end in a script |
| **4. Course search** ✅ | Hybrid search (BM25 + embeddings) + re-ranker; fallback: broaden → wider → "search this skill yourself" | retrieval, Dumpling | E2 labels done, precision@5 measured |
| **5. Plan + costing** ✅ | Order gaps into start → build → stand out; apply funding calculator; write `plan.json` | planning, verification | E5 property checks pass |
| **6. Streamlit viewer** | Pause/resume the graph per checkpoint using `thread_id` + checkpointer | threads, `Command(resume=…)` | a user can click through all 3 checkpoints |
| **7. Eval harness** ✅ | `run_eval` over E1–E5, k = 3 runs, two baselines | measurement | results table with mean ± sd |
| **8. Prove it** | Ablations, failure analysis, "what we tried but didn't use", report | evaluation, verification | final slides |

## Design decisions already made (Step 1)

1. Roles are keyed by (sector, track, name): 47 names repeat across sectors.
2. Skills are compared via the unique-skills mapping, so cross-sector switches compare like with like.
3. Critical core skills use Basic/Intermediate/Advanced; mapped to 2/4/6 on the 1–6 scale (**our assumption**).
4. Courses deduplicated to one row per course number (26,782 → 26,099).
5. `looks_subsidised` = listed fee drops after subsidy (73% of courses).

## Step 2 notes

- `src/funding.py`: subsidy tiers + SkillsFuture Credit, rules and sources in the docstring (`RULES_CHECKED_ON`).
- `evals/e3_funding.json`: 20 hand-worked cases. **Re-check each by hand before trusting.**
- Data finding: listed fee ÷ full fee is 0.30 (Tier 1), 0.50 (Tier 2) or 1.00 (none) for 99.6% of courses, so the tier is inferred from the data.
- Second-source check: for a citizen under 40, the calculator reproduces the directory's own listed after-subsidy fee for every tiered course.

## Step 3 notes

- `src/graph.py`: the LangGraph agent. AI decides in 2 nodes only (`read_profile`, `rank_paths`); 4 interrupt points (`ask_missing_info`, `confirm_role`, `choose_path`, `approve_plan`).
- `src/llm_steps.py`: Claude calls with Pydantic structured output. `CAREER_FAKE=1` = no-API rule mode (tests + baseline 2).
- `src/run_cli.py`: answer the checkpoints in the terminal.
- Known gap for Step 5: when all skill gaps share one level, the three phases are split arbitrarily (alphabetical). Needs a better ordering rule.

Run with Claude (PowerShell):
```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."     # never commit this
py src/run_cli.py examples/accounts_exec.json
```
Run offline: `$env:CAREER_FAKE = "1"` first.

## Step 4 notes

- `src/course_search.py`: BM25 + embeddings (bge-small) fused with RRF, then a cross-encoder re-ranker. Fallback: title → broadened (adds skill description) → widened (3x pool) → honest "no strong course found". No web search.
- Course cost in the plan is per course, BEFORE SkillsFuture Credit (credit is applied once, in Step 5).
- `CAREER_SEARCH_MODE` = `bm25` | `dense` | `hybrid` | `hybrid_rerank` (default). These are your Step 8 ablations.
- `RERANK_GOOD` threshold is a placeholder (0.0); tune it on E2 labels.
- Seen in BM25-only results: "Ethical Culture" ranks an ISO 42001 course first; "Data Collection and Analysis" pulls a trisector strategy course. The re-ranker should fix these: measure it.

Build the meaning index once:
```powershell
py src/course_search.py --build
py src/course_search.py "Data Governance"
```

## Step 5 notes

- `order_skills` [AI]: orders same-level skills, foundations first. Code rejects any order that drops/invents/repeats a skill or puts a higher level first, and falls back to the rule order (logged in `notes`).
- `plan` [code]: one course per skill (best match; a CLOSE and CHEAPER runner-up wins, `CAREER_CLOSE_MARGIN`, placeholder 1.0), phases, plan-wide cost with SkillsFuture Credit applied ONCE, total hours.
- `check_plan` postconditions (= eval E5) run on every plan; a failing plan raises instead of being shown.
- Unknown fees: a few courses have no listed after-subsidy fee, or a ratio matching no tier (e.g. 0.70). They show "unknown" and are left out of the total, with a note.
- In `bm25` mode there are no match scores, so price never overrides relevance (no confidence, no trade-off).

## Step 7a: labelling (TEAM WORK, do before running the agent on these cases)

E2 courses:
```powershell
py src/make_e2_sheet.py      # all 4 search modes, ~1 min
```
Two people each fill `labels/E2_labeller_A.xlsx` / `_B.xlsx` ALONE (column `relevant`, Y/N). Read the `instructions` tab first.

E1 paths: fill every `labels` block in `evals/e1_personas.json` from the sector guide career maps. Look up ids with `py src/find_role_id.py "Data Analyst"`.

Finding while building this: the "Trisector Strategy ... (Data Collection and Analysis)" course really is a Data Collection module. We had assumed it was a bad match. Only labels settle these.

## Step 7b-1/2: E2 with AI-assisted labels

1. Copy `labels/E2_labeller_A.xlsx` to `labels/E2_labeller_AI.xlsx`; ChatGPT labels ALL rows of the AI file.
2. `py src/e2_sample.py` marks ~50 rows (orange `LABEL_THIS` column) in A and B. Two teammates label only those, alone, without seeing ChatGPT's answers.
3. `py src/score_e2.py --tune` prints: agreement (kappa) A-B, AI-A, AI-B; precision@1/3/5 per search mode; suggested WEAK/STRONG thresholds.
Gold rule: sample rows = majority of A, B, AI; other rows = AI label. Report this.

## Step 7c: run the evaluation

```powershell
$env:HF_HUB_OFFLINE = "1"
py src/run_evals.py --quick        # 1 run per case: check it works (~$0.40)
py src/run_evals.py                # the real thing: 3 runs (~$1-2, 20-40 min)
```
Writes `results/eval_report.md` (tables for the report) and `results/eval_results.json` (raw data).

- E1 only runs personas whose labels are filled in `evals/e1_personas.json` (unlabelled ones are skipped, never run).
- Systems: `agent` (Claude + graph), `rules` (graph, no LLM = baseline 2), `single` (Claude, one call, no tools = baseline 1). E3 compares the calculator with Claude doing the maths from the same rules.
- The simulated user (docstring of `src/run_evals.py`) auto-approves plans. Say so in the report.
- Added before any eval run: E4 `must_flag_out_of_scope` (b01, b07, b08), and the agent now tells the user when a stated goal is not in the framework (E1 p12).

## Step 7c findings from quick run 1 (2026-10-13), and what changed

- Bug: Sonnet 5.5 replies are a list of blocks [thinking, text]; the single-call baseline stored str(list), so the thinking signature leaked into the graded text. Fixed: `baselines.visible_text`. Re-run the single-call numbers.
- Bug: a curly apostrophe (can’t) did not match "can't", so b07 wrongly failed "flagged_out_of_scope" for the baseline. Fixed: graders normalise text (`norm`).
- b03 never reached costing: the injected text broke the role shortlist (no Accountant in it), Claude correctly suggested nothing (confidence 0.05), and the run stopped. Added `user_role_id: 13` (the role a real user would click) so the funding check actually runs.
- E4 did not discriminate: the no-LLM rules baseline passed 10/10, because stopping and the fixed final message are in the graph code. Added b11-b13: the same out-of-scope requests without the words enrol/apply/fake.
- Single-call checks named `info:` (e.g. "asked for missing info") are reported but do not decide pass/fail.
- E3: Claude did the maths right on 20/20 in one run. The calculator's case rests on cost ($0 vs $0.0023/case), speed, and being a guarantee rather than an observation. Report that honestly.

## E1 answer key: auto labels from the framework (chosen approach, 2026-10-17)

```powershell
py src/e1_auto_labels.py           # writes labels into evals/e1_personas.json + labels/E1_auto_audit.xlsx
# ONE person checks labels/E1_auto_audit.xlsx (agree Y/N per row, ~10-15 min)
py src/e1_auto_labels.py audit     # prints the agreement rate: put it in the report
```

- Seniority = average skill level a job needs. On each track it orders jobs, e.g. Accounts Executive 2.96 -> Accountant 3.50 -> Finance Manager 4.29 -> Financial Controller 5.22.
- current = name match (several sectors with the same title all count; grader uses `current_role_alternatives`). acceptable = the 2 most similar step-ups on the same track + goal roles. must_not = jumps > 2.0 levels. goal_achievable = goal matches a framework role.
- 4 personas need a one-line `TITLE_MAP` (HR, Food Services, "relationship manager", "Artificial Intelligence"). These are assumptions: list them in the report.
- Rules fixed before any agent run on E1, and never tuned on agent output. Labels are "silver" (rule-made): report that, plus the audit agreement.
- Tried and dropped: a "name confuser" must_not rule (e.g. sales Key Accounts for an Accounts Executive). Cross-sector skill overlap cannot separate it from the same job in another sector (both ~0%). See the docstring.
- Rules baseline (offline check): it suggests no role when the top two name matches are close (Accounts Executive 1.00 vs Accountant 0.92), so `role_correct` is often False. That is the baseline's design, not a bug.

## E1 labelling sheet (manual alternative, not used)

```powershell
py src/e1_sheet.py make     # only if labels/E1_labels.xlsx does not exist yet
py src/e1_sheet.py load     # after filling it: writes labels into evals/e1_personas.json
```

## Step 8a: full run 1 (2026-10-18, 3 runs) and fixes from its failure analysis

Run 1 (keep it as `results_v1/`): E1 agent 78% ± 5% (pass^3 75%), single call 75%, rules 8% · E3 100% both · E4 agent 100%, rules 77%, single 8% · E5 100% · $1.67.

Agent failures on E1, read from `eval_results.json`:
- p11 (3/3) CRASH: `order_skills` got 49 skill gaps; the reply hit max_tokens=1500 (thinking counts) and lost the `reason` field; the ValueError was not caught. Fix: `graph.order_skills` falls back to the rule order and logs it; max_tokens 4000.
- p10 (3/3): the agent suggested no role. The framework's HR jobs are "Executive, Performance and Rewards" (HR only in the sector name), so they were not on the shortlist. Fix: `lookups.search_roles` (agent + single-call baseline only): framework wording (HR, Artificial Intelligence, service, outlet) and, only when no name matches exactly, "sector + job name" matching. Same fix in the single-call baseline so the comparison stays fair.
- p11 also: goal "restaurant manager" matched Accountancy "Treasury Manager". Same fix (restaurant -> outlet).
- p04 (2/3, flaky): suggested "Customer Service, Billing and Settlement Department Manager" (2.55 -> 5.21) to an executive. NOT fixed on purpose: a "too senior" filter in the agent is the same rule the E1 answer key uses, so it would pass by copying the grader. Report as a real failure.
- The E1 answer key (`e1_auto_labels.py`) still uses plain `find_roles`, so these fixes cannot change the labels.
- Caveat for the report: the fixes were made after seeing these 12 personas, so run 2's E1 number is optimistic (no held-out set).

## Step 6: Streamlit app

```powershell
pip install streamlit
$env:ANTHROPIC_API_KEY = "sk-ant-..."     # or switch on "Offline demo" in the sidebar
streamlit run src/app.py
```
- The page is only a view: every answer goes back through the graph with `Command(resume=...)`, so the same validation as the CLI and evals applies.
- Each plan is one `thread_id` on the checkpointer. It is in the URL (`?thread=...`), so refreshing the browser resumes the paused run (durability).
- "Offline demo" = the no-AI rules baseline (no key, no cost). Good for a live demo if Wi-Fi fails.
- Limit: `InMemorySaver`, so threads are lost when the app restarts. A SQLite checkpointer would keep them (not needed for the demo).
