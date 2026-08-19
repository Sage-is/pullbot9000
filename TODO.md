# TODO — Resident Agent Daemon™ (pullbot9000)

> Multi-harness agent platform by Sage.is: one `execute_command` facade (`src/backend/facade.py`), many agent cores behind it. Design home for new cores: `docs/decisions/multi-backend-chart.md`.

## Active — New Agent Cores: Pi + NanoCoder (2026-08-12)

Both cores drop in behind the existing facade contract:
`execute_command(prompt, working_directory, session_id, continue_session, stream_callback) -> ClaudeResponse`
(`content, session_id, cost, duration_ms, num_turns, tools_used`). Selection via `BACKEND` literal in `src/config/settings.py:66`. Mirror the OpenCode pattern: manager (`src/backend/opencode_integration.py`) + sidecar process lifecycle (`src/backend/opencode_server.py`).

### 0. Shared backend foundation (prereq — unblocks both)

- [ ] **Backend interface contract** — define an ABC/Protocol for managers: `execute_command(...)`, lifecycle hooks (`start`/`stop`/`health`), `get_active_process_count()`. Enforce with mypy + shared contract tests.
- [ ] **Config pattern** — per-backend nested settings with prefixed env vars (`PI_*`, `NANOCODER_*`); stop growing the single `Settings` model.
- [ ] **Facade rename** — `ClaudeIntegration` → backend-neutral name (e.g. `AgentIntegration`); add a backend registry mapping `BACKEND` → manager class.
- [ ] **Contract tests** — one parameterized suite over all managers: result schema, session-resume fallback (fresh-session retry from `facade.py:101`), error mapping (`ClaudeProcessError`/`ClaudeTimeoutError`/`ClaudeParsingError`), cost/turns aggregation.

### 1. Pi backend (pi.dev) — RPC-mode path

- [ ] **Research spike: Pi integration surface** — pin the RPC protocol + version; document LF-delimited JSONL framing (split on `\n` only), request/response shape, session create/resume + session-file semantics, and whether cost + tool events stream in JSON/RPC modes. (Loose thread in multi-backend-chart.)
- [ ] `PiManager` — implement the contract over `pi --mode rpc` (fall back to `--mode json` if RPC is insufficient).
- [ ] Process lifecycle — spawn `pi --mode rpc --cwd <workspace>`, healthcheck/ping, restart-on-death (mirror `OpenCodeServer`).
- [ ] Session mapping — Pi JSONL session files ↔ pullbot `session_id` auto-resume.
- [ ] Streaming → `StreamUpdate`; verify `/verbose 0|1|2` behaves.
- [ ] Tool validation — reuse `_validate_tool` logic / `monitor.py` helpers for Pi's read/write/edit/bash (+ optional grep/find/ls).
- [ ] Config — `PI_*` env vars (binary path, model/provider, timeout, auto-start).
- [ ] Tests — `tests/unit/test_backend/test_pi_integration.py`, `test_pi_server.py` (mirror `test_opencode_*.py`).
- [ ] Docs — `.env.example`, `docs/configuration.md`, `docs/tools.md`, README agent-core table.

### 2. NanoCoder backend (Nano-Collective/nanocoder)

- [ ] **Research spike: ACP vs headless** — verify the `nanocoder` ACP loop (JSON-RPC over stdio) maturity for tool-event streaming, cost, and session resume. If ACP is immature, gate on upstream issue #603 (`--json` machine output) or a `run --plain` parse fallback, and decide which path to take.
- [ ] `NanoCoderManager` — implement the contract over ACP (or `nanocoder run --plain` fallback).
- [ ] Process lifecycle — spawn headless/ACP subprocess, manage restart; respect `NANOCODER_MAX_TURNS` (default 200) as runaway protection.
- [ ] Session mapping + resume.
- [ ] Streaming → `StreamUpdate`; `/verbose` compatibility.
- [ ] Tool validation — map nanocoder tool names to the validator; note headless defaults to `auto-accept`, so pullbot's `SecurityValidator` is the enforcement layer.
- [ ] Config — `NANOCODER_*` env vars (provider, model, max turns, data dir).
- [ ] Tests — `tests/unit/test_backend/test_nanocoder_integration.py`, `test_nanocoder_server.py`.
- [ ] Docs — `.env.example`, `docs/configuration.md`, `docs/tools.md`, README agent-core table.

### 3. Cutover

- [ ] `BACKEND` enum: add `pi` and `nanocoder` literals.
- [ ] Full `make test && make lint` green.
- [ ] CHANGELOG entry + release notes.

## OpenAI-Compat API Backlog

- [x] Delta-only streaming
- [x] Cost tracking for API requests (both streaming and non-streaming paths)
- [x] `reasoning_content` + thinking tags (landed via `22bef2e`)
- [ ] Keep-alive comments during tool execution
- [ ] Tool call streaming (OpenAI format)
- [ ] Streaming error events
- [ ] Usage in final chunk
- [ ] `stop` vs `length` finish reason

## Infrastructure Backlog

- [ ] **`cloudflared tunnel login`** — run on this Pi to get `cert.pem` in `~/.cloudflared/`. Enables tunnel management commands (`tunnel info`, `tunnel route dns`) locally instead of requiring the Cloudflare dashboard. Not needed for `tunnel run` / `make serve`, but needed to add or change DNS routes from this machine.

## Repo Consolidation

- [x] Confirmed: same codebase, same schema, slightly diverged (9000 = API mode, 9001 = Telegram mode)
- [ ] Consolidate to one repo with two `.env` files (`.env.telegram`, `.env.api`)
- [ ] Merge 9000's Makefile targets (`tunnel`, `serve`) into the main Makefile
- [ ] Archive 9000 or 9001 after migration

---

## Archive — Pieter Levels Review (2026-04-15)

> "You have real usage data. Let it make the decisions."

**Usage snapshot:** 3 users (1 active), 1,219 msgs/~50 days, **$2,122 total spend** (~$830 last 14 days), peak $166.70 (Apr 4). Dead at review time: token auth (0), scheduler (0), webhooks (0), project threads (0). Audit events: only `claude_interaction`.

**Outcomes since the review** — the delete-heavy recommendations were deliberately superseded by the platform pivot:

- [x] **Shipped the multi-surface platform instead of deleting** — the "dead" subsystems (webhooks, scheduler, token auth, project threads) became advertised features of Resident Agent Daemon™ (README overhaul `e80e3ef`, `docs/` index set up).
- [x] **Multi-backend facade** (opposite of "flatten to 1 file") — OpenCode backend shipped (`fe41845`), SSE streaming (`536c323`), multi-backend design chart (`b15835e` → `docs/decisions/multi-backend-chart.md`).
- [x] **Schedule management routes** (`4c253ff`).
- [x] **Thinking/reasoning fix applied** — `22bef2e`.
- [ ] **Still open:** 1-power-user economics / spend budget; product-vs-internal positioning; classic-mode fate (kept, 3 handler files ~4k lines); whether to slim 5-layer security to 2 (deferred).