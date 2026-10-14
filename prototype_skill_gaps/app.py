"""THROWAWAY POC: can JSON skill names support a useful, reviewable coverage flow?

Run from repo root: .venv/bin/python -m streamlit run prototype_skill_gaps/app.py
Read-only career data; profile and confirmations live only in session memory.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from guide import run as run_guide
from lookup import CareerLookup, DEFAULT_DB
from skill_coverage import build_coverage

# Load explicitly: the project's profile.py shares a name with Python's profiler.
spec = importlib.util.spec_from_file_location("career_profile_schema", ROOT / "profile.py")
assert spec is not None and spec.loader is not None
profile_schema = importlib.util.module_from_spec(spec)
spec.loader.exec_module(profile_schema)

st.set_page_config(page_title="Skill coverage POC", layout="wide")
st.title("Skill coverage · Streamlit POC")
st.warning("Prototype only. Matched means a profile name/code or confirmed mapping—not "
           "verified competence. Not listed is not proof you lack a skill. "
           "Proficiency and readiness are NOT assessed.")

with st.sidebar:
    st.header("Local data")
    db_path = Path(st.text_input("Career database", value=str(DEFAULT_DB), key="database_path")).expanduser()
    st.caption("Read-only. No profile is written to disk or sent to an external model.")
    st.caption("Role discovery uses the existing hybrid index when available, otherwise "
               "disclosed keyword fallback. Skill matching uses local in-memory vectors.")

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
    st.info("No skills supplied. Requirements will be not listed, not confirmed gaps.")

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
    st.info("This role has no recorded requirements. Coverage cannot be assessed.")

# Bind confirmations to the profile, role and database—not to stale UI selections.
report_context = hashlib.sha256(json.dumps(
    [str(db_path.resolve()), role_id, skills], sort_keys=True).encode()).hexdigest()
if st.session_state.get("report_context") != report_context:
    st.session_state["report_context"] = report_context
    st.session_state["confirmed_mappings"] = {}
rows = build_coverage(skills, requirements, st.session_state["confirmed_mappings"])

st.header("3 · Review possible skill mappings")
st.caption("Exact names/codes are self-reported coverage. Other candidates combine word "
           "overlap and hash-ngram vectors over this role's titles, definitions and "
           "required proficiency descriptions. Top-three and 0.25 vector threshold are "
           "unvalidated POC heuristics; scores are relevance signals, not proficiency.")
with st.expander("Confirm or clear mappings", expanded=any(r["status"] == "possible_match" for r in rows)):
    if skills and requirements:
        with st.form("confirm_skill_mappings"):
            pending = {}
            for row in rows:
                if row["mapping_method"] == "exact_name_or_code":
                    continue
                candidate_indexes = {c["profile_index"] for c in row["candidates"]}
                options = [-1, *range(len(skills))]
                current = st.session_state["confirmed_mappings"].get(row["requirement_key"], -1)
                chosen = st.selectbox(
                    f"{row['title']} · {row['code']} · required level {row['required_level']}",
                    options, index=options.index(current),
                    key=f"mapping-{report_context}-{row['requirement_key']}",
                    format_func=lambda i, suggested=candidate_indexes: "Unconfirmed / not listed" if i == -1
                    else f"{skills[i]['name']} (profile entry {i + 1})" +
                         (" — suggested" if i in suggested else ""),
                )
                if chosen >= 0:
                    pending[row["requirement_key"]] = chosen
            st.caption("Confirmation establishes only a skill mapping, not a required proficiency level.")
            if st.form_submit_button("Apply confirmed mappings"):
                st.session_state["confirmed_mappings"] = pending
                st.rerun()
    else:
        st.write("No mappings to confirm.")

st.header("4 · Skill coverage report")
counts = {status: sum(row["status"] == status for row in rows)
          for status in ("matched", "possible_match", "not_listed")}
for column, (status, count) in zip(st.columns(3), counts.items()):
    column.metric(status.replace("_", " ").title(), count)
st.dataframe([
    {"Required skill": row["title"], "Code": row["code"], "Required level": row["required_level"],
     "Coverage": row["status"], "Profile match": ", ".join(row["matched_profile_skills"]),
     "Unconfirmed candidates": ", ".join(c["profile_skill"] for c in row["candidates"]),
     "Proficiency": row["proficiency_status"]}
    for row in rows
], hide_index=True, width="stretch")
st.caption("Not listed = candidate learning gap / unknown coverage, not a confirmed deficiency. "
           "We do not infer skill mastery from names, years of experience or current role.")
with st.expander("Requirement evidence, candidate scores, and missing-data flags"):
    for row in rows:
        st.subheader(f"{row['title']} · {row['required_level']}")
        st.write(row["definition"] or "Framework definition not recorded.")
        st.write(row["proficiency_description"] or "Required proficiency description not recorded.")
        st.json(row)
matched_indexes = {i for row in rows for i in row["matched_profile_indexes"]}
st.write("Profile skills without a confirmed requirement mapping:",
         ", ".join(s["name"] for i, s in enumerate(skills) if i not in matched_indexes) or "(none)")
report = {"prototype": True, "profile": profile, "role_id": role_id,
          "role_title": role["role_title"], "sector": role["sector"], "track": role["track"],
          "role_source_records": recorded["source_records"], "counts": counts,
          "proficiency_status": "not_assessed", "requirements": rows,
          "disclaimer": "Self-reported skill coverage only; not listed does not prove a missing skill."}
st.download_button("Download coverage report JSON", json.dumps(report, indent=2, default=str),
                   file_name="prototype-skill-coverage.json", mime="application/json")
with st.expander("Full current state (prototype)"):
    st.json(report, expanded=False)
