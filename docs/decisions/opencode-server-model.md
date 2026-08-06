# OpenCode Server Model

**Decision:** Sidecar subprocess managed by the bot process.

## How it runs

- Command: `opencode serve --port 4096 --hostname 127.0.0.1`
- Python bot starts it via `subprocess.Popen` on startup
- Health check: `GET /global/health` returns `{ healthy: true, version: "..." }`
- Auth: HTTP basic via `OPENCODE_SERVER_PASSWORD` / `OPENCODE_SERVER_USERNAME` env vars
- Multiple concurrent sessions supported on a single server

## Lifecycle

- Bot starts the server as a child process during initialization
- Bot monitors health via periodic `GET /global/health` calls
- Bot kills the subprocess on shutdown
- If server dies, bot restarts it (supervisor pattern)

## Open questions

- Does `opencode serve` need a `.opencode.json` in its cwd?
- Per-session working directory — how is cwd set per session?
- Server behavior on restart — do sessions persist?
- Memory usage under concurrent load
