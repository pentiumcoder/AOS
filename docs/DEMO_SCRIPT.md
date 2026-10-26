# Demo script

A walkthrough of under five minutes for a screen recording. It runs on mock models, so every take behaves the same and nothing needs an API key.

## Before recording

```bash
docker compose down -v
docker compose up -d --build --wait
docker compose exec api python scripts/seed.py
```

`down -v` deletes the volumes, so earlier runs and memories are gone and every take starts from the same three seeded memories. Open http://localhost:8501 in a browser at 1440 px or wider, with a terminal next to it, and set **User** in the sidebar to `demo`, the user the demo runs as.

## Recording

**0:00 – 0:20 · The pitch.** On the console's home page: "This is an orchestration system for AI agents. A supervisor plans, specialists use tools, a reviewer checks every output, memory carries lessons between tasks, and a human approves anything risky. Every step is traced, costed and replayable."

**0:20 – 1:00 · Submit the task.** In the terminal:

```bash
docker compose exec api python scripts/demo.py
```

As the events scroll, point out:
- the plan: s1 finds the three databases while s2 analyses the benchmark table in parallel, s3 looks up their managed offerings once s1 is done, and s4 writes the summary after all three;
- "shaped by 2 memories": a lesson from an earlier rejected run (use the benchmark table, not web figures) and the team's email preference;
- s2 querying the benchmark table through `db_query` and computing cost per query with `code_exec`, and s3 calling the `company_lookup` tool on an MCP server.

**1:00 – 1:30 · The reviewer catches a mistake.** The first summary draft gives Qdrant 4,600 QPS and calls it the throughput leader; the benchmark table says 3,650. Show the "rejected" event: 4,600 appears in no tool result, so the automatic figure check rejected the draft whatever the model thought, and the writer revised it with the reviewer's feedback.

**1:30 – 2:20 · The human step.** The run stops at "Waiting for a human: APPROVE_ACTION". Switch to the **Review queue** page:
- the writer's proposed `send_email`, with recipient, subject and body, and the reason it needs approval;
- the plan and the reviewed outputs behind it;
- in **Ask the agents**, type "Why is this waiting for me?" and show the answer;
- choose **Approve** and submit.

Back in the terminal the run finishes, the email is recorded in the outbox, and the final summary prints.

**2:20 – 3:10 · The trace.** Open **Trace explorer** and pick the task:
- the span tree from `task.run` through planning, the parallel specialists, the reviews and the escalation, then `task.resume` for the part after approval;
- turn on **Show model and tool calls** and click the rejected review's `llm.call` to show the prompt, response, tokens and latency;
- the timeline: s1 and s2 overlapping in the first invocation, and the resume after approval as a second panel.

**3:10 – 3:40 · Cost.** Open **Costs**: cost by task type, tokens by agent, tool latency percentiles and the escalation rate. Mock models use simulated prices; with Ollama the cost is zero and hosted models use the prices in `config/pricing.yaml`.

**3:40 – 4:30 · Replay.** Open **Replay** and pick the task:
- **Replay unchanged**: every model answer is reused, nothing calls a model, and the output is identical;
- pick the data analysis step, change the p95 latency of one database in the recorded answer, and click **Replay with my edit**;
- the comparison shows the run diverging at that step, the reviewer rejecting the edited figure because no tool result contains it, and the specialist's fresh attempt bringing the run back to the original summary;
- for a change that reaches the deliverable, edit the writer's final answer instead and replay again.

**4:30 – 4:50 · Memory.** Open **Memory** for user `demo`: the new task episode, the lesson extracted from the rejected draft (copy figures from the analysis exactly), the benchmark facts, and the approval just given, each with importance and last use. "The next similar task plans from these."

**4:50 – 5:00 · Close.** "Tasks, tools, memory, people and traces in one system, tested end to end on every push."

## If something goes wrong

- The terminal shows "API unreachable": `docker compose ps` should list every service as healthy; `docker compose logs worker` shows run errors.
- The Review queue is empty: the run is still before the email step, or `--auto-approve` was passed.
- A second take plans from different memories: the first take's memories are still there. Run the reset at the top again.
