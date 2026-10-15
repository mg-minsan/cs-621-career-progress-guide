"""THROWAWAY POC: can JSON skill names support a useful, reviewable coverage flow?

Run from repo root: .venv/bin/python -m streamlit run prototype_skill_gaps/app.py
Read-only career data; profile and LLM reports live only in session memory.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import os
from pathlib import Path
import sys

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from guide import run as run_guide
from lookup import CareerLookup, DEFAULT_DB
from openai import APIConnectionError, APIStatusError, APITimeoutError
from skill_coverage import GAP_STATUSES, PROMPT_VERSION, analyse_gaps, analysis_payload

# Load explicitly: the project's profile.py shares a name with Python's profiler.
spec = importlib.util.spec_from_file_location("career_profile_schema", ROOT / "profile.py")
assert spec is not None and spec.loader is not None
profile_schema = importlib.util.module_from_spec(spec)
spec.loader.exec_module(profile_schema)

st.set_page_config(page_title="LLM skill gaps POC", layout="wide")
st.title("Skill gaps · LangChain + OpenAI POC")
st.warning("Prototype only. Skill mappings and potential gaps are inferred by an LLM, "
           "not verified assessments. Missing profile evidence does not prove a missing "
           "skill. Required proficiency and readiness are NOT assessed.")

with st.sidebar:
    st.header("Local data")
    db_path = Path(st.text_input("Career database", value=str(DEFAULT_DB), key="database_path")).expanduser()
    st.caption("Read-only. Profiles and reports are not saved automatically.")
    st.caption("Role discovery uses the existing hybrid index when available, otherwise "
               "disclosed keyword fallback. Only the role needs user selection.")
    st.header("OpenAI")
    api_key = st.text_input("OpenAI API key (or use OPENAI_API_KEY)", type="password",
                            key="openai_api_key").strip() or os.environ.get("OPENAI_API_KEY", "")
    model = st.text_input("OpenAI model", value=os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"),
                          key="openai_model").strip()
    if not api_key:
        st.info("Add an API key to enable gap analysis. Role search still works locally.")
    st.caption("Analysis sends the displayed skill claims and recorded role requirements "
               "to OpenAI and may incur API charges. LangSmith tracing is disabled.")

st.header("1 · Provide a JSON profile")
sample = (Path(__file__).parent / "sample_profile.json").read_text(encoding="utf-8")
profile_text = st.text_area("Paste profile JSON", value=sample, height=180, key="profile_json")
upload = st.file_uploader("Or upload a JSON profile (takes precedence over pasted JSON)", type="json")
try:
    raw_profile = json.loads(upload.getvalue() if upload is not None else profile_text)
except (ValueError, UnicodeError) as exc:
    st.error(f"Invalid JSON: {exc}")
    st.stop()
validated = profile_schema.validate_profile(raw_profile)
if validated["status"] != "ok":
    st.error("Profile validation failed.")
    st.json(validated["errors"])
    st.stop()
profile = validated["data"]
skills = profile["skills"]
st.write("Profile skills:", ", ".join(skill["name"] for skill in skills) or "(none supplied)")
if not skills:
    st.info("No skills supplied. The report can only say insufficient information, not confirmed gaps.")

st.header("2 · Select a recorded target role")
query = st.text_input("Target title, description, or canonical role ID", value="Data Analyst", key="target_query")
context = (str(db_path.resolve()), query)
if st.button("Find roles", type="primary"):
    st.session_state.pop("role_candidates", None)
    st.session_state.pop("role_selection", None)
    st.session_state["role_context"] = context
    try:
        if not query.strip():
            raise ValueError("Enter a target role title, description, or canonical ID.")
        with CareerLookup(db_path) as lookup:
            exact = lookup.get_role(query.strip())
            if exact["status"] != "ok":
                exact = lookup.resolve_role(query)
            if exact["status"] == "ok":
                role = exact["data"]
                candidates = [{"role_id": role["role_id"], "title": role["role_title"],
                               "sector": role["sector"], "track": role["track"]}]
                disclosure = "Exact recorded target found."
            elif exact["status"] == "ambiguous":
                candidates = [{"role_id": role["role_id"], "title": role["role_title"],
                               "sector": role["sector"], "track": role["track"]}
                              for role in exact["data"]]
                disclosure = "Exact title is ambiguous. Choose a sector/track; no automatic pick."
            else:
                result = run_guide({"skills": [s["name"] for s in skills], "interests": []},
                                   role_title=query, db_path=db_path)
                candidates = result["suggestions"]
                disclosure = result["retrieval_disclosure"]
        st.session_state["role_candidates"] = candidates
        st.session_state["role_disclosure"] = disclosure
    except Exception as exc:
        # Prototype boundary: show DB/index errors rather than silently falling back.
        st.error(f"Role discovery failed: {exc}")

if st.session_state.get("role_context") != context or "role_candidates" not in st.session_state:
    st.info("Click Find roles, then explicitly select a recorded role.")
    st.stop()
st.info(st.session_state["role_disclosure"])
candidates = st.session_state["role_candidates"]
if not candidates:
    st.info("No recorded roles matched the supplied target.")
    st.stop()
by_id = {candidate["role_id"]: candidate for candidate in candidates}
role_id = st.selectbox(
    "Choose the role to compare (no automatic approximate selection)", list(by_id),
    index=None, key="role_selection",
    format_func=lambda rid: f"{by_id[rid]['title']} · {by_id[rid]['sector']} / "
                            f"{by_id[rid]['track']} · {rid}",
)
with st.expander("Role discovery evidence"):
    for candidate in candidates:
        st.write(f"{candidate['title']} · {candidate['sector']} / {candidate['track']}")
        st.code(candidate["role_id"])
        if candidate.get("description"):
            st.write(candidate["description"])
        if candidate.get("evidence"):
            st.json(candidate["evidence"])
        if candidate.get("sources"):
            st.write("Sources:", candidate["sources"])
if role_id is None:
    st.stop()
try:
    with CareerLookup(db_path) as lookup:
        recorded = lookup.get_role(role_id)
except Exception as exc:
    st.error(f"Role lookup failed: {exc}")
    st.stop()
if recorded["status"] != "ok":
    st.error("Selected role no longer exists. Find roles again.")
    st.stop()
role = recorded["data"]
requirements = role["skills"]
st.subheader(f"{role['role_title']} · {role['sector']} / {role['track']}")
st.write(role["description"] or "No recorded description.")
with st.expander("Canonical role and spreadsheet sources"):
    st.code(role_id)
    st.json(recorded["source_records"])
if not requirements:
    st.info("This role has no recorded requirements. Gap analysis cannot be performed.")
    st.stop()

payload = analysis_payload(skills, role, requirements)
report_context = hashlib.sha256(json.dumps(
    [str(db_path.resolve()), profile, payload, requirements, model, PROMPT_VERSION],
    sort_keys=True, default=str).encode()).hexdigest()
if st.session_state.get("report_context") != report_context:
    st.session_state["report_context"] = report_context
    st.session_state.pop("gap_rows", None)

st.header("3 · Analyse skill gaps automatically")
st.info("Only the target role needs confirmation. The LLM maps your skills and infers "
        "potential gaps automatically—there are no per-skill confirmation steps.")
st.caption("Clicking Analyse sends the payload below to OpenAI. Names alone support only "
           "tentative skill-area coverage, not mastery of a required framework level. "
           "Results are reused in this session; ordinary UI reruns do not call the API.")
with st.expander("Exact data sent to OpenAI (no API key or unrelated profile fields)"):
    st.json(payload, expanded=False)
if st.button("Analyse skill gaps with OpenAI", type="primary", key="analyse_gaps",
             disabled=not api_key or not model):
    st.session_state.pop("gap_rows", None)
    try:
        with st.spinner("LangChain + OpenAI are analysing every recorded requirement…"):
            st.session_state["gap_rows"] = analyse_gaps(
                skills, role, requirements, model=model, api_key=api_key)
    except APITimeoutError:
        st.error("OpenAI timed out. No report was accepted. Retry when ready.")
    except APIConnectionError:
        st.error("Could not connect to OpenAI. Check your network connection and retry.")
    except APIStatusError as exc:
        st.error(f"OpenAI rejected the request (HTTP {exc.status_code}). Check your API key, "
                 "model access, quota and rate limits. No report was accepted.")
    except ValueError:
        st.error("The model response failed schema or evidence validation. Every requirement "
                 "must be included exactly once with valid profile references. No partial "
                 "report was accepted; retry or choose another supported model.")
    except Exception as exc:
        # Log only the type: provider responses may contain credentials or profile data.
        logging.getLogger(__name__).warning("Gap analysis failed (%s)", type(exc).__name__)
        st.error("Analysis failed unexpectedly. No report was accepted. The server log "
                 "contains the error type, without the provider response or profile data.")
if "gap_rows" not in st.session_state:
    st.caption("Select a role, configure OpenAI, and click Analyse to generate the report.")
    st.stop()
rows = st.session_state["gap_rows"]

st.header("4 · LLM skill-gap report")
counts = {status: sum(row["status"] == status for row in rows) for status in GAP_STATUSES}
for column, (status, count) in zip(st.columns(4), counts.items()):
    column.metric(status.replace("_", " ").title(), count)
st.dataframe([
    {"Required skill": row["title"], "Code": row["code"], "Required level": row["required_level"],
     "LLM finding": row["status"], "Profile skills": ", ".join(row["mapped_profile_skills"]),
     "Reason": row["rationale"], "Scope not evidenced": "; ".join(row["missing_scope"]),
     "Uncertainty": row["uncertainty"], "Proficiency": row["proficiency_status"]}
    for row in rows
], hide_index=True, width="stretch")
st.caption("All findings are system-inferred. Covered means the profile represents a skill "
           "area, not verified required-level competence. Potential gap means scope not "
           "evidenced in this profile, not an established deficiency.")
with st.expander("Mapping rationale, profile evidence, recorded definitions and citations"):
    for row in rows:
        st.subheader(f"{row['title']} · {row['status']}")
        st.write(row["rationale"])
        st.write("Scope not evidenced:", row["missing_scope"] or "No specific missing scope identified.")
        st.write("Uncertainty:", row["uncertainty"])
        st.write(row["definition"] or "Framework definition not recorded.")
        st.write(row["proficiency_description"] or "Required proficiency description not recorded.")
        st.json(row)
report = {"prototype": True, "profile": profile, "role_id": role_id,
          "role_title": role["role_title"], "sector": role["sector"], "track": role["track"],
          "analysis_method": "langchain_openai", "model": model, "prompt_version": PROMPT_VERSION,
          "role_source_records": recorded["source_records"], "counts": counts,
          "proficiency_status": "not_assessed", "requirements": rows,
          "disclaimer": "LLM-inferred coverage and potential gaps, not verified competence or readiness."}
st.download_button("Download gap report JSON", json.dumps(report, indent=2, default=str),
                   file_name="prototype-skill-gaps.json", mime="application/json")
with st.expander("Full current state (prototype)"):
    st.json(report, expanded=False)
