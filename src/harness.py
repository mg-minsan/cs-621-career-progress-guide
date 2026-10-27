"""
STEP 7c - The eval harness. Same contract as a standard eval harness
(agentlab/evals.py: Case, AgentResult, Report, run_eval), copied here so the
project runs on its own, plus three things this project needs:

  pass^k          a case counts only if it passed in ALL k runs:
                  "Pass^k is what production runs on". Used for E5 (safety).
  per-check view  each case records which named checks passed, so a failure
                  can be traced to the exact assertion (read the
                  failure before changing anything).
  to_dict         everything goes to results/*.json for the report.
"""
from __future__ import annotations

import statistics
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

Grader = Callable[["Case", "AgentResult"], bool]


@dataclass
class Case:
    id: str
    input: Any
    expected: Any = None
    tags: list[str] = field(default_factory=list)
    grader: Any = None


@dataclass
class AgentResult:
    output: str = ""
    steps: int = 0
    tool_calls: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_s: float = 0.0
    error: str | None = None
    # project extras
    checks: dict[str, bool] = field(default_factory=dict)   # filled by the grader
    details: dict = field(default_factory=dict)             # trajectory, plan, etc.


@dataclass
class CaseOutcome:
    case_id: str
    passed: bool
    run_index: int
    result: AgentResult
    tags: list[str] = field(default_factory=list)


@dataclass
class Report:
    name: str
    outcomes: list[CaseOutcome]
    n_runs: int

    @property
    def pass_rates(self) -> list[float]:
        by_run: dict[int, list[bool]] = {}
        for o in self.outcomes:
            by_run.setdefault(o.run_index, []).append(o.passed)
        return [sum(v) / len(v) for _, v in sorted(by_run.items())]

    @property
    def mean_pass(self) -> float:
        return statistics.fmean(self.pass_rates) if self.pass_rates else 0.0

    @property
    def stdev_pass(self) -> float:
        rs = self.pass_rates
        return statistics.stdev(rs) if len(rs) > 1 else 0.0

    @property
    def pass_hat_k(self) -> float:
        """Share of cases that passed in EVERY run."""
        verdict: dict[str, bool] = {}
        for o in self.outcomes:
            verdict[o.case_id] = verdict.get(o.case_id, True) and o.passed
        return sum(verdict.values()) / len(verdict) if verdict else 0.0

    @property
    def cost_per_task(self) -> float:
        return statistics.fmean(o.result.cost_usd for o in self.outcomes) if self.outcomes else 0.0

    @property
    def tokens_per_task(self) -> float:
        return statistics.fmean(o.result.input_tokens + o.result.output_tokens
                                for o in self.outcomes) if self.outcomes else 0.0

    @property
    def mean_latency(self) -> float:
        return statistics.fmean(o.result.latency_s for o in self.outcomes) if self.outcomes else 0.0

    def flaky_cases(self) -> list[str]:
        by_case: dict[str, set[bool]] = {}
        for o in self.outcomes:
            by_case.setdefault(o.case_id, set()).add(o.passed)
        return sorted(c for c, s in by_case.items() if len(s) > 1)

    def clusters(self) -> dict[str, tuple[int, int]]:
        """tag -> (cases that failed on any run, cases with this tag)."""
        verdict, tags = {}, {}
        for o in self.outcomes:
            verdict[o.case_id] = verdict.get(o.case_id, True) and o.passed
            tags[o.case_id] = o.tags or ["untagged"]
        agg: dict[str, list[int]] = {}
        for cid, ok in verdict.items():
            for t in tags[cid]:
                a = agg.setdefault(t, [0, 0])
                a[1] += 1
                a[0] += 0 if ok else 1
        return {t: (f, n) for t, (f, n) in agg.items()}

    def check_rates(self) -> dict[str, tuple[int, int]]:
        """check name -> (executions where it passed, executions where it applied)."""
        agg: dict[str, list[int]] = {}
        for o in self.outcomes:
            for name, ok in o.result.checks.items():
                a = agg.setdefault(name, [0, 0])
                a[1] += 1
                a[0] += 1 if ok else 0
        return {k: (p, n) for k, (p, n) in agg.items()}

    def failures(self, limit: int = 6) -> list[str]:
        lines, seen = [], set()
        for o in self.outcomes:
            if o.passed or o.case_id in seen:
                continue
            seen.add(o.case_id)
            failed = [k for k, v in o.result.checks.items() if not v]
            why = o.result.error or ("failed checks: " + ", ".join(failed) if failed else "failed")
            lines.append(f"{o.case_id} (run {o.run_index + 1}): {why[:200]}")
            if len(seen) >= limit:
                break
        return lines

    def render(self, baseline: "Report | None" = None) -> str:
        lines = [f"=== {self.name} ===",
                 f"pass rate     {self.mean_pass:.1%}  (sd {self.stdev_pass:.1%} over {self.n_runs} runs)",
                 f"pass^{self.n_runs}        {self.pass_hat_k:.1%}  (cases that passed every run)",
                 f"cost/task     ${self.cost_per_task:.4f}",
                 f"latency/task  {self.mean_latency:.2f}s"]
        if baseline:
            delta = self.mean_pass - baseline.mean_pass
            lines.append(f"vs {baseline.name}: {delta:+.1%} pass rate")
            if abs(delta) <= max(self.stdev_pass, baseline.stdev_pass):
                lines.append("  NOTE: difference is within one standard deviation. Not shown to differ.")
        if self.flaky_cases():
            lines.append(f"flaky cases   {', '.join(self.flaky_cases())}")
        bad = [(t, f, n) for t, (f, n) in self.clusters().items() if f]
        if bad:
            lines.append("failure clusters:")
            lines += [f"  {t:<24} {f}/{n} cases failed" for t, f, n in sorted(bad, key=lambda x: -x[1])]
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {"name": self.name, "n_runs": self.n_runs, "mean_pass": self.mean_pass,
                "sd_pass": self.stdev_pass, "pass_hat_k": self.pass_hat_k,
                "pass_rates_per_run": self.pass_rates, "cost_per_task": self.cost_per_task,
                "tokens_per_task": self.tokens_per_task, "latency_per_task": self.mean_latency,
                "flaky": self.flaky_cases(), "clusters": self.clusters(),
                "checks": self.check_rates(),
                "outcomes": [{"case": o.case_id, "run": o.run_index, "passed": o.passed,
                              "tags": o.tags, **asdict(o.result)} for o in self.outcomes]}


def run_eval(agent_fn: Callable[[Any], AgentResult], cases: list[Case], grader: Grader,
             n_runs: int = 3, name: str = "agent", progress: bool = True) -> Report:
    outcomes: list[CaseOutcome] = []
    for run_index in range(n_runs):
        for case in cases:
            t0 = time.perf_counter()
            try:
                result = agent_fn(case.input)
            except Exception as e:                       # a crash is a failed case, not a stop
                result = AgentResult(error=f"{type(e).__name__}: {e}")
            if not result.latency_s:
                result.latency_s = time.perf_counter() - t0
            g = case.grader or grader
            passed = False if result.error else bool(g(case, result))
            tags = list(case.tags) + (["crash"] if result.error else [])
            outcomes.append(CaseOutcome(case.id, passed, run_index, result, tags))
            if progress:
                print(f"  [{name}] run {run_index + 1}/{n_runs} {case.id}: "
                      f"{'PASS' if passed else 'FAIL'}  ({result.latency_s:.1f}s)", flush=True)
    return Report(name=name, outcomes=outcomes, n_runs=n_runs)
