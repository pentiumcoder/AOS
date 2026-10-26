import streamlit as st
from lib.api_client import ApiError
from lib.view import age, api, words

st.set_page_config(page_title="Memory", page_icon=":material/neurology:", layout="wide")
st.title("Memory")
st.caption("What the agents remember about each user, and how much each memory still counts.")

KINDS = ["task_episode", "approach", "tool_usage", "fact", "preference", "human_decision"]

user_id = st.sidebar.text_input("User", value=st.session_state.get("user_id", "default"))
st.session_state["user_id"] = user_id
kind = st.sidebar.selectbox("Kind", ["all", *KINDS], format_func=words)

try:
    found = api().memories(user_id, None if kind == "all" else kind)
except ApiError as exc:
    st.error(str(exc))
    st.stop()

active = [m for m in found if not m["consolidated_into"]]
merged = len(found) - len(active)
left, middle, right = st.columns(3)
left.metric("Active memories", len(active))
middle.metric("Merged into summaries", merged)
right.metric("Recalled in total", sum(m["access_count"] for m in found))

if not found:
    st.info(f"Nothing remembered for {user_id} yet. Memories appear after a task finishes.")
else:
    st.dataframe(
        [
            {
                "kind": words(m["kind"]),
                "memory": m["text"],
                "weight": m["effective_importance"],
                "recalled": m["access_count"],
                "last used": age(m["last_accessed_at"]),
                "outcome": m["outcome"],
                "merged": "yes" if m["consolidated_into"] else "",
                "id": m["id"][:8],
            }
            for m in found
        ],
        hide_index=True,
        width="stretch",
        column_config={
            "weight": st.column_config.ProgressColumn(
                "weight", min_value=0.0, max_value=1.0, format="%.2f"
            ),
            "memory": st.column_config.TextColumn(width="large"),
        },
    )

st.divider()
manage, forget = st.columns(2)
with manage:
    st.subheader("Maintenance")
    st.caption("Expire faded memories and merge near-duplicates. Runs hourly on its own.")
    if st.button("Run maintenance now"):
        report = api().maintain(user_id)
        st.success(
            f"Expired {report['expired']}, merged {report['consolidated_members']} into "
            f"{report['consolidated_groups']} summaries; {report['remaining']} remain."
        )
    if found:
        labels = {m["id"]: f"{m['id'][:8]} · {m['text'][:70]}" for m in found}
        doomed = st.selectbox("Delete one memory", list(labels), format_func=labels.get)
        if st.button("Delete memory"):
            api().delete_memory(doomed)
            st.rerun()
with forget:
    st.subheader("Forget this user")
    st.caption("Deletes every memory and retrieval record for the user, for data requests.")
    sure = st.checkbox(f"I want to delete everything remembered about {user_id}")
    if st.button("Forget user", type="primary", disabled=not sure):
        report = api().forget(user_id)
        st.success(
            f"Deleted {report['memories_deleted']} memories and "
            f"{report['retrievals_deleted']} retrieval records."
        )
