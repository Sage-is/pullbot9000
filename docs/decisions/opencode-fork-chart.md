# OpenCode Pullbot Fork — Chart

## Destination

Add OpenCode as a toggleable backend alongside Claude Code. A single `BACKEND=opencode`
env var swaps the harness. Telegram UX, OpenAI-compat API, and Sage.is surface unchanged.

## Notes

Domain: Telegram bot, OpenCode HTTP API, Claude Code SDK, Sage.is platform.
Pullbot source at `/home/replicant/pullbot9000`. OpenCode server docs at
https://opencode.ai/docs/server/. Branch: `feature/opencode-backend`.

Renamed `src/claude/` to `src/backend/` for clarity across both backends.

## In Progress

## TODO
- [ ] **Integration test**: End-to-end test with OpenCode server running. #task

## Backlog

- Session persistence strategy — OpenCode forks sessions (not resumes). Adapt session manager.
- Multi-provider LLM selection — expose provider choice or lock to one?
- MCP server migration — static config or `POST /mcp` registration

## Out of scope

## Done

- [x] **Language choice**: Python + HTTP. — [decision](language-choice.md)
- [x] **Sage.is integration scope**: Existing OpenAI-compat API. No new work. — [decision](sage-integration-scope.md)
- [x] **OpenCode API client mapping**: 14 SDK operations mapped, 4 gaps mitigated. — [decision](opencode-api-client.md)
- [x] **OpenCode server model**: Sidecar subprocess. — [decision](opencode-server-model.md)
- [x] **Fork identity**: Branch `feature/opencode-backend`. — [decision](fork-identity.md)
- [x] **Feature triage**: Toggle, not replace. — [decision](feature-triage.md)
- [x] **Backend toggle config**: `BACKEND` setting added to `settings.py`. Values: `claude` (default), `opencode`. OpenCode settings: port, host, password, cli path, auto-start.
- [x] **OpenCode HTTP client**: `OpenCodeManager` built in `src/backend/opencode_integration.py`. Same `execute_command()` interface. Uses `httpx` against OpenCode REST + SSE.
- [x] **OpenCode server lifecycle**: `OpenCodeServer` built in `src/backend/opencode_server.py`. Start/stop/health-check sidecar.
- [x] **Facade toggle**: `ClaudeIntegration.__init__()` picks manager by `config.backend`. Wired in both `main.py` and `api_main.py`.
- [x] **Tool permission interceptor**: `_validate_tool()` in `OpenCodeManager` checks file paths and bash boundaries against `SecurityValidator` on tool-use events.
- [x] **Directory rename**: `src/claude/` to `src/backend/`, all imports updated, 203 tests pass.
- [x] **Makefile update**: `check-deps`, `setup-claude`, `setup-opencode` targets. Serve targets add OpenCode pane when `BACKEND=opencode`. — [decision](makefile-update.md)
