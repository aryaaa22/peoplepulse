import pandas as pd
import streamlit as st

st.set_page_config(page_title="PeoplePulse", layout="wide")

DATA = "data"


@st.cache_data
def load_data():
    emp = pd.read_parquet(f"{DATA}/staging/employee_master.parquet")
    emp["left"] = (emp["attrition"] == "Yes").astype(int)
    risk = pd.read_csv(f"{DATA}/processed/risk_scores.csv")
    emp = emp.merge(risk, on="employee_id")
    att = pd.read_parquet(f"{DATA}/synthetic/syn_attendance_monthly.parquet")
    req = pd.read_parquet(f"{DATA}/synthetic/syn_requisitions.parquet")
    forecast = pd.read_csv(f"{DATA}/processed/headcount_forecast.csv")
    scorecard = pd.read_csv(f"{DATA}/processed/talent_health_scorecard.csv")
    return emp, att, req, forecast, scorecard


emp, att, req, forecast, scorecard = load_data()

st.title("PeoplePulse - Workforce Attrition Dashboard")
st.write("IBM HR dataset, 1,470 employees. Absenteeism and hiring figures are synthetic (not in the source data).")

dept = st.selectbox("Department", ["All", "Research & Development", "Sales", "Human Resources"])
if dept != "All":
    emp = emp[emp["department"] == dept]
    req = req[req["department"] == dept]
att = att[att["employee_id"].isin(emp["employee_id"])]

# KPIs
total = len(emp)
exits = emp["left"].sum()
active = total - exits
attrition = exits / ((total + active) / 2)
absenteeism = att["absent_days"].sum() / att["scheduled_days"].sum()

c1, c2, c3, c4 = st.columns(4)
c1.metric("Headcount", f"{active:,}")
c2.metric("Attrition rate", f"{attrition:.1%}")
c3.metric("Absenteeism*", f"{absenteeism:.1%}")
c4.metric("Avg time to hire*", f"{req['time_to_fill_days'].mean():.0f} days")

st.divider()

# Attrition by group
st.subheader("Attrition by group")
group = st.radio("Group by", ["job_role", "tenure_band", "grade", "overtime"], horizontal=True)
by_group = (emp.groupby(group)["left"].mean() * 100).round(1).reset_index(name="pct_left")
st.bar_chart(by_group, x=group, y="pct_left", horizontal=True, sort="-pct_left",
             x_label="", y_label="% who left")

col1, col2 = st.columns(2)
with col1:
    st.subheader("Attrition by department and tenure (%)")
    table = emp.pivot_table(index="department", columns="tenure_band", values="left", aggfunc="mean") * 100
    order = ["0–1 Years", "2–3 Years", "4–5 Years", "6–10 Years", "10+ Years"]
    st.dataframe(table[[c for c in order if c in table.columns]].round(1))
with col2:
    st.subheader("Time with current manager")
    bands = pd.cut(emp["years_with_current_manager"], [-1, 0, 2, 5, 100],
                   labels=["a) under 1 yr", "b) 1-2 yrs", "c) 3-5 yrs", "d) 6+ yrs"])
    mgr = emp.groupby(bands, observed=True)["left"].mean() * 100
    st.bar_chart(mgr, x_label="", y_label="% who left")

st.divider()

# Risk
st.subheader("High risk employees")
high = emp[(emp["left"] == 0) & (emp["risk_tier"] == "High")]
st.write(f"{len(high)} current employees have a high attrition risk (logistic regression model, AUC 0.77).")
st.dataframe(high[["employee_id", "department", "job_role", "risk_probability", "top_risk_drivers"]]
             .sort_values("risk_probability", ascending=False), hide_index=True, height=250)

st.divider()

# Forecast and scorecard
col1, col2 = st.columns(2)
with col1:
    st.subheader("Headcount forecast")
    f = forecast[forecast["department"] == ("All" if dept == "All" else dept)]
    chart = f.pivot(index="quarter", columns="scenario", values="headcount_p50")
    chart.columns = [c.split(":")[0].split(" (")[0] for c in chart.columns]
    st.line_chart(chart)
with col2:
    st.subheader("Department scorecard")
    st.dataframe(scorecard[["department", "attrition_rate", "overtime_share", "talent_health_score", "rag"]],
                 hide_index=True)

st.subheader("Recommendations")
st.markdown("""
1. Reduce overtime - employees on overtime leave about 3x more often.
2. Better onboarding for new joiners - most exits happen in the first 1-2 years.
3. Support employees when their manager changes.
4. Review pay and promotion for grade G1 and Sales Representatives.
5. Plan replacements for Sales Executives, the critical role with the most expected exits.
""")
