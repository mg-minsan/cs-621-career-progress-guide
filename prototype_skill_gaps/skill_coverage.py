"""Throwaway skill-name coverage logic; never assesses proficiency or readiness."""
from __future__ import annotations

import re

from embeddings import embed_text


def _name(value: str) -> str:
    return " ".join(value.casefold().split())


def _words(value: str) -> set[str]:
    return set(re.findall(r"[\w]+", value.casefold()))


def build_coverage(skills: list[dict], requirements: list[dict],
                   confirmed: dict[str, int] | None = None) -> list[dict]:
    """Compare self-reported names/codes; confirmations only establish mappings.

    Approximate candidates use word overlap and the project's hash-ngram vectors
    over this role's requirements only. No persistent skill index is created.
    The threshold and top-three cut-off are prototype heuristics, not validated
    competency rules. All required levels remain not_assessed.
    """
    confirmed = confirmed or {}
    rows = []
    for requirement in requirements:
        code, level = requirement["framework_skill_code"], requirement["required_level"]
        title = requirement["source_skill_title"]
        exact = [i for i, skill in enumerate(skills)
                 if (skill.get("framework_code") == code if skill.get("framework_code")
                     else _name(skill["name"]) in {
                         _name(title), _name(requirement.get("framework_title") or title)})]
        key = f"{code}::{level}"
        chosen = confirmed.get(key)
        matched = exact or ([chosen] if chosen is not None and 0 <= chosen < len(skills) else [])
        rows.append({
            "requirement_key": key, "title": title, "code": code,
            "required_level": level, "status": "matched" if matched else "not_listed",
            "matched_profile_indexes": matched,
            "matched_profile_skills": [skills[i]["name"] for i in matched],
            "mapping_method": ("exact_name_or_code" if exact else
                               "user_confirmed" if matched else None),
            "proficiency_status": "not_assessed", "candidates": [],
            "definition": requirement.get("framework_description"),
            "proficiency_description": requirement.get("proficiency_description"),
            "source_records": requirement.get("source_records", []),
            "definition_source_records": requirement.get("definition_source_records", []),
            "proficiency_source_records": requirement.get("proficiency_source_records", []),
            "missing_data": requirement.get("missing_data", []),
        })

    # Rank each free-text profile skill against the bounded requirement set.
    documents = [" ".join(filter(None, [row["title"], row["definition"],
                                        row["proficiency_description"]])) for row in rows]
    vectors = [embed_text(text) for text in documents]
    already_exact = {i for row in rows if row["mapping_method"] == "exact_name_or_code"
                     for i in row["matched_profile_indexes"]}
    for index, skill in enumerate(skills):
        if index in already_exact or skill.get("framework_code"):
            continue
        words, vector = _words(skill["name"]), embed_text(skill["name"])
        matches = []
        for offset, text in enumerate(documents):
            overlap = words & _words(text)
            cosine = float(vector @ vectors[offset])
            keyword = len(overlap) / len(words) if words else 0.0
            if keyword > 0 or cosine >= 0.25:
                matches.append((offset, keyword, cosine, sorted(overlap)))
        keyword_ranks = {item[0]: rank for rank, item in enumerate(
            sorted((m for m in matches if m[1] > 0), key=lambda m: -m[1]), 1)}
        vector_ranks = {item[0]: rank for rank, item in enumerate(
            sorted((m for m in matches if m[2] >= 0.25), key=lambda m: -m[2]), 1)}
        ranked = []
        for offset, keyword, cosine, matched_terms in matches:
            score = sum(1 / (60 + ranks[offset]) for ranks in (keyword_ranks, vector_ranks)
                        if offset in ranks)
            ranked.append((score, offset, keyword, cosine, matched_terms))
        for score, offset, keyword, cosine, matched_terms in sorted(ranked, reverse=True)[:3]:
            if rows[offset]["status"] == "matched":
                continue
            rows[offset]["candidates"].append({
                "profile_index": index, "profile_skill": skill["name"],
                "retrieval_method": "in_memory_keyword_vector_rrf",
                "score": score, "keyword_score": keyword, "vector_score": cosine,
                "matched_terms": matched_terms,
            })
            rows[offset]["status"] = "possible_match"
    return rows
