"""Phase 1a: read the source workbook into tidy staging tables and log data-quality findings."""
import json

import pandas as pd

from config import RAW_XLSX, STAGE

SAMPLE_SHEETS = {"Attendance": "attendance", "Performance": "performance", "Hiring": "hiring"}


def snake(cols):
    return [c.strip().lower() for c in cols]


def main():
    issues = []

    em = pd.read_excel(RAW_XLSX, sheet_name="Employee_Master")
    em.columns = snake(em.columns)
    n = len(em)
    if not em.employee_id.is_unique:
        issues.append({"table": "employee_master", "severity": "high", "issue": "Duplicate Employee_ID values"})
    for col in ("hire_date", "exit_date"):
        if em[col].isna().all():
            issues.append({"table": "employee_master", "severity": "info",
                           "issue": f"{col} blank for all {n} rows (not in IBM source); left blank, not imputed"})
    if (em.location == "Not provided").all():
        issues.append({"table": "employee_master", "severity": "info",
                       "issue": "location = 'Not provided' for all rows; location analysis not possible"})
    bad_tenure = em[(em.years_at_company > em.total_working_years)
                    | (em.years_in_current_role > em.years_at_company)
                    | (em.years_with_current_manager > em.years_at_company)]
    issues.append({"table": "employee_master", "severity": "ok" if bad_tenure.empty else "medium",
                   "issue": f"Tenure consistency checks: {len(bad_tenure)} violating rows"})
    mismatch = (em.attrition.eq("Yes") != em.employment_status.eq("Exited")).sum()
    issues.append({"table": "employee_master", "severity": "ok" if mismatch == 0 else "high",
                   "issue": f"Attrition vs Employment_Status mismatches: {mismatch}"})
    em = em.drop(columns=["hire_date", "exit_date"])
    em.to_parquet(STAGE / "employee_master.parquet", index=False)

    ids = set(em.employee_id)
    for sheet, name in SAMPLE_SHEETS.items():
        df = pd.read_excel(RAW_XLSX, sheet_name=sheet, header=1)  # row 1 is a 'SYNTHETIC ILLUSTRATION' banner
        df.columns = snake(df.columns)
        id_col = "employee_id" if "employee_id" in df else "candidate_employee_id"
        orphan = sorted(set(df[id_col]) - ids)
        if orphan:
            issues.append({"table": f"sample_{name}", "severity": "high",
                           "issue": f"{len(orphan)} IDs not in Employee_Master: {', '.join(orphan)}"})
        df["is_synthetic"] = True
        df.to_parquet(STAGE / f"sample_{name}.parquet", index=False)

    hiring = pd.read_parquet(STAGE / "sample_hiring.parquet").merge(
        em[["employee_id", "department", "years_at_company"]],
        left_on="candidate_employee_id", right_on="employee_id", how="left", suffixes=("", "_master"))
    dept_mis = hiring.dropna(subset=["department_master"]).query("department != department_master")
    issues.append({"table": "sample_hiring", "severity": "high",
                   "issue": f"{len(dept_mis)} requisitions whose department differs from the hired employee's master department"})
    tenure_mis = hiring.query("years_at_company > 1")
    issues.append({"table": "sample_hiring", "severity": "high",
                   "issue": f"{len(tenure_mis)} candidates filled in 2026 but with >1 year tenure in master (ID collision with IBM records)"})
    issues.append({"table": "sample_hiring", "severity": "medium",
                   "issue": "Early_Exit_Within_1_Year populated for hires filled <1 year before the export date (outcome not yet observable)"})
    issues.append({"table": "kpi_summary", "severity": "high",
                   "issue": "'Exited employee records' formula uses COUNTA(Employee_ID) -> 1,470; should be COUNTIF(Attrition,\"Yes\") -> 237"})
    issues.append({"table": "kpi_summary", "severity": "low",
                   "issue": "'Employees with performance records' COUNTA includes the header row (21 vs 20)"})
    issues.append({"table": "dimensions", "severity": "medium",
                   "issue": "Tenure bands (<1, 1–3, 3–5, 5+) do not match Employee_Master Tenure_Band (0–1, 2–3, 4–5, 6–10, 10+); grade list G1–G4 omits G5 (69 rows)"})

    (STAGE / "data_quality.json").write_text(json.dumps(issues, indent=2, ensure_ascii=False))
    for i in issues:
        print(f"[{i['severity']:>6}] {i['table']}: {i['issue']}")


if __name__ == "__main__":
    main()
