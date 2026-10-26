import pandas as pd
import streamlit as st
from lib.api_client import ApiError
from lib.view import api, words

st.set_page_config(page_title="Costs", page_icon=":material/payments:", layout="wide")
st.title("Cost and performance")

days = st.sidebar.slider("Days", min_value=1, max_value=90, value=7)
try:
    summary = api().summary(days)
except ApiError as exc:
    st.error(str(exc))
    st.stop()

runs, llm = summary["runs"], summary["llm"]
if not runs["total"]:
    st.info(f"No runs in the last {days} days.")
    st.stop()
if llm["simulated_prices"]:
    st.caption("Mock-model calls use simulated prices from config/pricing.yaml.")
if llm["unpriced_calls"]:
    st.warning(f"{llm['unpriced_calls']} model calls have no price in config/pricing.yaml.")

a, b, c, d, e = st.columns(5)
a.metric("Runs", runs["total"])
b.metric("Total cost", f"${runs['total_cost_usd']:.3f}")
c.metric("Per run", f"${runs['avg_cost_usd']:.3f}")
d.metric("Escalation rate", f"{runs['escalation_rate']:.0%}")
review = runs["avg_review_seconds"]
e.metric("Avg review", f"{review:.0f}s" if review is not None else "none")

left, right = st.columns(2)
with left:
    st.subheader("Cost by task type")
    frame = pd.DataFrame(summary["cost_by_task_type"])
    st.bar_chart(
        frame, x="task_type", y="total_cost_usd", horizontal=True, x_label="USD", y_label=""
    )
with right:
    st.subheader("Tokens by agent")
    agents = pd.DataFrame(
        [
            {"agent": agent, "input": v["input_tokens"], "output": v["output_tokens"]}
            for agent, v in llm["by_agent"].items()
        ]
    )
    st.bar_chart(
        agents, x="agent", y=["input", "output"], horizontal=True, x_label="tokens", y_label=""
    )

left, right = st.columns(2)
with left:
    st.subheader("Most expensive agents")
    st.dataframe(
        sorted(
            (
                {"agent": agent, "calls": v["calls"], "cost_usd": round(v["cost_usd"], 4)}
                for agent, v in llm["by_agent"].items()
            ),
            key=lambda row: row["cost_usd"],
            reverse=True,
        ),
        hide_index=True,
        width="stretch",
    )
with right:
    st.subheader("Tool usage")
    st.dataframe(
        summary["tools"],
        hide_index=True,
        width="stretch",
        column_config={"failure_rate": st.column_config.NumberColumn(format="percent")},
    )

left, right = st.columns(2)
with left:
    st.subheader("Escalations by trigger")
    triggers = summary["escalations"]["by_trigger"]
    if triggers:
        st.bar_chart(
            pd.DataFrame([{"trigger": words(k), "count": v} for k, v in triggers.items()]),
            x="trigger",
            y="count",
            horizontal=True,
        )
    else:
        st.caption("No escalations.")
with right:
    st.subheader("Runs and escalations per day")
    daily = pd.DataFrame(summary["daily"])
    st.line_chart(daily, x="date", y=["runs", "escalated"])
