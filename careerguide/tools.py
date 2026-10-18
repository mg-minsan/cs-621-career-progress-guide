"""Deterministic tools the agent calls: lookups, set comparison, course search.
Everything here is read-only. No tool enrols, pays, applies or edits a profile."""
from __future__ import annotations

import re
from functools import lru_cache

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from .data import load_courses, load_framework

ROLES, SKILLS = load_framework()
COURSES = load_courses()

# Phrases that ask the agent to ACT. The agent only reads and plans; it notes these and carries on.
ACTION_PATTERN = re.compile(
    r"\b(enrol(l)?|pay|apply|register|sign me up|submit|book|purchase|buy|"
    r"(edit|update|change|delete) (my )?(profile|details)|ignore (all |any )?(previous|prior) instructions|"
    r"system prompt)\b", re.I)


# ---------------------------------------------------------------- stage 1: profile
def check_profile(profile: dict) -> list[str]:
    problems = []
    for f in ("role", "age", "residency", "status"):
        if profile.get(f) in (None, ""):
            problems.append(f"Missing field: {f}")
    if profile.get("residency") not in (None, "", "citizen", "pr"):
        problems.append("This guide covers Singapore citizens and PRs only.")
    try:
        if not 15 <= int(profile.get("age", 0)) <= 80:
            problems.append("Age looks out of range.")
    except (TypeError, ValueError):
        problems.append("Age must be a number.")
    return problems


def boundary_notices(goal: str) -> list[str]:
    hits = sorted({m.group(0).lower() for m in ACTION_PATTERN.finditer(goal or "")})
    if not hits:
        return []
    return [f"Your goal mentions an action ({', '.join(hits)}). I only read, compare and plan: I never enrol, "
            "pay, apply or edit your profile. I've used the rest of your goal as direction only."]


@lru_cache(maxsize=1)
def _title_index():
    labels, ids = [], []
    for r in ROLES.values():
        for t in (r.title, *r.aliases):
            labels.append(t.lower())
            ids.append(r.id)
    vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4)).fit(labels)
    return vec, vec.transform(labels), ids


def map_role(job_title: str, k: int = 3) -> list[dict]:
    """Free-text job title -> closest framework roles, best first, with a 0-1 match score."""
    vec, mat, ids = _title_index()
    sims = (mat @ vec.transform([job_title.lower()]).T).toarray().ravel()
    best: dict[str, float] = {}
    for rid, s in zip(ids, sims):
        best[rid] = max(best.get(rid, 0.0), float(s))
    ranked = sorted(best.items(), key=lambda x: -x[1])[:k]
    return [{"role_id": rid, "title": ROLES[rid].title, "score": round(s, 2)} for rid, s in ranked]


# ---------------------------------------------------------------- stage 2: paths
@lru_cache(maxsize=1)
def _role_text_index():
    ids = list(ROLES)
    docs = [f"{r.title} {r.sector} {r.description} {' '.join(r.skills)}" for r in ROLES.values()]
    vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True).fit(docs)
    return vec, vec.transform(docs), ids


GOAL_SYNONYMS = {"data": "data analytics analyst sql statistics", "ai": "generative ai machine learning automation",
                 "tech": "software cloud python", "finance": "financial accounting budgeting",
                 "marketing": "digital marketing market research"}


def goal_scores(goal: str) -> dict[str, float]:
    if not goal.strip():
        return {}
    text = goal.lower()
    for k, v in GOAL_SYNONYMS.items():
        if re.search(rf"\b{k}\b", text):
            text += " " + v
    vec, mat, ids = _role_text_index()
    sims = (mat @ vec.transform([text]).T).toarray().ravel()
    return {rid: float(s) for rid, s in zip(ids, sims)}


def skill_overlap(current_id: str, target_id: str) -> dict:
    cur, tgt = ROLES[current_id].skills, ROLES[target_id].skills
    have = [s for s, lv in tgt.items() if cur.get(s, 0) >= lv]
    return {"have": have, "share": len(have) / len(tgt)}


def candidate_paths(current_id: str, goal: str, n: int = 6) -> list[dict]:
    """Shortlist of roles. Goal given -> goal relevance leads; none -> nearest roles by skill overlap."""
    gs = goal_scores(goal)
    out = []
    for rid, role in ROLES.items():
        if rid == current_id:
            continue
        ov = skill_overlap(current_id, rid)
        g = gs.get(rid, 0.0)
        score = (0.65 * g + 0.35 * ov["share"]) if gs else ov["share"]
        out.append({"role_id": rid, "title": role.title, "sector": role.sector, "score": round(score, 3),
                    "goal_score": round(g, 3), "overlap": round(ov["share"], 2),
                    "kind": "Step-up" if role.sector == ROLES[current_id].sector else "Switch",
                    "n_gaps": len(compute_gaps(current_id, rid))})
    out.sort(key=lambda p: -p["score"])
    return out[:n]


# ---------------------------------------------------------------- stage 3: gaps
def compute_gaps(current_id: str, target_id: str) -> list[dict]:
    """Target skills the person lacks or holds at a lower level. Pure set/level comparison."""
    cur, tgt = ROLES[current_id].skills, ROLES[target_id].skills
    gaps = [{"skill": s, "need": lv, "have": cur.get(s, 0), "description": SKILLS[s]}
            for s, lv in tgt.items() if cur.get(s, 0) < lv]
    return sorted(gaps, key=lambda g: (g["need"], g["skill"]))


# ---------------------------------------------------------------- stage 4: course search
@lru_cache(maxsize=1)
def _course_index():
    ids = list(COURSES)
    docs = [f"{c.title}. {c.description}" for c in COURSES.values()]
    vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True).fit(
        docs + [f"{s} {d}" for s, d in SKILLS.items()])
    return vec, vec.transform(docs), ids


def search_courses(skill: str, k: int = 5) -> list[dict]:
    """Rank courses by similarity of their description to the skill (no skill tags exist).
    Offline stand-in for the week-4 embedding search: swap `_course_index` for embeddings later."""
    vec, mat, ids = _course_index()
    q = f"{skill} {SKILLS.get(skill, '')}"
    sims = (mat @ vec.transform([q]).T).toarray().ravel()
    order = np.argsort(-sims)[:k]
    return [{"course_id": ids[i], "score": round(float(sims[i]), 3)} for i in order if sims[i] > 0]
