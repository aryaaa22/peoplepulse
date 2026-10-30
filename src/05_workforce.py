"""Phase 3-4: productivity & hiring insights, talent-health scorecard, critical-role risk and the
quarterly headcount forecast. Writes an_* tables to DuckDB and CSVs to data/processed."""
import json

import duckdb
import numpy as np
import pandas as pd

from config import DB, PROC, SEED, SNAPSHOT_DATE

rng = np.random.default_rng(SEED)
FORECAST_QUARTERS = [str(q) for q in pd.period_range(pd.Period(SNAPSHOT_DATE, "Q") + 1, periods=4, freq="Q")]
N_SIMS = 2000


def productivity(con):
    by_role = con.execute("SELECT * FROM vw_productivity_by_role").df()
    by_rating = con.execute("""
        SELECT f.performance_rating, CASE WHEN f.overtime THEN 'Yes' ELSE 'No' END AS overtime,
               count(DISTINCT p.employee_id) AS employees, round(avg(p.productivity_score), 1) AS avg_productivity
        FROM fct_productivity_quarterly p JOIN fct_employee_snapshot f USING (employee_id)
        GROUP BY ALL ORDER BY 1, 2""").df()
    return by_role, by_rating


def hiring(con):
    src = con.execute("SELECT * FROM vw_hiring_by_source").df()
    by_grade = con.execute("""
        SELECT grade, department, count(*) AS hires, round(avg(time_to_fill_days), 1) AS avg_time_to_fill
        FROM fct_requisition GROUP BY ALL ORDER BY 1, 2""").df()
    probation = con.execute("""
        SELECT probation_result, early_exit_within_1_year, count(*) AS hires FROM fct_requisition GROUP BY ALL ORDER BY 1, 2""").df()
    first_year = con.execute("""
        SELECT department, count(*) AS first_year_records, sum(is_exit) AS first_year_exits,
               round(sum(is_exit) / count(*), 4) AS first_year_exit_proportion
        FROM vw_employee WHERE years_at_company = 0 GROUP BY ALL ORDER BY 1""").df()
    return src, by_grade, probation, first_year


def scorecard(con):
    sc = con.execute("""
        WITH e AS (
          SELECT v.department, count(*) AS records, sum(v.is_active) AS active, sum(v.is_exit) AS exits,
                 attr_rate(sum(v.is_exit), count(*)) AS attrition_rate,
                 avg(CASE WHEN v.is_active = 1 THEN (r.risk_tier = 'High')::INT END) AS high_risk_share,
                 avg(CASE WHEN v.is_active = 1 THEN v.overtime::INT END) AS overtime_share,
                 avg(CASE WHEN v.is_active = 1 THEN (v.job_satisfaction <= 2)::INT END) AS low_satisfaction_share,
                 avg(CASE WHEN v.is_active = 1 THEN v.promotion_stalled END) AS promotion_stalled_share
          FROM vw_employee v JOIN an_risk_scores r USING (employee_id) GROUP BY 1),
        a AS (SELECT department, sum(absent_days) / sum(scheduled_days) AS absenteeism_rate_syn FROM vw_absenteeism_monthly GROUP BY 1),
        p AS (SELECT d.department, avg(productivity_score) AS avg_productivity_syn
              FROM fct_productivity_quarterly pq JOIN dim_employee de USING (employee_id) JOIN dim_department d USING (department_key)
              WHERE review_period = (SELECT max(review_period) FROM fct_productivity_quarterly) GROUP BY 1),
        h AS (SELECT department, avg(time_to_fill_days) AS avg_time_to_fill_syn FROM fct_requisition GROUP BY 1)
        SELECT * FROM e JOIN a USING (department) JOIN p USING (department) JOIN h USING (department) ORDER BY department""").df()
    # Composite 0-100 (higher = healthier): each metric scored against the company-wide value
    company = con.execute("""SELECT attr_rate(sum(is_exit), count(*)) AS attrition_rate FROM fct_employee_snapshot""").fetchone()[0]
    weights = {"attrition_rate": 0.30, "high_risk_share": 0.20, "low_satisfaction_share": 0.15, "overtime_share": 0.10,
               "promotion_stalled_share": 0.05, "absenteeism_rate_syn": 0.10, "avg_time_to_fill_syn": 0.10}
    score = np.zeros(len(sc))
    for m, w in weights.items():
        ref = company if m == "attrition_rate" else (sc[m] * sc.active).sum() / sc.active.sum()
        score += w * np.clip(100 - 200 * (sc[m] / ref - 1), 0, 100)  # 100 at/under company level, -2 pts per 1% worse
    sc["talent_health_score"] = score.round(1)
    sc["rag"] = np.select([sc.talent_health_score >= 90, sc.talent_health_score >= 75], ["Green", "Amber"], "Red")
    return sc.round(4), weights


def critical_roles(con):
    return con.execute("""
        SELECT v.job_role, v.role_family, v.is_critical, count(*) AS records, sum(v.is_active) AS active, sum(v.is_exit) AS exits,
               attr_rate(sum(v.is_exit), count(*)) AS attrition_rate,
               round(avg(r.risk_probability) FILTER (WHERE v.is_active = 1), 4) AS avg_risk_active,
               count(*) FILTER (WHERE v.is_active = 1 AND r.risk_tier = 'High') AS high_risk_active,
               round(sum(r.risk_probability) FILTER (WHERE v.is_active = 1), 1) AS expected_exits_12m,
               round(avg(v.years_at_company) FILTER (WHERE v.is_active = 1), 1) AS avg_tenure_active,
               round(avg(v.monthly_income) FILTER (WHERE v.is_active = 1), 0) AS avg_income_active
        FROM vw_employee v JOIN an_risk_scores r USING (employee_id)
        GROUP BY ALL ORDER BY is_critical DESC, expected_exits_12m DESC""").df()


def forecast(con):
    """Quarterly headcount forecast per department, Monte Carlo over individual exit risk.

    Assumptions (documented in README): model probability = 12-month exit probability (IBM exits treated as one
    year); quarterly hazard = 1-(1-p)^(1/4); backfill hires arrive one quarter after the exit (avg time to fill
    ~6 weeks + notice/onboarding); backfilled hires carry the first-year exit hazard observed in IBM data.
    """
    act = con.execute("""SELECT v.employee_id, v.department, r.risk_probability, r.risk_tier
                         FROM vw_employee v JOIN an_risk_scores r USING (employee_id) WHERE v.is_active = 1""").df()
    fy = con.execute("SELECT sum(is_exit)/count(*) FROM vw_employee WHERE years_at_company = 0").fetchone()[0]
    scenarios = {
        "Base: backfill 80% of exits": dict(backfill=0.8, retention_cut=0.0, growth=0),
        "Hiring freeze": dict(backfill=0.0, retention_cut=0.0, growth=0),
        "Retention programme (-30% risk for High tier) + 80% backfill": dict(backfill=0.8, retention_cut=0.3, growth=0),
        "Growth plan: 80% backfill + 2% net new hires per quarter": dict(backfill=0.8, retention_cut=0.0, growth=0.02),
    }
    rows = []
    for name, s in scenarios.items():
        for dept, g in act.groupby("department"):
            p = g.risk_probability.to_numpy() * np.where(g.risk_tier.eq("High"), 1 - s["retention_cut"], 1.0)
            qh = 1 - (1 - p) ** 0.25
            qh_new = 1 - (1 - fy) ** 0.25
            start = len(g)
            sims = np.zeros((N_SIMS, 4))
            exits_sims = np.zeros((N_SIMS, 4))
            for i in range(N_SIMS):
                alive = np.ones(len(g), bool)
                new_hc, pending = 0, 0
                for q in range(4):
                    ex_old = rng.random(len(g)) < qh
                    ex_old &= alive
                    alive &= ~ex_old
                    ex_new = rng.binomial(new_hc, qh_new) if new_hc else 0
                    new_hc -= ex_new
                    new_hc += pending + int(round(s["growth"] * start))
                    exits = ex_old.sum() + ex_new
                    pending = rng.binomial(exits, s["backfill"]) if s["backfill"] else 0
                    sims[i, q] = alive.sum() + new_hc
                    exits_sims[i, q] = exits
            for q in range(4):
                rows.append({"scenario": name, "department": dept, "quarter": FORECAST_QUARTERS[q], "start_headcount": start,
                             "headcount_p50": float(np.median(sims[:, q])), "headcount_p10": float(np.percentile(sims[:, q], 10)),
                             "headcount_p90": float(np.percentile(sims[:, q], 90)), "expected_exits": float(exits_sims[:, q].mean())})
    fc = pd.DataFrame(rows)
    total = fc.groupby(["scenario", "quarter"], as_index=False)[["start_headcount", "headcount_p50", "headcount_p10", "headcount_p90", "expected_exits"]].sum()
    total["department"] = "All"
    return pd.concat([fc, total], ignore_index=True).round(1), {"first_year_exit_proportion": round(fy, 4), "sims": N_SIMS,
                                                                "quarters": FORECAST_QUARTERS}


def main():
    con = duckdb.connect(str(DB))
    out = {}
    out["productivity_by_role_syn"], out["productivity_by_rating_syn"] = productivity(con)
    out["hiring_by_source_syn"], out["time_to_fill_by_grade_syn"], out["probation_outcomes_syn"], out["first_year_exits"] = hiring(con)
    out["talent_health_scorecard"], weights = scorecard(con)
    out["critical_role_risk"] = critical_roles(con)
    out["headcount_forecast"], fmeta = forecast(con)
    for name, df in out.items():
        con.register("tmp", df)
        con.execute(f"CREATE OR REPLACE TABLE an_{name} AS SELECT * FROM tmp")
        con.unregister("tmp")
        df.to_csv(PROC / f"{name}.csv", index=False)
    (PROC / "workforce_meta.json").write_text(json.dumps({"scorecard_weights": weights, "forecast": fmeta}, indent=2))
    for k in ["hiring_by_source_syn", "first_year_exits", "talent_health_scorecard", "critical_role_risk"]:
        print("==", k); print(out[k].to_string(index=False))
    print(out["headcount_forecast"].query("department == 'All'").to_string(index=False))
    print(out["productivity_by_rating_syn"].to_string(index=False))
    con.close()


if __name__ == "__main__":
    main()
