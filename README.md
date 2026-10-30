# PeoplePulse – Workforce Attrition & Productivity Analytics

End-to-end HR analytics project from the internship brief (`docs/project_brief.pdf`): an HR data model, attrition and
productivity analytics, an early-warning risk model, a quarterly headcount forecast, an interactive dashboard and an HR
recommendation deck.

## Streamlit app

`app.py` is a one-page Streamlit dashboard: KPIs, attrition by group, department x tenure table, manager tenure, high-risk
employees, headcount forecast, department scorecard and recommendations, with a department filter.

```bash
pip install -r requirements.txt
# to rebuild data/processed: pip install -r requirements-pipeline.txt && ./run_all.sh
streamlit run app.py    # opens http://localhost:8501
```

## Deliverables (`outputs/`)

| File | What it is |
|---|---|
| `PeoplePulse_Dashboard.html` | Interactive workforce analytics website (single offline file). Department filter, base KPI cards and tabs for Overview with brief coverage, 1. Data foundation, 2. Attrition & risk, 3. Productivity & hiring, 4. Workforce planning, and Recommendations |
| `PeoplePulse_HR_Recommendations.pptx` | 13-slide HR planning recommendation deck |
| `PeoplePulse_Analytics.xlsx` | Power BI / Excel-ready workbook: star-schema tables, KPI views, risk scores, forecast, scorecard, data-quality log and a corrected KPI summary |
| `charts/*.png` | Static charts used in the deck (`*_syn.png` = synthetic data) |
| `data/peoplepulse.duckdb` | The analytical warehouse (rebuilt by `run_all.sh`) |

## Data: real vs synthetic

**Real – IBM HR Analytics, `Employee_Master` (1,470 records, 237 exits).** Department, role, grade, tenure, pay, overtime,
satisfaction, performance rating, manager and promotion history. All attrition, risk-model, scorecard, critical-role and
forecast results come from this data.

The source has **no hire dates, exit dates or locations**. They are left blank, not invented. No location analysis is
done. Rates that need a time window assume the 237 exits happened during the 12 months before the snapshot (2026-09-30).

**Synthetic – `data/synthetic/`, every row flagged `is_synthetic = TRUE`, tables prefixed `syn_`.** The data has no
attendance, requisitions or productivity, so `src/02_synthetic.py` generates them with a fixed seed (42), keyed to the
real employee IDs:
- 12 months of attendance
- 4 quarters of productivity scores
- 215 requisitions with source and time-to-fill

They are built only from real attributes (overtime, satisfaction, rating, level, tenure), with no exit signal added.
They show that the method works and are **not findings**. Replace them with HRIS, time-and-attendance and ATS data
when those are available.

The workbook's starter Attendance / Performance / Hiring sheets were **not** used:
- they contain IDs (E0003, E0006, E0009, E0017) that are not in the master
- their records collide with unrelated IBM employees

### Source issues found and fixed

| Sheet | Issue | Fix |
|---|---|---|
| KPI_Summary | "Exited employee records" = `COUNTA(...)` → 1,470 | `COUNTIF(Attrition,"Yes")` → 237 |
| KPI_Summary | Performance-record count includes the header row | Counted from data |
| Attendance / Performance / Hiring | Orphan IDs, department conflicts, sample hires matched to long-tenured IBM IDs | Replaced by the labelled synthetic layer |
| Dimensions | Tenure bands differ from the data; grade list omits G5 | Dimensions rebuilt from the data |

## Data model (DuckDB, `sql/`)

- **Dimensions:**
  - `dim_department`
  - `dim_job_role` (role family, `is_critical`)
  - `dim_grade`
  - `dim_tenure_band`
  - `dim_location` (placeholder: "Not provided")
  - `dim_date`
  - `dim_employee`
- **Facts:**
  - `fct_employee_snapshot` (real)
  - `fct_attendance_monthly` (syn)
  - `fct_productivity_quarterly` (syn)
  - `fct_requisition` (syn)
  - `fct_headcount_monthly` (syn timeline)
- **KPI views:**
  - `vw_kpi_overall`
  - `vw_attrition_by_dimension`
  - `vw_attrition_cohort`
  - `vw_absenteeism_monthly`
  - `vw_hiring_by_source`
  - `vw_productivity_by_role`
- **Analysis tables:** `an_*`, written by the Python steps.

## KPI dictionary

| KPI | Definition | Basis | Value |
|---|---|---|---|
| Active headcount | Records with Attrition = No | Real | 1,233 |
| Exits | Records with Attrition = Yes | Real | 237 |
| Exit proportion | Exits / records in a segment (95% Wilson CI; "significant" = CI excludes company rate) | Real | 16.1% |
| Annualised attrition rate | Exits / average headcount = exits / ((records + active) / 2) | Real + 12-month assumption | 17.5% |
| Early exit within 1 year | Exited with Years_at_Company = 0, over employees with Years_at_Company = 0 | Real | 36% (16 / 44) |
| Overtime share | Records with OverTime = Yes / all records | Real | 28.3% |
| Risk probability | Out-of-fold probability from 5-fold logistic regression (10 numeric + 4 categorical features) | Real | – |
| Risk tier | High ≥ 0.313 (top 10% of active), Medium ≥ 0.161 (next 20%), else Low | Real | 124 High active |
| Expected exits (12 mo) | Sum of risk probabilities over active employees | Real | 165 |
| Early-warning flags | Count of: overtime, job satisfaction = 1, grade G1, tenure ≤ 1 yr, new manager (< 1 yr), bottom-quartile pay, ≤ 2 yrs total experience | Real | – |
| Talent health score | 0–100 weighted composite vs company level (100 at or better; −2 pts per 1% worse). Weights: attrition 30%, high-risk 20%, low satisfaction 15%, overtime 10%, absenteeism 10%, time to fill 10%, promotion stalled 5%. Green ≥ 90, Amber ≥ 75, else Red | Mixed (20% synthetic) | Sales 60 Red, HR 80 Amber, R&D 99 Green |
| Absenteeism rate | Absent days / scheduled workdays | Synthetic | 3.4% |
| Time to fill | Fill date − open date (days) | Synthetic | 41 days |
| Productivity score | 0–100 quarterly index | Synthetic | 64.8 |
| Headcount forecast | Median and P10–P90 of 2,000 Monte Carlo runs over individual quarterly hazards `1-(1-p)^0.25`; backfills arrive one quarter after the exit; new hires carry the observed first-year exit rate | Real + assumptions | Base 2027Q3 ≈ 1,164 |

**Critical roles (assumption):** Manager, Research Director, Manufacturing Director, Sales Executive. Change them in
`sql/02_dimensions.sql`.

## Key findings

- **Overtime** is the strongest driver of exits:
  - 30.5% exit with overtime vs 10.4% without
  - odds ratio ×4.4 after controlling for role, pay, tenure and satisfaction
- **Exits peak early:**
  - 0–1 yr tenure: 35%
  - new manager within the last year: 32%
  - grade G1: 26%
  - age under 25: 39%
- **Hotspot roles:**
  - Sales Representatives: 40% exit proportion, 50% annualised
  - Laboratory Technicians: 24%
- **Department health:** Sales is Red on talent health.
- **Early-warning model:**
  - ROC AUC 0.77
  - the top-10% tier holds 44% of all exits
- **Forecast:**
  - with 80% backfill, headcount falls from 1,233 to about 1,164 by 2027Q3
  - a hiring freeze takes it to about 1,068
  - targeting the High tier avoids about 17 exits a year

## Reproduce

```bash
pip install -r requirements.txt
./run_all.sh                     # ingest → synthetic → DuckDB model → analytics → workbook/charts → deck
```

The dashboard is compiled from `dashboard/dashboard_body.html` with `dashboard/dashboard_data.json` (written by
`06_export.py`) using the Devin artifact kit. The compiled `outputs/PeoplePulse_Dashboard.html` needs no server or
internet connection.

## Limitations

- A single snapshot with no dates, so attrition is cross-sectional. The risk model shows association, not cause, and
  needs validation against a future period.
- "New manager" stands in for a manager change, using Years_With_Current_Manager = 0.
- Gender is a model input. Audit the tiers for fairness before operational use. Use scores for planning in aggregate,
  not for decisions about individuals.
- Small cells, such as HR 0–1 yr (n = 5), are directional only.
