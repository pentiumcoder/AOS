# Day 3 — Observability, replay, packaging

Status: NOT_STARTED
<!-- NOT_STARTED | IN_PROGRESS | COMPLETE. The build agent updates this; the commit agent reads it. -->

Theme: Observability, replay and packaging - tracing, costs, trace explorer, replay, docker demo, e2e tests, docs
Tag when complete: day-3
Plan: docs/IMPLEMENTATION_PLAN.md, section "Day 3"
Requires: tag day-2 (Day 2 committed)

## Phase checklist
- [ ] 3.1 Execution tracing with OpenTelemetry
- [ ] 3.2 Cost and performance tracking
- [ ] 3.3 Trace explorer + cost dashboard
- [ ] 3.4 Replay system
- [ ] 3.5 Containerize + demo scenario
- [ ] 3.6 End-to-end tests + CI
- [ ] 3.7 Portfolio polish

## Commit plan
> The file lists in blocks still marked `ready: no` are **planned**. When the build agent finishes a phase, it replaces that block's list with the **actual** changed paths and sets `ready: yes`.
> Each path appears in exactly one block. If a later phase touches a file listed earlier, move it to the later block.

### Commit 1 — Phase 3.1: Tracing
- ready: no
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
  - src/aos/llm/router.py
  - src/aos/tools/registry.py
  - src/aos/api/routes/traces.py

### Commit 2 — Phase 3.2: Cost and performance tracking
- ready: no
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

### Commit 3 — Phase 3.3: Trace explorer + cost dashboard
- ready: no
- message: feat(ui): trace explorer and cost dashboard
- body:
  - colour-coded execution tree with drill-down into prompts, responses and tool calls
  - timeline view of parallel specialists
  - cost, token, tool usage and escalation charts
- files:
  - ui/pages/3_Trace_Explorer.py
  - ui/pages/4_Costs.py

### Commit 4 — Phase 3.4: Replay system
- ready: no
- message: feat(replay): checkpoint replay with state overrides and run comparison
- body:
  - step through checkpoints and fork any step into a new run with overrides
  - recorded-response replay with divergence detection, sensitive actions never re-executed
  - run comparison of plans, outputs, reviews and costs, replay API and UI
- files:
  - src/aos/replay/
  - src/aos/api/routes/replay.py
  - src/aos/api/main.py
  - ui/pages/5_Replay.py
  - ui/lib/api_client.py

### Commit 5 — Phase 3.5: Containerize + demo scenario
- ready: no
- message: build: full docker-compose stack and automated showcase demo
- body:
  - app and UI images, compose stack with api, worker, beat, ui, infra and optional Jaeger
  - seed script for demo data and prior memories
  - demo script running the vector database research scenario end to end
- files:
  - docker/
  - .dockerignore
  - docker-compose.yml
  - scripts/

### Commit 6 — Phase 3.6: End-to-end tests + CI
- ready: no
- message: test: end-to-end tests for planning, tools, review, memory, escalation and recovery
- body:
  - six e2e suites covering the required behaviours
  - services tier against the compose stack
  - GitHub Actions CI running lint and tests
- files:
  - tests/e2e/
  - tests/conftest.py
  - .github/workflows/ci.yml

### Commit 7 — Phase 3.7: Portfolio polish
- ready: no
- message: docs: README, architecture deep dive and demo recording script
- body:
  - README with narrative, architecture diagram, quickstart and design decisions
  - ARCHITECTURE.md and DEMO_SCRIPT.md
  - Day 3 progress log
- files:
  - README.md
  - docs/ARCHITECTURE.md
  - docs/DEMO_SCRIPT.md
  - docs/img/
  - docs/progress/DAY-3.md

## Verification
<!-- Build agent: list the commands you ran and summarize their results. -->

## Handoff
<!-- Build agent: known issues, limitations and follow-ups after the final day. -->
