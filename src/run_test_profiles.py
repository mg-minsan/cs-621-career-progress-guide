"""
Run the test profiles in examples/test_profiles/ against the agent graph.

    CAREER_FAKE=1 CAREER_SEARCH_MODE=bm25 py src/run_test_profiles.py            # offline, free
    py src/run_test_profiles.py                                                   # real Claude (~$0.02 a case)
    py src/run_test_profiles.py 05 07                                             # only cases whose file starts with 05 or 07

Each case file is JSON:
    profile   the input, as run_cli.py would read it
    answers   replies to the pauses, in order. Anything a pause expects:
              ask_missing_info {"field": value}, confirm_role / choose_path {"role_id": ...},
              approve_plan {"approved": true}
    stop_at   (optional) stop when the graph pauses at this checkpoint, instead of answering it
    expect    {"fake": {...}, "real": {...}}  (the block for the current mode is used)

Checks inside `expect`:
    pauses                list of checkpoint names, in order
    error_contains        the run must raise, and the message must contain this text
    done                  true: the run must reach the final message
    missing_contains      text in the first ask_missing_info "missing" list
    suggested_role_id     confirm_role payload (null allowed)
    top_candidate_id      first candidate at confirm_role
    max_confidence        confirm_role confidence must be <= this
    no_candidate_sector   no confirm_role candidate may be in this sector
    goal_status           matched | not_found | none  (read at choose_path)
    gap_total             new_skills + level_ups in the final plan
    payload_error_contains  every pause after the first of this checkpoint carries this error text
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from langgraph.types import Command  # noqa: E402

from graph import build, config  # noqa: E402
from settings import load_env  # noqa: E402

load_env()
CASES = Path(__file__).resolve().parent.parent / "examples" / "test_profiles"


def run_case(case: dict) -> dict:
    """Play the case through the graph. Returns what was seen: pauses, error, final state."""
    graph, cfg = build(), config(uuid.uuid4().hex)
    answers, seen = list(case.get("answers", [])), {"pauses": [], "payloads": [], "error": None, "out": None}
    try:
        out = graph.invoke({"profile": case["profile"]}, cfg)
        while "__interrupt__" in out:
            payload = out["__interrupt__"][0].value
            seen["pauses"].append(payload["checkpoint"])
            seen["payloads"].append(payload)
            if payload["checkpoint"] == case.get("stop_at") or not answers:
                break
            out = graph.invoke(Command(resume=answers.pop(0)), cfg)
        seen["out"] = out
    except Exception as e:                                   # ToolError etc: this is what we assert on
        seen["error"] = f"{type(e).__name__}: {e}"
    return seen


def check(expect: dict, seen: dict) -> list[str]:
    """Return a list of problems (empty = pass)."""
    bad, payloads, out = [], seen["payloads"], seen["out"] or {}
    first = lambda cp: next((p for p in payloads if p["checkpoint"] == cp), None)   # noqa: E731
    if "error_contains" in expect:
        if not seen["error"]:
            bad.append(f"expected an error containing {expect['error_contains']!r}, but the run did not fail")
        elif expect["error_contains"] not in seen["error"]:
            bad.append(f"error was {seen['error']!r}, expected it to contain {expect['error_contains']!r}")
    elif seen["error"]:
        bad.append(f"unexpected error: {seen['error']}")
    if "pauses" in expect and seen["pauses"] != expect["pauses"]:
        bad.append(f"pauses were {seen['pauses']}, expected {expect['pauses']}")
    if expect.get("done") and "final_message" not in out:
        bad.append("run did not reach the final message")
    if "missing_contains" in expect:
        p = first("ask_missing_info")
        if not p or not any(expect["missing_contains"] in m for m in p["missing"]):
            bad.append(f"ask_missing_info did not list {expect['missing_contains']!r}: {p and p['missing']}")
    c = first("confirm_role")
    for key in ("suggested_role_id", "max_confidence", "top_candidate_id", "no_candidate_sector"):
        if key in expect and c is None:
            bad.append(f"{key}: the graph never paused at confirm_role")
    if c:
        if "suggested_role_id" in expect and c["suggested_role_id"] != expect["suggested_role_id"]:
            bad.append(f"suggested_role_id was {c['suggested_role_id']}, expected {expect['suggested_role_id']}")
        if "max_confidence" in expect and c["confidence"] > expect["max_confidence"]:
            bad.append(f"confidence {c['confidence']:.2f} is above {expect['max_confidence']}")
        if "top_candidate_id" in expect and c["candidates"][0]["role_id"] != expect["top_candidate_id"]:
            bad.append(f"top candidate was {c['candidates'][0]['role_id']}, expected {expect['top_candidate_id']}")
        if "no_candidate_sector" in expect:
            hit = [x["role_id"] for x in c["candidates"] if x["sector"] == expect["no_candidate_sector"]]
            if hit:
                bad.append(f"candidates {hit} are in sector {expect['no_candidate_sector']!r}")
    if "goal_status" in expect:
        p = first("choose_path")
        if not p:
            bad.append("goal_status: the graph never paused at choose_path")
        elif p["goal_status"] != expect["goal_status"]:
            bad.append(f"goal_status was {p['goal_status']!r}, expected {expect['goal_status']!r}")
    if "gap_total" in expect:
        gs = (out.get("plan") or {}).get("gap_summary")
        if not gs:
            bad.append("gap_total: no plan was produced")
        elif gs["new_skills"] + gs["level_ups"] != expect["gap_total"]:
            bad.append(f"gap was {gs['new_skills'] + gs['level_ups']} skills, expected {expect['gap_total']}")
    if "payload_error_contains" in expect:
        cps = [p for p in payloads if p["checkpoint"] == "confirm_role"][1:]
        if not cps or not all(expect["payload_error_contains"] in p.get("error", "") for p in cps):
            bad.append(f"later confirm_role pauses did not all say {expect['payload_error_contains']!r}")
    return bad


def main(prefixes: list[str]) -> int:
    mode = "fake" if os.getenv("CAREER_FAKE") == "1" else "real"
    files = sorted(f for f in CASES.glob("*.json") if not prefixes or any(f.name.startswith(p) for p in prefixes))
    print(f"mode: {mode}   cases: {len(files)}\n")
    failed = 0
    for f in files:
        case = json.loads(f.read_text(encoding="utf-8"))
        expect = case["expect"].get(mode)
        if expect is None:
            print(f"SKIP  {f.stem}  (no '{mode}' expectation)")
            continue
        problems = check(expect, run_case(case))
        print(f"{'FAIL' if problems else 'PASS'}  {f.stem}")
        for p in problems:
            print(f"        - {p}")
        failed += bool(problems)
    print(f"\n{len(files) - failed} of {len(files)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
