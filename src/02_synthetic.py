"""Phase 1b: SYNTHETIC operational layer keyed to the real IBM employee IDs.

The IBM HR dataset has no dates, attendance, requisitions or productivity measures. This script
generates them so the pipeline and dashboards can be demonstrated end to end. Every table it writes
carries is_synthetic = TRUE. Rules:
  * Real IBM fields are never modified (Employee_Master stays as-is in staging).
  * Absence and productivity are driven only by real IBM attributes (overtime, satisfaction,
    rating, level, tenure). No exit signal is injected, so any leave/exit relationship found later
    arises indirectly through those real attributes.
  * Early exit (< 1 year) for recent hires is the REAL IBM outcome (Attrition = Yes and
    Years_at_Company = 0). Only hiring source, dates and time-to-fill are synthetic.
  * Assumption used for timing: the 237 IBM exits occurred during the 12 months before the snapshot.
"""
import numpy as np
import pandas as pd

from config import SEED, SNAPSHOT_DATE, STAGE, SYN

rng = np.random.default_rng(SEED)
SNAP = pd.Timestamp(SNAPSHOT_DATE)
WINDOW = pd.period_range(end=SNAP.to_period("M"), periods=12, freq="M")
SOURCES = ["Referral", "Job Portal", "Campus", "Recruitment Agency", "Company Website"]
SOURCE_P = {
    "Research & Development": [0.25, 0.25, 0.25, 0.15, 0.10],
    "Sales": [0.30, 0.30, 0.10, 0.15, 0.15],
    "Human Resources": [0.20, 0.35, 0.10, 0.15, 0.20],
}
TTF_MEDIAN = {"Referral": 32, "Job Portal": 45, "Campus": 55, "Recruitment Agency": 38, "Company Website": 50}


def month_start(ts):
    return ts.to_period("M").to_timestamp()


def timeline(em):
    n = len(em)
    exited = em.attrition.eq("Yes").to_numpy()
    yrs = em.years_at_company.to_numpy()
    exit_offset_days = rng.integers(0, 365, n)
    end_date = np.where(exited, (SNAP - pd.to_timedelta(exit_offset_days, "D")).values, SNAP.to_datetime64())
    end_date = pd.to_datetime(end_date)
    extra_days = rng.integers(0, 365, n)
    hire_date = end_date - pd.to_timedelta(yrs * 365 + extra_days, "D")
    tl = pd.DataFrame({
        "employee_id": em.employee_id,
        "syn_hire_date": hire_date.normalize(),
        "syn_exit_date": pd.Series(end_date.normalize()).where(exited),
        "is_synthetic": True,
    })
    return tl


def attendance(em, tl):
    base = 0.028 * np.where(em.overtime.eq("Yes"), 1.30, 1.0) \
        * em.job_satisfaction.map({1: 1.40, 2: 1.20, 3: 1.0, 4: 0.9}).to_numpy() \
        * np.where(em.years_since_last_promotion >= 5, 1.10, 1.0) \
        * rng.gamma(4, 0.25, len(em))
    rows = []
    for (eid, hire, exit_), rate in zip(tl[["employee_id", "syn_hire_date", "syn_exit_date"]].itertuples(index=False), base):
        for m in WINDOW:
            ms, me = m.start_time, m.end_time
            if hire > me or (pd.notna(exit_) and exit_ < ms):
                continue
            first = max(ms, hire)
            last = min(me.normalize(), exit_) if pd.notna(exit_) else me.normalize()
            sched = int(np.busday_count(first.date(), (last + pd.Timedelta(days=1)).date()))
            if sched <= 0:
                continue
            absent = int(rng.binomial(sched, min(rate, 0.5)))
            leave = int(min(sched - absent, rng.poisson(1.2 * sched / 21)))
            rows.append((f"A{eid[1:]}-{m.strftime('%Y%m')}", eid, ms.date(), sched, absent, leave))
    df = pd.DataFrame(rows, columns=["attendance_id", "employee_id", "month", "scheduled_days", "absent_days", "leave_days"])
    df["month"] = pd.to_datetime(df.month)
    df["is_synthetic"] = True
    return df


def productivity(em, tl):
    quarters = pd.period_range(end=SNAP.to_period("Q"), periods=4, freq="Q")
    e = em.merge(tl, on="employee_id")
    rows = []
    for r in e.itertuples(index=False):
        person = rng.normal(0, 5)
        for q in quarters:
            qs, qe = q.start_time, q.end_time
            if r.syn_hire_date > qe or (pd.notna(r.syn_exit_date) and r.syn_exit_date < qs):
                continue
            tenure_m = (qe - r.syn_hire_date).days / 30.4
            ramp = min(1.0, 0.6 + 0.4 * tenure_m / 9)
            score = (62 + 9 * (r.performance_rating == 4) + 1.5 * (r.job_level - 1)
                     + 2.0 * (r.job_satisfaction - 2.5) - 2.5 * (r.overtime == "Yes") + person) * ramp
            score += rng.normal(0, 6)
            rows.append((r.employee_id, f"{q.year}-Q{q.quarter}", int(np.clip(round(score), 0, 100)),
                         int(rng.integers(0, 30))))
    df = pd.DataFrame(rows, columns=["employee_id", "review_period", "productivity_score", "training_hours"])
    df["is_synthetic"] = True
    return df


def requisitions(em, tl):
    e = em.merge(tl, on="employee_id").query("years_at_company <= 1").reset_index(drop=True)
    src = [rng.choice(SOURCES, p=SOURCE_P[d]) for d in e.department]
    grade_mult = e.job_level.map({1: 0.9, 2: 1.0, 3: 1.2, 4: 1.4, 5: 1.6}).to_numpy()
    ttf = np.round(np.array([TTF_MEDIAN[s] for s in src]) * grade_mult * rng.lognormal(0, 0.30, len(e))).astype(int)
    fill = e.syn_hire_date - pd.to_timedelta(rng.integers(7, 22, len(e)), "D")  # offer accepted 1–3 weeks before start
    opening = fill - pd.to_timedelta(ttf, "D")
    days_since_hire = (SNAP - e.syn_hire_date).dt.days
    exited = e.attrition.eq("Yes")
    days_to_exit = (e.syn_exit_date - e.syn_hire_date).dt.days
    early_exit = np.where(exited & e.years_at_company.eq(0), "Yes",
                          np.where(exited | (days_since_hire >= 365), "No", "Not yet observable"))
    probation = np.where(exited & (days_to_exit <= 180), "Failed / exited",
                         np.where(days_since_hire < 180, "Pending", "Passed"))
    df = pd.DataFrame({
        "job_id": [f"J{i + 1:04d}" for i in range(len(e))],
        "department": e.department, "job_role": e.job_role, "grade": e.grade,
        "hiring_source": src, "opening_date": opening.dt.normalize(), "fill_date": fill.dt.normalize(),
        "time_to_fill_days": ttf, "candidate_employee_id": e.employee_id,
        "probation_result": probation, "early_exit_within_1_year": early_exit,
    })
    df["is_synthetic"] = True
    return df


def main():
    em = pd.read_parquet(STAGE / "employee_master.parquet")
    tl = timeline(em)
    att = attendance(em, tl)
    prod = productivity(em, tl)
    req = requisitions(em, tl)
    for name, df in [("employee_timeline", tl), ("attendance_monthly", att),
                     ("productivity_quarterly", prod), ("requisitions", req)]:
        df.to_parquet(SYN / f"syn_{name}.parquet", index=False)
        print(f"syn_{name}: {len(df):,} rows")


if __name__ == "__main__":
    main()
