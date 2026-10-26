import json
from typing import Any

import streamlit as st
from lib.api_client import ApiError
from lib.view import age, api, level_badge, subtask_rows, words

st.set_page_config(page_title="Review queue", page_icon=":material/fact_check:", layout="wide")
st.title("Review queue")

reviewer = st.sidebar.text_input("Your name", value=st.session_state.get("reviewer", "reviewer"))
st.session_state["reviewer"] = reviewer

DECISION_LABELS = {
    "approve": "Approve",
    "modify": "Modify",
    "reject": "Reject",
    "take_over": "Take over",
}
APPROVE_MEANS = {
    "repeated_specialist_failure": "Retry once more, with your comment as a hint",
    "low_review_score": "Accept the output as it is",
    "low_plan_confidence": "Run this plan",
    "user_requested_review": "Deliver this result",
    "sensitive_operation": "Run this action",
}


@st.fragment(run_every=5)
def queue() -> str | None:
    try:
        pending = api().escalations()
    except ApiError as exc:
        st.error(str(exc))
        return None
    if not pending:
        st.success("Nothing is waiting for a decision.")
        return None
    labels = {
        e["id"]: f"{words(e['level'])} · {words(e['trigger'])} · {age(e['created_at'])}"
        for e in pending
    }
    ids = list(labels)
    chosen = st.session_state.get("escalation")
    selected = st.selectbox(
        f"{len(pending)} waiting",
        ids,
        index=ids.index(chosen) if chosen in ids else 0,
        format_func=labels.get,
    )
    st.session_state["escalation"] = selected
    return selected


def show(escalation_id: str) -> None:
    escalation = api().escalation(escalation_id)
    context = escalation["context"]
    st.markdown(f"#### {level_badge(escalation['level'])} {words(escalation['trigger'])}")
    st.write(escalation["reason"])
    st.caption(f"Task: {context['task']['request']}")

    main, side = st.columns([3, 2], gap="large")
    with main:
        decision_point(escalation, context)
        decide(escalation, context)
    with side:
        progress(escalation)
        memories(context)
        conversation(escalation)


def decision_point(escalation: dict[str, Any], context: dict[str, Any]) -> None:
    action = escalation.get("proposed_action")
    current = context.get("current")
    if action:
        st.subheader("Proposed action")
        st.write(f"**{action['agent']}** wants to run **{action['tool']}**")
        if action.get("reasoning"):
            st.caption(action["reasoning"])
        st.json(action["args"])
        if context.get("final_output"):
            with st.expander("Deliverable it will use"):
                st.markdown(context["final_output"])
    elif escalation["origin"] == "plan":
        st.subheader("Proposed plan")
        plan = context["plan"]
        st.write(f"Confidence {plan['confidence']:.2f}. {plan['rationale']}")
        st.dataframe(
            [
                {"id": s["id"], "specialist": s["specialist"], "description": s["description"]}
                for s in plan["subtasks"]
            ],
            hide_index=True,
            width="stretch",
        )
    elif current:
        st.subheader(f"Subtask {current['subtask']['id']}: {current['subtask']['description']}")
        if current.get("error"):
            st.error(current["error"])
        if current.get("output"):
            st.markdown(current["output"])
        for review in current.get("reviews", []):
            st.caption(f"Review {review['score']:.2f}: {'; '.join(review['issues'])}")
        if current.get("evidence"):
            with st.expander("Tool results the agent saw"):
                for item in current["evidence"]:
                    st.code(item, language=None)
    elif context.get("final_output"):
        st.subheader("Deliverable")
        st.markdown(context["final_output"])


def decide(escalation: dict[str, Any], context: dict[str, Any]) -> None:
    st.subheader("Your decision")
    allowed = escalation["allowed_decisions"]
    options = [a for a in DECISION_LABELS if a in allowed]
    choice = st.radio(
        "Decision",
        options,
        format_func=DECISION_LABELS.get,
        horizontal=True,
        label_visibility="collapsed",
        key=f"choice-{escalation['id']}",
    )
    if choice == "approve":
        st.caption(APPROVE_MEANS.get(escalation["trigger"], "Continue as proposed"))
    payload = edit_payload(choice, escalation, context)
    comment = st.text_area(
        "Comment", key=f"comment-{escalation['id']}", placeholder="Why, or what to change"
    )
    if st.button(f"Submit: {DECISION_LABELS[choice]}", type="primary"):
        if choice == "reject" and not comment.strip():
            st.warning("Say what is wrong so the agents can fix it.")
            return
        try:
            api().decide(
                escalation["id"], choice, payload=payload, comment=comment, reviewer=reviewer
            )
        except ApiError as exc:
            st.error(str(exc))
            return
        st.session_state.pop("escalation", None)
        st.toast("Decision sent; the run is resuming.")
        st.rerun()


def edit_payload(choice: str, escalation: dict[str, Any], context: dict[str, Any]) -> Any:
    key = f"payload-{escalation['id']}-{choice}"
    if choice == "modify" and escalation.get("proposed_action"):
        text = st.text_area(
            "Arguments (JSON)",
            json.dumps(escalation["proposed_action"]["args"], indent=2),
            height=200,
            key=key,
        )
        return _json(text)
    if choice == "modify" and escalation["origin"] == "plan":
        text = st.text_area(
            "Plan (JSON)", json.dumps(context["plan"], indent=2), height=320, key=key
        )
        return _json(text)
    if choice in ("modify", "take_over"):
        current = context.get("current") or {}
        start = current.get("output") or context.get("final_output") or ""
        label = "Your output" if choice == "take_over" else "Edited output"
        return st.text_area(label, start, height=240, key=key)
    return None


def _json(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        st.error(f"Not valid JSON: {exc}")
        st.stop()


def progress(escalation: dict[str, Any]) -> None:
    st.subheader("Progress")
    try:
        task = api().task(escalation["task_id"])
    except ApiError as exc:
        st.error(str(exc))
        return
    st.dataframe(subtask_rows(task["run"]), hide_index=True, width="stretch")


def memories(context: dict[str, Any]) -> None:
    recalled, decisions = context.get("memories", []), context.get("past_decisions", [])
    if not recalled and not decisions:
        return
    with st.expander(f"Memories ({len(recalled)}) and past decisions ({len(decisions)})"):
        for memory in recalled:
            st.markdown(f"- *{words(memory['kind'])}*: {memory['text']}")
        for decision in decisions:
            st.markdown(f"- *past decision*: {decision['text']}")


def conversation(escalation: dict[str, Any]) -> None:
    st.subheader("Ask the agents")
    for turn in escalation["chat"]:
        with st.chat_message("user" if turn["role"] == "reviewer" else "assistant"):
            st.write(turn["content"])
    question = st.chat_input("Ask about this decision", key=f"chat-{escalation['id']}")
    if question:
        try:
            api().chat(escalation["id"], question)
        except ApiError as exc:
            st.error(str(exc))
            return
        st.rerun()


selected = queue()
if selected:
    show(selected)
