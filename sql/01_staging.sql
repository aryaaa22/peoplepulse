-- Load staging (real IBM) and synthetic parquet files. {stage} / {syn} are substituted by build_model.py
CREATE OR REPLACE TABLE stg_employee_master AS SELECT * FROM read_parquet('{stage}/employee_master.parquet');
CREATE OR REPLACE TABLE syn_employee_timeline AS SELECT * FROM read_parquet('{syn}/syn_employee_timeline.parquet');
CREATE OR REPLACE TABLE syn_attendance_monthly AS SELECT * FROM read_parquet('{syn}/syn_attendance_monthly.parquet');
CREATE OR REPLACE TABLE syn_productivity_quarterly AS SELECT * FROM read_parquet('{syn}/syn_productivity_quarterly.parquet');
CREATE OR REPLACE TABLE syn_requisitions AS SELECT * FROM read_parquet('{syn}/syn_requisitions.parquet');
