"""Phase 2: attrition diagnostics, early-warning indicators and the attrition risk model (real IBM data)."""
import json

import duckdb
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from config import DB, PROC, SEED

NUM = ["age", "monthly_income", "job_level", "job_satisfaction", "performance_rating", "years_at_company",
       "total_working_years", "years_in_current_role", "years_since_last_promotion", "years_with_current_manager"]
CAT = ["department", "job_role", "gender", "overtime"]


def wilson(k, n, z=1.96):
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


def diagnostics(con):
    df = con.execute("SELECT * FROM vw_attrition_by_dimension").df()
    overall = con.execute("SELECT sum(is_exit)/count(*) FROM fct_employee_snapshot").fetchone()[0]
    df["exit_proportion"] = df.exits / df.records
    df["ci_low"], df["ci_high"] = wilson(df.exits, df.records)
    df["lift_vs_overall"] = df.exit_proportion / overall
    df["significant"] = (df.ci_low > overall) | (df.ci_high < overall)
    return df.round(4), overall


def early_warning_flags(emp):
    q1 = emp.monthly_income.quantile(0.25)
    flags = pd.DataFrame({
        "employee_id": emp.employee_id,
        "flag_overtime": emp.overtime.astype(int),
        "flag_low_satisfaction": (emp.job_satisfaction == 1).astype(int),
        "flag_entry_grade": (emp.job_level == 1).astype(int),
        "flag_first_year": (emp.years_at_company <= 1).astype(int),
        "flag_new_manager": (emp.years_with_current_manager == 0).astype(int),
        "flag_low_pay_quartile": (emp.monthly_income <= q1).astype(int),
        "flag_early_career": (emp.total_working_years <= 2).astype(int),
    })
    flags["flag_count"] = flags.filter(like="flag_").sum(axis=1)
    return flags, q1


def model(emp):
    X = emp[NUM + CAT].copy()
    X["overtime"] = X.overtime.map({True: "Yes", False: "No"})
    y = emp.is_exit.to_numpy()
    pre = ColumnTransformer([("num", StandardScaler(), NUM), ("cat", OneHotEncoder(drop="first"), CAT)])
    cv = StratifiedKFold(5, shuffle=True, random_state=SEED)
    candidates = {
        "logistic_regression": Pipeline([("pre", pre), ("clf", LogisticRegression(C=0.5, max_iter=2000))]),
        "gradient_boosting": Pipeline([("pre", pre), ("clf", GradientBoostingClassifier(
            n_estimators=200, max_depth=2, learning_rate=0.05, subsample=0.8, random_state=SEED))]),
    }
    metrics, oof = {}, {}
    for name, pipe in candidates.items():
        p = cross_val_predict(pipe, X, y, cv=cv, method="predict_proba")[:, 1]
        oof[name] = p
        metrics[name] = {"roc_auc": round(roc_auc_score(y, p), 3), "pr_auc": round(average_precision_score(y, p), 3),
                         "brier": round(brier_score_loss(y, p), 4)}
    chosen = max(metrics, key=lambda k: metrics[k]["roc_auc"])
    if metrics["logistic_regression"]["roc_auc"] >= metrics[chosen]["roc_auc"] - 0.01:
        chosen = "logistic_regression"  # prefer the explainable model when within 0.01 AUC
    lr = candidates["logistic_regression"].fit(X, y)
    names = lr.named_steps["pre"].get_feature_names_out()
    coefs = pd.DataFrame({"feature": [n.split("__", 1)[1] for n in names], "coef": lr.named_steps["clf"].coef_[0]})
    coefs["odds_ratio"] = np.exp(coefs.coef)
    coefs["direction"] = np.where(coefs.coef > 0, "raises risk", "lowers risk")
    coefs = coefs.reindex(coefs.coef.abs().sort_values(ascending=False).index).round(4)

    contrib = lr.named_steps["pre"].transform(X)
    contrib = np.asarray(contrib.todense() if hasattr(contrib, "todense") else contrib) * lr.named_steps["clf"].coef_[0]
    readable = [n.split("__", 1)[1] for n in names]
    top = [", ".join(readable[j] for j in np.argsort(-row)[:3] if row[j] > 0) for row in contrib]

    scores = emp[["employee_id"]].copy()
    scores["risk_probability"] = oof[chosen].round(4)
    scores["top_risk_drivers"] = top
    active = emp.is_active == 1
    hi, med = np.quantile(scores.risk_probability[active], [0.90, 0.70])
    scores["risk_tier"] = np.select([scores.risk_probability >= hi, scores.risk_probability >= med], ["High", "Medium"], "Low")

    y_tier = pd.DataFrame({"tier": scores.risk_tier, "y": y})
    tier_perf = y_tier.groupby("tier").agg(records=("y", "size"), exits=("y", "sum"))
    tier_perf["exit_proportion"] = (tier_perf.exits / tier_perf.records).round(3)
    tier_perf["share_of_all_exits"] = (tier_perf.exits / y.sum()).round(3)
    metrics.update({"chosen_model": chosen, "cv": "5-fold stratified, out-of-fold probabilities",
                    "tier_thresholds": {"high": round(float(hi), 4), "medium": round(float(med), 4)},
                    "tier_performance": tier_perf.reset_index().to_dict("records")})
    return scores, coefs, metrics


def leave_vs_exit(con):
    """SYNTHETIC: absence in the 3 months before exit vs stayers' last 3 months."""
    return con.execute("""
        WITH last3 AS (
          SELECT a.employee_id, f.is_exit, sum(a.absent_days) AS absent, sum(a.scheduled_days) AS sched
          FROM fct_attendance_monthly a
          JOIN fct_employee_snapshot f USING (employee_id)
          JOIN syn_employee_timeline t USING (employee_id)
          WHERE a.month_start > coalesce(t.syn_exit_date, DATE '2026-09-30') - INTERVAL 3 MONTH
          GROUP BY ALL)
        SELECT CASE WHEN is_exit = 1 THEN 'Exited (3 months before exit)' ELSE 'Active (last 3 months)' END AS grp,
               count(*) AS employees, round(sum(absent) / sum(sched), 4) AS absenteeism_rate
        FROM last3 GROUP BY ALL ORDER BY 1""").df()


def main():
    con = duckdb.connect(str(DB))
    diag, overall = diagnostics(con)
    emp = con.execute("""SELECT f.*, d.department, r.job_role, de.gender, de.age, f.grade_key AS job_level
                         FROM fct_employee_snapshot f JOIN dim_employee de USING (employee_id)
                         JOIN dim_department d ON d.department_key = f.department_key
                         JOIN dim_job_role r ON r.job_role_key = f.job_role_key""").df()
    flags, q1 = early_warning_flags(emp)
    flag_perf = flags.assign(y=emp.is_exit).assign(flag_bucket=lambda d: d.flag_count.clip(upper=4).astype(str).replace("4", "4+")) \
        .groupby("flag_bucket").agg(records=("y", "size"), exits=("y", "sum")).reset_index()
    flag_perf["exit_proportion"] = (flag_perf.exits / flag_perf.records).round(4)
    scores, coefs, metrics = model(emp)
    lve = leave_vs_exit(con)

    for name, df in [("attrition_diagnostics", diag), ("early_warning_flags", flags), ("early_warning_flag_performance", flag_perf),
                     ("risk_scores", scores), ("risk_drivers", coefs), ("leave_vs_exit_syn", lve)]:
        con.register("tmp", df)
        con.execute(f"CREATE OR REPLACE TABLE an_{name} AS SELECT * FROM tmp")
        con.unregister("tmp")
        df.to_csv(PROC / f"{name}.csv", index=False)
    metrics["overall_exit_proportion"] = round(overall, 4)
    metrics["low_pay_quartile_threshold"] = float(q1)
    (PROC / "model_metrics.json").write_text(json.dumps(metrics, indent=2))

    print(json.dumps(metrics, indent=2))
    print(diag[diag.significant].sort_values("lift_vs_overall", ascending=False).to_string(index=False))
    print(flag_perf.to_string(index=False))
    print(coefs.head(12).to_string(index=False))
    print(lve.to_string(index=False))
    print(con.execute("SELECT * FROM vw_attrition_cohort").df().to_string(index=False))
    con.close()


if __name__ == "__main__":
    main()
