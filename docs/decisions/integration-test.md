# Integration Test

## Decision

Unit tests covering both OpenCode modules (`OpenCodeManager` and `OpenCodeServer`)
with mocked HTTP/subprocess. 43 tests across two files.

## What's tested

### `test_opencode_integration.py` (26 tests)
- Manager init (base URL, auth, custom URL)
- Session creation and forking (`_get_or_create_session`)
- SSE event processing: content.delta, content.done, tool_use.start, thinking.delta,
  message.complete, result, error
- Tool validation: file tools inside/outside approved dir, bash boundary checks,
  Claude internal paths, no-validator passthrough
- `execute_command()`: response shape, timeout → `ClaudeTimeoutError`,
  connect error → `ClaudeProcessError`, stream callback wiring

### `test_opencode_server.py` (17 tests)
- `find_opencode_cli()`: explicit path, env var, which fallback, not found
- Server init (base URL, not-started state)
- Start: already started noop, already running externally, CLI not found,
  successful launch, failed health check
- Stop: SIGTERM, kill after timeout, no-process noop
- `ensure_running()`: noop if not started, restart if process died

## Rationale

Used `unittest.mock` + `httpx.Response` stubs rather than adding a test dependency
(respx, pytest-httpx). The existing test suite follows the same pattern. A true
end-to-end test against a live OpenCode server would require `opencode serve` running —
that's a manual verification step, not a CI-friendly test.
