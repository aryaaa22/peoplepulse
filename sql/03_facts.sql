-- Facts. fct_employee_snapshot is REAL IBM data; facts prefixed by syn_ source are SYNTHETIC (is_synthetic = TRUE)
CREATE OR REPLACE TABLE fct_employee_snapshot AS
SELECT e.employee_id, de.department_key, de.job_role_key, de.grade_key, de.tenure_band_key, de.location_key,
       DATE '{snapshot}' AS snapshot_date,
       (e.attrition = 'Yes')::INT AS is_exit,
       (e.attrition = 'No')::INT AS is_active,
       e.monthly_income, e.overtime = 'Yes' AS overtime, e.job_satisfaction, e.performance_rating,
       e.years_at_company, e.total_working_years, e.years_in_current_role, e.years_since_last_promotion,
       e.years_with_current_manager,
       (e.years_with_current_manager = 0)::INT AS recent_manager_change,
       (e.years_since_last_promotion >= 5)::INT AS promotion_stalled,
       FALSE AS is_synthetic
FROM stg_employee_master e JOIN dim_employee de USING (employee_id);

CREATE OR REPLACE TABLE fct_attendance_monthly AS
SELECT a.attendance_id, a.employee_id, a.month::DATE AS month_start, a.scheduled_days, a.absent_days, a.leave_days, a.is_synthetic
FROM syn_attendance_monthly a;

CREATE OR REPLACE TABLE fct_productivity_quarterly AS
SELECT p.*, de.job_role_key FROM syn_productivity_quarterly p JOIN dim_employee de USING (employee_id);

CREATE OR REPLACE TABLE fct_requisition AS
SELECT r.*, d.department_key, (SELECT job_role_key FROM dim_job_role j WHERE j.job_role = r.job_role) AS job_role_key
FROM syn_requisitions r JOIN dim_department d USING (department);

-- Monthly headcount movement from the synthetic timeline
CREATE OR REPLACE TABLE fct_headcount_monthly AS
WITH months AS (SELECT month_start FROM dim_date WHERE month_start BETWEEN DATE '{snapshot}' - INTERVAL 11 MONTH - INTERVAL 29 DAY AND DATE '{snapshot}')
SELECT m.month_start, de.department_key,
       count(*) FILTER (WHERE t.syn_hire_date < m.month_start AND (t.syn_exit_date IS NULL OR t.syn_exit_date >= m.month_start)) AS opening_headcount,
       count(*) FILTER (WHERE t.syn_hire_date >= m.month_start AND t.syn_hire_date < m.month_start + INTERVAL 1 MONTH) AS hires,
       count(*) FILTER (WHERE t.syn_exit_date >= m.month_start AND t.syn_exit_date < m.month_start + INTERVAL 1 MONTH) AS exits,
       TRUE AS is_synthetic
FROM months m CROSS JOIN syn_employee_timeline t JOIN dim_employee de USING (employee_id)
GROUP BY ALL;
