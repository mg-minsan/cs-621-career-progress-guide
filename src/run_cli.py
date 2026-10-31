"""
Run the agent in the terminal and answer its checkpoints yourself.

    py src/run_cli.py examples/accounts_exec.json
    (offline, no API:  set CAREER_FAKE=1  first)

Each pause prints what the agent wants, then you type an answer:
    confirm_role / choose_path : a role_id number
    ask_missing_info           : JSON, e.g. {"residency": "citizen"} or {"credit_balance": null}
    approve_plan               : y or n
"""
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from langgraph.types import Command  # noqa: E402

from graph import build, config  # noqa: E402
from settings import load_env  # noqa: E402

load_env()


def show(payload: dict) -> None:
    cp = payload["checkpoint"]
    print(f"\n=== PAUSED: {cp} ===")
    if payload.get("error"):
        print("!!", payload["error"])
    if cp == "ask_missing_info":
        print(payload["message"])
    elif cp == "confirm_role":
        print(f"Suggested: {payload['suggested_role_id']}  (confidence {payload['confidence']:.2f}) "
              f"- {payload['reason']}")
        for c in payload["candidates"]:
            print(f"  [{c['role_id']}] {c['sector']} / {c['role']}  (match {c['score']})")
        print("Goal read as:", payload["goal_titles"] or "none")
        if payload["cannot_do"]:
            print("I can't do:", payload["cannot_do"])
    elif cp == "choose_path":
        if payload.get("goal_message"):
            print("NOTE:", payload["goal_message"])
        for p in payload["paths"]:
            print(f"  [{p['role_id']}] {p['role']} ({p['sector']}) - {p['kind']}: "
                  f"{p['new_skills']} new skills + {p['level_ups']} level-ups\n      {p['reason']}")
    elif cp == "approve_plan":
        plan = payload["plan"]
        gs = plan["gap_summary"]
        print(f"{plan['current_role']}  ->  {plan['target_role']}   "
              f"({gs['new_skills']} new skills, {gs['level_ups']} level-ups)")
        for phase, items in plan["phases"].items():
            print(f"\n  {phase.upper()}")
            for it in items:
                core = " [core]" if it.get("importance") == "core" else ""
                print(f"    {it['skill']}{core} (level {it['need_level']}, {it['status']})")
                why = (it.get("why") or "").strip()
                if why and not why.startswith("rule:"):     # Fix 2: the AI's reason, shown at last
                    print(f"      why: {why}")
                for label, c in (("take", it["course"]), ("or", it["alternative"])):
                    if c:
                        fee = "unknown" if c.get("your_fee") is None else f"${c['your_fee']:,.2f}"
                        sc = "" if c.get("score") is None else f" match {c['score']:.1f},"
                        print(f"      {label}: {c['title'][:55]}  [{c['provider'][:25]}]{sc} you pay {fee}")
                if it["course"]:
                    warn = "  ⚠ WEAK MATCH - check this course" if it.get("match_quality") == "weak" else ""
                    print(f"            ({it['why_this_course']}){warn}")
                elif it.get("message"):
                    print(f"      - {it['message']}")
        c = plan["cost"]
        print(f"\n  COST  after subsidies ${c['total_after_subsidy']:,.2f}  - credit ${c['credit_used']:,.2f}"
              f"  = you pay ${c['out_of_pocket']:,.2f}   |  about {plan['total_hours']:,.0f} training hours")
        for n in c["notes"]:
            print("   *", n)
        spend = plan.get("spend") or {}
        if spend.get("capped"):                   # Fix 3
            print(f"   ! AI budget (${spend['cap_usd']:.2f}) reached: some steps used the rule-based version")


def answer_for(payload: dict):
    cp = payload["checkpoint"]
    raw = input("> ").strip()
    if cp == "ask_missing_info":
        return json.loads(raw)
    if cp in ("confirm_role", "choose_path"):
        return {"role_id": raw}
    return {"approved": raw.lower().startswith("y"), "feedback": raw}


def main(path: str) -> None:
    graph, cfg = build(), config(uuid.uuid4().hex)
    out = graph.invoke({"profile": json.loads(Path(path).read_text())}, cfg)
    while "__interrupt__" in out:
        payload = out["__interrupt__"][0].value
        show(payload)
        out = graph.invoke(Command(resume=answer_for(payload)), cfg)
    print("\n=== DONE ===\n" + out["final_message"])
    cost = sum(u.get("cost_usd", 0) for u in out.get("usage", []))
    print(f"checkpoints: {out['checkpoints']}   AI cost: ${cost:.4f}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "examples/accounts_exec.json")
