"""Career Progress Guide - Streamlit front end (MyCareersPlan-style).
Run:  python -m streamlit run app.py
The UI only renders the agent's state and relays the user's three decisions; no agent logic lives here."""
from __future__ import annotations

import html
import json
import uuid

import streamlit as st

from careerguide import tools
from careerguide.data import SAMPLE_PROFILES
from careerguide.graph import PHASES, Session
from careerguide.llm import llm_available

st.set_page_config(page_title="MyCareersPlan · Career Progress Guide", page_icon="🧭", layout="wide")

STAGES = [("profile", "Confirm your role and goal"), ("paths", "Choose a path"),
          ("gaps", "See your skill gaps"), ("courses", "Pick your courses"), ("plan", "Approve your plan")]
PHASE_LABEL = {"start": "1 · Start here", "build": "2 · Build", "stand_out": "3 · Stand out"}

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Open+Sans:wght@400;600;700&display=swap');
html, body, [class*="css"], .stApp { font-family: 'Open Sans', sans-serif; }
.block-container { max-width: 1240px; padding-top: 1.6rem; }
header[data-testid="stHeader"] { background: transparent; }
:root { --mag:#c4007f; --pur:#5b2ea6; --ink:#2a1760; --line:#e6dff0; --soft:#f7f3fb; }
h1.brand { color: var(--mag); font-weight: 700; font-size: 2.1rem; margin: 0; line-height: 1.1; }
.tag { color:#3b3552; margin: 4px 0 0 0; }
.h-mag { color: var(--mag); font-weight: 700; font-size: 1.25rem; margin: 6px 0 12px; }
.h-ink { color: var(--ink); font-weight: 700; font-size: 1.3rem; margin: 0 0 12px; }
.focus { background: linear-gradient(135deg,#5b3fc2,#7d52d9); color:#fff; border-radius: 10px; padding: 20px;
  box-shadow: 0 6px 16px rgba(91,63,194,.35); }
.focus .t { font-weight:700; font-size:1.15rem; line-height:1.35; }
.focus .s { margin-top: 10px; font-size:.95rem; opacity:.95; }
.note { font-style: italic; color:#6d6783; font-size:.85rem; text-align:center; margin-top:10px; }
.stat { border:1px solid var(--line); border-radius:8px; padding:16px 20px; background:#fff; }
.stat.green { background:#f1fcf5; border-color:#bfe9cf; }
.stat .k { font-size:.78rem; letter-spacing:.08em; color:#3b3552; text-transform:uppercase; }
.stat .v { font-size:1.9rem; font-weight:700; color:#1f1b2e; line-height:1.3; }
.stat .v small { font-size:1rem; font-weight:400; }
.stat .m { color:#4a4560; font-size:.92rem; }
.insight { background:#faf5fd; border:1px solid var(--line); border-radius:8px; padding:16px 20px; margin-top:14px; }
.insight .k { color: var(--pur); font-weight:700; font-size:.82rem; letter-spacing:.08em; }
.ready { background: linear-gradient(180deg,#eef3ff,#fbf4fb); border-radius: 24px 24px 0 0; padding: 22px 22px 0; margin-top: 26px; }
.tiles { display:flex; gap:12px; overflow:hidden; padding-bottom:18px; }
.tile { flex:1 1 0; min-width:0; background:#fff; border:1px solid var(--line); border-radius:10px; padding:16px;
  color:#4a4560; font-weight:600; font-size:.92rem; min-height:78px; display:flex; align-items:center; gap:8px; }
.tile.on { background: linear-gradient(135deg,#9333ea,#db2777); color:#fff; border:0; box-shadow:0 6px 14px rgba(147,51,234,.35); }
.tile.done { color:#2c7a4b; border-color:#bfe9cf; background:#f4fcf7; }
.st-key-box { border:1px solid #e3b6dd; border-radius:8px; padding: 30px 22px 14px; margin-top:26px; position:relative; background:#fff; }
.st-key-box::before { content:"WHAT YOU CAN DO"; position:absolute; top:-14px; left:20px; background:#c4007f; color:#fff;
  font-weight:700; font-size:.78rem; letter-spacing:.08em; padding:7px 16px; border-radius:6px; }
.box h4 { color: var(--mag); margin: 4px 0 2px; font-size:1.1rem; }
.box p.sub { color:#2a2540; margin: 0 0 14px; }
.lbl { color:#4a4560; font-weight:600; font-size:.82rem; letter-spacing:.08em; text-transform:uppercase; margin:18px 0 8px; }
.chip { display:inline-block; background:#eeeaf3; border-radius:6px; padding:8px 14px; margin:0 8px 8px 0; font-size:.95rem; color:#26213a; }
.chip.have { background:#6d47b8; color:#fff; }
.chip small { opacity:.7; }
.legend span { margin-right: 18px; font-size:.92rem; }
.dot { display:inline-block; width:34px; height:8px; border-radius:6px; vertical-align:middle; margin-right:6px; }
.crd { display:flex; border:1px solid var(--line); border-radius:8px; overflow:hidden; margin-bottom:10px; background:#fff; }
.crd .l { flex:1; padding:14px 18px; }
.crd .p { font-size:.78rem; letter-spacing:.06em; text-transform:uppercase; color:#2a2540; font-weight:600; }
.crd .ti { color:#5b2ea6; font-weight:600; font-size:1.12rem; margin:3px 0 8px; }
.crd .meta { font-size:.8rem; letter-spacing:.05em; color:#3b3552; font-weight:600; text-transform:uppercase; }
.crd .teach { margin-top:8px; font-size:.85rem; color:#4a4560; }
.crd .r { width: 230px; background:#faf3fb; padding:14px 18px; }
.crd .r .k { font-size:.72rem; letter-spacing:.06em; color:#3b3552; text-transform:uppercase; }
.crd .r .v { font-size:1.25rem; font-weight:700; color:#1f1b2e; }
.crd .r .pay { font-size:.85rem; color:#2c7a4b; margin-top:4px; font-weight:600; }
.sumtbl { width:100%; border-collapse:collapse; font-size:.95rem; }
.sumtbl td { padding:7px 4px; border-bottom:1px solid var(--line); }
.sumtbl td:last-child { text-align:right; font-variant-numeric: tabular-nums; }
.sumtbl tr.tot td { font-weight:700; font-size:1.1rem; color:var(--ink); border-bottom:0; }
.phase { color:var(--pur); font-weight:700; margin:20px 0 8px; font-size:1rem; }
.link { color:#1769c2; }
div[data-testid="stSegmentedControl"] button { padding: 10px 26px; font-weight:600; }
.stButton > button[kind="primary"] { background:#6b2fb3; border:0; font-weight:600; }
.stButton > button { border-radius:8px; }
</style>
""", unsafe_allow_html=True)


def esc(x) -> str:
    return html.escape(str(x))


def usd(x: float) -> str:
    return f"${x:,.2f}"


# ---------------------------------------------------------------- session
ss = st.session_state
ss.setdefault("sess", None)
ss.setdefault("todos", [])
ss.setdefault("view", "My career focus")
ss.setdefault("profile", dict(next(iter(SAMPLE_PROFILES.values()))))


def start(profile: dict):
    ss.sess = Session(uuid.uuid4().hex)
    ss.sess.start(profile)


def answer(value: dict):
    ss.sess.answer(value)
    st.rerun()


# ---------------------------------------------------------------- sidebar: the mock portal profile
with st.sidebar:
    st.markdown("### Your profile")
    st.caption("A MyCareersFuture-style mock profile (no live portal access). Edit it or pick a sample.")
    pick = st.selectbox("Sample profile", ["(custom)"] + list(SAMPLE_PROFILES))
    if pick != "(custom)" and ss.get("last_pick") != pick:
        ss.profile = dict(SAMPLE_PROFILES[pick])
        ss.last_pick = pick
        ss.sess = None
    p = ss.profile
    p["role"] = st.text_input("Current role", p["role"])
    c1, c2 = st.columns(2)
    p["age"] = c1.number_input("Age", 15, 80, int(p["age"]))
    p["residency"] = c2.selectbox("Residency", ["citizen", "pr"], ["citizen", "pr"].index(p["residency"]))
    p["status"] = st.selectbox("Status", ["employed", "retrenched", "unemployed"],
                               ["employed", "retrenched", "unemployed"].index(p["status"]))
    p["salary"] = st.number_input("Monthly salary (S$)", 0, 50000, int(p.get("salary", 0)), step=100)
    p["goal"] = st.text_area("Goal (optional)", p.get("goal", ""), height=80)
    if st.button("Analyse my profile", type="primary", use_container_width=True):
        start(dict(p))
        st.rerun()
    st.divider()
    st.caption(f"Path ranking: {'LLM (Groq) with rule fallback' if llm_available() else 'rule-based (no API key found)'}")
    st.caption("The agent reads, compares and calculates. It never edits your profile, enrols, pays or applies.")

sess: Session | None = ss.sess
state = sess.state if sess else {}
pending = sess.pending() if sess else None
stage = pending["stage"] if pending else ("done" if state.get("status") == "approved" else
                                          "needs_info" if state.get("status") == "needs_info" else "idle")
stage_index = {"idle": -1, "needs_info": -1, "profile": 0, "paths": 1, "plan": 4, "done": 5}[stage]

# ---------------------------------------------------------------- header
h1, h2 = st.columns([3, 2])
h1.markdown('<h1 class="brand">MyCareersPlan</h1><p class="tag">Strategise your career move with clarity and confidence.</p>',
            unsafe_allow_html=True)
with h2:
    ss.view = st.segmented_control("view", ["My career focus", "My to-do list"], default=ss.view,
                                   label_visibility="collapsed") or ss.view
st.write("")

# ---------------------------------------------------------------- to-do tab
if ss.view == "My to-do list":
    st.markdown('<div class="h-ink">My to-do list</div>', unsafe_allow_html=True)
    if not ss.todos:
        st.info("Nothing here yet. Use “Add as to-do” on a course in your plan.")
    for i, t in enumerate(ss.todos):
        st.checkbox(f"{t['title']} - {t['provider']}  ·  {t['phase']}", key=f"todo{i}")
    st.caption("This list lives in this app only. The agent never enrols you in anything: "
               "you enrol yourself at MySkillsFuture.")
    st.stop()

# ---------------------------------------------------------------- focus tab
focus_id = state.get("chosen_id") or ss.get("preview_id")
focus = tools.ROLES.get(focus_id) if focus_id else None
left, right = st.columns([1, 2.6], gap="large")

with left:
    st.markdown('<div class="h-mag">I\'m working towards…</div>', unsafe_allow_html=True)
    if focus:
        st.markdown(f'<div class="focus"><div class="t">{esc(focus.title)}</div>'
                    f'<div class="s">Salary range: ${focus.salary[0]:,} - ${focus.salary[1]:,}</div></div>',
                    unsafe_allow_html=True)
    else:
        st.markdown('<div class="focus"><div class="t">No focus yet</div>'
                    '<div class="s">Analyse your profile, then choose a path.</div></div>', unsafe_allow_html=True)
    st.write("")
    if stage == "plan" and st.button("＋  Try another path", use_container_width=True):
        answer({"action": "change_path"})
    st.markdown('<div class="note">The agent suggests 2–3 realistic paths. You choose; you can always go back.</div>',
                unsafe_allow_html=True)
    st.markdown("""
<svg viewBox="0 0 240 190" width="100%" style="margin-top:18px" xmlns="http://www.w3.org/2000/svg">
 <ellipse cx="110" cy="165" rx="88" ry="14" fill="#e8dff5"/>
 <circle cx="60" cy="40" r="16" fill="#e9e4f7"/><circle cx="78" cy="46" r="12" fill="#e9e4f7"/>
 <rect x="170" y="38" width="5" height="95" rx="2" fill="#8c63c9"/><path d="M175 40 h38 l-8 12 8 12 h-38z" fill="#f08aa8"/>
 <rect x="62" y="62" width="82" height="78" rx="18" fill="#b79be0"/><rect x="74" y="78" width="58" height="28" rx="10" fill="#f3b5c4"/>
 <circle cx="92" cy="92" r="4" fill="#4a2c85"/><circle cx="114" cy="92" r="4" fill="#4a2c85"/>
 <line x1="103" y1="62" x2="103" y2="46" stroke="#4a2c85" stroke-width="4"/><circle cx="103" cy="42" r="6" fill="#4a2c85"/>
 <rect x="84" y="140" width="10" height="20" rx="4" fill="#8c63c9"/><rect x="112" y="140" width="10" height="20" rx="4" fill="#8c63c9"/>
 <circle cx="40" cy="132" r="14" fill="#9a6fd6"/><circle cx="40" cy="132" r="5" fill="#fff"/>
</svg>""", unsafe_allow_html=True)

with right:
    # -------- hiring outlook
    if focus:
        n_have = n_gap = None
        if state.get("gaps") is not None:
            n_gap = len(state["gaps"])
            n_have = len(focus.skills) - n_gap
        st.markdown('<div class="h-ink">Hiring outlook for this role</div>', unsafe_allow_html=True)
        a, b = st.columns(2)
        a.markdown(f'<div class="stat green"><div class="k">Currently on MyCareersFuture</div>'
                   f'<div class="v">{focus.jobs:,} <small>Jobs</small></div>'
                   f'<div class="m">Across {focus.companies} active hiring companies</div></div>', unsafe_allow_html=True)
        b.markdown(f'<div class="stat"><div class="k">2026 hiring demand</div><div class="v">{esc(focus.demand)}</div>'
                   f'<div class="m">Mock figures for the prototype</div></div>', unsafe_allow_html=True)
        trend = {"High": "strong and growing", "Moderate": "steady", "Low": "modest, so a clear edge matters"}[focus.demand]
        extra = (f" You already hold {n_have} of its {len(focus.skills)} framework skills; {n_gap} to close."
                 if n_gap is not None else "")
        st.markdown(f'<div class="insight"><div class="k">✦ WHAT THIS MEANS FOR YOU</div>'
                    f'<p style="margin:8px 0 0">Demand for {esc(focus.title)} is {trend}, with {focus.jobs:,} live postings.{extra}</p></div>',
                    unsafe_allow_html=True)
    else:
        st.markdown('<div class="h-ink">Where do you want to go?</div>', unsafe_allow_html=True)
        st.markdown('<div class="insight"><div class="k">✦ HOW THIS WORKS</div><p style="margin:8px 0 0">'
                    'Your profile goes in on the left. The agent maps your role, shortlists realistic next roles, '
                    'finds your skill gaps, matches SkillsFuture courses and works out what you would pay after '
                    'funding. You make the three judgement calls.</p></div>', unsafe_allow_html=True)

    # -------- ways to build your readiness (the five stages)
    tiles = ""
    for i, (_, label) in enumerate(STAGES):
        cls = "on" if i == min(stage_index, 4) and stage_index >= 0 and stage != "done" else \
              "done" if i < stage_index or stage == "done" else ""
        tiles += f'<div class="tile {cls}">{"✓ " if cls == "done" else ""}{esc(label)}</div>'
    st.markdown(f'<div class="ready"><div class="h-ink">Ways to build your readiness</div><div class="tiles">{tiles}</div></div>',
                unsafe_allow_html=True)

    with st.container(key="box"):

        # ======== idle
        if stage == "idle":
            st.markdown("<h4>Start with your profile</h4><p class='sub'>Check the details on the left, then press "
                        "<b>Analyse my profile</b>.</p>", unsafe_allow_html=True)
            st.json(ss.profile, expanded=False)
            if st.button("Analyse my profile", type="primary", key="go"):
                start(dict(ss.profile)); st.rerun()

        # ======== needs info
        elif stage == "needs_info":
            st.markdown("<h4>I need a little more from you</h4>", unsafe_allow_html=True)
            for pr in state.get("problems", []):
                st.warning(pr)

        # ======== checkpoint 1
        elif stage == "profile":
            st.markdown("<h4>Is this the right reading of your profile?</h4><p class='sub'>Your job title is free text; "
                        "I map it to the official Skills Framework role.</p>", unsafe_allow_html=True)
            for n in pending["notices"]:
                st.warning(n)
            cands = pending["candidates"]
            labels = {f"{c['title']}  (match {int(c['score'] * 100)}%)": c["role_id"] for c in cands}
            chosen = st.radio("Your role in the framework", list(labels), key="role_pick")
            goal = st.text_input("Your goal", pending["goal"], key="goal_edit")
            st.info(pending["goal_reading"] if goal == pending["goal"] else "I'll re-read your goal once you confirm.")
            if st.button("Yes, continue", type="primary"):
                answer({"role_id": labels[chosen], "goal": goal})

        # ======== checkpoint 2
        elif stage == "paths":
            st.markdown("<h4>Which direction do you want to explore?</h4><p class='sub'>These are the most realistic next "
                        "roles from where you are. Pick one; I'll work out the rest.</p>", unsafe_allow_html=True)
            paths = pending["paths"]
            if not pending["used_llm"]:
                st.caption("Ranked by skill overlap and goal relevance (offline mode).")
            by_label = {f"{p['title']}": p for p in paths}
            pick_title = st.radio("Paths", list(by_label), key="path_pick", label_visibility="collapsed",
                                  captions=[f"{p['kind']} · {int(p['overlap'] * 100)}% skills match · "
                                            f"{p['n_gaps']} to close — {p['why']}" for p in paths])
            ss.preview_id = by_label[pick_title]["role_id"]
            if st.button("Choose this path", type="primary"):
                answer({"role_id": by_label[pick_title]["role_id"]})

        # ======== checkpoint 3 / final
        elif stage in ("plan", "done"):
            plan = pending["plan"] if stage == "plan" else state["plan"]
            cost = plan["cost"]
            gaps = plan["skill_gaps"]
            target = tools.ROLES[state["chosen_id"]]
            approved = stage == "done"
            st.markdown(f"<h4>Your plan to become a {esc(plan['target_role'])}</h4>"
                        f"<p class='sub'>From {esc(plan['current_role'])}: {len(gaps)} skills to close, in three steps, "
                        f"simpler ones first.</p>", unsafe_allow_html=True)
            if approved:
                st.success("Plan approved. Nothing has been booked or paid: enrol yourself on MySkillsFuture when ready.")

            # skills
            gap_names = {g["skill"]: g for g in gaps}
            have = [s for s in target.skills if s not in gap_names]
            st.markdown('<div class="lbl">Skills required for this role</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="legend"><span><i class="dot" style="background:#6d47b8"></i>Skills I have ({len(have)})</span>'
                        f'<span><i class="dot" style="background:#cfcbd6"></i>Skills to build ({len(gaps)})</span></div>',
                        unsafe_allow_html=True)
            chips = "".join(f'<span class="chip have">{esc(s)}</span>' for s in have)
            chips += "".join(f'<span class="chip">{esc(g["skill"])} <small>L{g["have"]}→L{g["need"]}</small></span>' for g in gaps)
            st.markdown(chips, unsafe_allow_html=True)

            # courses
            cr = cost["credits_available"]
            total_credit = cr["SkillsFuture Credit"] + cr["Mid-Career Credit"]
            st.markdown('<div class="lbl">Recommended courses</div>', unsafe_allow_html=True)
            if total_credit:
                st.markdown(f'<span class="link">{usd(total_credit)} SkillsFuture Credits available</span>', unsafe_allow_html=True)
            with st.expander("VIEW HOW THESE ARE RECOMMENDED"):
                st.caption("Courses carry no skill tags, so each gap skill is matched to course descriptions by "
                           "text similarity. You can swap any course below.")
                for t in state.get("trace", []):
                    st.write(f"**{t['stage']}** · {t['msg']}")

            line_by_id = {l["id"]: l for l in cost["lines"]}
            course_by_id = {c["id"]: c for c in plan["courses"]}
            shown: set[str] = set()
            for ph in PHASES:
                rows = plan["direction"][ph]
                if not rows:
                    continue
                st.markdown(f'<div class="phase">{PHASE_LABEL[ph]}</div>', unsafe_allow_html=True)
                for r in rows:
                    cid = r["course"]
                    if not cid or cid in shown:
                        continue
                    shown.add(cid)
                    c, ln, full = tools.COURSES[cid], line_by_id[cid], course_by_id[cid]
                    st.markdown(
                        f'<div class="crd"><div class="l"><div class="p">{esc(c.provider)}</div>'
                        f'<div class="ti">{esc(c.title)}</div>'
                        f'<div class="meta">⏱ {esc(c.duration)} &nbsp; ▭ {esc(c.mode)} &nbsp; · {c.hours} hrs</div>'
                        f'<div class="teach">Closes: {esc(", ".join(full["teaches"]))}</div></div>'
                        f'<div class="r"><div class="k">Full course fee</div><div class="v">{usd(c.fee)}</div>'
                        f'<div class="pay">You pay {usd(ln["you_pay"])}</div></div></div>', unsafe_allow_html=True)
                    if not approved:
                        skill = full["teaches"][0]
                        opts = [o["course_id"] for o in pending["options"][skill]]
                        a1, a2 = st.columns([3, 1.4])
                        new = a1.selectbox(f"Swap the course for “{skill}”", opts, index=opts.index(cid),
                                           format_func=lambda i: f"{tools.COURSES[i].title} — {usd(tools.COURSES[i].fee)}",
                                           key=f"swap_{ph}_{cid}", label_visibility="collapsed")
                        if new != cid:
                            answer({"action": "swap", "skill": skill, "course_id": new})
                        if a2.button("＋ Add as to-do", key=f"td_{cid}"):
                            if not any(t["title"] == c.title for t in ss.todos):
                                ss.todos.append({"title": c.title, "provider": c.provider, "phase": PHASE_LABEL[ph]})
                            st.toast("Added to your to-do list")

            # cost
            st.markdown('<div class="lbl">What it costs after funding</div>', unsafe_allow_html=True)
            rows = [("Full course fees", cost["full_fee"]),
                    (f"Fee subsidy ({int(cost['rate'] * 100)}%)", -cost["subsidy"]),
                    ("SkillsFuture Credit", -cost["skillsfuture_credit"]),
                    ("Mid-Career Credit", -cost["mid_career_credit"])]
            body = "".join(f"<tr><td>{esc(k)}</td><td>{'−' if v < 0 else ''}{usd(abs(v))}</td></tr>" for k, v in rows if v or k == "Full course fees")
            st.markdown(f'<table class="sumtbl">{body}<tr class="tot"><td>You pay</td><td>{usd(cost["you_pay"])}</td></tr></table>',
                        unsafe_allow_html=True)
            for n in cost["notes"]:
                st.caption("ℹ " + n)

            st.write("")
            if approved:
                st.download_button("Download plan.json", json.dumps(plan, indent=2), "plan.json", "application/json",
                                   type="primary")
                with st.expander("View plan.json"):
                    st.json(plan)
            else:
                b1, b2 = st.columns([1, 3])
                if b1.button("Approve this plan", type="primary"):
                    answer({"action": "approve"})
                b2.caption("Approving saves the plan only. I won't enrol you or spend your credits.")

