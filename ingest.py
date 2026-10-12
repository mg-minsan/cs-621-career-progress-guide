"""Import the supplied SkillsFuture workbooks into a local DuckDB database.

Run: python ingest.py --input-dir . --db data/career.duckdb
No PDF extraction, embeddings, user profiles, or funding inference is performed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

import duckdb
import pandas as pd
from openpyxl import load_workbook


SOURCES = {
    "jobsandskills-skillsfuture-skills-framework-dataset.xlsx": {
        "Job Role_Description": "roles",
        "Job Role_CWF_KT": "role_tasks",
        "Job Role_TSC_CCS": "role_skills",
        "TSC_CCS_Key": "framework_skills",
        "TSC_CCS_Key_Retired": "retired_skills",
        "TSC_CCS_K&A": "knowledge_abilities",
    },
    "jobsandskills-skillsfuture-unique-skills-list.xlsx": {
        "Unique Skills List": "unique_skills",
    },
    "jobsandskills-skillsfuture-tsc-to-unique-skills-mapping.xlsx": {
        "data": "skill_mappings",
    },
    "MySkillsFutureCourseDirectory.xlsx": {"Sheet2": "courses"},
}

# Explicit header contracts prevent a changed source schema from silently
# producing an incorrect database. Additional columns are preserved in raw.
REQUIRED = {
    "roles": ["Sector", "Track", "Job Role", "Job Role Description", "Performance Expectation"],
    "role_tasks": ["Sector", "Track", "Job Role", "Critical Work Function", "Key Tasks"],
    "role_skills": ["Sector", "Track", "Job Role", "TSC_CCS Title", "TSC_CCS Type", "Proficiency Level", "TSC_CCS Code"],
    "framework_skills": ["TSC Code", "Sector", "TSC_CCS Category", "TSC_CCS Title", "TSC_CCS Description", "TSC_CCS Type", "Latest Update Date"],
    "retired_skills": ["TSC Code", "Retired Date"],
    "knowledge_abilities": ["TSC_CCS Code", "Proficiency Level", "Proficiency Description", "Knowledge / Ability Items", "Knowledge / Ability Classification"],
    "unique_skills": ["skill_id", "skill_transaction_id", "skill_title", "skill_description", "skill_type", "Emerging Skills", "CASL Skills"],
    "skill_mappings": ["skills_framework_skill_code", "skills_framework_skill_pl", "Unique skill_updated_skill_title"],
    "courses": ["coursereferencenumber", "coursetitle", "trainingprovideruen", "trainingprovideralias", "full_course_fee", "course_fee_after_subsidies", "number_of_hours", "training_commitment", "conducted_in", "about_this_course", "what_you_learn", "minimum_entry_requirement"],
}


def column_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def source_text(value):
    """Raw cells use text storage to avoid inferred numeric/identifier coercion."""
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def load_raw(con, input_dir: Path) -> dict:
    counts = {}
    con.execute("CREATE SCHEMA raw; CREATE SCHEMA core; CREATE SCHEMA audit")
    con.execute("""CREATE TABLE audit.sources (
        source_file VARCHAR, source_sheet VARCHAR, raw_table VARCHAR,
        file_sha256 VARCHAR, row_count BIGINT, imported_at TIMESTAMP DEFAULT current_timestamp
    )""")
    for filename, sheets in SOURCES.items():
        path = input_dir / filename
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        workbook = load_workbook(path, read_only=True, data_only=False)
        try:
            for sheet_name, table in sheets.items():
                if sheet_name not in workbook.sheetnames:
                    raise ValueError(f"Missing sheet {sheet_name!r} in {filename}")
                sheet = workbook[sheet_name]
                rows = sheet.iter_rows(values_only=True)
                headers = list(next(rows))
                missing = set(REQUIRED[table]) - set(headers)
                if missing:
                    raise ValueError(f"{filename}/{sheet_name}: missing columns {sorted(missing)}")
                names = [column_name(str(h)) for h in headers]
                if len(set(names)) != len(names) or any(not n for n in names):
                    raise ValueError(f"Ambiguous column headers in {filename}/{sheet_name}")
                names += ["source_file", "source_sheet", "source_row"]
                records = [
                    [*(source_text(v) for v in row), filename, sheet_name, row_number]
                    for row_number, row in enumerate(rows, start=2)
                    if any(v is not None for v in row)
                ]
                # Object dtype lets DuckDB scan the raw text without interpreting
                # the literal skill value "No mapping" or other strings as null.
                frame = pd.DataFrame(records, columns=names, dtype=object)
                con.register("incoming", frame)
                columns = ", ".join(f'"{n}" {"BIGINT" if n == "source_row" else "VARCHAR"}' for n in names)
                con.execute(f"CREATE TABLE raw.{table} ({columns})")
                con.execute(f"INSERT INTO raw.{table} SELECT * FROM incoming")
                con.unregister("incoming")
                counts[table] = len(records)
                con.execute("INSERT INTO audit.sources (source_file,source_sheet,raw_table,file_sha256,row_count) VALUES (?,?,?,?,?)",
                            [filename, sheet_name, table, digest, len(records)])
                print(f"Loaded raw.{table}: {len(records):,} rows", flush=True)
        finally:
            workbook.close()
    return counts


def validate(con, raw_counts: dict) -> dict:
    """Fail on broken internal joins; expose source quality gaps as warnings."""
    for table, expected in raw_counts.items():
        actual = con.execute(f"SELECT count(*) FROM raw.{table}").fetchone()[0]
        if actual != expected:
            raise ValueError(f"Raw row-count mismatch: {table}")
    fatal = {
        "role_skills_without_role": "SELECT count(*) FROM core.role_skills s LEFT JOIN core.roles r USING(role_id) WHERE r.role_id IS NULL",
        "role_skills_without_definition": "SELECT count(*) FROM core.role_skills s LEFT JOIN core.framework_skills f USING(framework_skill_code) WHERE f.framework_skill_code IS NULL",
        "tasks_without_role": "SELECT count(*) FROM core.role_tasks s LEFT JOIN core.roles r USING(role_id) WHERE r.role_id IS NULL",
        "mappings_with_invalid_unique_id": "SELECT count(*) FROM core.skill_mappings m LEFT JOIN core.unique_skills u USING(skill_id) WHERE m.skill_id IS NOT NULL AND u.skill_id IS NULL",
        "proficiency_items_without_parent": "SELECT count(*) FROM core.skill_knowledge_abilities a LEFT JOIN core.skill_proficiency p USING(framework_skill_code,level) WHERE p.framework_skill_code IS NULL",
        "blank_course_ids": "SELECT count(*) FROM core.courses WHERE course_id IS NULL OR course_id = ''",
        "blank_role_keys": "SELECT count(*) FROM core.roles WHERE sector IS NULL OR track IS NULL OR role_title IS NULL",
        "missing_source_links": "SELECT count(*) FROM core.search_documents d WHERE NOT EXISTS (SELECT 1 FROM core.source_records s WHERE s.entity_type=d.entity_type AND s.entity_id=d.entity_id)",
    }
    checks = {name: con.execute(sql).fetchone()[0] for name, sql in fatal.items()}
    failures = {name: count for name, count in checks.items() if count}
    if failures:
        raise ValueError(f"Integrity checks failed: {failures}")
    counts = dict(con.execute("""SELECT table_name, 0 FROM information_schema.tables
        WHERE table_schema='core' AND table_type='BASE TABLE' ORDER BY table_name""").fetchall())
    for table in counts:
        counts[table] = con.execute(f"SELECT count(*) FROM core.{table}").fetchone()[0]
    warnings = dict(con.execute("SELECT check_name, affected_count FROM audit.quality_summary ORDER BY check_name").fetchall())
    return {"raw_counts": raw_counts, "core_counts": counts, "integrity_checks": checks, "quality_warnings": warnings}


def ingest(input_dir: Path, db_path: Path, replace: bool = False) -> dict:
    input_dir, db_path = input_dir.resolve(), db_path.resolve()
    missing = [name for name in SOURCES if not (input_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(f"Missing input workbooks: {missing}")
    if db_path.exists() and not replace:
        raise FileExistsError(f"Database already exists: {db_path}. Use --replace to rebuild it.")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # Build beside the destination and publish only after successful validation.
    # A failed rebuild leaves the previous database untouched.
    fd, temp_name = tempfile.mkstemp(prefix=".ingest-", suffix=".duckdb", dir=db_path.parent)
    os.close(fd)
    temporary = Path(temp_name)
    temporary.unlink()  # DuckDB expects either a database or a nonexistent file.
    con = None
    try:
        con = duckdb.connect(str(temporary))
        con.execute("BEGIN TRANSACTION")
        counts = load_raw(con, input_dir)
        con.execute(Path(__file__).with_name("sql").joinpath("build_core.sql").read_text())
        report = validate(con, counts)
        con.execute("COMMIT")
        con.close()
        con = None
        # link gives no-overwrite publication even if another process created
        # the destination while this import was running.
        if replace:
            os.replace(temporary, db_path)
        else:
            os.link(temporary, db_path)
            temporary.unlink()
        report_path = db_path.with_suffix(".quality.json")
        report_path.write_text(json.dumps(report, indent=2) + "\n")
        print(f"Database: {db_path}\nQuality report: {report_path}", flush=True)
        return report
    finally:
        if con is not None:
            con.close()
        temporary.unlink(missing_ok=True)
        Path(str(temporary) + ".wal").unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=Path(__file__).parent)
    parser.add_argument("--db", type=Path, default=Path(__file__).parent / "data/career.duckdb")
    parser.add_argument("--replace", action="store_true", help="Rebuild an existing database after validation; close database readers first.")
    args = parser.parse_args()
    try:
        report = ingest(args.input_dir, args.db, args.replace)
    except (ValueError, OSError, duckdb.Error) as error:
        parser.exit(1, f"Ingestion failed: {error}\n")
    print(json.dumps(report["core_counts"], indent=2))


if __name__ == "__main__":
    main()
