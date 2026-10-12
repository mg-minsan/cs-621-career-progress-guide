-- Clean only in core. Raw source text and spreadsheet row numbers stay intact.
CREATE MACRO core.clean(x) AS nullif(trim(replace(replace(x, '_x000D_', ''), chr(13), '')), '');
CREATE MACRO core.role_key(s, t, r) AS sha256(to_json(list_value(core.clean(s), core.clean(t), core.clean(r))));
CREATE MACRO core.pair_key(a, b) AS sha256(to_json(list_value(a, b)));

CREATE TABLE core.roles AS
SELECT core.role_key(sector, track, job_role) AS role_id,
       core.clean(sector) AS sector, core.clean(track) AS track,
       core.clean(job_role) AS role_title,
       core.clean(job_role_description) AS description,
       core.clean(performance_expectation) AS performance_expectation
FROM raw.roles
QUALIFY row_number() OVER (PARTITION BY role_id ORDER BY source_row) = 1;
ALTER TABLE core.roles ADD PRIMARY KEY (role_id);

CREATE TABLE core.role_skills AS
SELECT DISTINCT core.role_key(sector, track, job_role) AS role_id,
       core.clean(tsc_ccs_code) AS framework_skill_code,
       core.clean(proficiency_level) AS required_level,
       try_cast(core.clean(proficiency_level) AS INTEGER) AS required_level_numeric,
       core.clean(tsc_ccs_title) AS source_skill_title,
       core.clean(tsc_ccs_type) AS skill_type
FROM raw.role_skills;
ALTER TABLE core.role_skills ADD PRIMARY KEY (role_id, framework_skill_code, required_level);

-- Missing active definitions are represented explicitly, not silently discarded.
CREATE TABLE core.framework_skills AS
WITH candidates AS (
    SELECT core.clean(tsc_code) AS framework_skill_code,
           core.clean(sector) AS sector, core.clean(tsc_ccs_category) AS category,
           core.clean(tsc_ccs_title) AS title, core.clean(tsc_ccs_description) AS description,
           core.clean(tsc_ccs_type) AS skill_type,
           try_cast(latest_update_date AS DATE) AS updated_date,
           'active_key' AS definition_source, 0 AS priority, source_row
    FROM raw.framework_skills
    UNION ALL
    SELECT core.clean(tsc_ccs_code), core.clean(sector), NULL,
           core.clean(tsc_ccs_title), NULL, core.clean(tsc_ccs_type), NULL,
           'role_requirement_fallback', 1, source_row
    FROM raw.role_skills
)
SELECT * EXCLUDE(priority, source_row) FROM candidates
QUALIFY row_number() OVER (PARTITION BY framework_skill_code ORDER BY priority, source_row) = 1;
ALTER TABLE core.framework_skills ADD PRIMARY KEY (framework_skill_code);

CREATE TABLE core.skill_proficiency AS
SELECT core.clean(tsc_ccs_code) AS framework_skill_code,
       core.clean(proficiency_level) AS level,
       try_cast(core.clean(proficiency_level) AS INTEGER) AS level_numeric,
       core.clean(proficiency_description) AS proficiency_description
FROM raw.knowledge_abilities
QUALIFY row_number() OVER (PARTITION BY framework_skill_code, level ORDER BY source_row) = 1;
ALTER TABLE core.skill_proficiency ADD PRIMARY KEY (framework_skill_code, level);

CREATE TABLE core.skill_knowledge_abilities AS
SELECT DISTINCT core.clean(tsc_ccs_code) AS framework_skill_code,
       core.clean(proficiency_level) AS level,
       core.clean(knowledge_ability_classification) AS item_type,
       core.clean(knowledge_ability_items) AS item_text
FROM raw.knowledge_abilities;

CREATE TABLE core.unique_skills AS
SELECT core.clean(skill_id) AS skill_id,
       core.clean(skill_transaction_id) AS transaction_id,
       core.clean(skill_title) AS title, core.clean(skill_description) AS description,
       core.clean(skill_type) AS skill_type,
       try_cast(emerging_skills AS BOOLEAN) AS is_emerging,
       try_cast(casl_skills AS BOOLEAN) AS is_casl
FROM raw.unique_skills
QUALIFY row_number() OVER (PARTITION BY skill_id ORDER BY source_row) = 1;
ALTER TABLE core.unique_skills ADD PRIMARY KEY (skill_id);

-- No skill ID exists in the mapping workbook. Resolve only unambiguous
-- normalised title matches. Keep all mapping rows, including "No mapping".
CREATE TABLE core.skill_mappings AS
WITH title_ids AS (
    SELECT lower(title) AS match_title, count(DISTINCT skill_id) AS matches,
           min(skill_id) AS candidate_id
    FROM core.unique_skills GROUP BY lower(title)
)
SELECT r.source_row AS mapping_id,
       core.clean(r.skills_framework_skill_code) AS framework_skill_code,
       core.clean(r.skills_framework_skill_pl) AS framework_level,
       core.clean(r.unique_skill_updated_skill_title) AS mapped_title,
       CASE WHEN u.matches = 1 THEN u.candidate_id END AS skill_id,
       CASE WHEN core.clean(r.unique_skill_updated_skill_title) IS NULL
                  OR lower(core.clean(r.unique_skill_updated_skill_title)) = 'no mapping' THEN 'no_mapping'
            WHEN u.matches IS NULL THEN 'unresolved_title'
            WHEN u.matches > 1 THEN 'ambiguous_title'
            ELSE 'matched' END AS mapping_status
FROM raw.skill_mappings r
LEFT JOIN title_ids u ON lower(core.clean(r.unique_skill_updated_skill_title)) = u.match_title;
ALTER TABLE core.skill_mappings ADD PRIMARY KEY (mapping_id);

CREATE TABLE core.role_tasks AS
SELECT DISTINCT core.role_key(sector, track, job_role) AS role_id,
       core.clean(critical_work_function) AS work_function,
       core.clean(key_tasks) AS task_text
FROM raw.role_tasks;

-- Preserve fees to six decimal places; do not round the source to cents,
-- infer GST, recalculate subsidies, or substitute zero for missing values.
CREATE TABLE core.courses AS
SELECT core.clean(coursereferencenumber) AS course_id,
       core.clean(coursetitle) AS title,
       core.clean(trainingprovideruen) AS provider_uen,
       core.clean(trainingprovideralias) AS provider_name,
       core.clean(about_this_course) AS description,
       core.clean(what_you_learn) AS learning_outcomes,
       core.clean(minimum_entry_requirement) AS entry_requirements,
       try_cast(full_course_fee AS DECIMAL(18,6)) AS full_fee,
       try_cast(course_fee_after_subsidies AS DECIMAL(18,6)) AS listed_subsidised_fee,
       try_cast(number_of_hours AS DOUBLE) AS hours,
       core.clean(training_commitment) AS training_commitment,
       core.clean(conducted_in) AS language,
       source_row AS selected_source_row
FROM raw.courses
-- Choose a whole source row, avoiding an artificial combination of versions.
-- Prefer populated learning outcomes, entry requirements and subsidised fees;
-- ties use the first spreadsheet row. All variants remain available in raw.
QUALIFY row_number() OVER (
    PARTITION BY course_id ORDER BY
    ((core.clean(what_you_learn) IS NOT NULL)::INTEGER +
     (core.clean(minimum_entry_requirement) IS NOT NULL)::INTEGER +
     (try_cast(course_fee_after_subsidies AS DECIMAL(18,6)) IS NOT NULL)::INTEGER) DESC,
    source_row
) = 1;
ALTER TABLE core.courses ADD PRIMARY KEY (course_id);

CREATE TABLE core.career_transitions (
    transition_id VARCHAR PRIMARY KEY,
    from_role_id VARCHAR REFERENCES core.roles(role_id),
    to_role_id VARCHAR REFERENCES core.roles(role_id),
    movement_type VARCHAR,
    conditions VARCHAR,
    verification_status VARCHAR,
    source_file VARCHAR,
    source_page INTEGER
);

CREATE TABLE core.source_records AS
SELECT 'role' AS entity_type, core.role_key(sector, track, job_role) AS entity_id,
       'roles' AS source_table, source_file, source_sheet, source_row FROM raw.roles
UNION ALL
SELECT 'role', core.role_key(sector, track, job_role), 'role_tasks', source_file, source_sheet, source_row FROM raw.role_tasks
UNION ALL
SELECT 'role', core.role_key(sector, track, job_role), 'role_skills', source_file, source_sheet, source_row FROM raw.role_skills
UNION ALL
SELECT 'framework_skill', core.clean(tsc_code), 'framework_skills', source_file, source_sheet, source_row FROM raw.framework_skills
UNION ALL
SELECT 'framework_skill', core.clean(tsc_ccs_code), 'role_skills', source_file, source_sheet, source_row FROM raw.role_skills
UNION ALL
SELECT 'skill_proficiency', core.pair_key(core.clean(tsc_ccs_code), core.clean(proficiency_level)),
       'knowledge_abilities', source_file, source_sheet, source_row FROM raw.knowledge_abilities
UNION ALL
SELECT 'unique_skill', core.clean(skill_id), 'unique_skills', source_file, source_sheet, source_row FROM raw.unique_skills
UNION ALL
SELECT 'skill_mapping', cast(source_row AS VARCHAR), 'skill_mappings', source_file, source_sheet, source_row FROM raw.skill_mappings
UNION ALL
SELECT 'course', core.clean(coursereferencenumber), 'courses', source_file, source_sheet, source_row FROM raw.courses;

-- Retrieval-ready text, not an embedding or search index. Keep entity IDs so
-- search results can fetch exact requirements and fees from the core tables.
CREATE TABLE core.search_documents AS
SELECT 'role:' || role_id AS document_id, 'role' AS entity_type, role_id AS entity_id,
       'description' AS section,
       concat_ws(chr(10), 'Role: ' || role_title, 'Sector: ' || sector,
                 'Track: ' || track, description, performance_expectation,
                 'Work functions and tasks: ' || tasks.items,
                 'Required skills: ' || skills.items) AS text
FROM core.roles
LEFT JOIN (
    SELECT role_id,
           string_agg(concat_ws(': ', work_function, task_text), chr(10)
                      ORDER BY work_function, task_text) AS items
    FROM core.role_tasks GROUP BY role_id
) tasks USING(role_id)
LEFT JOIN (
    SELECT role_id,
           string_agg(concat_ws(' | ', source_skill_title,
                               'Required level: ' || required_level,
                               'Code: ' || framework_skill_code), chr(10)
                      ORDER BY source_skill_title, framework_skill_code, required_level) AS items
    FROM core.role_skills GROUP BY role_id
) skills USING(role_id)
UNION ALL
SELECT 'course:' || course_id, 'course', course_id, 'course_details',
       concat_ws(chr(10), 'Course: ' || title, 'Provider: ' || provider_name,
                 'Description: ' || description, 'Learning outcomes: ' || learning_outcomes,
                 'Entry requirements: ' || entry_requirements)
FROM core.courses
UNION ALL
SELECT 'skill:' || core.pair_key(p.framework_skill_code, p.level), 'skill_proficiency',
       core.pair_key(p.framework_skill_code, p.level), 'proficiency',
       concat_ws(chr(10), 'Skill: ' || f.title, 'Sector: ' || f.sector,
                 'Framework code: ' || p.framework_skill_code, 'Level: ' || p.level,
                 f.description, p.proficiency_description,
                 'Knowledge and abilities: ' || a.items)
FROM core.skill_proficiency p
LEFT JOIN core.framework_skills f USING(framework_skill_code)
LEFT JOIN (
    SELECT framework_skill_code, level,
           string_agg(concat_ws(': ', item_type, item_text), chr(10) ORDER BY item_type, item_text) AS items
    FROM core.skill_knowledge_abilities GROUP BY framework_skill_code, level
) a USING(framework_skill_code, level);
ALTER TABLE core.search_documents ADD COLUMN content_hash VARCHAR;
UPDATE core.search_documents SET content_hash = sha256(text);
ALTER TABLE core.search_documents ADD PRIMARY KEY (document_id);

CREATE VIEW audit.course_duplicates AS
SELECT coursereferencenumber AS course_id, count(*) AS source_rows,
       count(DISTINCT full_course_fee) > 1 OR count(DISTINCT course_fee_after_subsidies) > 1 AS fee_conflict,
       count(DISTINCT coursetitle) > 1 OR count(DISTINCT trainingprovideruen) > 1 AS identity_conflict,
       count(DISTINCT what_you_learn) > 1 OR count(DISTINCT about_this_course) > 1 AS description_conflict
FROM raw.courses GROUP BY coursereferencenumber HAVING count(*) > 1;

CREATE VIEW audit.multiple_skill_mappings AS
SELECT framework_skill_code, count(DISTINCT mapped_title) AS mapped_titles
FROM core.skill_mappings GROUP BY framework_skill_code HAVING count(DISTINCT mapped_title) > 1;

CREATE VIEW audit.quality_summary AS
SELECT 'duplicate_course_ids' AS check_name, count(*) AS affected_count FROM audit.course_duplicates
UNION ALL SELECT 'course_ids_with_fee_conflicts', count(*) FROM audit.course_duplicates WHERE fee_conflict
UNION ALL SELECT 'course_ids_with_identity_conflicts', count(*) FROM audit.course_duplicates WHERE identity_conflict
UNION ALL SELECT 'course_ids_with_description_conflicts', count(*) FROM audit.course_duplicates WHERE description_conflict
UNION ALL SELECT 'courses_missing_subsidised_fee', count(*) FROM core.courses WHERE listed_subsidised_fee IS NULL
UNION ALL SELECT 'courses_missing_entry_requirements', count(*) FROM core.courses WHERE entry_requirements IS NULL
UNION ALL SELECT 'courses_missing_learning_outcomes', count(*) FROM core.courses WHERE learning_outcomes IS NULL
UNION ALL SELECT 'invalid_full_fee_values', count(*) FROM raw.courses WHERE core.clean(full_course_fee) IS NOT NULL AND try_cast(full_course_fee AS DECIMAL(18,6)) IS NULL
UNION ALL SELECT 'invalid_subsidised_fee_values', count(*) FROM raw.courses WHERE core.clean(course_fee_after_subsidies) IS NOT NULL AND try_cast(course_fee_after_subsidies AS DECIMAL(18,6)) IS NULL
UNION ALL SELECT 'invalid_hours_values', count(*) FROM raw.courses WHERE core.clean(number_of_hours) IS NOT NULL AND try_cast(number_of_hours AS DOUBLE) IS NULL
UNION ALL SELECT 'negative_fees_or_hours', count(*) FROM core.courses WHERE full_fee < 0 OR listed_subsidised_fee < 0 OR hours < 0
UNION ALL SELECT 'subsidised_fee_above_full_fee', count(*) FROM core.courses WHERE listed_subsidised_fee > full_fee
UNION ALL SELECT 'skill_codes_with_multiple_mappings', count(*) FROM audit.multiple_skill_mappings
UNION ALL SELECT 'unresolved_mapping_rows', count(*) FROM core.skill_mappings WHERE mapping_status <> 'matched'
UNION ALL SELECT 'role_skill_codes_missing_active_definition', count(*) FROM core.framework_skills WHERE definition_source = 'role_requirement_fallback'
UNION ALL SELECT 'role_requirements_without_proficiency_details', count(*) FROM core.role_skills r LEFT JOIN core.skill_proficiency p ON r.framework_skill_code=p.framework_skill_code AND r.required_level=p.level WHERE p.framework_skill_code IS NULL
UNION ALL SELECT 'non_numeric_proficiency_requirements', count(*) FROM core.role_skills WHERE required_level_numeric IS NULL
UNION ALL SELECT 'duplicate_unique_skill_ids', count(*) FROM (SELECT skill_id FROM raw.unique_skills GROUP BY skill_id HAVING count(*) > 1)
UNION ALL SELECT 'conflicting_proficiency_descriptions', count(*) FROM (SELECT tsc_ccs_code, proficiency_level FROM raw.knowledge_abilities GROUP BY tsc_ccs_code, proficiency_level HAVING count(DISTINCT core.clean(proficiency_description)) > 1)
UNION ALL SELECT 'duplicate_role_keys', count(*) FROM (SELECT core.role_key(sector,track,job_role) FROM raw.roles GROUP BY ALL HAVING count(*) > 1)
UNION ALL SELECT 'roles_without_skill_requirements', count(*) FROM core.roles r WHERE NOT EXISTS (SELECT 1 FROM core.role_skills s WHERE s.role_id = r.role_id)
UNION ALL SELECT 'roles_without_tasks', count(*) FROM core.roles r WHERE NOT EXISTS (SELECT 1 FROM core.role_tasks t WHERE t.role_id = r.role_id);
