# Grounding check (Fix 7)

Source: 2026-10-31 02:25 run, 3 run(s) per case, boundary profiles. Graph systems are counted only on runs that reached a plan.

| System | answers | names a specific course (ref) | every ref is real | states the person's own fee | prices only as ranges | suggests it may cost $0 |
|---|---|---|---|---|---|---|
| agent (Claude) | 39 | 39/39 | 39/39 | 39/39 | 0/39 | 0/39 |
| rules (no LLM) | 39 | 39/39 | 39/39 | 39/39 | 0/39 | 0/39 |
| single call (Claude, no tools) | 51 | 0/51 | 0/51 | 0/51 | 50/51 | 8/51 |

Read with E5: the single call refuses to enrol and claims no actions as well as the agent does. Its gap is grounding: it cannot name a real course or say what this person will pay, because it has no catalogue and no calculator.
