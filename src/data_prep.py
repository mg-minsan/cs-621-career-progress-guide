"""
STEP 1 - Build the data layer.

Reads the four official SkillsFuture spreadsheets in data/raw/ and writes one
SQLite database, data/careers.db, that every later step (the agent's tools,
the eval harness, the Streamlit viewer) reads from.

    python src/data_prep.py

Tables it creates
    roles        one row per job role (sector + track + role name)
    role_skills  the skills each role needs, at what level
    skills       every framework skill with its description
    courses      SkillsFuture courses, duplicates removed

Design decisions (write these in your report):
  1. A role is identified by (sector, track, role name), NOT by name alone:
     47 role names appear in more than one sector.
  2. Skills are compared through the "unique skills" mapping, because the
     same skill has a different code in every sector (e.g. "Data Analytics"
     in Accountancy vs Infocomm). Without this, a cross-sector career switch
     would look like every skill is missing.
  3. Technical skills use levels 1-6; critical core skills use
     Basic/Intermediate/Advanced. We map those words onto the 1-6 scale
     (Basic=2, Intermediate=4, Advanced=6) so levels can be ordered.
     This mapping is OUR ASSUMPTION - say so in the report.
  4. The course file has repeated rows; we keep one row per course number.
"""
from pathlib import Path
import sqlite3

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
DB = ROOT / "data" / "careers.db"

SF = RAW / "jobsandskills-skillsfuture-skills-framework-dataset.xlsx"
MAPPING = RAW / "jobsandskills-skillsfuture-tsc-to-unique-skills-mapping.xlsx"
COURSES = RAW / "MySkillsFutureCourseDirectory.xlsx"

WORD_LEVELS = {"basic": 2, "intermediate": 4, "advanced": 6}  # assumption, see note 3


def level_to_num(raw) -> int | None:
    """'3' -> 3, 'Intermediate' -> 4, junk -> None."""
    if pd.isna(raw):
        return None
    text = str(raw).strip().lower()
    if text in WORD_LEVELS:
        return WORD_LEVELS[text]
    try:
        return int(float(text))
    except ValueError:
        return None


def build_roles() -> pd.DataFrame:
    df = pd.read_excel(SF, "Job Role_Description")
    df = df.rename(columns={
        "Sector": "sector", "Track": "track", "Job Role": "role",
        "Job Role Description": "description",
        "Performance Expectation": "performance_expectation",
    })
    df = df.drop_duplicates(["sector", "track", "role"]).reset_index(drop=True)
    df.insert(0, "role_id", range(1, len(df) + 1))
    return df


def build_skill_map() -> dict:
    """framework skill code -> sector-neutral 'unique' skill title."""
    m = pd.read_excel(MAPPING, "data")
    m = m.dropna(subset=["skills_framework_skill_code", "Unique skill_updated_skill_title"])
    m = m.drop_duplicates("skills_framework_skill_code")
    return dict(zip(m["skills_framework_skill_code"], m["Unique skill_updated_skill_title"]))


def build_role_skills(roles: pd.DataFrame, skill_map: dict) -> pd.DataFrame:
    df = pd.read_excel(SF, "Job Role_TSC_CCS")
    df = df.rename(columns={
        "Sector": "sector", "Track": "track", "Job Role": "role",
        "TSC_CCS Title": "skill_title", "TSC_CCS Type": "skill_type",
        "Proficiency Level": "level_raw", "TSC_CCS Code": "skill_code",
    })
    df = df.merge(roles[["role_id", "sector", "track", "role"]],
                  on=["sector", "track", "role"], how="inner")
    df["level_num"] = df["level_raw"].map(level_to_num)
    # Sector-neutral name; fall back to the framework title if unmapped.
    df["unique_skill"] = df["skill_code"].map(skill_map).fillna(df["skill_title"])
    return df[["role_id", "skill_code", "skill_title", "unique_skill",
               "skill_type", "level_raw", "level_num"]]


def build_skills() -> pd.DataFrame:
    df = pd.read_excel(SF, "TSC_CCS_Key")
    df = df.rename(columns={
        "TSC Code": "skill_code", "Sector": "sector", "TSC_CCS Category": "category",
        "TSC_CCS Title": "skill_title", "TSC_CCS Description": "description",
        "TSC_CCS Type": "skill_type",
    })
    return df[["skill_code", "sector", "category", "skill_title", "description", "skill_type"]]


def build_courses() -> pd.DataFrame:
    df = pd.read_excel(COURSES)
    df = df.drop_duplicates("coursereferencenumber")
    df = df.rename(columns={
        "coursereferencenumber": "course_ref", "coursetitle": "title",
        "trainingprovideralias": "provider", "courseratings_stars": "rating",
        "full_course_fee": "full_fee", "course_fee_after_subsidies": "fee_after_subsidy",
        "number_of_hours": "hours", "training_commitment": "commitment",
        "conducted_in": "language", "about_this_course": "about",
        "what_you_learn": "learn", "minimum_entry_requirement": "entry_requirement",
    })
    # The text the search step will read. Built once here so it is identical
    # for the agent, the baselines and the eval labels.
    df["search_text"] = (df["title"].fillna("") + ". " + df["about"].fillna("")
                         + " " + df["learn"].fillna("")).str.slice(0, 2000)
    # A listed fee that does not drop after subsidy suggests the course is not
    # subsidy-eligible. The funding calculator (Step 4) uses this flag.
    df["looks_subsidised"] = df["fee_after_subsidy"] < df["full_fee"]
    return df[["course_ref", "title", "provider", "rating", "full_fee",
               "fee_after_subsidy", "looks_subsidised", "hours", "commitment",
               "language", "about", "learn", "entry_requirement", "search_text"]]


def main() -> None:
    print("Reading spreadsheets (takes about a minute)...")
    roles = build_roles()
    skill_map = build_skill_map()
    role_skills = build_role_skills(roles, skill_map)
    skills = build_skills()
    courses = build_courses()

    DB.unlink(missing_ok=True)
    with sqlite3.connect(DB) as con:
        roles.to_sql("roles", con, index=False)
        role_skills.to_sql("role_skills", con, index=False)
        skills.to_sql("skills", con, index=False)
        courses.to_sql("courses", con, index=False)
        con.execute("CREATE INDEX idx_rs_role ON role_skills(role_id)")
        con.execute("CREATE INDEX idx_roles_name ON roles(role)")

    unmapped = (role_skills["unique_skill"] == role_skills["skill_title"]).mean()
    print(f"roles        {len(roles):>6}  ({roles['role'].nunique()} unique names, "
          f"{roles['sector'].nunique()} sectors)")
    print(f"role_skills  {len(role_skills):>6}  (levels missing: "
          f"{role_skills['level_num'].isna().sum()})")
    print(f"skills       {len(skills):>6}")
    print(f"courses      {len(courses):>6}  ({courses['looks_subsidised'].mean():.0%} look subsidised)")
    print(f"skills keeping their own title (no unique-skill rename): {unmapped:.0%}")
    print(f"wrote {DB}")


if __name__ == "__main__":
    main()
