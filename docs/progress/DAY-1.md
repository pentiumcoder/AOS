# Day 1 — Core engine

Status: COMPLETE
<!-- NOT_STARTED | IN_PROGRESS | COMPLETE. The build agent updates this; the commit agent reads it. -->

Theme: Core engine - agents, tools, LangGraph state machine, API and worker
Tag when complete: day-1
Plan: docs/IMPLEMENTATION_PLAN.md, section "Day 1"

## Phase checklist
- [x] 0 Planning docs (written before Day 1 started)
- [x] 1.1 Foundation
- [x] 1.2 LLM layer + core schemas
- [x] 1.3 Tool registry, built-in tools, MCP
- [x] 1.4 Agents
- [x] 1.5 LangGraph state machine, API, worker
- [x] 1.6 Tests + Day 1 handoff

## Commit plan
> The file lists in blocks still marked `ready: no` are **planned**. When the build agent finishes a phase, it replaces that block's list with the **actual** changed paths and sets `ready: yes`.
> Each path appears in exactly one block. The commit agent commits ready blocks in order (AGENTS.md → Commit protocol).

### Commit 1 — Phase 0: Planning docs
- ready: yes
- message: docs: add 3-day implementation plan and agent protocols
- body:
  - IMPLEMENTATION_PLAN.md with phases, seams between days and data model
  - progress manifests for days 2 and 3
- files:
  - docs/IMPLEMENTATION_PLAN.md
  - docs/progress/DAY-2.md
  - docs/progress/DAY-3.md

### Commit 2 — Phase 1.1: Foundation
- ready: yes
- message: chore(foundation): project skeleton, settings, database models and infra compose
- body:
  - uv-managed Python 3.11 package aos with all Day 1 dependencies
  - pydantic-settings config, request context vars, JSON logging
  - SQLAlchemy models for tasks, runs, tool_calls, llm_calls, outbox and a Redis client
  - docker-compose with Postgres, Redis and ChromaDB on non-default host ports
  - gitignore keeping local agent instructions, secrets and runtime data out of the repo
- files:
  - .gitignore
  - .python-version
  - pyproject.toml
  - uv.lock
  - .env.example
  - docker-compose.yml
  - src/aos/__init__.py
  - src/aos/config.py
  - src/aos/context.py
  - src/aos/logging.py
  - src/aos/db/

### Commit 3 — Phase 1.2: LLM layer + core schemas
- ready: yes
- message: feat(llm): provider layer for Ollama, Anthropic, OpenAI and mock with model routing and structured output
- body:
  - LLMProvider interface with structured output, repair retry and usage capture
  - local Ollama provider so live mode needs no API keys
  - router with per-role provider chains, retries and fallback, skipping providers without keys
  - LLM call hooks persisting llm_calls, request context vars
  - plan, result, review and graph state schemas with DAG validation
- files:
  - src/aos/llm/
  - src/aos/schemas/
  - config/models.yaml

### Commit 4 — Phase 1.3: Tool registry, built-in tools, MCP
- ready: yes
- message: feat(tools): tool registry with permissions, rate limits and call logging plus MCP adapter
- body:
  - single invoke path with permission checks, schema validation, per-minute Redis rate limits, timeouts
  - web_search, http_get, file_read, file_write, code_exec, db_query, send_email, file_delete
  - read-only demo benchmark table for db_query, with lowest and highest row per numeric column
  - sensitive tool policy: only offered when the request asks, recipients limited to known contacts
  - MCP client adapter for the 2.x SDK and a demo MCP server
- files:
  - src/aos/tools/
  - config/tools.yaml
  - config/mcp_servers.yaml
  - mcp_servers/demo_server.py

### Commit 5 — Phase 1.4: Agents
- ready: yes
- message: feat(agents): supervisor planner, tool-using specialists and reviewer
- body:
  - supervisor decomposes requests into validated execution plans and synthesizes results
  - research, data analysis, writing and code specialists with tool-use loops
  - sensitive tool calls are proposed, not executed, once per attempt
  - reviewer checks work against the tool results the specialist saw
  - automatic figure check rejects numbers found in no tool result or input
- files:
  - src/aos/agents/

### Commit 6 — Phase 1.5: LangGraph state machine, API, worker
- ready: yes
- message: feat(graph): LangGraph orchestration with parallel specialists, review loop, API and Celery worker
- body:
  - intake, plan, schedule with Send fan-out, review, synthesize, actions, deliver nodes
  - retry with alternative approach, reviewer feedback loop, escalation routing stubs
  - action policy re-checked before execution, duplicate actions merged
  - Postgres checkpointer, traced_node instrumentation seam
  - FastAPI task endpoints, Celery run_task worker, CLI run command
- files:
  - src/aos/graph/
  - src/aos/worker/
  - src/aos/api/
  - src/aos/__main__.py

### Commit 7 — Phase 1.6: Tests + Day 1 handoff
- ready: yes
- message: test: day 1 unit tests for planning, LLM routing, tools, agents, graph and API
- body:
  - plan validation, structured-output repair, retries and provider fallback, live routing without keys
  - tool permissions, rate limits, workspace confinement, read-only SQL, code_exec limits, MCP discovery
  - agent behaviour, reviewer rejection, retry, escalation predicates and API task lifecycle
  - mock LLM scripts, web search fixtures and synthetic benchmark data
  - Day 1 progress log and handoff notes
- files:
  - tests/conftest.py
  - tests/unit/
  - tests/fixtures/
  - docs/progress/DAY-1.md

## Verification
- `python -m uv sync` installed Python 3.11.9 venv with langgraph 1.2.16, langgraph-checkpoint-postgres 3.2.0, mcp 2.3.0, fastapi 0.161.1, celery 5.6.3, anthropic 0.117.0, openai 1.95.1.
- `docker compose up -d --wait postgres redis chromadb`: all three healthy.
- `python -m aos db init`: tables tasks, runs, tool_calls, llm_calls, outbox plus demo.benchmarks in Postgres.
- `ruff check .` clean; `ruff format --check .` reports 97 files formatted.
- `pytest -q`: 73 passed in about 26 s, including the MCP subprocess test.
- `python -m aos run "<showcase request>" --sync` against Postgres with the real MCP server: plan of 4 subtasks, s1 and s2 dispatched in parallel, s3 used `mcp__demo__company_lookup`, reviewer rejected the first s4 draft (0.45, wrong Qdrant QPS) and approved the revision (0.91), send_email went through the escalation stub and landed in `outbox` with the final deliverable as its body.
- API + worker: `POST /tasks` queued the run, the Celery worker (`--pool=solo`) completed it, and `GET /tasks/{id}` read subtask state from the Postgres checkpoint in the API process; `GET /tasks/{id}/tool-calls` returned all 6 calls.
- Live mode on the local model (`ollama pull qwen2.5:7b`, no API keys): `LLM_MODE=live python -m aos llm-smoke` reached qwen2.5:7b for supervisor, research and reviewer with valid structured output (7.8 s cold start, about 0.3 s after).
- Live end-to-end runs of "Using our internal benchmark data, which vector database has the lowest p95 latency and which is cheapest per month? Answer in three bullet points." on qwen2.5:7b:
  - before the quality work: 5 subtasks with a missing dependency, 6 reviewer rejections, a wrong answer (Milvus), two unrequested emails to an invented address, 3 min 13 s;
  - after: 3 subtasks (s1 and s2 in parallel, s3 after both), no rejections, the correct answer (Qdrant 14.9 ms, pgvector $760.00) in three bullets, no email, 45 s.
- The same question with "and email the answer to the team" queued exactly one email, to team@example.com from the contact directory, and the outbox holds one message with the final answer as body.
- The mock showcase still completes; its first s4 draft is now rejected first by the automatic figure check ("Figures not found in any tool result or input: 4,600").
- Anthropic and OpenAI providers are untested against their APIs (no keys); their routing is covered by unit tests.

## Handoff to Day 2
Deviations and decisions:
- **No API keys.** Live mode runs on a local Ollama model (`OLLAMA_BASE_URL`, `OLLAMA_MODEL`, default `qwen2.5:7b`). `config/models.yaml` lists hosted providers first; the router skips any without a key, so every role resolves to Ollama. Run `ollama pull qwen2.5:7b` before using `LLM_MODE=live`.
- **Ollama uses its native `/api/chat`**, not the OpenAI-compatible endpoint, because only the native API accepts `num_ctx` and sampling options; the compatible endpoint ran the model at 4096 tokens of context and temperature 0.8. Defaults: `OLLAMA_NUM_CTX=8192`, `OLLAMA_TEMPERATURE=0.2`, keep-alive 15 min.
- **Host ports:** Postgres 5433, Redis 6380, Chroma 8001, because a local Postgres and Memurai already use 5432 and 6379. The Chroma image is `chromadb/chroma:latest` (no `1.4.4` tag exists); pin a real tag on Day 3.
- **MCP SDK 2.x:** the demo server uses `MCPServer` (FastMCP was renamed) and the adapter uses `mcp.Client`. MCP tools are named `mcp__<server>__<tool>`, not `mcp.<server>.<tool>`, because provider APIs reject dots.
- **Structured output** goes through a forced `respond` tool on Anthropic and OpenAI. Ollama uses its `format` JSON schema: with tools offered it first runs a tools-only call, and when the model replies in prose it makes one more schema-enforced call (`OllamaProvider._tools_then_answer`).
- **Rate limiting** uses fixed one-minute windows in Redis rather than a token bucket, and allows the call if Redis is unreachable.
- Extra columns beyond the plan: `runs.error`, `llm_calls.purpose`.
- **Sensitive tool policy** (`tools/policy.py`, `config/tools.yaml`): a sensitive tool is offered only when the subtask lists it in the new `Subtask.actions` field and the user's request contains one of the tool's `requested_by` words; `send_email` recipients must be in `email_directory` or written in the request. Proposals are checked when made and again in `execute_actions` before running, so a Day 2 reviewer edit cannot bypass it. Each sensitive tool can be queued once per attempt and is withdrawn after queueing; identical proposals from different subtasks are merged.
- **Grounding:** specialists keep the tool results they saw (`SpecialistResult.evidence`) and the reviewer is shown them. `reviewer.unsupported_figures` flags numbers that appear in no tool result or input (allowing rounding and percentages); any flagged figure forces a rejection with the score capped at 0.45. `db_query` results include a `summary` with the lowest and highest row per numeric column.
- **Planning:** `infer_dependencies` adds dependencies a subtask names in its description or inputs but leaves out of `depends_on`. The planner prompt has examples showing one-subtask plans for simple questions.
- Specialists do not re-run a tool call with identical arguments within one attempt.
- `REVIEW_ESCALATE_SCORE` default is 0.6 (was 0.5), matching the reviewer's scoring bands: below 0.5 is wrong content, 0.6 to 0.8 is format only.
- The demo table column holding the database name is `database` (was `name`); `python -m aos db reset` now also drops and reseeds the demo table.
- uv is installed with `pip install --user uv` and is not on PATH; use `python -m uv` or add `%APPDATA%\Python\Python313\Scripts` to PATH.

Interfaces Day 2 builds on:
- **Escalations.** Producer nodes call predicates in `graph/routing.py` (`plan_escalation`, `failure_escalation`, `review_escalation`, `final_escalation`, `action_escalation`) and store requests in `state.pending_escalations`. Each request has `trigger`, `level`, `origin`, `reason`, optional `subtask_id`/`action_id`, and a `step_key` (`origin:trigger:scope`) to use as the idempotency key for the `escalations` table. `graph/nodes/escalate.py` currently resolves the whole batch through `AUTO_DECISIONS` and sets `resume_at` from `RESUME_AT[origin]`; replace that with `interrupt()` and the predicate bodies with `EscalationPolicy`. NOTIFY for borderline plan confidence is not emitted yet.
- **Sensitive actions.** Specialists record `ProposedAction`s instead of running sensitive tools. `execute_actions` collects them from subtasks marked done, raises one `sensitive_operation` request per action, and runs approved ones through the registry with `{{final_output}}` filled in.
- **Subtask bookkeeping.** Statuses: pending, running, awaiting_review, errored, needs_revision, retry, escalate, done, failed. Counters: `visits` (the attempt number passed to agents), `failures`, `revisions`; plus `feedback` and `approach_hints` per subtask.
- **Memory seams.** `retrieve_memory` sets `memory_context` to None and `persist_memory` does nothing. `supervisor.plan(memory_context=...)` takes text, so render the Day 2 planning context to text or widen the signature.
- **State and API.** Graph state is plain JSON (`schemas/state.py`, plus `SpecialistTask` for `Send` payloads and an `events` timeline). The API reads live state from checkpoints through `runner.run_state(thread_id)`.
- **Mock LLM.** Scripts in `tests/fixtures/mock_llm/*.yaml` are chosen by `match` keywords. Callers pass `meta={"purpose": ...}`; handled purposes are plan, synthesize, specialist and review, and any other purpose (memory extraction, chat) reads a list under that key in the script.
- **Worker.** `resume_run` exists as a Celery task stub that raises NotImplementedError. The worker initialises through `worker_init`, which also fires with `--pool=solo`.
- **Tests.** `tests/conftest.py::reset_state` clears every process-level cache; extend it when adding new ones (for example a Chroma client).

Known issues:
- qwen2.5:7b still writes filler when asked for more bullet points than it has facts, and the reviewer cannot always get that fixed within two revisions. Work scoring 0.6 to 0.69 after the last revision is accepted with a warning; the Day 2 policy could emit NOTIFY for it.
- The Day 1 escalation stub still approves policy-compliant sensitive actions automatically. The outbox never really sends, and the Day 2 approval gate replaces the stub.
- Live web search (Tavily or DuckDuckGo) and `http_get` are not exercised by tests because they need the network.
- LLM and tool call rows are written synchronously on the calling thread.
