# Day 3 — Observability, replay, packaging

Status: COMPLETE
<!-- NOT_STARTED | IN_PROGRESS | COMPLETE. The build agent updates this; the commit agent reads it. -->

Theme: Observability, replay and packaging - tracing, costs, trace explorer, replay, docker demo, e2e tests, docs
Tag when complete: day-3
Plan: docs/IMPLEMENTATION_PLAN.md, section "Day 3"
Requires: tag day-2 (Day 2 committed)

## Phase checklist
- [x] 3.1 Execution tracing with OpenTelemetry
- [x] 3.2 Cost and performance tracking
- [x] 3.3 Trace explorer + cost dashboard
- [x] 3.4 Replay system
- [x] 3.5 Containerize + demo scenario
- [x] 3.6 End-to-end tests + CI
- [x] 3.7 Portfolio polish

## Commit plan
> The file lists in blocks still marked `ready: no` are **planned**. When the build agent finishes a phase, it replaces that block's list with the **actual** changed paths and sets `ready: yes`.
> Each path appears in exactly one block. If a later phase touches a file listed earlier, move it to the later block.

### Commit 1 — Phase 3.1: Tracing
- ready: yes
- message: feat(observability): OpenTelemetry tracing across agents, tools, memory and escalations
- body:
  - span tree from task run through nodes, LLM calls, tool calls, memory and escalations
  - aos.* attributes for agent, decision, tokens, cost, status
  - Postgres span exporter with optional OTLP, trace continuity across pause and resume
  - trace API endpoints, Day 3 dependencies and spans table
- files:
  - pyproject.toml
  - uv.lock
  - .env.example
  - src/aos/config.py
  - src/aos/db/models.py
  - src/aos/observability/__init__.py
  - src/aos/observability/tracing.py
  - src/aos/observability/exporter.py
  - src/aos/graph/instrument.py
  - src/aos/api/routes/traces.py

### Commit 2 — Phase 3.2: Cost and performance tracking
- ready: yes
- message: feat(observability): token, cost and latency tracking with cross-task aggregates
- body:
  - per-call cost from model pricing config
  - per-run metrics including human review time
  - aggregates by task type, agent, tool and escalation trend
- files:
  - config/pricing.yaml
  - src/aos/observability/costs.py
  - src/aos/observability/metrics.py
  - src/aos/api/routes/metrics.py
  - src/aos/graph/runner.py

### Commit 3 — Phase 3.3: Trace explorer + cost dashboard
- ready: yes
- message: feat(ui): trace explorer and cost dashboard
- body:
  - colour-coded execution tree with drill-down into prompts, responses and tool calls
  - timeline view of parallel specialists
  - cost, token, tool usage and escalation charts
- files:
  - ui/pages/3_Trace_Explorer.py
  - ui/pages/4_Costs.py
  - ui/Home.py
  - ui/pages/1_Review_Queue.py
  - ui/pages/2_Memory.py

### Commit 4 — Phase 3.4: Replay system
- ready: yes
- message: feat(replay): replay runs from recorded model calls with overrides and run comparison
- body:
  - re-run a finished task reusing recorded model answers and tool results matched by call position
  - override any recorded answer; the first changed prompt is reported as the divergence point
  - recorded human decisions reused, sensitive actions skipped, memory neither queried nor written
  - run comparison of plans, outputs, reviews and costs, replay API, worker task and UI
  - prompts render stored dicts in sorted key order so Postgres JSONB cannot cause false divergence
- files:
  - src/aos/replay/
  - src/aos/api/routes/replay.py
  - src/aos/api/main.py
  - ui/pages/5_Replay.py
  - ui/lib/api_client.py
  - src/aos/llm/base.py
  - src/aos/llm/router.py
  - src/aos/llm/hooks.py
  - src/aos/tools/base.py
  - src/aos/tools/registry.py
  - src/aos/graph/nodes/escalate.py
  - src/aos/graph/nodes/memory.py
  - src/aos/graph/nodes/actions.py
  - src/aos/schemas/results.py
  - src/aos/worker/tasks.py
  - src/aos/agents/specialists/base.py
  - src/aos/agents/reviewer.py

### Commit 5 — Phase 3.5: Containerize + demo scenario
- ready: yes
- message: build: full docker-compose stack and automated showcase demo
- body:
  - one application image for api, worker, beat and ui; compose stack with infra and optional Jaeger
  - seed script for demo data and prior memories
  - demo script running the vector database research scenario end to end
  - schema and checkpoint setup behind a Postgres advisory lock so api and worker can start together on an empty database
- files:
  - docker/
  - .dockerignore
  - docker-compose.yml
  - scripts/
  - src/aos/db/session.py
  - src/aos/graph/checkpointer.py

### Commit 6 — Phase 3.6: End-to-end tests + CI
- ready: yes
- message: test: end-to-end tests for planning, tools, review, memory, escalation and recovery
- body:
  - six e2e suites covering the required behaviours
  - services tier against the compose stack
  - GitHub Actions CI running lint and tests
- files:
  - tests/e2e/
  - tests/conftest.py
  - .github/workflows/ci.yml
  - tests/unit/test_tracing.py
  - tests/unit/test_costs.py
  - tests/unit/test_replay.py
  - tests/fixtures/mock_llm/

### Commit 7 — Phase 3.7: Portfolio polish
- ready: yes
- message: docs: README, architecture deep dive and demo recording script
- body:
  - README with narrative, architecture diagram, quickstart and design decisions
  - ARCHITECTURE.md and DEMO_SCRIPT.md
  - Day 3 progress log
- files:
  - README.md
  - docs/ARCHITECTURE.md
  - docs/DEMO_SCRIPT.md
  - docs/progress/DAY-3.md

## Verification
<!-- Build agent: list the commands you ran and summarize their results. -->
- `uv run ruff check .`: all checks passed. `uv run ruff format --check .`: 157 files already formatted.
- `uv run pytest -q`: 148 passed in about 88 s (in-memory tier: SQLite, fakeredis, Chroma EphemeralClient, InMemorySaver, mock models).
- `uv run pytest -q -m e2e`: 22 passed (six suites, through the HTTP API only).
- `uv run pytest -q -m e2e --services` against the fresh compose stack: 21 passed, 1 skipped in 45 s; the skipped test is the provider fallback, which patches providers inside the test process.
- Fresh-clone quickstart: the committable files (`git ls-files -co --exclude-standard`) copied to an empty folder, no `.env`, empty volumes, then exactly the README's three commands:
  - `docker compose up -d --build --wait`: every service healthy;
  - `docker compose exec api python scripts/seed.py`: 3 memories for `demo`;
  - `docker compose exec api python scripts/demo.py --auto-approve`: plan of 4 subtasks shaped by 2 memories, s1 and s2 in parallel, `db_query` and `code_exec` in s2, the MCP `company_lookup` tool in s3, the s4 draft rejected by the figure check (4,600 is in no tool result) and approved after revision, `send_email` approved and executed once, 5 memories saved, 20 model calls, 17,666 tokens, $0.0240 at simulated prices, 56 spans.
  - The first attempt found a startup race: on an empty database the api and worker both ran `create_all` and the api exited with a `pg_type` unique violation. Fixed with a Postgres advisory lock around schema and checkpoint setup (held on an autocommit connection, since the checkpointer's `CREATE INDEX CONCURRENTLY` otherwise waits on the lock holder's transaction).
- Replay in the compose stack: replaying the showcase run unchanged reused 19 recorded calls with 0 fresh ones and an identical final output; overriding the s2 answer with an invented figure (4,900) diverged at the s2 review, the figure check rejected it, and the run converged back to the original summary; editing the writer's final answer changed the deliverable and nothing upstream.
- UI checked in the browser: Trace explorer (tree with model and tool calls, span detail with prompt and response, per-invocation timeline), Costs and Replay (unchanged and edited replays with the comparison view) against the stack during 3.3 and 3.4; on the fresh stack after the demo, all six pages render (Home shows the run and both cited memories for user `demo`, Memory shows 9 memories). The Review queue's approve and chat flow was checked on Day 2 and is covered by the escalation e2e suite.
- `git status --porcelain -uall` compared with the commit blocks: every changed path is in exactly one block; secret patterns from the commit protocol match no committable file; `.env`, `AGENTS.md` and `CLAUDE.md` are ignored.

## Handoff
<!-- Build agent: known issues, limitations and follow-ups after the final day. -->
### Deviations from the plan
- **Replay (3.4)** re-runs from recorded model calls instead of forking a LangGraph checkpoint. `GET /runs/{id}/steps` lists the parent run's recorded model calls (agent, purpose, subtask, attempt, answer preview) rather than `get_state_history()` entries. `POST /runs/{id}/replay` takes `{mode, overrides, request}`: `overrides` maps an `llm_calls.id` to a replacement response, and `request` optionally replaces the task text. Each replay is a new task and run from the start (`parent_run_id` set, `replay_of_checkpoint = "replay"`, a new thread). Reason: the effect of a changed answer can be shown anywhere in the run, divergence is exact (first `call_key` whose `prompt_hash` differs), and recordings survive code changes that would make old checkpoints unloadable.
- Replay also reuses recorded tool outputs (failed ones included, so retry paths replay too) and recorded human decisions, reuses the parent's memory context, and writes no memories. Sensitive tools are not run; the action is marked `skipped`.
- Prompts render stored dicts with sorted keys (specialist inputs, evidence arguments, reviewer data, tool output) because Postgres JSONB does not preserve key order, which made replays diverge in the services tier only.
- **Tracing (3.1)** uses a `BatchSpanProcessor` flushed at the end of every graph invocation; per-span export slowed the test suite to about two minutes.
- **Trace explorer (3.3)** draws one timeline panel per invocation (first run, each resume), in milliseconds from that invocation's start, because a pause for a human can last hours.
- **Containers (3.5)**: one image, `docker/app.Dockerfile`, serves api, worker, beat and ui; there is no `ui.Dockerfile`. Host ports are 5433 (Postgres), 6380 (Redis) and 8001 (Chroma) to avoid local services. Chroma is pinned to `chromadb/chroma:1.5.9` to match the client. `OLLAMA_BASE_URL` in compose points at `host.docker.internal`.
- `scripts/demo.py` has no `--live` flag: it is an API client, and the model mode is the server's `LLM_MODE` (set it in `.env` and restart the stack).
- **README (3.7)** has no screenshots or `docs/img/`; the demo script describes each page instead.
- `src/aos/db/session.py` and `src/aos/graph/checkpointer.py` (Day 1 files) gained `schema_lock()` for the fresh-database race found during verification; they are in the 3.5 block.

### Interface additions
- Endpoints: `GET /runs/{id}/trace`, `GET /spans/{id}`, `GET /runs/{id}/metrics`, `GET /metrics/summary?days=`, `GET /runs/{id}/steps`, `POST /runs/{id}/replay`, `GET /runs/{a}/compare/{b}`.
- Celery task `aos.replay_run`. Table `spans`. Env vars `OTEL_SERVICE_NAME`, `OTEL_EXPORTER_OTLP_ENDPOINT`. Config file `config/pricing.yaml`.
- `ProposedAction.status` can be `skipped`; `LLMResult.replayed`.

### Known issues and limitations
- `config/pricing.yaml` ships no hosted-model prices; Anthropic and OpenAI calls cost $0 until prices are added. Mock calls use simulated prices and are labelled as such.
- In mock mode the reviewer chat answers with a fixed line naming the escalation reason; useful answers need live mode.
- `code_exec` is a subprocess with a stripped environment and a timeout, not a sandbox.
- No authentication on the API or the console.
- The hash embedder matches shared words, not paraphrases; use `EMBEDDING_PROVIDER=ollama` for semantic recall.
- The application image is about 2.8 GB (ChromaDB's ONNX runtime, Streamlit, Altair).
- Spans are kept indefinitely; there is no retention job.
- Roadmap: a real code sandbox (gVisor or Firecracker), authentication, a React console, span retention, and checkpoint forking as a second replay mode.
