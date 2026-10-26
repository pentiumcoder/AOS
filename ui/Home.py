import streamlit as st
from lib.api_client import ApiError
from lib.view import age, api, status_badge, subtask_rows, words

st.set_page_config(page_title="AOS", page_icon=":material/hub:", layout="wide")
st.title("Agent Orchestration System")
st.caption("A supervisor plans, specialists work with tools, a reviewer checks, and you approve.")

with st.sidebar:
    try:
        health = api().health()
        st.success(f"API {health['status']} · {health['llm_mode']} models")
    except ApiError as exc:
        st.error(str(exc))
        st.stop()
    user_id = st.text_input("User", value=st.session_state.get("user_id", "default"))
    st.session_state["user_id"] = user_id

with st.form("submit", clear_on_submit=True):
    request = st.text_area(
        "New task",
        placeholder="Research the top 3 open-source vector databases, compare them using our "
        "benchmark data, write an executive summary and email it to the team",
    )
    review = st.checkbox("Require my review before the result is delivered")
    if st.form_submit_button("Run", type="primary") and request.strip():
        try:
            accepted = api().submit(request.strip(), user_id, review)
            st.session_state["selected_task"] = accepted["task_id"]
            st.toast(f"Task queued: {accepted['task_id'][:8]}")
        except ApiError as exc:
            st.error(str(exc))


@st.fragment(run_every=5)
def overview() -> None:
    try:
        pending = api().escalations()
        tasks = api().tasks(user_id=user_id or None)
    except ApiError as exc:
        st.error(str(exc))
        return

    left, right = st.columns([1, 2])
    left.metric("Waiting for you", len(pending))
    if pending:
        left.page_link(
            "pages/1_Review_Queue.py", label="Open review queue", icon=":material/fact_check:"
        )

    if not tasks:
        right.info("No tasks yet. Submit one above.")
        return
    labels = {t["id"]: f"[{words(t['status'])}] {t['request'][:90]}" for t in tasks}
    ids = list(labels)
    chosen = st.session_state.get("selected_task")
    selected = right.selectbox(
        "Recent tasks",
        ids,
        index=ids.index(chosen) if chosen in ids else 0,
        format_func=labels.get,
    )
    st.session_state["selected_task"] = selected
    show_task(selected)


def show_task(task_id: str) -> None:
    detail = api().task(task_id)
    run = detail.get("run") or {}
    st.markdown(f"### {status_badge(detail['status'])}")
    st.caption(f"{detail['request']} · started {age(detail['created_at'])}")

    if run.get("pending_escalations"):
        st.warning(
            f"Paused: {run['pending_escalations'][0]['reason']}. Decide in the review queue."
        )
    plan_tab, timeline_tab, result_tab = st.tabs(["Plan", "Timeline", "Result"])
    with plan_tab:
        if run.get("plan"):
            plan = run["plan"]
            st.write(
                f"**{plan['task_type']}** · confidence {plan['confidence']:.2f} · "
                f"{plan['rationale']}"
            )
            st.dataframe(subtask_rows(run), hide_index=True, use_container_width=True)
            for influence in plan.get("memory_influence", []):
                st.caption(
                    f"Shaped by memory {influence['memory_id'][:8]}: {influence['how_used']}"
                )
        else:
            st.info("No plan yet.")
    with timeline_tab:
        for item in run.get("events", []):
            st.markdown(f"`{item['node']}` {item['message']}")
    with result_tab:
        if detail.get("final_output"):
            st.markdown(detail["final_output"])
        else:
            st.info(run.get("error") or "No deliverable yet.")
        for action in run.get("actions", []):
            st.caption(f"Action {action['tool']}: {action['status']}")


overview()
