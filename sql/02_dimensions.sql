-- Star-schema dimensions
CREATE OR REPLACE TABLE dim_department AS
SELECT row_number() OVER (ORDER BY department) AS department_key, department,
       CASE department WHEN 'Research & Development' THEN 'R&D' WHEN 'Human Resources' THEN 'HR' ELSE department END AS department_short
FROM (SELECT DISTINCT department FROM stg_employee_master);

-- role_family groups roles for productivity comparison; is_critical = leadership or revenue-carrying roles (documented assumption)
CREATE OR REPLACE TABLE dim_job_role AS
SELECT row_number() OVER (ORDER BY job_role) AS job_role_key, job_role,
       CASE WHEN job_role IN ('Manager','Research Director','Manufacturing Director') THEN 'Leadership'
            WHEN job_role IN ('Sales Executive','Sales Representative','Healthcare Representative') THEN 'Commercial'
            WHEN job_role IN ('Research Scientist','Laboratory Technician') THEN 'Research & Lab'
            ELSE 'Support functions' END AS role_family,
       job_role IN ('Manager','Research Director','Manufacturing Director','Sales Executive') AS is_critical
FROM (SELECT DISTINCT job_role FROM stg_employee_master);

CREATE OR REPLACE TABLE dim_grade AS
SELECT DISTINCT job_level AS grade_key, grade,
       CASE WHEN job_level <= 2 THEN 'Junior' WHEN job_level = 3 THEN 'Mid' ELSE 'Senior' END AS grade_band
FROM stg_employee_master;

CREATE OR REPLACE TABLE dim_tenure_band AS
SELECT * FROM (VALUES
  (1, '0–1 Years', 0, 1), (2, '2–3 Years', 2, 3), (3, '4–5 Years', 4, 5),
  (4, '6–10 Years', 6, 10), (5, '10+ Years', 11, 99)
) t(tenure_band_key, tenure_band, min_years, max_years);

CREATE OR REPLACE TABLE dim_location AS
SELECT 1 AS location_key, 'Not provided' AS location, 'IBM source has no location field' AS note;

CREATE OR REPLACE TABLE dim_date AS
SELECT d::DATE AS month_start, year(d) AS year, quarter(d) AS quarter,
       strftime(d, '%Y-%m') AS year_month, year(d) || '-Q' || quarter(d) AS year_quarter
FROM range(DATE '2024-01-01', DATE '2028-01-01', INTERVAL 1 MONTH) r(d);

CREATE OR REPLACE TABLE dim_employee AS
SELECT e.employee_id, e.gender, e.age,
       CASE WHEN e.age < 25 THEN '<25' WHEN e.age < 35 THEN '25–34' WHEN e.age < 45 THEN '35–44' ELSE '45+' END AS age_band,
       d.department_key, r.job_role_key, g.grade_key, t.tenure_band_key, 1 AS location_key,
       e.employment_status, e.source
FROM stg_employee_master e
JOIN dim_department d USING (department)
JOIN dim_job_role r USING (job_role)
JOIN dim_grade g ON g.grade_key = e.job_level
JOIN dim_tenure_band t ON e.years_at_company BETWEEN t.min_years AND t.max_years;
