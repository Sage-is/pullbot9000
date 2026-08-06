# Feature Triage

## Keep (unchanged)

- Telegram bot + all handlers
- OpenAI-compat API + SSE streaming (Sage.is surface)
- Security middleware (auth, rate limit, input validation)
- Storage layer (SQLite — sessions, messages, audit, cost tracking)
- Events / webhooks / scheduler
- Notifications service

## Add (toggle)

- `src/claude/opencode_integration.py` — new OpenCode HTTP client (`httpx` against port 4096), same interface as `ClaudeSDKManager`
- `src/claude/opencode_server.py` — sidecar lifecycle manager for `opencode serve`
- `BACKEND` config setting — `claude` (default) or `opencode`

## Adapt

- `src/claude/facade.py` — same public interface, delegates to OpenCode client instead of SDK
- `src/claude/session.py` — session fork model (parentID) instead of resume
- `src/claude/monitor.py` — dynamic tool permission via SSE stream interception or MCP permission server. SecurityValidator path checks and bash boundary enforcement remain.
- MCP config loading — static config or `POST /mcp` registration before session
- Makefile serve targets — add `opencode serve` pane alongside bot and API server

## Simplify

- `SecurityValidator` path validation — OpenCode has its own sandboxing. Keep the bot-layer checks but do not duplicate what OpenCode enforces.

## Drop candidate

- Classic mode handlers — per Pieter Levels review. Separate decision.
