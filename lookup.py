"""Read-only, source-backed lookups for databases built by ingest.py.

Use CareerLookup as a context manager. Results have status (ok, not_found or
ambiguous), data, missing_data and source_records. Empty recorded collections
are not evidence that a role has no responsibilities or skill requirements.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import duckdb


DEFAULT_DB = Path(__file__).parent / "data/career-ingested.duckdb"
SOURCE_FIELDS = (
    "entity_type", "entity_id", "source_table", "source_file", "source_sheet",
    "source_row", "file_sha256",
)


def _result(data, *, status="ok", missing=(), sources=()):
    return {"status": status, "data": data, "missing_data": list(missing),
            "source_records": list(sources)}


def _missing(record, fields):
    return [field for field in fields if record.get(field) is None]


def _attach_sources(records, sources, keys):
    """Group provenance separately, never multiply tasks by requirements."""
    grouped = defaultdict(list)
    for source in sources:
        grouped[tuple(source[key] for key in keys)].append(
            {field: source[field] for field in SOURCE_FIELDS})
    for record in records:
        record["source_records"] = grouped[tuple(record[key] for key in keys)]


class CareerLookup:
    """Own one read-only DuckDB connection; no database is created implicitly.

    Inputs are exact identifiers/level labels, except name search and title
    resolution, which trim inputs and match case-insensitively. Return values
    preserve DuckDB's Decimal fees and date objects (not lossy JSON floats).
    """

    def __init__(self, db_path: str | Path = DEFAULT_DB):
        self.db_path = Path(db_path).resolve()
        if not self.db_path.is_file():
            raise FileNotFoundError(
                f"Career database not found: {self.db_path}. Run ingest.py first.")
        self._con = duckdb.connect(str(self.db_path), read_only=True)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def close(self):
        self._con.close()

    def _query(self, sql, params=()):
        cursor = self._con.execute(sql, params)
        columns = [column[0] for column in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def _role(self, role_id):
        rows = self._query("SELECT * FROM core.roles WHERE role_id = ?", [role_id])
        return rows[0] if rows else None

    def _name_matches(self, query, sector, track, *, exact):
        predicate = "lower(role_title) = lower(?)" if exact else (
            "contains(lower(role_title), lower(?))")
        matches = self._query(f"""
            SELECT role_id, sector, track, role_title FROM core.roles
            WHERE {predicate}
              AND (? IS NULL OR lower(sector) = lower(?))
              AND (? IS NULL OR lower(track) = lower(?))
            ORDER BY sector, track, role_title, role_id
        """, [query.strip(), sector.strip() if sector is not None else None,
              sector.strip() if sector is not None else None,
              track.strip() if track is not None else None,
              track.strip() if track is not None else None])
        if matches:
            sources = self._query("""
                SELECT DISTINCT s.entity_id AS role_id, s.*, a.file_sha256
                FROM core.source_records s LEFT JOIN audit.sources a
                  ON a.raw_table = s.source_table AND a.source_file = s.source_file
                 AND a.source_sheet = s.source_sheet
                WHERE s.entity_type = 'role' AND s.source_table = 'roles'
                  AND s.entity_id IN (SELECT unnest(?))
                ORDER BY source_file, source_sheet, source_row
            """, [[match["role_id"] for match in matches]])
            _attach_sources(matches, sources, ("role_id",))
        return matches

    def search_role_names(self, query: str, sector: str | None = None,
                          track: str | None = None) -> dict:
        """All literal substring matches; % and _ are not SQL wildcards.

        An empty query lists all roles, optionally filtered by sector/track.
        This is name lookup, not ranked keyword or semantic search.
        """
        matches = self._name_matches(query, sector, track, exact=False)
        return _result(matches, sources=[
            source for match in matches for source in match["source_records"]])

    def resolve_role(self, title: str, sector: str | None = None,
                     track: str | None = None) -> dict:
        """Resolve an exact title, or return every ambiguous candidate ID."""
        matches = self._name_matches(title, sector, track, exact=True)
        if not matches:
            return _result(None, status="not_found")
        if len(matches) > 1:
            return _result(matches, status="ambiguous", sources=[
                source for match in matches for source in match["source_records"]])
        return self.get_role(matches[0]["role_id"])

    def get_source_records(self, entity_type: str, entity_id: str) -> dict:
        """All contributing rows and source hashes, not just selected variants.

        entity_type is one of the ingestion entity types (role, framework_skill,
        skill_proficiency, unique_skill, skill_mapping, course). No recorded
        links returns not_found, including for unknown entity types.
        """
        rows = self._query("""
            SELECT DISTINCT s.*, a.file_sha256
            FROM core.source_records s LEFT JOIN audit.sources a
              ON a.raw_table = s.source_table AND a.source_file = s.source_file
             AND a.source_sheet = s.source_sheet
            WHERE s.entity_type = ? AND s.entity_id = ?
            ORDER BY source_table, source_file, source_sheet, source_row
        """, [entity_type, entity_id])
        return _result(rows, status="ok" if rows else "not_found")

    def _raw_role_sources(self, role_id, table, fields_sql):
        # Table/column expressions are internal constants, never caller input.
        return self._query(f"""
            SELECT 'role' AS entity_type, ? AS entity_id,
                   '{table}' AS source_table, r.source_file, r.source_sheet,
                   r.source_row, a.file_sha256, {fields_sql}
            FROM raw.{table} r LEFT JOIN audit.sources a
              ON a.raw_table = '{table}' AND a.source_file = r.source_file
             AND a.source_sheet = r.source_sheet
            WHERE core.role_key(r.sector, r.track, r.job_role) = ?
            ORDER BY r.source_row
        """, [role_id, role_id])

    def get_role_tasks(self, role_id: str) -> dict:
        if self._role(role_id) is None:
            return _result(None, status="not_found")
        tasks = self._query("""
            SELECT role_id, work_function, task_text FROM core.role_tasks
            WHERE role_id = ? ORDER BY work_function, task_text
        """, [role_id])
        sources = self._raw_role_sources(role_id, "role_tasks", """
            core.clean(r.critical_work_function) AS work_function,
            core.clean(r.key_tasks) AS task_text
        """)
        _attach_sources(tasks, sources, ("work_function", "task_text"))
        for task in tasks:
            task["missing_data"] = _missing(task, ("work_function", "task_text"))
        refs = [{field: row[field] for field in SOURCE_FIELDS} for row in sources]
        return _result(tasks, missing=[] if tasks else ["tasks"], sources=refs)

    def get_role_skills(self, role_id: str) -> dict:
        """Every recorded requirement, with definition/proficiency gap flags.

        Fetch full proficiency knowledge/abilities with get_skill(code, level).
        No top-k limit, code suffix stripping or named-level conversion is used.
        """
        if self._role(role_id) is None:
            return _result(None, status="not_found")
        skills = self._query("""
            SELECT s.*, f.title AS framework_title,
                   f.description AS framework_description, f.definition_source,
                   p.proficiency_description,
                   CASE WHEN p.framework_skill_code IS NOT NULL
                        THEN core.pair_key(p.framework_skill_code, p.level)
                   END AS proficiency_id
            FROM core.role_skills s
            LEFT JOIN core.framework_skills f USING(framework_skill_code)
            LEFT JOIN core.skill_proficiency p
              ON s.framework_skill_code = p.framework_skill_code
             AND s.required_level = p.level
            WHERE s.role_id = ?
            ORDER BY s.source_skill_title, s.framework_skill_code, s.required_level
        """, [role_id])
        sources = self._raw_role_sources(role_id, "role_skills", """
            core.clean(r.tsc_ccs_code) AS framework_skill_code,
            core.clean(r.proficiency_level) AS required_level
        """)
        _attach_sources(skills, sources, ("framework_skill_code", "required_level"))
        for skill in skills:
            skill["missing_data"] = _missing(
                skill, ("framework_description", "proficiency_description"))
            if skill["definition_source"] != "active_key":
                skill["missing_data"].append("active_definition")
            if skill["proficiency_id"] is None:
                skill["missing_data"].append("proficiency_details")
        evidence = self._query("""
            SELECT DISTINCT s.*, a.file_sha256
            FROM core.source_records s LEFT JOIN audit.sources a
              ON a.raw_table = s.source_table AND a.source_file = s.source_file
             AND a.source_sheet = s.source_sheet
            WHERE (s.entity_type = 'framework_skill' AND s.entity_id IN (
                SELECT framework_skill_code FROM core.role_skills WHERE role_id = ?))
               OR (s.entity_type = 'skill_proficiency' AND s.entity_id IN (
                SELECT core.pair_key(framework_skill_code, required_level)
                FROM core.role_skills WHERE role_id = ?))
            ORDER BY source_table, source_file, source_sheet, source_row
        """, [role_id, role_id])
        by_entity = defaultdict(list)
        for source in evidence:
            by_entity[(source["entity_type"], source["entity_id"])].append(source)
        for skill in skills:
            definition_table = ("framework_skills" if skill["definition_source"] == "active_key"
                                else "role_skills")
            skill["definition_source_records"] = [
                row for row in by_entity[("framework_skill", skill["framework_skill_code"])]
                if row["source_table"] == definition_table]
            skill["proficiency_source_records"] = by_entity[
                ("skill_proficiency", skill["proficiency_id"])]
        refs = [{field: row[field] for field in SOURCE_FIELDS} for row in sources]
        return _result(skills, missing=[] if skills else ["skill_requirements"],
                       sources=refs)

    def get_role(self, role_id: str) -> dict:
        """Full role with separate task and requirement collections."""
        role = self._role(role_id)
        if role is None:
            return _result(None, status="not_found")
        tasks, skills = self.get_role_tasks(role_id), self.get_role_skills(role_id)
        role["tasks"], role["skills"] = tasks["data"], skills["data"]
        missing = _missing(role, ("description", "performance_expectation"))
        missing += tasks["missing_data"] + skills["missing_data"]
        return _result(role, missing=missing,
                       sources=self.get_source_records("role", role_id)["data"])

    def get_skill(self, framework_skill_code: str, level: str | None = None) -> dict:
        """Definition plus all levels, or an exact original level label.

        A known code with an unrecorded requested level remains ok, flagged
        requested_proficiency. K&A-only codes remain visible without an active
        definition. Proficiency IDs use the ingestion pair-key macro.
        """
        definitions = self._query("""
            SELECT * FROM core.framework_skills WHERE framework_skill_code = ?
        """, [framework_skill_code])
        levels = self._query("""
            SELECT *, core.pair_key(framework_skill_code, level) AS proficiency_id
            FROM core.skill_proficiency WHERE framework_skill_code = ?
            ORDER BY level
        """, [framework_skill_code])
        if not definitions and not levels:
            return _result(None, status="not_found")
        skill = definitions[0] if definitions else {
            "framework_skill_code": framework_skill_code, "sector": None,
            "category": None, "title": None, "description": None,
            "skill_type": None, "updated_date": None, "definition_source": None,
        }
        missing = _missing(skill, ("title", "description"))
        if skill["definition_source"] != "active_key":
            missing.append("active_definition")
        selected = levels if level is None else [p for p in levels if p["level"] == level]
        items = self._query("""
            SELECT framework_skill_code, level, item_type, item_text
            FROM core.skill_knowledge_abilities WHERE framework_skill_code = ?
            ORDER BY level, item_type, item_text
        """, [framework_skill_code])
        sources = self.get_source_records("framework_skill", framework_skill_code)["data"]
        for proficiency in selected:
            proficiency["knowledge_abilities"] = [
                item for item in items if item["level"] == proficiency["level"]]
            proficiency["missing_data"] = _missing(
                proficiency, ("proficiency_description",))
            if not proficiency["knowledge_abilities"]:
                proficiency["missing_data"].append("knowledge_abilities")
            proficiency["source_records"] = self.get_source_records(
                "skill_proficiency", proficiency["proficiency_id"])["data"]
            sources += proficiency["source_records"]
        if not selected:
            missing.append("proficiency_details" if level is None else "requested_proficiency")
        if not definitions and not selected:
            # Cite the known K&A-only code even when the requested level is absent.
            for proficiency in levels:
                sources += self.get_source_records(
                    "skill_proficiency", proficiency["proficiency_id"])["data"]
        skill["available_levels"] = [p["level"] for p in levels]
        skill["proficiencies"] = selected
        return _result(skill, missing=missing, sources=sources)

    def get_course(self, course_id: str) -> dict:
        rows = self._query("SELECT * FROM core.courses WHERE course_id = ?", [course_id])
        if not rows:
            return _result(None, status="not_found")
        course = rows[0]
        sources = self.get_source_records("course", course_id)["data"]
        course["selected_source_records"] = [
            source for source in sources
            if source["source_row"] == course["selected_source_row"]]
        return _result(course, missing=_missing(course, (
            "title", "provider_uen", "provider_name", "description",
            "learning_outcomes", "entry_requirements", "full_fee",
            "listed_subsidised_fee", "hours", "training_commitment", "language")),
            sources=sources)

    def compare_roles(self, role_id_a: str, role_id_b: str) -> dict:
        """Compare recorded requirements, not readiness or promotion eligibility.

        Shared means identical code AND original level label. Different labels
        for an identical code are returned unassessed; different codes are never
        treated as a cross-level match even when their titles are identical.
        """
        a, b = self.get_role(role_id_a), self.get_role(role_id_b)
        if a["status"] == "not_found" or b["status"] == "not_found":
            return _result(None, status="not_found", missing=[
                name for name, result in (("role_a", a), ("role_b", b))
                if result["status"] == "not_found"])
        by_a, by_b = defaultdict(list), defaultdict(list)
        for skill in a["data"]["skills"]:
            by_a[skill["framework_skill_code"]].append(skill)
        for skill in b["data"]["skills"]:
            by_b[skill["framework_skill_code"]].append(skill)
        shared, different = [], []
        for code in sorted(by_a.keys() & by_b.keys()):
            levels_a = {s["required_level"]: s for s in by_a[code]}
            levels_b = {s["required_level"]: s for s in by_b[code]}
            for label in sorted(levels_a.keys() & levels_b.keys()):
                shared.append({"a": levels_a[label], "b": levels_b[label]})
            if levels_a.keys() != levels_b.keys():
                different.append({"framework_skill_code": code,
                                  "a": by_a[code], "b": by_b[code],
                                  "comparison_status": "not_assessed"})
        data = {
            "role_a": a["data"], "role_b": b["data"],
            "shared_requirements": shared, "different_levels": different,
            "only_a": [s for s in a["data"]["skills"]
                       if s["framework_skill_code"] not in by_b],
            "only_b": [s for s in b["data"]["skills"]
                       if s["framework_skill_code"] not in by_a],
        }
        missing = [f"{name}.{flag}" for name, result in (("role_a", a), ("role_b", b))
                   for flag in result["missing_data"]]
        sources = a["source_records"] + b["source_records"]
        return _result(data, missing=missing, sources=sources)
