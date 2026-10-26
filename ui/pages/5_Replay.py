import json
import time

import streamlit as st
from lib.api_client import ApiError
from lib.view import api, words

st.set_page_config(page_title="Replay", page_icon=":material/replay:", layout="wide")
st.title("Replay")
st.caption(
    "Re-run a finished task. Unchanged steps reuse the recorded model answers; edit any "
    "answer to see where the run diverges."
)

try:
    tasks = [t for t in api().tasks(limit=50) if t["status"] == "completed"]
except ApiError as exc:
    st.error(str(exc))
    st.stop()
if not tasks:
    st.info("Replay needs a completed task.")
    st.stop()

labels = {t["id"]: t["request"][:90] for t in tasks}
task_id = st.sidebar.selectbox("Original task", list(labels), format_func=labels.get)
mode = st.sidebar.radio(
    "Mode",
    ["recorded", "live"],
    help="recorded reuses answers whose inputs are unchanged; live asks the models again",
)
run_id = api().task(task_id)["run"]["id"]
steps = api().steps(run_id)

st.subheader("Recorded decisions")
st.dataframe(
    [
        {
            "#": s["index"],
            "agent": s["agent"],
            "purpose": s["purpose"],
            "subtask": s["subtask_id"] or "",
            "attempt": s["attempt"] or "",
            "answer": s["preview"],
        }
        for s in steps
    ],
    hide_index=True,
    width="stretch",
)

picked = st.selectbox(
    "Step to edit",
    range(len(steps)),
    format_func=lambda i: (
        f"#{i} {steps[i]['agent']} · {steps[i]['purpose']} {steps[i]['subtask_id'] or ''}"
    ),
)
step = steps[picked]
edited = st.text_area(
    "Recorded answer (JSON)", json.dumps(step["response"], indent=2), height=260, key=step["id"]
)

left, right = st.columns(2)
overrides = None
if left.button("Replay unchanged"):
    overrides = {}
if right.button("Replay with my edit", type="primary"):
    try:
        overrides = {step["id"]: json.loads(edited)}
    except json.JSONDecodeError as exc:
        st.error(f"Not valid JSON: {exc}")
if overrides is not None:
    accepted = api().replay(run_id, mode, overrides)
    st.session_state["replay"] = {"original": run_id, **accepted}

replay = st.session_state.get("replay")
if not replay or replay["original"] != run_id:
    st.stop()

with st.spinner("Replaying"):
    for _ in range(120):
        status = api().task(replay["task_id"])["status"]
        if status in ("completed", "failed"):
            break
        time.sleep(1)
if status != "completed":
    st.warning(f"Replay {words(status)}.")
    st.stop()

result = api().compare(run_id, replay["run_id"])
summary = result["replay"] or {}
st.divider()
st.subheader("What changed")
a, b, c = st.columns(3)
a.metric("Reused answers", summary.get("replayed_calls", 0))
b.metric("New model calls", summary.get("fresh_calls", 0))
c.metric("Final output", "same" if result["final_output"]["same"] else "changed")
divergence = summary.get("divergence")
if divergence:
    st.info(
        f"First divergence: {divergence['agent']} · {divergence['purpose']} "
        f"{divergence.get('subtask_id') or ''} ({divergence['reason']})"
    )
elif not summary.get("overridden_calls"):
    st.success("The replay reproduced the original run exactly.")

plan = result["plan"]
if not plan["same"]:
    st.warning(f"Plan changed: {json.dumps({k: plan[k] for k in ('added', 'removed', 'changed')})}")

st.dataframe(
    [
        {
            "subtask": row["id"],
            "status": " → ".join(str(s) for s in row["status"]),
            "attempts": " → ".join(str(v) for v in row["visits"]),
            "review scores": f"{row['scores'][0]} → {row['scores'][1]}",
            "output": "same" if row["same_output"] else "changed",
        }
        for row in result["subtasks"]
    ],
    hide_index=True,
    width="stretch",
)
for row in result["subtasks"]:
    if row["diff"]:
        with st.expander(f"{row['id']} output diff"):
            st.code("\n".join(row["diff"]), language="diff")
if result["final_output"]["diff"]:
    with st.expander("Final output diff", expanded=True):
        st.code("\n".join(result["final_output"]["diff"]), language="diff")

st.subheader("Cost and size")
st.dataframe(
    [
        {"metric": words(k), "original": v["a"], "replay": v["b"]}
        for k, v in result["metrics"].items()
    ],
    hide_index=True,
    width="stretch",
)
