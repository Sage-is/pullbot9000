# Resident Agent Daemon™

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

A self-hosted AI agent platform by [Sage.is](https://sage.is). One agent core — Claude Code or OpenCode today, more coming soon — exposed through **Telegram**, an **OpenAI-compatible API**, **webhooks**, and **scheduled jobs**.

Run your own resident agent: an always-on daemon, security-hardened, that lives on your server, keeps per-project context, and is reachable from anywhere.

## What is this?

Resident Agent Daemon™ is a deployable agent platform, not a library you code against. You configure it, run it, and it serves your agent through multiple interfaces:

- **One core, many surfaces** — the same agent backend answers a Telegram chat, an OpenAI-compatible REST API, incoming webhooks, and cron jobs
- **Swappable agent cores** — Claude Code (Python SDK) and OpenCode (HTTP API) today, selectable with one env var; the facade is built for more cores to drop in
- **General-purpose agents** — monitor services, research the web, run scheduled reports, and yes, write code. Coding is one use case, not the identity
- **Conversational from anywhere** — chat with your agent from any device with Telegram, no terminal needed
- **Per-project context** — sessions persist per user + directory and auto-resume; switch projects without losing context
- **Event-driven** — webhooks and cron jobs trigger agent runs that land in your Telegram chats
- **Stay secure** — whitelist/token authentication, directory sandboxing, input validation, rate limiting, and audit logging
- **Extensible** — a plugin system for custom agents and interfaces is on the roadmap (see [Planned Enhancements](#planned-enhancements))

## Architecture at a Glance

```
                 ┌─────────────────────────────────────────────────┐
                 │            Resident Agent Daemon™               │
                 │                                                 │
 Telegram bot ───┤  ┌───────────────────────────────────────────┐  │
 OpenAI API ─────┤  │  Orchestrator / EventBus                  │  │
 Webhooks ────────┤  │  → AgentHandler → ClaudeIntegration      │  │
 Cron scheduler ──┤  │       ├─ Claude Code SDK (BACKEND=claude) │  │
                 │  │       └─ OpenCode HTTP API (BACKEND=opencode)│  │
                 │  └───────────────────────────────────────────┘  │
                 │  Sessions · Storage (SQLite) · Security         │
                 │  Notifications · Audit · Rate limits            │
                 └─────────────────────────────────────────────────┘
```

The core talks to the agent through a facade (`ClaudeIntegration`) with a single `execute_command` interface. Both `ClaudeSDKManager` and `OpenCodeManager` implement it — swapping cores is a config change, not a code change.

## Interfaces

### 1. Telegram Bot

The flagship interface. Two interaction modes:

#### Agentic Mode (Default)

Just talk to your agent naturally — no special commands required.

**Commands:** `/start`, `/new`, `/status`, `/verbose`, `/repo`
If `ENABLE_PROJECT_THREADS=true`: `/sync_threads`

```
You: What files are in this project?
Bot: Working... (3s)
     📖 Read
     📂 LS
     💬 Let me describe the project structure
Bot: [Agent describes the project structure]

You: Add a retry decorator to the HTTP client
Bot: Working... (8s)
     📖 Read: http_client.py
     💬 I'll add a retry decorator with exponential backoff
     ✏️ Edit: http_client.py
     💻 Bash: uv run pytest tests/ -v
Bot: [Agent shows the changes and test results]

You: /verbose 0
Bot: Verbosity set to 0 (quiet)
```

Use `/verbose 0|1|2` to control how much background activity is shown:

| Level | Shows |
|-------|-------|
| **0** (quiet) | Final response only (typing indicator stays active) |
| **1** (normal, default) | Tool names + reasoning snippets in real-time |
| **2** (detailed) | Tool names with inputs + longer reasoning text |

#### GitHub Workflow

Agents already know how to use `gh` CLI and `git`. Authenticate on your server with `gh auth login`, then work with repos conversationally:

```
You: List my repos related to monitoring
Bot: [Agent runs gh repo list, shows results]

You: Clone the uptime one
Bot: [Agent runs gh repo clone, clones into workspace]

You: /repo
Bot: 📦 uptime-monitor/  ◀
     📁 other-project/

You: Show me the open issues
Bot: [Agent runs gh issue list]

You: Create a fix branch and push it
Bot: [Agent creates branch, commits, pushes]
```

Use `/repo` to list cloned repos in your workspace, or `/repo <name>` to switch directories (sessions auto-resume).

#### Classic Mode

Set `AGENTIC_MODE=false` to enable the full 13-command terminal-like interface with directory navigation, inline keyboards, quick actions, git integration, and session export.

**Commands:** `/start`, `/help`, `/new`, `/continue`, `/end`, `/status`, `/cd`, `/ls`, `/pwd`, `/projects`, `/export`, `/actions`, `/git`
If `ENABLE_PROJECT_THREADS=true`: `/sync_threads`

```
You: /cd my-web-app
Bot: Directory changed to my-web-app/

You: /ls
Bot: src/  tests/  package.json  README.md

You: /actions
Bot: [Run Tests] [Install Deps] [Format Code] [Run Linter]
```

#### Multi-Project Topics

With `ENABLE_PROJECT_THREADS=true`, projects are mapped to Telegram forum topics — each topic is its own project workspace, and messages in a topic automatically route to that project's directory.

### 2. OpenAI-Compatible API

`ENABLE_API_SERVER=true` mounts a `/v1/chat/completions` endpoint (streaming and non-streaming) on the API server. Any OpenAI client — `curl`, the `openai` Python library, IDEs, `ollama`-style tools — can talk to the same agent core the Telegram bot uses.

```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Authorization: Bearer $WEBHOOK_API_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"model": "claude-sonnet-4-20250514",
       "messages": [{"role": "user", "content": "Summarize today's logs"}]}'
```

- `API_STREAM_THINKING=true` includes `<thinking>` blocks in streaming responses
- Cron jobs are managed via REST — `POST /schedules` (cron expression + prompt + target chats), `GET /schedules`, and `DELETE /schedules/{job_id}`, all requiring the Bearer token
- `/health` for health checks

The API server can also run **standalone without Telegram** (see [Quick Start](#4-run)).

### 3. Webhooks

`POST /webhooks/{provider}` receives external events (GitHub push/PR/issue, CI/CD, generic providers) and routes them through the agent for automated summaries, reviews, or responses:

- GitHub: HMAC-SHA256 signature verification (`GITHUB_WEBHOOK_SECRET`)
- Generic providers: Bearer token auth (`WEBHOOK_API_SECRET`)
- Atomic deduplication so duplicate deliveries don't double-run the agent

### 4. Scheduler

`ENABLE_SCHEDULER=true` enables cron jobs that trigger agent runs on a schedule — e.g. a daily code health check or a morning status report — with results delivered to configured Telegram chats (`NOTIFICATION_CHAT_IDS`). Jobs persist in SQLite and can be managed via the API server's schedule routes.

## Agent Cores

The agent core is selected with the `BACKEND` env var:

| Core | `BACKEND` | How it connects |
|------|-----------|-----------------|
| **Claude Code** | `claude` | Anthropic's [Claude Agent SDK](https://claude.ai/code) (Python), authenticated via `ANTHROPIC_API_KEY` or an existing CLI login |
| **OpenCode** | `opencode` | [OpenCode](https://opencode.ai) HTTP API — the bot auto-starts the server as a sidecar (`OPENCODE_AUTO_START`) or connects to an existing one |

Both cores share the same session model: sessions are per user + project directory, persisted in SQLite, and auto-resume across conversations.

> **More cores coming soon.** The facade is designed for new backends to drop in behind the same `execute_command` interface — no bot changes required.

## Quick Start

### Demo

```
You: Can you help me add error handling to src/api.py?

Bot: I'll analyze src/api.py and add error handling...
     [Agent reads your code, suggests improvements, and can apply changes directly]

You: Looks good. Now run the tests to make sure nothing broke.

Bot: Running pytest...
     All 47 tests passed. The error handling changes are working correctly.

You: Check our uptime monitor every morning and ping me if anything's down

Bot: Done. I've scheduled a daily check — I'll message you if there's a problem.
```

### 1. Prerequisites

- **Python 3.11+** — [Download here](https://www.python.org/downloads/)
- **Telegram Bot Token** — Get one from [@BotFather](https://t.me/botfather)
- **One agent core:**
  - **Claude Code** (`BACKEND=claude`): install the [Claude Code CLI](https://claude.ai/code) and authenticate (`claude auth login`), or set `ANTHROPIC_API_KEY`
  - **OpenCode** (`BACKEND=opencode`): install the [opencode CLI](https://opencode.ai/docs) — the bot auto-starts the server

### 2. Install

Choose your preferred method:

#### Option A: Install from a release tag (Recommended)

```bash
# Using uv (recommended — installs in an isolated environment)
uv tool install git+https://github.com/Sage-is/pullbot9000@v1.3.0

# Or using pip
pip install git+https://github.com/Sage-is/pullbot9000@v1.3.0

# Track the latest stable release
pip install git+https://github.com/Sage-is/pullbot9000@latest
```

#### Option B: From source (for development)

```bash
git clone https://github.com/Sage-is/pullbot9000.git
cd pullbot9000
make dev  # requires uv
```

> **Note:** Always install from a tagged release (not `main`) for stability. The **OpenCode core** is currently on `main` only — it ships in the next release. See [Releases](https://github.com/Sage-is/pullbot9000/releases) for available versions.

### 3. Configure

```bash
cp .env.example .env
# Edit .env with your settings:
```

**Minimum required:**
```bash
TELEGRAM_BOT_TOKEN=1234567890:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
TELEGRAM_BOT_USERNAME=my_agent_bot
APPROVED_DIRECTORY=/Users/yourname/projects
ALLOWED_USERS=123456789  # Your Telegram user ID
BACKEND=claude           # or opencode
```

### 4. Run

**Full platform** (Telegram bot + optional API server, scheduler, webhooks):

```bash
make run          # Production
make run-debug    # With debug logging
```

**API-only mode** (OpenAI-compatible server, no Telegram):

```bash
uv run claude-api-server          # Port 8080 by default
uv run claude-api-server --debug  # Debug logging
```

Message your bot on Telegram to get started.

> **Detailed setup:** See [docs/setup.md](docs/setup.md) for core authentication options and troubleshooting.

## Configuration

### Required

```bash
TELEGRAM_BOT_TOKEN=...           # From @BotFather
TELEGRAM_BOT_USERNAME=...        # Your bot's username
APPROVED_DIRECTORY=...           # Base directory for project access
ALLOWED_USERS=123456789          # Comma-separated Telegram user IDs
```

### Agent Core

```bash
BACKEND=claude                   # Core selector: claude | opencode

# Claude Code core
ANTHROPIC_API_KEY=sk-ant-...     # API key (optional if using CLI auth)
CLAUDE_MAX_COST_PER_USER=10.0    # Spending limit per user (USD)
CLAUDE_TIMEOUT_SECONDS=300       # Operation timeout

# OpenCode core
OPENCODE_SERVER_PORT=4096        # Server port
OPENCODE_SERVER_HOST=127.0.0.1   # Server hostname
OPENCODE_SERVER_PASSWORD=        # HTTP basic auth password (optional)
OPENCODE_CLI_PATH=               # Path to opencode CLI (auto-detected)
OPENCODE_AUTO_START=true         # Auto-start server as sidecar
```

### Telegram Behavior

```bash
AGENTIC_MODE=true                # Agentic (default) or classic mode
VERBOSE_LEVEL=1                  # 0=quiet, 1=normal (default), 2=detailed

# Rate Limiting
RATE_LIMIT_REQUESTS=10           # Requests per window
RATE_LIMIT_WINDOW=60             # Window in seconds

# Features (classic mode)
ENABLE_GIT_INTEGRATION=true
ENABLE_FILE_UPLOADS=true
ENABLE_QUICK_ACTIONS=true
```

### Interfaces

```bash
# OpenAI-compatible API
ENABLE_API_SERVER=false          # Enable FastAPI server
API_SERVER_HOST=0.0.0.0          # Bind address (0.0.0.0 = all interfaces)
API_SERVER_PORT=8080             # Server port
API_STREAM_THINKING=false        # Include <thinking> blocks in streams

# Webhook Authentication
GITHUB_WEBHOOK_SECRET=...        # GitHub HMAC-SHA256 secret
WEBHOOK_API_SECRET=...           # Bearer token for generic providers + API

# Scheduler
ENABLE_SCHEDULER=false           # Enable cron job scheduler

# Notifications
NOTIFICATION_CHAT_IDS=123,456    # Default chat IDs for proactive notifications
```

### Project Threads Mode

```bash
# Enable strict topic routing by project
ENABLE_PROJECT_THREADS=true

# Mode: private (default) or group
PROJECT_THREADS_MODE=private

# YAML registry file (see config/projects.example.yaml)
PROJECTS_CONFIG_PATH=config/projects.yaml

# Required only when PROJECT_THREADS_MODE=group
PROJECT_THREADS_CHAT_ID=-1001234567890

# Minimum delay (seconds) between Telegram API calls during topic sync
# Set 0 to disable pacing
PROJECT_THREADS_SYNC_ACTION_INTERVAL_SECONDS=1.1
```

In strict mode, only `/start` and `/sync_threads` work outside mapped project topics.
In private mode, `/start` auto-syncs project topics for your private bot chat.
To use topics with your bot, enable them in BotFather:
`Bot Settings -> Threaded mode`.

> **Full reference:** See [docs/configuration.md](docs/configuration.md) and [`.env.example`](.env.example).

### Finding Your Telegram User ID

Message [@userinfobot](https://t.me/userinfobot) on Telegram — it will reply with your user ID number.

## Features

### Working Features

- Conversational agentic mode (default) with natural language interaction
- Classic terminal-like mode with 13 commands and inline keyboards
- Plug-and-play agent cores: Claude Code SDK and OpenCode HTTP API (more coming soon)
- Standalone OpenAI-compatible API server (`/v1/chat/completions`, streaming + thinking blocks)
- Webhook API server (GitHub HMAC-SHA256, generic Bearer token) with atomic deduplication
- Job scheduler with cron expressions and persistent storage
- Notification service with per-chat rate limiting
- Automatic session persistence per user/project directory with auto-resume
- Multi-project support via Telegram forum topics
- Multi-layer authentication (whitelist + optional token-based)
- Rate limiting with token bucket algorithm
- Directory sandboxing with path traversal prevention
- File upload handling with archive extraction
- Image/screenshot upload with analysis
- Git integration with safe repository operations
- Quick actions system with context-aware buttons
- Session export in Markdown, HTML, and JSON formats
- SQLite persistence with migrations
- Usage and cost tracking
- Audit logging and security event tracking
- Event bus for decoupled message routing
- Tunable verbose output showing agent tool usage and reasoning in real-time
- Persistent typing indicator so users always know the bot is working
- 17 configurable tools with allowlist/disallowlist control (see [docs/tools.md](docs/tools.md))
- Model Context Protocol (MCP) support

### Planned Enhancements

- Plugin system for third-party extensions and custom interfaces
- Additional agent cores

## Troubleshooting

**Bot doesn't respond:**
- Check your `TELEGRAM_BOT_TOKEN` is correct
- Verify your user ID is in `ALLOWED_USERS`
- Ensure your chosen core's CLI is installed and accessible
- Check bot logs with `make run-debug`

**Claude core not working:**
- Check `claude auth status` or verify `ANTHROPIC_API_KEY`
- Verify `claude --version`
- Check `CLAUDE_ALLOWED_TOOLS` includes necessary tools (see [docs/tools.md](docs/tools.md) for the full reference)

**OpenCode core not working:**
- Ensure the `opencode` CLI is installed (`opencode --version`) or set `OPENCODE_CLI_PATH`
- Check the sidecar server is reachable on `OPENCODE_SERVER_HOST:OPENCODE_SERVER_PORT` (`curl http://localhost:4096/global/health`)
- If a password is set, make sure `OPENCODE_SERVER_PASSWORD` matches the server's
- Port conflicts: stop other servers on `OPENCODE_SERVER_PORT` or change it

**API-only mode not working:**
- Set `API_SERVER_HOST` to `127.0.0.1` if the API should not be reachable on your LAN
- All requests need the Bearer token (`WEBHOOK_API_SECRET`)

**High usage costs:**
- Adjust `CLAUDE_MAX_COST_PER_USER` to set spending limits
- Monitor usage with `/status`
- Use shorter, more focused requests

## Security

This platform implements defense-in-depth security:

- **Access Control** -- Whitelist-based user authentication (+ optional tokens)
- **Directory Isolation** -- Sandboxing to approved directories
- **Rate Limiting** -- Request and cost-based limits
- **Input Validation** -- Injection and path traversal protection
- **Webhook Authentication** -- GitHub HMAC-SHA256 and Bearer token verification
- **Audit Logging** -- Complete tracking of all user actions

See [SECURITY.md](SECURITY.md) for details.

## Development

```bash
make dev           # Install all dependencies
make test          # Run tests with coverage
make lint          # Black + isort + flake8 + mypy
make format        # Auto-format code
make run-debug     # Run with debug logging
```

> **Full documentation:** See the [docs index](docs/README.md) for all guides and references.

### Version Management

The version is defined once in `pyproject.toml` and read at runtime via `importlib.metadata`. To cut a release:

```bash
make bump-patch    # 1.2.0 -> 1.2.1 (bug fixes)
make bump-minor    # 1.2.0 -> 1.3.0 (new features)
make bump-major    # 1.2.0 -> 2.0.0 (breaking changes)
```

Each command commits, tags, and pushes automatically, triggering CI tests and a GitHub Release with auto-generated notes.

### Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/amazing-feature`
3. Make changes with tests: `make test && make lint`
4. Submit a Pull Request

**Code standards:** Python 3.11+, Black formatting (88 chars), type hints required, pytest with >85% coverage.

## License

MIT License -- see [LICENSE](LICENSE).

## Acknowledgments

- Originally created by [Richard Atkinson](https://github.com/RichardAtCT) as [claude-code-telegram](https://github.com/RichardAtCT/claude-code-telegram); forked and evolved by [Sage.is](https://sage.is) as Resident Agent Daemon™ (pullbot9000)
- [Claude](https://claude.ai) by Anthropic
- [OpenCode](https://opencode.ai)
- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot)

---

*Every Daemon needs a story: read [The Dweller Who Never Slept](docs/fable.md).*
