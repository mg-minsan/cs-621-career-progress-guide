"""
STEP 6 - Streamlit viewer for the Career Progress Guide.

    streamlit run src/app.py

Ideas shown here (cite in the report):
  - one graph, many conversations: each run is a thread_id on the checkpointer
  - interrupt() pauses the graph; the page shows the payload; the button sends
    Command(resume=...) and the graph continues from the same node
  - the thread_id sits in the page URL (?thread=...), so a browser refresh
    resumes the paused run from the checkpointer instead of starting again
  - the page never decides anything itself: every choice goes back through the
    graph, so the same validation as the CLI and the evals applies

The page is a VIEW. All rules live in graph.py / funding.py / plan_rules.py.
Look and icons: ui_art.py (original SVG doodles, no external images).
"""
from __future__ import annotations

import json
import os
import re
import sys
import uuid
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
from langgraph.types import Command  # noqa: E402

import ui_art as art  # noqa: E402
from settings import load_env  # noqa: E402

load_env()

STEPS = [("profile", "Your profile"), ("confirm_role", "Confirm job"),
         ("choose_path", "Choose a path"), ("approve_plan", "Review plan"), ("done", "Done")]
RESIDENCY = {"Singapore Citizen": "citizen", "Permanent Resident": "pr", "Other": "other"}

st.set_page_config(page_title="Career Progress Guide", page_icon="🧭", layout="wide")
st.markdown(art.CSS, unsafe_allow_html=True)


# ------------------------------------------------------------------ graph (one per process)
@st.cache_resource(show_spinner="Loading the course index and models (first time only)...")
def get_graph():
    import graph as g
    from course_search import SearchError
    note = ""
    try:
        g.get_index()                              # warm the course index once
    except SearchError as e:                       # app only: fall back so a teammate can still try it
        os.environ["CAREER_SEARCH_MODE"] = "bm25"  # (the evals never fall back; they fail loudly)
        g._INDEX = None
        g.get_index()
        note = f"Meaning search unavailable ({e}). Using keyword search (BM25) only."
    return g.build(), g, note


def snapshot(graph, cfg):
    snap = graph.get_state(cfg)
    if not snap.values:
        return None, None, {}
    pending = [i.value for i in getattr(snap, "interrupts", ())]
    if pending:
        return pending[0]["checkpoint"], pending[0], snap.values
    if snap.values.get("final_message"):
        return "done", None, snap.values
    return "error", None, snap.values               # stopped without finishing (an exception)


def run(graph, cfg, inp) -> None:
    try:
        with st.spinner("The agent is thinking..."):
            graph.invoke(inp, cfg)
        st.session_state.pop("error", None)
    except Exception as e:                           # shown on the page, never swallowed
        st.session_state["error"] = f"{type(e).__name__}: {e}"
    st.rerun()


def resume(graph, cfg, answer) -> None:
    run(graph, cfg, Command(resume=answer))


def new_thread() -> None:
    st.query_params.clear()
    st.session_state.clear()
    st.rerun()


def money(x) -> str:
    return "unknown" if x is None else f"${x:,.2f}"


def html(s: str) -> None:
    st.markdown(s, unsafe_allow_html=True)


def heading(icon: str, text: str, sub: str = "") -> None:
    """Icon + st.subheader (kept as a real subheader so tests and screen readers see it)."""
    a, b = st.columns([1, 12], vertical_alignment="center")
    a.markdown(art.icon(icon, 54), unsafe_allow_html=True)
    b.subheader(text, anchor=False)
    if sub:
        st.caption(sub)


# ------------------------------------------------------------------ sidebar
with st.sidebar:
    html(f'<div style="display:flex;align-items:center;gap:10px">{art.icon("choose_path", 46)}'
         f'<div class="serif" style="font-family:\'DM Serif Display\',serif;font-size:1.35rem;line-height:1.1;'
         f'color:{art.TEAL_DARK}">'
         f'Career Progress<br>Guide</div></div>')
    st.caption("Profile in → costed SkillsFuture plan out. You decide at every checkpoint.")
    has_key = bool(os.getenv("ANTHROPIC_API_KEY"))
    fake = st.toggle("Offline demo (rules only, no Claude)", value=not has_key,
                     help="Uses the no-AI rules baseline. Needs no API key and costs nothing.")
    if not fake and not has_key:
        st.error("ANTHROPIC_API_KEY is not set. In PowerShell:\n\n"
                 "`$env:ANTHROPIC_API_KEY = \"sk-ant-...\"`\n\nthen restart the app.")
        st.stop()
    os.environ["CAREER_FAKE"] = "1" if fake else "0"     # read at call time by llm_steps.fake_mode()
    graph, g, search_note = get_graph()
    html(f'<span class="pill {"y" if fake else "p"}">{"Rules only · $0" if fake else "Claude Sonnet"}</span>'
         f'<span class="pill t">search: {g.get_index().mode}</span>')
    if search_note:
        st.warning(search_note)

thread = st.query_params.get("thread")
cfg = g.config(thread) if thread else None
where, payload, values = snapshot(graph, cfg) if cfg else (None, None, {})
if where is None:
    where = "profile"

with st.sidebar:
    if thread:
        st.caption(f"thread_id `{thread[:8]}…` · refresh-safe (it is in the URL)")
        if st.button("Start a new plan", width="stretch"):
            new_thread()
    if values.get("usage"):
        cost = sum(u.get("cost_usd", 0) for u in values["usage"])
        st.metric("AI cost so far", f"${cost:.4f}")
        st.caption(f"{len(values['usage'])} AI steps")
    if values.get("checkpoints"):
        st.caption("Checkpoints answered: " + " → ".join(values["checkpoints"]))
    html('<div style="margin-top:1.2rem;font-size:.78rem;opacity:.7">I only advise. I never enrol, '
         'pay or apply for you.</div>')

# ------------------------------------------------------------------ roadmap progress bar
order = [k for k, _ in STEPS]
now = order.index(where) if where in order else 0
html(f'<div class="topbar"><span>Career Progress Guide</span><span>SkillsFuture · CS621</span>'
     f'<span>Step {now + 1} of {len(STEPS)}</span></div>')
html(art.roadmap_html(STEPS, now))

if st.session_state.get("error"):
    st.error("The agent stopped: " + st.session_state["error"])
    st.caption("Nothing was saved or sent. You can start again.")
    if st.button("Start again"):
        new_thread()
    st.stop()


# ------------------------------------------------------------------ 0. profile
if where == "profile":
    left, right = st.columns([1.1, 1], vertical_alignment="center")
    with left:
        html('<div class="big-title">Career<br><span>Planner</span></div>'
             '<div class="lead">Tell me your job and goal. I find realistic next roles in the SkillsFuture '
             'framework, the skills you are missing, real courses, and what they cost <b>you</b> after '
             'subsidies.</div>'
             '<div class="check">You confirm your job</div><div class="check">You pick the path</div>'
             '<div class="check">You approve the plan</div>')
    with right:
        html(art.hero_img())
    st.write("")
    with st.container(key="formcard"):
        heading("profile", "Tell me about yourself", "Only these details are used.")
        with st.form("profile", border=False):
            c1, c2 = st.columns(2)
            role = c1.text_input("Current job title", placeholder="e.g. Accounts Executive")
            goal = c2.text_input("Goal (optional)", placeholder="e.g. move into data analyst")
            c3, c4, c5 = st.columns(3)
            age = c3.number_input("Age", min_value=16, max_value=100, value=35)
            res = c4.selectbox("Residency", list(RESIDENCY))
            status = c5.selectbox("Status", ["employed", "retrenched", "unemployed", "student"])
            c6, c7 = st.columns([2, 1], vertical_alignment="bottom")
            bal = c6.number_input("SkillsFuture Credit balance ($)", min_value=0.0, value=500.0, step=50.0)
            unknown = c7.checkbox("I don't know my balance", value=False)
            go = st.form_submit_button("Make my plan ✨", type="primary")
    if go:
        if not role.strip():
            st.warning("Please enter your current job title.")
            st.stop()
        profile = {"role": role.strip(), "age": int(age), "residency": RESIDENCY[res], "status": status}
        if goal.strip():
            profile["goal"] = goal.strip()
        if not unknown:
            profile["credit_balance"] = bal
        tid = uuid.uuid4().hex
        st.query_params["thread"] = tid
        run(graph, g.config(tid), {"profile": profile})

# ------------------------------------------------------------------ ask_missing_info
elif where == "ask_missing_info":
    with st.container(key="card0"):
        heading("warning", "I need a few more details")
        st.info(payload["message"])
        if payload.get("error"):
            st.error(payload["error"])
        miss = " ".join(payload["missing"])
        with st.form("missing", border=False):
            ans = {}
            if "role" in miss:
                ans["role"] = st.text_input("Current job title")
            if "residency" in miss:
                ans["residency"] = RESIDENCY[st.selectbox("Residency", list(RESIDENCY))]
            if "age" in miss:
                ans["age"] = int(st.number_input("Age", 16, 100, 35))
            if "credit_balance" in miss:
                b = st.number_input("SkillsFuture Credit balance ($)", min_value=0.0, value=0.0, step=50.0)
                ans["credit_balance"] = None if st.checkbox("I don't know") else b
            ok = st.form_submit_button("Continue", type="primary")
    if ok:
        resume(graph, cfg, ans or {"credit_balance": None})   # never an empty dict (graph.py note)

# ------------------------------------------------------------------ confirm_role
elif where == "confirm_role":
    heading("confirm_role", "Which of these is your current job?",
            "The framework has 2,030 jobs and some names repeat across sectors, so you confirm it.")
    if payload.get("error"):
        st.error(payload["error"])
    if payload.get("cannot_do"):
        st.warning("I can't do these for you: " + "; ".join(payload["cannot_do"])
                   + ". I only advise; enrolling, paying and applying are up to you.")
    cands = payload["candidates"]
    sug = payload.get("suggested_role_id")
    if sug:
        st.success(f"My suggestion: **{next((c['role'] for c in cands if c['role_id'] == sug), sug)}** "
                   f"(confidence {payload['confidence']:.0%}). {payload['reason']}")
    else:
        st.info("I'm not sure which one fits, so please pick.")
    labels = {c["role_id"]: f"**{c['role']}**  ·  {c['sector']}  ·  name match {c['score']:.0%}" for c in cands}
    ids = list(labels)
    pick = st.radio("Your job", ids, index=ids.index(sug) if sug in ids else 0,
                    format_func=lambda i: labels[i], label_visibility="collapsed")
    if payload.get("goal_titles"):
        html('I read your goal as: ' + "".join(f'<span class="pill b">{t}</span>' for t in payload["goal_titles"]))
    st.write("")
    if st.button("Yes, this is my job", type="primary"):
        resume(graph, cfg, {"role_id": int(pick)})

# ------------------------------------------------------------------ choose_path
elif where == "choose_path":
    heading("choose_path", "Where would you like to go next?",
            "Fewer skills to gain = a faster move. Pick one to see the full costed plan.")
    if payload.get("goal_message"):
        st.warning(payload["goal_message"])
    if payload.get("error"):
        st.error(payload["error"])
    for n, p in enumerate(payload["paths"]):
        goal_match = p.get("kind") == "goal_match"
        with st.container(key=f"card{n % 5}_{p['role_id']}"):
            a, b, c = st.columns([1, 7, 3], vertical_alignment="center")
            a.markdown(art.icon("goal" if goal_match else "nearby", 56), unsafe_allow_html=True)
            b.markdown(f"#### {p['role']}")
            b.markdown(f'<span class="pill {"p" if goal_match else "t"}">'
                       f'{"🎯 matches your goal" if goal_match else "↗ nearby move"}</span>'
                       f'<span class="pill b">{p["sector"]}</span>', unsafe_allow_html=True)
            if p.get("reason"):
                b.caption(p["reason"])
            c.markdown(f'<div style="text-align:center"><div style="font-family:\'DM Serif Display\',serif;'
                       f'font-size:2.3rem;line-height:1;color:{art.TEAL_DARK}">{p["new_skills"] + p["level_ups"]}</div>'
                       f'<div class="small" style="font-size:.8rem">skills to gain<br>{p["new_skills"]} new · '
                       f'{p["level_ups"]} level-ups</div></div>', unsafe_allow_html=True)
            if c.button("Plan this path", key=f"pick_{p['role_id']}", type="primary", width="stretch"):
                resume(graph, cfg, {"role_id": int(p["role_id"])})

# ------------------------------------------------------------------ approve_plan
elif where == "approve_plan":
    plan = payload["plan"]
    gs, c = plan["gap_summary"], plan["cost"]
    heading("approve_plan", f"{plan['current_role']}  →  {plan['target_role']}",
            "Your plan, in three phases. Check it, then approve or say no.")
    # Keep review styling here so a page rerun picks up changes even when the
    # imported theme module is still cached in the running Streamlit process.
    html(f"""<style>
    div.st-key-target_role_about {{
        background: {art.TEAL_SOFT} !important; color: {art.NAVY};
        border: 1px solid {art.TEAL_UI}; border-radius: 18px;
        padding: 20px 24px; margin-bottom: 16px;
        width: 100%; box-sizing: border-box;
    }}
    div.st-key-target_role_about [data-testid="stMarkdownContainer"] {{
        width: 100% !important; max-width: none !important;
    }}
    div.st-key-target_role_about [data-testid="stMarkdownContainer"] p,
    div.st-key-target_role_about [data-testid="stMarkdownContainer"] li {{
        font-size: .95rem; line-height: 1.65;
    }}
    div.st-key-target_role_about [data-testid="stMarkdownContainer"] li {{margin-bottom: .3rem;}}
    div.st-key-target_role_about [data-testid="stMarkdownContainer"] li p {{margin-bottom: 0;}}
    </style>""")
    with st.container(key="target_role_about"):
        st.markdown("**About your target role**")
        details_key = f"role_details_{thread}"
        expanded = st.session_state.get(details_key, False)
        description = (plan.get("target_role_description") or "").strip()
        # Plans already paused at review may predate the description field.
        if not description and values.get("target_role_id") is not None:
            description = (g.get_role(values["target_role_id"]).get("description") or "").strip()
        if description:
            sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", description)
            shown = sentences if expanded else sentences[:2]
            # Short paragraphs keep the full description readable when expanded.
            st.markdown("\n\n".join(" ".join(shown[i:i + 3]) for i in range(0, len(shown), 3)))
        else:
            st.caption("No framework description is available for this role.")
        tasks = plan.get("target_role_tasks")
        if tasks is None and values.get("target_role_id") is not None:
            from lookups import get_role_tasks
            tasks = get_role_tasks(values["target_role_id"])
        if tasks:
            st.markdown("**Tasks include:**")
            shown_tasks = tasks if expanded else tasks[:3]
            st.markdown("\n".join(f"- {' '.join(task.split())}" for task in shown_tasks))
        if (description and len(sentences) > 2) or (tasks and len(tasks) > 3):
            st.button("Show less" if expanded else "Show more",
                      key=f"toggle_{details_key}",
                      on_click=lambda: st.session_state.__setitem__(details_key, not expanded))
        if description or tasks:
            st.caption("Source: SkillsFuture Skills Framework")
    html(art.tiles_html([
        ("skills", "Skills to gain", str(gs["new_skills"] + gs["level_ups"]),
         f"{gs['new_skills']} new · {gs['level_ups']} level-ups"),
        ("subsidy", "After subsidies", money(c["total_after_subsidy"]), "course fees for you"),
        ("credit", "SkillsFuture Credit", "−" + money(c["credit_used"]), "applied once, across the plan"),
        ("pay", "You pay", money(c["out_of_pocket"]), f"about {plan['total_hours']:,.0f} training hours"),
    ]))
    for n in c["notes"]:
        st.caption("• " + n)
    st.caption(f"Funding rules checked on {c['rules_checked_on']}. Check course pages before you enrol.")

    for key, items in plan["phases"].items():
        html(art.phase_html(key, len(items)))
        for it in items:
            course = it["course"]
            weak = it.get("match_quality") == "weak"
            with st.expander(f"{'⚠️ ' if weak else ''}**{it['skill']}** · level {it['need_level']} "
                             f"({'new' if it['status'] == 'missing' else 'level up'})"
                             + (f" · {money(course.get('your_fee'))}" if course else " · no course found")):
                if not course:
                    st.info(it.get("message") or "No strong course found. Search this skill yourself.")
                    continue
                if weak:
                    st.warning("Weak match: check this course really covers the skill.")
                st.markdown(f"**{course['title']}**  \n{course['provider']} · {course.get('hours') or '?'} h · "
                            f"course ref `{course['course_ref']}` · you pay **{money(course.get('your_fee'))}**")
                st.caption(it["why_this_course"])
                if course.get("schemes"):
                    html("".join(f'<span class="pill t">{s}</span>' for s in course["schemes"]))
                alt = it.get("alternative")
                if alt:
                    st.caption(f"Alternative: {alt['title']} ({alt['provider']}) · you pay {money(alt.get('your_fee'))}")

    st.write("")
    with st.container(key="card2_decide"):
        fb = st.text_input("Anything to tell me? (optional)")
        a, b, _ = st.columns([1.2, 1, 3])
        if a.button("Approve plan", type="primary"):
            resume(graph, cfg, {"approved": True, "feedback": fb})
        if b.button("Not for me"):
            resume(graph, cfg, {"approved": False, "feedback": fb})

# ------------------------------------------------------------------ done
elif where == "done":
    ok = values.get("decision", {}).get("approved")
    plan = values["plan"]
    if ok:
        html(art.banner_html("Your plan is ready!",
                             f"{plan['current_role']} → {plan['target_role']} · you pay "
                             f"{money(plan['cost']['out_of_pocket'])}"))
        st.success(values["final_message"])
    else:
        st.info(values["final_message"])
    a, b, _ = st.columns([1.3, 1.1, 2])
    a.download_button("Download plan (JSON)", json.dumps(plan, indent=2),
                      file_name="career_plan.json", mime="application/json")
    if b.button("Start a new plan", key="new_main"):
        new_thread()
    with st.expander("Agent trace (for the report)"):
        st.write("Checkpoints:", " → ".join(values.get("checkpoints", [])))
        for n in values.get("notes", []):
            st.caption("• " + n)
        st.dataframe([{k: u.get(k) for k in ("step", "input_tokens", "output_tokens", "cost_usd")}
                      for u in values.get("usage", [])], width="stretch")

else:
    st.error("This run stopped before finishing (see the error above, or start again).")
    if st.button("Start again"):
        new_thread()
