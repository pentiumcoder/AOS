# Day 2 — Memory + human-in-the-loop

Status: COMPLETE
<!-- NOT_STARTED | IN_PROGRESS | COMPLETE. The build agent updates this; the commit agent reads it. -->

Theme: Memory and human-in-the-loop - working and semantic memory, escalation, approval queue, review console
Tag when complete: day-2
Plan: docs/IMPLEMENTATION_PLAN.md, section "Day 2"
Requires: tag day-1 (Day 1 committed)

## Phase checklist
- [x] 2.1 Working memory in Redis
- [x] 2.2 Long-term semantic memory in ChromaDB
- [x] 2.3 Memory-informed planning
- [x] 2.4 Memory management
- [x] 2.5 Escalation policy + approval levels
- [x] 2.6 Approval queue, pause and resume
- [x] 2.7 Review console + memory dashboard
- [x] 2.8 Tests + Day 2 handoff

## Commit plan
> The file lists in blocks still marked `ready: no` are **planned**. When the build agent finishes a phase, it replaces that block's list with the **actual** changed paths and sets `ready: yes`.
> Each path appears in exactly one block. If a later phase touches a file listed earlier, move it to the later block.

### Commit 1 — Phase 2.1: Working memory
- ready: yes
- message: feat(memory): Redis working memory shared across agents within a task
- body:
  - per-run plan, outputs, notes and errors in Redis with TTL safety net
  - specialists read dependency outputs from working memory
  - snapshot archived to Postgres and cleared on delivery
  - Day 2 dependencies and tables for escalations, notifications, memory_retrievals
- files:
  - pyproject.toml
  - uv.lock
  - .env.example
  - src/aos/db/models.py
  - src/aos/memory/__init__.py
  - src/aos/memory/working.py
  - src/aos/graph/nodes/specialist.py
  - src/aos/graph/nodes/deliver.py
  - src/aos/schemas/state.py

### Commit 2 — Phase 2.2: Long-term semantic memory
- ready: yes
- message: feat(memory): ChromaDB long-term memory with post-task extraction
- body:
  - memory items for episodes, approaches, tool usage, facts, preferences, human decisions
  - live and deterministic offline embedders
  - LLM extraction after delivery with similarity dedupe
- files:
  - src/aos/schemas/memory.py
  - src/aos/memory/extraction.py
  - src/aos/agents/prompts/memory_extraction.md

### Commit 3 — Phase 2.3: Memory-informed planning
- ready: yes
- message: feat(memory): retrieve past tasks, lessons and preferences to inform planning
- body:
  - importance-weighted retrieval per memory kind with use-based importance and time decay
  - supervisor prompt gains remembered context, plans cite memory ids in memory_influence
  - cited ids are grounded against what was recalled; retrievals logged, used ones marked
  - similarity threshold per embedder so offline hash embeddings still recall similar tasks
  - writing subtasks without dependencies wait for the findings they write up
- files:
  - src/aos/memory/retrieval.py
  - src/aos/memory/scoring.py
  - src/aos/graph/nodes/memory.py
  - src/aos/graph/nodes/plan.py
  - src/aos/agents/supervisor.py
  - src/aos/schemas/plan.py
  - src/aos/agents/prompts/supervisor_plan.md

### Commit 4 — Phase 2.4: Memory management
- ready: yes
- message: feat(memory): importance scoring, decay, consolidation and user data deletion API
- body:
  - access-based importance with per-kind half-life decay
  - similarity clustering consolidated into summaries, expiry of stale memories
  - consolidation threshold per embedder so paraphrased lessons merge with offline embeddings
  - hourly Celery beat maintenance and memory REST endpoints including user deletion
- files:
  - src/aos/memory/management.py
  - src/aos/api/routes/memory.py
  - src/aos/worker/celery_app.py
  - src/aos/memory/longterm.py
  - src/aos/config.py
  - src/aos/memory/embeddings.py

### Commit 5 — Phase 2.5: Escalation policy
- ready: yes
- message: feat(hitl): escalation policy with graded approval levels
- body:
  - Notify, Approve action, Approve plan, Take over levels
  - six configurable triggers mapped to levels
  - graph routing delegates to the policy
- files:
  - src/aos/hitl/__init__.py
  - src/aos/hitl/levels.py
  - src/aos/hitl/policy.py
  - src/aos/schemas/escalation.py
  - config/escalation.yaml
  - src/aos/graph/routing.py

### Commit 6 — Phase 2.6: Approval queue, pause and resume
- ready: yes
- message: feat(hitl): approval queue with pause and resume via LangGraph interrupts
- body:
  - idempotent escalation records with packaged context and past similar decisions
  - approve, modify, reject and take-over semantics, sensitive actions gated
  - decision and clarifying-chat endpoints, notifications, Celery resume
  - human decisions saved as memories
- files:
  - src/aos/hitl/queue.py
  - src/aos/hitl/notifications.py
  - src/aos/hitl/chat.py
  - src/aos/graph/nodes/escalate.py
  - src/aos/graph/nodes/actions.py
  - src/aos/graph/builder.py
  - src/aos/api/routes/escalations.py
  - src/aos/api/main.py
  - src/aos/worker/tasks.py
  - src/aos/graph/runner.py
  - src/aos/api/routes/tasks.py
  - src/aos/__main__.py
  - src/aos/llm/mock_provider.py

### Commit 7 — Phase 2.7: Review console + memory dashboard
- ready: yes
- message: feat(ui): Streamlit review console and memory dashboard
- body:
  - task submission and status overview
  - review queue with context, proposed action, memories, decision buttons and chat
  - per-user memory dashboard with delete and maintenance controls
- files:
  - ui/

### Commit 8 — Phase 2.8: Tests + Day 2 handoff
- ready: yes
- message: test: day 2 tests for memory lifecycle and human escalation flow
- body:
  - working memory, long-term memory, memory-informed planning, memory management
  - escalation policy table tests and pause/resume flows
  - Day 2 progress log and handoff notes
- files:
  - tests/conftest.py
  - tests/unit/test_graph.py
  - tests/unit/test_working_memory.py
  - tests/unit/test_longterm_memory.py
  - tests/unit/test_memory_planning.py
  - tests/unit/test_memory_management.py
  - tests/unit/test_escalation_policy.py
  - tests/unit/test_hitl_flow.py
  - tests/fixtures/mock_llm/
  - docs/progress/DAY-2.md
  - tests/unit/test_plan_validation.py

## Verification
- `python -m uv add "chromadb>=1.0" "streamlit>=1.40"`: chromadb 1.5.9, streamlit 1.66.1.
- `ruff check .` clean; `ruff format --check .` reports 126 files formatted.
- `pytest -q`: 112 passed in about 45 s (in-memory tier: SQLite, fakeredis, Chroma EphemeralClient, InMemorySaver).
- Services tier with `docker compose up -d --wait postgres redis chromadb` (Chroma server 1.4.4, client 1.5.9) and `python -m aos db init` (adds escalations, notifications, memory_retrievals):
  - `python -m aos run "<showcase request>" --sync --user demo` paused at the send_email APPROVE_ACTION and the process exited;
  - a fresh API process answered `POST /escalations/{id}/chat` and accepted `POST /escalations/{id}/decision` (approve, 16 s review time);
  - a separate Celery worker (`--pool=solo`) resumed the run from the Postgres checkpoint: one email in `outbox`, run completed, working-memory snapshot in `runs.wm_snapshot`, no `aos:wm:<run>:*` keys left in Redis, six memories (including the human decision) in the Chroma server.
- Learning loop on the services tier: the first "[test:learning]" run was rejected once for web figures; the second similar run recalled that lesson from the Chroma server, planned a benchmark query instead, cited the memory and needed no revision.
- Live mode on qwen2.5:7b (services tier, `--auto-approve`):
  - "...lowest p95 latency and which is cheapest per month? Answer in two bullet points and email the answer to the team." paused at send_email, was approved, sent one email to team@example.com, answered correctly (Qdrant, pgvector) and saved six memories with sensible facts, a tool tip and a format preference (2 min 34 s).
  - A similar follow-up recalled 5 memories and cited one in the plan, but the planner gave its writing subtask no dependency, so the writer ran without the data and hunted for files. Fixed in `infer_dependencies` (a writing subtask with no dependencies waits for the non-writing subtasks) and in the planner prompt; the rerun answered "Qdrant, 14.9 ms" in 43 s with s2 after s1.
- Live consolidation on qwen2.5:7b against the Chroma server: three paraphrased latency lessons (hash similarity 0.58 to 0.71) did not merge at the old 0.85 threshold; with the embedder-specific threshold (hash 0.55, semantic 0.85) they merged into one summary (importance 0.80), a cost lesson sharing most of the vocabulary stayed separate, search returned the summary instead of the copies, and a second pass changed nothing.
- Streamlit walkthrough in the built-in browser (API in memory mode with inline execution): Home showed the paused task and pending count; the review queue showed the proposed send_email with arguments and reasoning, answered a chat question, and an Approve with a comment resumed the run to completion (69 s review time recorded); the Memory page listed six memories with weights.

## Handoff to Day 3
Deviations and decisions:
- **Working memory** is mirrored rather than exclusive: graph state still holds full results (review, synthesis and the API need them), and specialists read dependency outputs from Redis. `SpecialistTask` no longer carries `dep_outputs`; `run_specialist` reads them with `WorkingMemory.get_outputs(subtask.depends_on)`. **Replay must restore working memory from `runs.wm_snapshot` before re-running specialists**, because deliver clears the Redis keys.
- **Embeddings:** `EMBEDDING_PROVIDER=hash` (default) is a deterministic hashed bag of words that needs no download; it matches shared vocabulary, not paraphrases. `ollama` (`nomic-embed-text`, not pulled yet) or `openai` give semantic recall. Similarity thresholds belong to the embedder (retrieval: hash 0.15, others 0.35; consolidation: hash 0.55, others 0.85) unless `MEMORY_MIN_SIMILARITY` or `MEMORY_CONSOLIDATE_SIMILARITY` is set. Vectors are computed in `memory/embeddings.py` and passed to Chroma, so Chroma's own embedding functions are never used.
- **Memory items:** a `task_episode` is built in code from the run after delivery; the model extracts approaches, tool usage, facts and preferences (`memory_extraction` purpose). Human decisions are stored as `human_decision` memories when the decision is recorded, not inside the graph. Near-duplicates (similarity >= 0.92, same kind) strengthen the existing memory; consolidation merges looser groups of three or more.
- **Importance** is computed at read time (`memory/scoring.py`: base + 0.1 ln(1 + accesses), halved every 30 days idle, 180 for preferences, 90 for decisions) and never written back, so maintenance does not compound decay.
- **Planning:** `supervisor.plan(memory=PlanningContext)` replaces the text argument. Memories are shown with 8-character ids; `memory_influence` entries that do not match a recalled memory are dropped and the rest get full ids. `memory_retrievals.used_in_plan` marks the cited ones.
- **Escalation policy:** trigger-to-level mapping in `config/escalation.yaml`; thresholds stay in settings. New `PLAN_NOTIFY_THRESHOLD=0.75` emits NOTIFY between 0.6 and 0.75, which records an `auto_proceeded` escalation and a notification without pausing.
- **Pause and resume:** `escalate` calls `interrupt()` for every non-NOTIFY request in order, every time it runs (LangGraph re-runs the node on resume and returns answers by call order). Queue rows are keyed `step_key#n`, where n counts earlier resolved escalations with the same step_key in state, so a re-planned run that trips the same trigger gets a new row. `after_escalation` can now route back to `plan` (plan rejected).
- **Decision semantics:** plan approve/modify (edited plan JSON is validated; invalid edits re-plan with the errors)/reject (re-plan with the comment); subtask take_over or modify uses the human text as the output (`specialist="human"`), approve accepts it, or for TAKE_OVER retries once with the comment as the hint; deliverable reject sends the last writing subtask back with the comment; action modify merges argument edits and the recipient policy is re-checked before running.
- **Runner:** `resume_run(run_id, decision)`, `is_paused(final)` and `run_to_completion(run_id, decide)`; the CLI's `--auto-approve` and the tests' `finish` fixture use the same decision path as the API.
- **API additions:** `/escalations` (list, detail, `/decision`, `/chat`), memory routes (`/users/{id}/memories`, `/memories/{id}`, `DELETE /users/{id}/memories`, `POST /memory/maintenance`); task detail now has `pending_escalations` and `memory`.
- **UI:** `ui/Home.py`, `ui/pages/1_Review_Queue.py`, `ui/pages/2_Memory.py`, with `ui/lib/api_client.py` (all HTTP) and `ui/lib/view.py` (formatting). Run with `API_URL=http://localhost:8000 streamlit run Home.py` from `ui/`. Day 3 pages should follow the same pattern.
- **Celery:** beat schedule `memory-maintenance` (every `MEMORY_MAINTENANCE_MINUTES`) runs `aos.memory_maintenance`; Day 3's compose needs a `beat` service. `resume_run` is now real.
- New env vars: `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`, `NOTIFY_WEBHOOK_URL`, `CHROMA_COLLECTION`, `MEMORY_*`, `PLAN_NOTIFY_THRESHOLD`.
- Tests: each test gets its own Chroma collection because the in-memory client is process-wide; `conftest.reset_state` also clears the embedder and policy caches.

Known issues:
- The Chroma image is still `chromadb/chroma:latest` (it reports 1.4.4, but that tag is not published); pin the image digest on Day 3.
- The review console needs the API running with `TASK_EXECUTION=celery` and a worker, or `inline`, for decisions to resume runs.
- Escalation chat in mock mode returns a canned answer.
- qwen2.5:7b consolidation summaries tend to repeat themselves, though they keep every fact.
