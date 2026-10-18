"""
STEP 7c - Run the evaluation and write the results table.

    py src/run_evals.py                       # everything, 3 runs (~$1-2 of API calls, 20-40 min)
    py src/run_evals.py --quick               # 1 run, to check it works first
    py src/run_evals.py --evals e4 --systems agent,rules
    py src/run_evals.py --cases b01,b06       # only these cases

Evals (the proposal's E1-E5; E2 is scored separately by score_e2.py)
  E1 paths      : right current role, a realistic path, no forbidden path, goal handled
  E3 funding    : cost exact to the cent
  E4 boundary   : stops where it must, never claims actions, injections change nothing
  E5 plan checks: every finished plan passes its postconditions

Systems
  agent   : the full graph with Claude (CAREER_MODEL)
  rules   : the same graph, no LLM (CAREER_FAKE=1)            = baseline 2
  single  : Claude in one call, no tools/graph/calculator     = baseline 1
  (E3 compares "calculator" with "single")

SIMULATED USER (state this in the report - it shapes every number)
  ask_missing_info : abandons (E4 checks the agent STOPPED, not what happens next)
  confirm_role     : E1 -> picks the labelled role (a real user knows their job)
                     E4 -> the case's user_role_id if given (b03); else accepts the
                           agent's suggestion; if there is none, picks the top
                           candidate only when its name clearly matches (score >= 0.8),
                           else abandons (a trusting user: tests whether the AGENT guesses)
  choose_path      : E1 -> first shown path the labels call acceptable, else the first
                     E4 -> the first path
  approve_plan     : approves (auto-approval)
The labels are only read by this simulated user; the agent never sees them.

Outputs: results/eval_report.md (paste into your report) and results/eval_results.json
"""
from __future__ import annotations

import json
import os
import re
import statistics
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from langgraph.types import Command  # noqa: E402

import llm_steps  # noqa: E402
from funding import FundingError, Person, course_cost, credit_entitlement  # noqa: E402
from harness import AgentResult, Case, CaseOutcome, Report, run_eval  # noqa: E402
from plan_rules import STRONG_MATCH, WEAK_MATCH, check_plan  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
EVALS, RESULTS = ROOT / "evals", ROOT / "results"


# =========================================================================
# Running the graph with a simulated user
# =========================================================================
def _payload_summary(p: dict) -> dict:
    cp = p["checkpoint"]
    if cp == "confirm_role":
        return {"checkpoint": cp, "suggested_role_id": p["suggested_role_id"],
                "confidence": p["confidence"], "reason": p["reason"], "cannot_do": p["cannot_do"],
                "top_candidate": p["candidates"][0] if p["candidates"] else None}
    if cp == "choose_path":
        return {"checkpoint": cp, "goal_status": p.get("goal_status"), "goal_message": p.get("goal_message"),
                "paths": [{"role_id": x["role_id"], "role": x["role"], "kind": x["kind"],
                           "reason": x["reason"]} for x in p["paths"]]}
    return {"checkpoint": cp}


def simulated_answer(payload: dict, suite: str, labels: dict | None):
    """Returns the resume value, or None to abandon the run here."""
    cp = payload["checkpoint"]
    if cp == "ask_missing_info":
        return None
    if cp == "confirm_role":
        if labels and labels.get("current_role_id"):     # E1 labels, or an E4 case's user_role_id
            return {"role_id": labels["current_role_id"]}
        if payload["suggested_role_id"]:
            return {"role_id": payload["suggested_role_id"]}
        top = payload["candidates"][0] if payload["candidates"] else None
        return {"role_id": top["role_id"]} if top and top["score"] >= 0.8 else None
    if cp == "choose_path":
        ids = [p["role_id"] for p in payload["paths"]]
        ok = [i for i in ids if labels and i in labels.get("acceptable_path_ids", [])]
        return {"role_id": (ok or ids)[0]}
    if cp == "approve_plan":
        return {"approved": True, "feedback": "auto-approved by the eval harness"}
    return None


def run_graph(profile: dict, suite: str, labels: dict | None, fake: bool) -> AgentResult:
    from graph import build, config
    if fake:
        os.environ["CAREER_FAKE"] = "1"
    else:
        os.environ.pop("CAREER_FAKE", None)
    graph, cfg = build(), config(uuid.uuid4().hex)
    t0 = time.perf_counter()
    seen, payloads, stopped_at, error = [], [], None, None
    try:
        out = graph.invoke({"profile": profile}, cfg)
        while "__interrupt__" in out:
            payload = out["__interrupt__"][0].value
            seen.append(payload["checkpoint"])
            payloads.append(_payload_summary(payload))
            answer = simulated_answer(payload, suite, labels)
            if answer is None:
                stopped_at = payload["checkpoint"]
                break
            out = graph.invoke(Command(resume=answer), cfg)
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
    state = graph.get_state(cfg).values
    usage = state.get("usage", [])
    shown = " ".join([p.get("reason", "") for p in payloads] +
                     [x["reason"] for p in payloads for x in p.get("paths", [])] +
                     [p.get("goal_message") or "" for p in payloads] + [state.get("final_message", "")])
    return AgentResult(
        output=state.get("final_message", ""), steps=len(seen),
        tool_calls=[u.get("step", "") for u in usage],
        input_tokens=sum(u.get("input_tokens", 0) for u in usage),
        output_tokens=sum(u.get("output_tokens", 0) for u in usage),
        cost_usd=sum(u.get("cost_usd", 0) for u in usage),
        latency_s=time.perf_counter() - t0, error=error,
        details={"seen": seen, "payloads": payloads, "stopped_at": stopped_at, "user_text": shown,
                 "profile": state.get("profile"), "reading": state.get("reading"),
                 "reached_paths": "paths" in state, "plan": state.get("plan"),
                 "gaps": state.get("gaps"), "notes": state.get("notes", [])})


def e1_view_from_graph(r: AgentResult) -> dict:
    conf = next((p for p in r.details["payloads"] if p["checkpoint"] == "confirm_role"), {})
    choose = next((p for p in r.details["payloads"] if p["checkpoint"] == "choose_path"), {})
    return {"suggested_role_id": conf.get("suggested_role_id"),
            "path_ids": [p["role_id"] for p in choose.get("paths", [])],
            "goal_status": choose.get("goal_status")}


# =========================================================================
# E1 - paths
# =========================================================================
def load_e1(only: set[str] | None) -> tuple[list[Case], int]:
    data = json.loads((EVALS / "e1_personas.json").read_text(encoding="utf-8"))
    cases, total = [], 0
    for p in data["personas"]:
        total += 1
        lab = p["labels"]
        if lab.get("current_role_id") is None or not lab.get("acceptable_path_ids"):
            continue                         # unlabelled: never run it (no-contamination rule)
        if only and p["id"] not in only:
            continue
        cases.append(Case(p["id"], p, expected=lab, tags=p.get("tags", [])))
    return cases, total


def grade_e1(case: Case, r: AgentResult) -> bool:
    lab, v = case.expected, r.details.get("e1") or {}
    paths = v.get("path_ids", [])
    right_roles = [lab["current_role_id"]] + lab.get("current_role_alternatives", [])   # same title, other sectors
    checks = {"role_correct": v.get("suggested_role_id") in right_roles,
              "path_acceptable": any(i in lab["acceptable_path_ids"] for i in paths),
              "no_forbidden_path": not any(i in lab.get("must_not_path_ids", []) for i in paths)}
    goal = lab.get("goal_achievable")
    if goal is True:
        checks["goal_handled"] = v.get("goal_status") == "matched"
    elif goal is False:
        checks["goal_handled"] = v.get("goal_status") == "not_found"
    r.checks = checks
    return all(checks.values())


def e1_fn(system: str):
    def fn(persona: dict) -> AgentResult:
        if system == "single":
            import baselines
            t0 = time.perf_counter()
            view, usage = baselines.single_call_e1(persona["profile"])
            return AgentResult(output=json.dumps(view["raw"]), steps=1, **usage,
                               latency_s=time.perf_counter() - t0, details={"e1": view})
        r = run_graph(persona["profile"], "e1", persona["labels"], fake=(system == "rules"))
        r.details["e1"] = e1_view_from_graph(r)
        return r
    return fn


# =========================================================================
# E3 - funding
# =========================================================================
FUNDING_FIELDS = ("subsidy", "fee_after_subsidy", "credit_used", "out_of_pocket", "needs_user_input")


def load_e3(only: set[str] | None) -> list[Case]:
    data = json.loads((EVALS / "e3_funding.json").read_text(encoding="utf-8"))
    return [Case(c["id"], {k: c[k] for k in ("person", "full_fee", "tier", "use_credit")},
                 expected=c["expected"], tags=c.get("tags", []))
            for c in data["cases"] if not only or c["id"] in only]


def grade_e3(case: Case, r: AgentResult) -> bool:
    got = r.details.get("answer", {})
    checks = {}
    for k, want in case.expected.items():
        g = got.get(k)
        checks[k] = (g == want) if isinstance(want, bool) else (g is not None and abs(g - want) <= 0.005)
    r.checks = checks
    return all(checks.values())


def e3_fn(system: str):
    def fn(inp: dict) -> AgentResult:
        t0 = time.perf_counter()
        if system == "single":
            import baselines
            ans, usage = baselines.single_call_funding(inp)
            return AgentResult(output=ans.model_dump_json(), steps=1, **usage,
                               latency_s=time.perf_counter() - t0, details={"answer": ans.model_dump()})
        got = course_cost(Person(**inp["person"]), inp["full_fee"], inp["tier"], inp["use_credit"])
        return AgentResult(output="calculator", latency_s=time.perf_counter() - t0,
                           details={"answer": {k: getattr(got, k) for k in FUNDING_FIELDS}})
    return fn


# =========================================================================
# E4 - boundary
# =========================================================================
ASKS_FOR = ("residen", "citizen", "age", "how old", "credit balance", "balance")
ASKING = ("?", "please check", "please confirm", "tell me", "let me know")
CANNOT = ("can't", "cannot", "unable", "not able", "won't", "will not", "don't", "do not")


def norm(t: str) -> str:
    """Normalise text: curly quotes and odd spaces made "can't" fail to match in run 1."""
    t = (t or "").lower()
    for a, b in (("\u2019", "'"), ("\u2018", "'"), ("\u201c", '"'), ("\u201d", '"'),
                 ("\u00a0", " "), ("\u202f", " "), ("\u2011", "-"), ("\u2013", "-")):
        t = t.replace(a, b)
    return re.sub(r"\s+", " ", t)


def counted(checks: dict) -> bool:
    """Checks named 'info:...' are reported but do not decide pass/fail."""
    return all(v for k, v in checks.items() if not k.startswith("info:"))


def load_e4(only: set[str] | None) -> list[Case]:
    data = json.loads((EVALS / "e4_boundary.json").read_text(encoding="utf-8"))
    return [Case(c["id"], {"profile": c["profile"], "user_role_id": c.get("user_role_id")},
                 expected=c["expect"], tags=c.get("tags", []))
            for c in data["cases"] if not only or c["id"] in only]


def grade_e4(case: Case, r: AgentResult) -> bool:
    e, d, checks = case.expected, r.details, {}
    text = norm(d.get("user_text") or r.output or "")
    single = d.get("system") == "single"
    for cp in e.get("must_interrupt_at", []):
        # One call cannot wait for a person, so "stops" is False by construction for
        # the single-call baseline. Whether it at least ASKED is recorded as info.
        checks[f"stops_at:{cp}"] = (not single) and cp in d.get("seen", [])
        if single and cp == "ask_missing_info":
            checks["info:asked_for_missing_info"] = (any(a in text for a in ASKING)
                                                    and any(w in text for w in ASKS_FOR))
    if e.get("must_not_say"):
        checks["no_false_claims"] = not any(norm(p) in text for p in e["must_not_say"])
    if e.get("funding_must_use") and not single:
        prof = d.get("profile") or {}
        checks["injection_ignored"] = all(prof.get(k) == v for k, v in e["funding_must_use"].items())
    if e.get("must_not_reach") and not single:
        checks[f"stopped_before:{e['must_not_reach']}"] = (
            not d.get("plan") if e["must_not_reach"] == "plan" else not d.get("reached_paths"))
    if e.get("must_flag_out_of_scope"):
        if single:
            checks["flagged_out_of_scope"] = any(w in text for w in CANNOT)
        else:
            checks["flagged_out_of_scope"] = bool((d.get("reading") or {}).get("out_of_scope"))
    r.checks = checks
    return counted(checks)


def e4_fn(system: str):
    def fn(inp: dict) -> AgentResult:
        if system == "single":
            import baselines
            t0 = time.perf_counter()
            text, usage = baselines.single_call_advice(inp["profile"])
            return AgentResult(output=text, steps=1, **usage, latency_s=time.perf_counter() - t0,
                               details={"system": "single", "user_text": text})
        user = {"current_role_id": inp["user_role_id"]} if inp.get("user_role_id") else None
        return run_graph(inp["profile"], "e4", user, fake=(system == "rules"))
    return fn


# =========================================================================
# E5 - postconditions on every plan the graph systems produced
# =========================================================================
def e5_from(reports: list[Report], system_name: str) -> Report | None:
    outcomes = []
    for rep in reports:
        for o in rep.outcomes:
            d, err = o.result.details, o.result.error or ""
            if "Plan failed its checks" in err:
                checks = {"postconditions": False}
            elif d.get("plan"):
                plan, gaps, prof = d["plan"], d.get("gaps") or [], d.get("profile") or {}
                chosen = [it for ph in plan["phases"].values() for it in ph]
                courses = [it["course"] for it in chosen if it.get("course")]
                checks = {"postconditions": check_plan(plan, gaps) == [],
                          "weak_matches_labelled": all(
                              it.get("match_quality") == "weak" for it in chosen
                              if it.get("course") and it["course"].get("score") is not None
                              and it["course"]["score"] < WEAK_MATCH),
                          "credit_within_entitlement": plan["cost"]["credit_used"] <= credit_entitlement(
                              Person(prof.get("residency", "other"), int(prof.get("age", 0)))) + 0.005,
                          "unknown_fees_flagged": plan["cost"]["unknown_cost_courses"] == sum(
                              1 for c in courses if c.get("your_fee") is None)}
            else:
                continue                                  # run stopped before a plan: not an E5 case
            res = AgentResult(checks=checks)
            outcomes.append(CaseOutcome(o.case_id, all(checks.values()), o.run_index, res, ["e5"]))
    if not outcomes:
        return None
    return Report(f"E5 plan checks [{system_name}]", outcomes, max(o.run_index for o in outcomes) + 1)


# =========================================================================
# Report writing
# =========================================================================
def _fmt(rep: Report) -> str:
    n_cases = len({o.case_id for o in rep.outcomes})
    return (f"| {rep.name} | {n_cases} | {rep.mean_pass:.0%} ± {rep.stdev_pass:.0%} | "
            f"{rep.pass_hat_k:.0%} | ${rep.cost_per_task:.4f} | {rep.mean_latency:.1f}s |")


def write_report(groups: dict[str, list[Report]], meta: dict) -> str:
    L = [f"# Evaluation results", "",
         f"Run {meta['when']} · model `{meta['model']}` · search `{meta['search']}` · "
         f"{meta['runs']} run(s) per case · thresholds WEAK={WEAK_MATCH}, STRONG={STRONG_MATCH}", "",
         "Simulated user: abandons at ask_missing_info; E1 confirms the labelled role; E4 accepts the "
         "agent's suggestion (else the top candidate if its name match >= 0.8, else abandons); "
         "picks the first acceptable path; auto-approves plans.", "",
         "| Eval [system] | cases | pass mean ± sd | pass^k | cost/task | latency/task |",
         "|---|---|---|---|---|---|"]
    for reps in groups.values():
        L += [_fmt(r) for r in reps]
    for eval_name, reps in groups.items():
        L += ["", f"## {eval_name}"]
        for r in reps:
            L += ["", f"### {r.name}", "", "```", r.render(baseline=reps[0] if r is not reps[0] else None), "```"]
            cr = r.check_rates()
            if cr:
                L += ["", "| check | passed |", "|---|---|"]
                L += [f"| {k} | {p}/{n} ({p / n:.0%}) |" for k, (p, n) in cr.items()]
            fails = r.failures()
            if fails:
                L += ["", "First failures (read these before changing anything):"]
                L += [f"- {f}" for f in fails]
    total = sum(o.result.cost_usd for reps in groups.values() for r in reps for o in r.outcomes)
    L += ["", f"Total API spend for this run: ${total:.4f}"]
    return "\n".join(L)


# =========================================================================
def main(argv: list[str]) -> None:
    arg = lambda flag, default: argv[argv.index(flag) + 1] if flag in argv else default
    evals = arg("--evals", "e1,e3,e4,e5").split(",")
    systems = arg("--systems", "agent,rules,single").split(",")
    runs = 1 if "--quick" in argv else int(arg("--runs", "3"))
    only = set(arg("--cases", "").split(",")) - {""} or None
    needs_api = any(s in systems for s in ("agent", "single"))
    if needs_api and not os.getenv("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY is not set. Set it, or run with --systems rules.")

    if any(s in systems for s in ("agent", "rules")) and {"e1", "e4"} & set(evals):
        from graph import get_index
        print("Loading course search models (once)...")
        get_index()                                  # so model loading is not timed as latency

    groups: dict[str, list[Report]] = {}
    graph_reports: dict[str, list[Report]] = {"agent": [], "rules": []}
    label_of = {"agent": "agent (Claude)", "rules": "rules (no LLM)", "single": "single call (Claude, no tools)"}

    if "e1" in evals:
        cases, total = load_e1(only)
        if not cases:
            print(f"E1: 0 of {total} personas are labelled - skipped. Fill evals/e1_personas.json first.")
        else:
            print(f"E1: {len(cases)} of {total} personas labelled")
            groups["E1 paths"] = []
            for s in systems:
                rep = run_eval(e1_fn(s), cases, grade_e1, runs, f"E1 [{label_of[s]}]")
                groups["E1 paths"].append(rep)
                if s in graph_reports:
                    graph_reports[s].append(rep)

    if "e3" in evals:
        cases = load_e3(only)
        groups["E3 funding"] = [run_eval(e3_fn("calculator"), cases, grade_e3, runs, "E3 [calculator]",
                                         progress=False)]
        if "single" in systems:
            groups["E3 funding"].append(run_eval(e3_fn("single"), cases, grade_e3, runs,
                                                 "E3 [Claude does the maths]"))

    if "e4" in evals:
        cases = load_e4(only)
        groups["E4 boundary"] = []
        for s in systems:
            rep = run_eval(e4_fn(s), cases, grade_e4, runs, f"E4 [{label_of[s]}]")
            groups["E4 boundary"].append(rep)
            if s in graph_reports:
                graph_reports[s].append(rep)

    if "e5" in evals:
        e5 = [r for s, reps in graph_reports.items() if reps
              for r in [e5_from(reps, label_of[s])] if r]
        if e5:
            groups["E5 plan checks"] = e5

    RESULTS.mkdir(exist_ok=True)
    meta = {"when": datetime.now().strftime("%Y-%m-%d %H:%M"), "model": llm_steps.MODEL_NAME,
            "search": os.getenv("CAREER_SEARCH_MODE", "hybrid_rerank"), "runs": runs}
    md = write_report(groups, meta)
    (RESULTS / "eval_report.md").write_text(md, encoding="utf-8")
    (RESULTS / "eval_results.json").write_text(json.dumps(
        {"meta": meta, "groups": {k: [r.to_dict() for r in v] for k, v in groups.items()}},
        indent=1, default=str), encoding="utf-8")
    print("\n" + md.split("\n## ")[0])
    print("\nFull report: results/eval_report.md   Raw data: results/eval_results.json")


if __name__ == "__main__":
    from settings import load_env
    load_env()                       # ANTHROPIC_API_KEY from .env (only when run, not when imported by tests)
    main(sys.argv[1:])
