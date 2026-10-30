-- KPI views (see docs/KPI_DICTIONARY.md). Attrition rate = exits / average headcount, where
-- average headcount = (records + active) / 2, under the assumption that IBM exits span one year.
CREATE OR REPLACE VIEW vw_employee AS
SELECT f.*, d.department, d.department_short, r.job_role, r.role_family, r.is_critical, g.grade, g.grade_band,
       t.tenure_band, de.gender, de.age, de.age_band
FROM fct_employee_snapshot f
JOIN dim_employee de USING (employee_id)
JOIN dim_department d ON d.department_key = f.department_key
JOIN dim_job_role r ON r.job_role_key = f.job_role_key
JOIN dim_grade g ON g.grade_key = f.grade_key
JOIN dim_tenure_band t ON t.tenure_band_key = f.tenure_band_key;

CREATE OR REPLACE MACRO attr_rate(exits, records) AS round(exits / ((records + (records - exits)) / 2.0), 4);

CREATE OR REPLACE VIEW vw_kpi_overall AS
SELECT count(*) AS employee_records, sum(is_active) AS active_headcount, sum(is_exit) AS exits,
       round(sum(is_exit) / count(*), 4) AS dataset_attrition_proportion,
       attr_rate(sum(is_exit), count(*)) AS annualised_attrition_rate,
       round(avg(monthly_income) FILTER (WHERE is_active = 1), 0) AS avg_monthly_income_active,
       round(avg(overtime::INT), 4) AS overtime_share,
       (SELECT round(sum(absent_days) / sum(scheduled_days), 4) FROM fct_attendance_monthly) AS absenteeism_rate_syn,
       (SELECT round(avg(time_to_fill_days), 1) FROM fct_requisition) AS avg_time_to_fill_days_syn,
       (SELECT round(avg(productivity_score), 1) FROM fct_productivity_quarterly
          WHERE review_period = (SELECT max(review_period) FROM fct_productivity_quarterly)) AS avg_productivity_latest_q_syn
FROM fct_employee_snapshot;

CREATE OR REPLACE VIEW vw_attrition_by_dimension AS
SELECT 'Department' AS dimension, department AS value, count(*) AS records, sum(is_exit) AS exits FROM vw_employee GROUP BY ALL
UNION ALL SELECT 'Job role', job_role, count(*), sum(is_exit) FROM vw_employee GROUP BY ALL
UNION ALL SELECT 'Grade', grade, count(*), sum(is_exit) FROM vw_employee GROUP BY ALL
UNION ALL SELECT 'Tenure band', tenure_band, count(*), sum(is_exit) FROM vw_employee GROUP BY ALL
UNION ALL SELECT 'Overtime', CASE WHEN overtime THEN 'Yes' ELSE 'No' END, count(*), sum(is_exit) FROM vw_employee GROUP BY ALL
UNION ALL SELECT 'Job satisfaction', job_satisfaction::VARCHAR, count(*), sum(is_exit) FROM vw_employee GROUP BY ALL
UNION ALL SELECT 'Age band', age_band, count(*), sum(is_exit) FROM vw_employee GROUP BY ALL
UNION ALL SELECT 'Gender', gender, count(*), sum(is_exit) FROM vw_employee GROUP BY ALL
UNION ALL SELECT 'Manager tenure', CASE WHEN years_with_current_manager = 0 THEN 'New manager (<1 yr)'
                                         WHEN years_with_current_manager <= 2 THEN '1–2 yrs' ELSE '3+ yrs' END, count(*), sum(is_exit) FROM vw_employee GROUP BY ALL
UNION ALL SELECT 'Promotion gap', CASE WHEN years_since_last_promotion >= 5 THEN '5+ yrs' WHEN years_since_last_promotion >= 2 THEN '2–4 yrs' ELSE '0–1 yrs' END, count(*), sum(is_exit) FROM vw_employee GROUP BY ALL;

CREATE OR REPLACE VIEW vw_attrition_cohort AS
SELECT department, tenure_band, t.tenure_band_key, count(*) AS records, sum(is_exit) AS exits,
       round(sum(is_exit) / count(*), 4) AS exit_proportion
FROM vw_employee JOIN dim_tenure_band t USING (tenure_band)
GROUP BY ALL ORDER BY department, tenure_band_key;

CREATE OR REPLACE VIEW vw_absenteeism_monthly AS
SELECT a.month_start, d.department, sum(a.scheduled_days) AS scheduled_days, sum(a.absent_days) AS absent_days,
       round(sum(a.absent_days) / sum(a.scheduled_days), 4) AS absenteeism_rate, TRUE AS is_synthetic
FROM fct_attendance_monthly a JOIN dim_employee de USING (employee_id) JOIN dim_department d USING (department_key)
GROUP BY ALL ORDER BY 1, 2;

CREATE OR REPLACE VIEW vw_hiring_by_source AS
SELECT hiring_source, count(*) AS hires, round(avg(time_to_fill_days), 1) AS avg_time_to_fill,
       round(median(time_to_fill_days), 1) AS median_time_to_fill,
       count(*) FILTER (WHERE early_exit_within_1_year <> 'Not yet observable') AS hires_with_outcome,
       count(*) FILTER (WHERE early_exit_within_1_year = 'Yes') AS early_exits,
       round(count(*) FILTER (WHERE early_exit_within_1_year = 'Yes')
             / nullif(count(*) FILTER (WHERE early_exit_within_1_year <> 'Not yet observable'), 0), 4) AS early_exit_rate,
       count(*) FILTER (WHERE probation_result = 'Failed / exited') AS probation_fails,
       TRUE AS source_is_synthetic
FROM fct_requisition GROUP BY ALL ORDER BY avg_time_to_fill;

CREATE OR REPLACE VIEW vw_productivity_by_role AS
SELECT r.role_family, r.job_role, p.review_period, count(*) AS employees, round(avg(productivity_score), 1) AS avg_productivity,
       TRUE AS is_synthetic
FROM fct_productivity_quarterly p JOIN dim_job_role r USING (job_role_key)
GROUP BY ALL ORDER BY 1, 2, 3;
