# Day 2 — Memory + human-in-the-loop

Status: NOT_STARTED
<!-- NOT_STARTED | IN_PROGRESS | COMPLETE. The build agent updates this; the commit agent reads it. -->

Theme: Memory and human-in-the-loop - working and semantic memory, escalation, approval queue, review console
Tag when complete: day-2
Plan: docs/IMPLEMENTATION_PLAN.md, section "Day 2"
Requires: tag day-1 (Day 1 committed)

## Phase checklist
- [ ] 2.1 Working memory in Redis
- [ ] 2.2 Long-term semantic memory in ChromaDB
- [ ] 2.3 Memory-informed planning
- [ ] 2.4 Memory management
- [ ] 2.5 Escalation policy + approval levels
- [ ] 2.6 Approval queue, pause and resume
- [ ] 2.7 Review console + memory dashboard
- [ ] 2.8 Tests + Day 2 handoff

## Commit plan
> The file lists in blocks still marked `ready: no` are **planned**. When the build agent finishes a phase, it replaces that block's list with the **actual** changed paths and sets `ready: yes`.
> Each path appears in exactly one block. If a later phase touches a file listed earlier, move it to the later block.

### Commit 1 — Phase 2.1: Working memory
- ready: no
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
  - src/aos/config.py
  - src/aos/db/models.py
  - src/aos/memory/__init__.py
  - src/aos/memory/working.py
  - src/aos/graph/nodes/plan.py
  - src/aos/graph/nodes/specialist.py
  - src/aos/graph/nodes/deliver.py

### Commit 2 — Phase 2.2: Long-term semantic memory
- ready: no
- message: feat(memory): ChromaDB long-term memory with post-task extraction
- body:
  - memory items for episodes, approaches, tool usage, facts, preferences, human decisions
  - live and deterministic offline embedders
  - LLM extraction after delivery with similarity dedupe
- files:
  - src/aos/schemas/memory.py
  - src/aos/memory/embeddings.py
  - src/aos/memory/longterm.py
  - src/aos/memory/extraction.py
  - src/aos/agents/prompts/memory_extraction.md

### Commit 3 — Phase 2.3: Memory-informed planning
- ready: no
- message: feat(memory): retrieve past tasks, lessons and preferences to inform planning
- body:
  - importance-weighted retrieval per memory kind
  - supervisor prompt gains remembered context, plans record memory_influence
  - retrievals logged and access counts bumped
- files:
  - src/aos/memory/retrieval.py
  - src/aos/graph/nodes/memory.py
  - src/aos/agents/supervisor.py
  - src/aos/agents/prompts/supervisor_plan.md

### Commit 4 — Phase 2.4: Memory management
- ready: no
- message: feat(memory): importance scoring, decay, consolidation and user data deletion API
- body:
  - access-based importance with per-kind half-life decay
  - similarity clustering consolidated into summaries, expiry of stale memories
  - hourly Celery beat maintenance and memory REST endpoints including user deletion
- files:
  - src/aos/memory/management.py
  - src/aos/api/routes/memory.py
  - src/aos/worker/celery_app.py
  - src/aos/__main__.py

### Commit 5 — Phase 2.5: Escalation policy
- ready: no
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
- ready: no
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

### Commit 7 — Phase 2.7: Review console + memory dashboard
- ready: no
- message: feat(ui): Streamlit review console and memory dashboard
- body:
  - task submission and status overview
  - review queue with context, proposed action, memories, decision buttons and chat
  - per-user memory dashboard with delete and maintenance controls
- files:
  - ui/

### Commit 8 — Phase 2.8: Tests + Day 2 handoff
- ready: no
- message: test: day 2 tests for memory lifecycle and human escalation flow
- body:
  - working memory, long-term memory, memory-informed planning, memory management
  - escalation policy table tests and pause/resume flows
  - Day 2 progress log and handoff notes
- files:
  - tests/unit/test_working_memory.py
  - tests/unit/test_longterm_memory.py
  - tests/unit/test_memory_planning.py
  - tests/unit/test_memory_management.py
  - tests/unit/test_escalation_policy.py
  - tests/unit/test_hitl_flow.py
  - tests/fixtures/mock_llm/
  - docs/progress/DAY-2.md

## Verification
<!-- Build agent: list the commands you ran and summarize their results. -->

## Handoff to Day 3
<!-- Build agent: deviations from the plan, interface or schema changes, new env vars, known issues, TODOs that Day 3 must pick up. -->
