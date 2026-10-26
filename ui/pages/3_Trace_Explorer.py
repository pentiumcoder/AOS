import json
from typing import Any

import altair as alt
import pandas as pd
import streamlit as st
from lib.api_client import ApiError
from lib.view import api, words

st.set_page_config(page_title="Trace explorer", page_icon=":material/account_tree:", layout="wide")
st.title("Trace explorer")

FILL = {
    "success": "#d7f0dc",
    "warning": "#ffe6b3",
    "failure": "#f8d0d0",
    "escalated": "#e5d8f7",
}
DETAIL_SPANS = ("llm.call", "tool.invoke")


def flatten(nodes: list[dict[str, Any]], depth: int = 0) -> list[tuple[int, dict[str, Any]]]:
    rows = []
    for node in nodes:
        rows.append((depth, node))
        rows.extend(flatten(node["children"], depth + 1))
    return rows


def label(node: dict[str, Any]) -> str:
    attributes = node["attributes"]
    title = node["name"]
    if attributes.get("aos.subtask_id"):
        title += f" · {attributes['aos.subtask_id']}"
    if node["name"] == "llm.call":
        title = f"{attributes.get('aos.agent')} · {attributes.get('aos.purpose')}"
    if node["name"] == "tool.invoke":
        title = f"{attributes.get('aos.tool')}"
    lines = [title]
    if attributes.get("aos.decision"):
        lines.append(attributes["aos.decision"][:60])
    if attributes.get("aos.escalation.trigger"):
        decision = attributes.get("aos.escalation.decision", "waiting")
        lines.append(f"{words(attributes['aos.escalation.trigger'])}: {decision}")
    footer = f"{node['duration_ms']:.0f} ms"
    if attributes.get("aos.cost_usd") is not None:
        footer += f" · ${attributes['aos.cost_usd']:.4f}"
    lines.append(footer)
    return "\\n".join(line.replace('"', "'") for line in lines)


def dot(roots: list[dict[str, Any]], show_details: bool) -> str:
    lines = [
        "digraph trace {",
        "rankdir=LR; nodesep=0.15; ranksep=0.35;",
        'node [shape=box style="rounded,filled" fontname="Helvetica" fontsize=10];',
    ]

    def visit(node: dict[str, Any]) -> None:
        children = node["children"]
        hidden = [] if show_details else [c for c in children if c["name"] in DETAIL_SPANS]
        text = label(node)
        if hidden:
            text += f"\\n+{len(hidden)} model/tool calls"
        fill = FILL.get(node["status"], "#eeeeee")
        lines.append(f'"{node["span_id"]}" [label="{text}" fillcolor="{fill}"];')
        for child in children:
            if child in hidden:
                continue
            lines.append(f'"{node["span_id"]}" -> "{child["span_id"]}";')
            visit(child)

    for root in roots:
        visit(root)
    lines.append("}")
    return "\n".join(lines)


def timeline(roots: list[dict[str, Any]]) -> alt.Chart | None:
    """Node spans per graph invocation, in ms from that invocation's start.

    A run that waited for a human has a long gap between invocations; measuring each from
    its own start keeps that wait from flattening every bar.
    """
    records: list[dict[str, Any]] = []

    def visit(node: dict[str, Any], invocation: str, origin: pd.Timestamp) -> None:
        if node["name"] in ("task.run", "task.resume"):
            invocation, origin = node["name"], pd.Timestamp(node["start_time"])
        elif node["name"].startswith("node."):
            begin = (pd.Timestamp(node["start_time"]) - origin).total_seconds() * 1000
            subtask = node["attributes"].get("aos.subtask_id")
            records.append(
                {
                    "invocation": invocation,
                    "step": node["name"].removeprefix("node.") + (f" {subtask}" if subtask else ""),
                    "start_ms": round(begin, 1),
                    "end_ms": round(begin + max(node["duration_ms"], 1.0), 1),
                    "status": node["status"],
                }
            )
        for child in node["children"]:
            visit(child, invocation, origin)

    for root in roots:
        visit(root, root["name"], pd.Timestamp(root["start_time"]))
    if not records:
        return None
    frame = pd.DataFrame(records)
    return (
        alt.Chart(frame)
        .mark_bar(cornerRadius=2)
        .encode(
            x=alt.X("start_ms:Q", title="ms since invocation start"),
            x2="end_ms:Q",
            y=alt.Y("step:N", sort=None, title=None),
            row=alt.Row("invocation:N", title=None, sort=["task.run", "task.resume"]),
            color=alt.Color(
                "status:N",
                scale=alt.Scale(
                    domain=list(FILL), range=["#4caf50", "#ffb300", "#e53935", "#8e63ce"]
                ),
            ),
            tooltip=["invocation", "step", "status", "start_ms", "end_ms"],
        )
        .resolve_scale(x="independent", y="independent")
        .properties(height=alt.Step(18))
    )


def show_span(span_id: str) -> None:
    detail = api().span(span_id)
    st.markdown(f"**{detail['name']}** · {detail['status']} · {detail['duration_ms']:.0f} ms")
    attributes = {k.removeprefix("aos."): v for k, v in detail["attributes"].items()}
    st.dataframe(
        [{"attribute": k, "value": str(v)} for k, v in sorted(attributes.items())],
        hide_index=True,
        width="stretch",
    )
    for event in detail["events"]:
        st.caption(f"{event['name']}: {json.dumps(event['attributes'])[:300]}")
    for call in detail["llm_calls"]:
        st.markdown(
            f"Model call: `{call['provider']}:{call['model']}` · {call['input_tokens']} in / "
            f"{call['output_tokens']} out tokens" + (" · replayed" if call["replayed"] else "")
        )
        with st.expander("Prompt"):
            if call["messages"].get("system"):
                st.text(call["messages"]["system"])
            for message in call["messages"]["messages"]:
                st.markdown(f"**{message['role']}**")
                st.text(message["content"] or json.dumps(message.get("tool_calls")))
        with st.expander("Response", expanded=True):
            st.json(call["response"])
    for call in detail["tool_calls"]:
        st.markdown(
            f"Tool call: `{call['tool']}` by {call['agent']} · "
            f"{'ok' if call['success'] else call['error']}"
        )
        left, right = st.columns(2)
        left.json(call["input"] or {})
        right.json(call["output"] or {})


try:
    tasks = api().tasks(limit=50)
except ApiError as exc:
    st.error(str(exc))
    st.stop()
if not tasks:
    st.info("No runs yet.")
    st.stop()

labels = {t["id"]: f"[{words(t['status'])}] {t['request'][:80]}" for t in tasks}
task_id = st.sidebar.selectbox("Task", list(labels), format_func=labels.get)
show_details = st.sidebar.toggle("Show model and tool calls", value=False)
run = api().task(task_id).get("run")
if not run:
    st.info("This task has not started.")
    st.stop()

trace = api().trace(run["id"])
if not trace["roots"]:
    st.info("No spans recorded for this run yet.")
    st.stop()
rows = flatten(trace["roots"])
metrics = api().run_metrics(run["id"])
llm = metrics["llm"]
a, b, c, d = st.columns(4)
a.metric("Spans", trace["span_count"])
b.metric("Model calls", llm["calls"])
c.metric("Tokens", f"{llm['input_tokens'] + llm['output_tokens']:,}")
d.metric(
    "Cost",
    f"${llm['cost_usd']:.4f}",
    help="Simulated mock-model prices" if llm["simulated_prices"] else None,
)

st.graphviz_chart(dot(trace["roots"], show_details), width="stretch")
chart = timeline(trace["roots"])
if chart is not None:
    st.subheader("Timeline")
    st.altair_chart(chart, width="stretch")

st.subheader("Span detail")
choices = {
    node["span_id"]: f"{'  ' * depth}{node['name']} [{node['status']}] "
    f"{node['attributes'].get('aos.subtask_id', '')} "
    f"{node['attributes'].get('aos.agent', '')}"
    for depth, node in rows
}
picked = st.selectbox("Span", list(choices), format_func=choices.get)
show_span(picked)
