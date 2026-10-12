"""Export every recorded role as source-backed JSON and Markdown.

Run: python export_roles.py --db data/career-ingested.duckdb
The default output is data/role-profiles. Existing output paths are protected;
choose a new directory for a fresh export. This is a local, single-writer tool.
"""
from __future__ import annotations

import argparse
from datetime import date
from decimal import Decimal
from functools import lru_cache
import hashlib
import html
import json
import os
from pathlib import Path
import re
import tempfile

import duckdb

from lookup import CareerLookup, DEFAULT_DB, SOURCE_FIELDS


DEFAULT_OUTPUT = Path(__file__).parent / "data/role-profiles"
SCHEMA_VERSION = 1


def _json_default(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"Unsupported JSON value: {type(value).__name__}")


def _json_bytes(value):
    return (json.dumps(value, default=_json_default, ensure_ascii=False,
                       sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_records(value):
    """Walk nested lookup results, including requirement and K&A provenance."""
    if isinstance(value, dict):
        if all(field in value for field in SOURCE_FIELDS):
            yield value
        else:
            for item in value.values():
                yield from _source_records(item)
    elif isinstance(value, list):
        for item in value:
            yield from _source_records(item)


def _source_key(source):
    return (source["source_file"], source["source_sheet"],
            source["source_row"], source["file_sha256"])


def _source_hashes(profile):
    hashes = {}
    for source in _source_records(profile):
        name, digest = source["source_file"], source["file_sha256"]
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError(f"Missing or invalid source hash for {name}")
        if name in hashes and hashes[name] != digest:
            raise ValueError(f"Conflicting source hashes for {name}")
        hashes[name] = digest
    return dict(sorted(hashes.items()))


def _inline(value):
    """Render source text literally, never as Markdown or executable HTML."""
    if value is None:
        return "Not recorded"
    text = " ".join(str(value).splitlines())
    text = html.escape(text, quote=False)
    return re.sub(r"([\\`*_{}\[\]()#+.!|>~\-])", r"\\\1", text)


def _block(value):
    if value is None:
        return "> Not recorded."
    return "\n".join("> " + _inline(line) for line in str(value).splitlines())


def _flags(flags):
    return ", ".join(_inline(flag) for flag in flags) if flags else "None flagged"


def render_role_markdown(profile: dict) -> str:
    """Render a profile without changing source text or inferring relationships.

    Physical spreadsheet rows are deduplicated into local Markdown footnotes;
    the JSON keeps every entity-specific provenance link and missing-data flag.
    """
    role = profile["data"]
    sources = {_source_key(source): source for source in _source_records(profile)}
    keys = sorted(sources)
    citations = {key: f"s{index:04d}" for index, key in enumerate(keys, start=1)}

    def refs(records):
        labels = dict.fromkeys(citations[_source_key(source)] for source in records)
        return " ".join(f"[^{label}]" for label in labels) if labels else "Not recorded"

    role_sources = [source for source in profile["source_records"]
                    if source["source_table"] == "roles"]
    lines = [
        f"# {_inline(role['role_title'])}", "",
        f"- **Role ID:** {_inline(role['role_id'])}",
        f"- **Sector:** {_inline(role['sector'])}",
        f"- **Track:** {_inline(role['track'])}",
        f"- **Missing data:** {_flags(profile['missing_data'])}", "",
        "This profile reports recorded facts, not readiness or an official career pathway.",
        "Missing records do not establish that a role needs no skills or responsibilities.", "",
        "## Description", "", _block(role["description"]), "",
        f"**Sources:** {refs(role_sources)}", "",
        "## Performance expectation", "", _block(role["performance_expectation"]), "",
        f"**Sources:** {refs(role_sources)}", "",
        f"## Work functions and tasks ({len(role['tasks'])})", "",
    ]
    if not role["tasks"]:
        lines += ["No task records are available. Coverage is unknown.", ""]
    for index, task in enumerate(role["tasks"], start=1):
        lines += [f"### Task {index}", "",
                  f"**Work function:** {_inline(task['work_function'])}", "",
                  _block(task["task_text"]), "",
                  f"**Missing data:** {_flags(task['missing_data'])}", "",
                  f"**Sources:** {refs(task['source_records'])}", ""]
    lines += [f"## Skill requirements ({len(role['skills'])})", "",
              "Original level labels are preserved. Named and numeric levels are not equated;",
              "different framework codes are not assumed to represent comparable levels.", ""]
    if not role["skills"]:
        lines += ["No skill requirement records are available. Coverage is unknown.", ""]
    for index, requirement in enumerate(role["skills"], start=1):
        detail = requirement["skill_details"]
        definition = detail["data"] or {}
        lines += [
            f"### Requirement {index}: {_inline(requirement['source_skill_title'])}", "",
            f"- **Framework code:** {_inline(requirement['framework_skill_code'])}",
            f"- **Required level (original):** {_inline(requirement['required_level'])}",
            f"- **Numeric level (where valid):** {_inline(requirement['required_level_numeric'])}",
            f"- **Skill type:** {_inline(requirement['skill_type'])}",
            f"- **Requirement missing data:** {_flags(requirement['missing_data'])}",
            f"- **Skill lookup status:** {_inline(detail['status'])}",
            f"- **Skill missing data:** {_flags(detail['missing_data'])}", "",
            f"**Requirement sources:** {refs(requirement['source_records'])}", "",
            "#### Definition", "",
            f"**Recorded title:** {_inline(definition.get('title'))}", "",
            f"**Definition source:** {_inline(definition.get('definition_source'))}", "",
            f"**Latest recorded update:** {_inline(definition.get('updated_date'))}", "",
            _block(definition.get("description")), "",
            f"**Definition sources:** {refs(requirement['definition_source_records'])}", "",
            "#### Required proficiency and knowledge/abilities", "",
        ]
        proficiencies = definition.get("proficiencies", [])
        if not proficiencies:
            lines += ["No proficiency details are recorded for this code and required level.", ""]
        for proficiency in proficiencies:
            lines += [f"**Original level:** {_inline(proficiency['level'])}", "",
                      _block(proficiency["proficiency_description"]), "",
                      f"**Missing data:** {_flags(proficiency['missing_data'])}", ""]
            items = proficiency["knowledge_abilities"]
            if not items:
                lines += ["No knowledge/ability items are recorded.", ""]
            for item in items:
                lines += [f"**Item type:** {_inline(item['item_type'])}", "",
                          _block(item["item_text"]), ""]
            lines += [f"**Proficiency sources:** {refs(proficiency['source_records'])}", ""]
    lines += ["## Source references", "",
              "These are spreadsheet locations and file hashes, not live availability or eligibility checks.", ""]
    for key in keys:
        source = sources[key]
        lines += [f"[^{citations[key]}]: {_inline(source['source_file'])}; "
                  f"sheet: {_inline(source['source_sheet'])}; row: {source['source_row']}; "
                  f"SHA-256: {source['file_sha256']}"]
    return "\n".join(lines) + "\n"


def export_roles(db_path: str | Path = DEFAULT_DB,
                 output_dir: str | Path = DEFAULT_OUTPUT) -> dict:
    """Export every role, publishing only after files and manifest are complete.

    Relative manifest paths use full canonical SHA-256 role IDs, never titles
    or slugs. JSON retains the lookup envelope plus schema_version, and adds
    get_skill(code, required_level) results under each requirement's
    skill_details. Outputs are deterministic for an unchanged database.
    """
    db_path = Path(db_path).resolve()
    # Preserve the final path component so even dangling symlinks are protected.
    requested = Path(os.path.abspath(output_dir))
    output_dir = requested.parent.resolve() / requested.name
    if os.path.lexists(output_dir):
        raise FileExistsError(f"Output already exists: {output_dir}. Choose a new directory.")
    with CareerLookup(db_path) as lookup:
        database_hash = _file_hash(db_path)
        roles = lookup.search_role_names("")["data"]
        output_dir.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".role-export-", dir=output_dir.parent) as temporary:
            staging = Path(temporary)
            (staging / "roles").mkdir()

            @lru_cache(maxsize=512)
            def skill_details(code, level):
                return lookup.get_skill(code, level)

            entries = []
            source_hashes = {}
            for index, role in enumerate(roles, start=1):
                role_id = role["role_id"]
                if not re.fullmatch(r"[0-9a-f]{64}", role_id):
                    raise ValueError(f"Invalid canonical role ID: {role_id!r}")
                profile = lookup.get_role(role_id)
                if profile["status"] != "ok":
                    raise ValueError(f"Role lookup failed during export: {role_id}")
                profile["schema_version"] = SCHEMA_VERSION
                for requirement in profile["data"]["skills"]:
                    requirement["skill_details"] = skill_details(
                        requirement["framework_skill_code"], requirement["required_level"])
                hashes = _source_hashes(profile)
                for name, digest in hashes.items():
                    if name in source_hashes and source_hashes[name] != digest:
                        raise ValueError(f"Conflicting source hashes for {name}")
                    source_hashes[name] = digest
                json_path = f"roles/{role_id}.json"
                markdown_path = f"roles/{role_id}.md"
                json_content = _json_bytes(profile)
                markdown_content = render_role_markdown(profile).encode("utf-8")
                (staging / json_path).write_bytes(json_content)
                (staging / markdown_path).write_bytes(markdown_content)
                entries.append({
                    "role_id": role_id, "sector": role["sector"], "track": role["track"],
                    "role_title": role["role_title"], "json_path": json_path,
                    "markdown_path": markdown_path,
                    "json_sha256": hashlib.sha256(json_content).hexdigest(),
                    "markdown_sha256": hashlib.sha256(markdown_content).hexdigest(),
                    "source_hashes": hashes, "missing_data": profile["missing_data"],
                    "task_count": len(profile["data"]["tasks"]),
                    "skill_requirement_count": len(profile["data"]["skills"]),
                })
                if index % 100 == 0 or index == len(roles):
                    print(f"Exported {index:,}/{len(roles):,} roles", flush=True)
            if _file_hash(db_path) != database_hash:
                raise ValueError("Database changed during export; output was not published.")
            manifest = {
                "schema_version": SCHEMA_VERSION, "database_sha256": database_hash,
                "role_count": len(entries), "source_hashes": dict(sorted(source_hashes.items())),
                "roles": entries,
            }
            (staging / "manifest.json").write_bytes(_json_bytes(manifest))
            if os.path.lexists(output_dir):
                raise FileExistsError(f"Output appeared during export: {output_dir}")
            # One-writer publication within the same filesystem. A failure above
            # leaves no visible partial export, and existing directories aren't reused.
            staging.rename(output_dir)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        manifest = export_roles(args.db, args.output_dir)
    except (ValueError, OSError, duckdb.Error) as error:
        parser.exit(1, f"Export failed: {error}\n")
    print(f"Exported {manifest['role_count']:,} roles to {args.output_dir}")
    print(f"Manifest: {args.output_dir / 'manifest.json'}")


if __name__ == "__main__":
    main()
