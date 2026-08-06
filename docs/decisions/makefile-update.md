# Makefile Update

## Changes

1. **`check-deps`** — verifies Node.js, Claude Code CLI, and OpenCode CLI are installed.
   Reports versions or install instructions. Runs automatically after `make dev`.

2. **`setup-claude`** / **`setup-opencode`** — installs the respective CLI via `npm install -g`.

3. **`BACKEND` awareness** — `serve` and `serve-bg` read `BACKEND` from `.env` (default: `claude`).
   When `BACKEND=opencode`, an additional tmux pane runs `opencode serve --port $OPENCODE_PORT`
   before the bot and API server start. The `OPENCODE_PORT` defaults to 4096, read from
   `OPENCODE_SERVER_PORT` in `.env`.

4. **`OPENCODE_PORT`** variable — read from `.env` like `TUNNEL_PORT`, defaults to 4096.
