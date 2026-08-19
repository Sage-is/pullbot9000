.PHONY: install dev test lint format clean help run run-api run-api-debug run-remote remote-attach remote-stop \
       bump-patch bump-minor bump-major release version tunnel serve serve-bg serve-stop \
       check-deps setup-claude setup-opencode

# Default target
help:
	@echo "Available commands:"
	@echo "  install       - Install production dependencies"
	@echo "  dev           - Install development dependencies"
	@echo "  test          - Run tests"
	@echo "  lint          - Run linting checks"
	@echo "  format        - Format code"
	@echo "  clean         - Clean up generated files"
	@echo "  run           - Run the bot"
	@echo "  run-api       - Run only the OpenAI-compatible API server"
	@echo "  run-api-debug - Run API server with debug logging"
	@echo "  tunnel        - Expose API server via cloudflared (TUNNEL_PORT=8080)"
	@echo "  serve         - Run bot + API server + cloudflared tunnel together"
	@echo "  serve-bg      - Start serve detached (no attach) — for systemd/autostart"
	@echo "  serve-stop    - Stop the serve tmux session"
	@echo "  (tmux session: $(SESSION_NAME))"
	@echo "  version       - Show current version"
	@echo "  bump-patch    - Bump patch version (1.2.0 -> 1.2.1), commit, and tag"
	@echo "  bump-minor    - Bump minor version (1.2.0 -> 1.3.0), commit, and tag"
	@echo "  bump-major    - Bump major version (1.2.0 -> 2.0.0), commit, and tag"
	@echo "  release       - Push current version tag to trigger release workflow"
	@echo "  check-deps    - Verify Node.js, Claude Code, and OpenCode CLIs"
	@echo "  setup-claude  - Install Claude Code CLI via npm"
	@echo "  setup-opencode - Install OpenCode CLI via npm"
	@echo "  run-remote    - Start bot in tmux on remote Mac (unlocks keychain)"
	@echo "  remote-attach - Attach to running bot tmux session"
	@echo "  remote-stop   - Stop the bot tmux session"

install:
	uv sync --no-dev

dev:
	uv sync
	uv run pre-commit install --install-hooks || echo "pre-commit not configured yet"
	@$(MAKE) check-deps

check-deps:  ## Verify Node.js and backend CLIs are available
	@echo "--- Dependency check ---"
	@command -v node >/dev/null 2>&1 \
		&& echo "  node:     $$(node --version)" \
		|| echo "  node:     MISSING — install Node.js >= 18 (https://nodejs.org)"
	@command -v claude >/dev/null 2>&1 \
		&& echo "  claude:   $$(claude --version 2>/dev/null || echo 'installed')" \
		|| echo "  claude:   not installed (run: make setup-claude)"
	@command -v opencode >/dev/null 2>&1 \
		&& echo "  opencode: $$(opencode --version 2>/dev/null || echo 'installed')" \
		|| echo "  opencode: not installed (run: make setup-opencode)"
	@echo "--- Backend: $${BACKEND:-claude} ---"

setup-claude:  ## Install Claude Code CLI globally via npm
	npm install -g @anthropic-ai/claude-code

setup-opencode:  ## Install OpenCode CLI globally via npm
	npm install -g opencode-ai

test:
	uv run pytest

lint:
	uv run black --check src tests
	uv run isort --check-only src tests
	uv run flake8 src tests
	uv run mypy src

format:
	uv run black src tests
	uv run isort src tests

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -rf .coverage htmlcov/ .pytest_cache/ dist/ build/

run:
	env -u CLAUDECODE uv run sage-is-agent-bot

# For debugging
run-debug:
	env -u CLAUDECODE uv run sage-is-agent-bot --debug

# API-only mode (no Telegram)
run-api:
	uv run claude-api-server

run-api-debug:
	uv run claude-api-server --debug

# Remote (SSH session)
run-remote:  ## Start bot on remote in tmux (persists after SSH disconnect)
	security unlock-keychain ~/Library/Keychains/login.keychain-db
	tmux new-session -d -s claude-bot 'uv run sage-is-agent-bot'
	@echo "Bot started in tmux session 'claude-bot'"
	@echo "  Attach: make remote-attach"
	@echo "  Stop:   make remote-stop"

remote-attach:  ## Attach to running bot tmux session
	tmux attach -t claude-bot

remote-stop:  ## Stop the bot tmux session
	tmux kill-session -t claude-bot

# --- Tunnel / Serve ---

# Port the API server listens on — must match API_SERVER_PORT in .env
TUNNEL_PORT ?= $(shell grep -E '^API_SERVER_PORT=' .env 2>/dev/null | cut -d= -f2 | tr -d ' ' || echo 8080)
TUNNEL_PORT := $(if $(TUNNEL_PORT),$(TUNNEL_PORT),8080)

# Backend selection from .env (claude or opencode)
BACKEND ?= $(shell grep -E '^BACKEND=' .env 2>/dev/null | cut -d= -f2 | tr -d ' ' || echo claude)
BACKEND := $(if $(BACKEND),$(BACKEND),claude)

# OpenCode server port from .env
OPENCODE_PORT ?= $(shell grep -E '^OPENCODE_SERVER_PORT=' .env 2>/dev/null | cut -d= -f2 | tr -d ' ' || echo 4096)
OPENCODE_PORT := $(if $(OPENCODE_PORT),$(OPENCODE_PORT),4096)

# Approved directory from .env — OpenCode server must start here for sandboxing
APPROVED_DIR ?= $(shell grep -E '^APPROVED_DIRECTORY=' .env 2>/dev/null | cut -d= -f2 | tr -d ' ')
APPROVED_DIR := $(if $(APPROVED_DIR),$(APPROVED_DIR),$(CURDIR))

# Tmux session name — derived from directory so sibling deployments don't collide
SESSION_NAME := serve-$(notdir $(CURDIR))

# Named tunnel ID from .env — when set, serve via a stable named tunnel
# (dedicated hostname like bot9000.sage.is) instead of a random quick tunnel
TUNNEL_ID ?= $(shell grep -E '^TUNNEL_ID=' .env 2>/dev/null | cut -d= -f2 | tr -d ' ')
TUNNEL_ID := $(if $(TUNNEL_ID),$(TUNNEL_ID),)
ifeq ($(strip $(TUNNEL_ID)),)
TUNNEL_CMD = cloudflared tunnel --url http://localhost:$(TUNNEL_PORT)
else
TUNNEL_CMD = cloudflared tunnel run --url http://localhost:$(TUNNEL_PORT) $(TUNNEL_ID)
endif

tunnel:  ## Expose the API server to the web via cloudflared
	@if [ -f .env ] && grep -q '^WEBHOOK_API_SECRET=.\+' .env; then \
		echo "API key is set — bearer auth will be enforced."; \
		echo "Clients must send: Authorization: Bearer <WEBHOOK_API_SECRET>"; \
	else \
		echo "WARNING: WEBHOOK_API_SECRET is not set in .env"; \
		echo "The API will be open to anyone with the tunnel URL!"; \
		echo "Generate one with: openssl rand -hex 32"; \
	fi
	$(TUNNEL_CMD)

serve:  ## Run bot + API + tunnel (+ opencode server if BACKEND=opencode)
	@if [ -f .env ] && grep -q '^WEBHOOK_API_SECRET=.\+' .env; then \
		echo "API key is set — bearer auth will be enforced."; \
	else \
		echo "WARNING: WEBHOOK_API_SECRET is not set in .env"; \
		echo "The API will be open to anyone with the tunnel URL!"; \
		echo "Generate one with: openssl rand -hex 32"; \
	fi
	@if tmux has-session -t $(SESSION_NAME) 2>/dev/null; then \
		echo "Killing existing '$(SESSION_NAME)' tmux session..."; \
		tmux kill-session -t $(SESSION_NAME); \
	fi
	@echo "Starting $(SESSION_NAME): backend=$(BACKEND) bot + api (port $(TUNNEL_PORT)) + tunnel"
	@if [ -n "$$TMUX" ]; then \
		echo "Inside tmux — creating new '$(SESSION_NAME)' window in current session..."; \
		tmux kill-window -t $(SESSION_NAME) 2>/dev/null || true; \
		if [ "$(BACKEND)" = "opencode" ]; then \
			tmux new-window -n $(SESSION_NAME) \
				"cd $(APPROVED_DIR) && opencode serve --port $(OPENCODE_PORT); echo '--- opencode exited, press enter to close ---'; read"; \
			tmux split-window -v -t $(SESSION_NAME) \
				"env -u CLAUDECODE uv run sage-is-agent-bot; echo '--- bot exited, press enter to close ---'; read"; \
		else \
			tmux new-window -n $(SESSION_NAME) \
				"env -u CLAUDECODE uv run sage-is-agent-bot; echo '--- bot exited, press enter to close ---'; read"; \
		fi; \
		tmux split-window -v -t $(SESSION_NAME) \
			"uv run claude-api-server; echo '--- api exited, press enter to close ---'; read"; \
		tmux split-window -h -t $(SESSION_NAME) \
			"$(TUNNEL_CMD); echo '--- tunnel exited, press enter to close ---'; read"; \
		tmux select-layout -t $(SESSION_NAME) main-horizontal; \
		tmux select-pane -t $(SESSION_NAME).0; \
	else \
		$(MAKE) serve-bg; \
		tmux attach -t $(SESSION_NAME); \
	fi

serve-bg:  ## Start serve detached (+ opencode server if BACKEND=opencode)
	@if tmux has-session -t $(SESSION_NAME) 2>/dev/null; then \
		echo "'$(SESSION_NAME)' session already running — use 'make serve-stop' first"; \
	else \
		echo "Starting $(SESSION_NAME) (detached): backend=$(BACKEND) bot + api (port $(TUNNEL_PORT)) + tunnel"; \
		if [ "$(BACKEND)" = "opencode" ]; then \
			tmux new-session -d -s $(SESSION_NAME) -n bot -c $(CURDIR) \
				"cd $(APPROVED_DIR) && opencode serve --port $(OPENCODE_PORT); echo '--- opencode exited, press enter to close ---'; read" \; \
				split-window -v -t $(SESSION_NAME):bot -c $(CURDIR) \
				"env -u CLAUDECODE uv run sage-is-agent-bot; echo '--- bot exited, press enter to close ---'; read" \; \
				split-window -v -t $(SESSION_NAME):bot -c $(CURDIR) \
				"uv run claude-api-server; echo '--- api exited, press enter to close ---'; read" \; \
				split-window -h -t $(SESSION_NAME):bot -c $(CURDIR) \
				"$(TUNNEL_CMD); echo '--- tunnel exited, press enter to close ---'; read" \; \
				select-layout -t $(SESSION_NAME):bot main-horizontal \; \
				select-pane -t $(SESSION_NAME):bot.0; \
		else \
			tmux new-session -d -s $(SESSION_NAME) -n bot -c $(CURDIR) \
				"env -u CLAUDECODE uv run sage-is-agent-bot; echo '--- bot exited, press enter to close ---'; read" \; \
				split-window -v -t $(SESSION_NAME):bot -c $(CURDIR) \
				"uv run claude-api-server; echo '--- api exited, press enter to close ---'; read" \; \
				split-window -h -t $(SESSION_NAME):bot -c $(CURDIR) \
				"$(TUNNEL_CMD); echo '--- tunnel exited, press enter to close ---'; read" \; \
				select-layout -t $(SESSION_NAME):bot main-horizontal \; \
				select-pane -t $(SESSION_NAME):bot.0; \
		fi; \
		echo "Attach anytime with: tmux attach -t $(SESSION_NAME)"; \
	fi

serve-stop:  ## Stop the serve tmux session
	@tmux kill-session -t $(SESSION_NAME) 2>/dev/null && echo "'$(SESSION_NAME)' session stopped" || echo "No '$(SESSION_NAME)' session running"

# --- Version Management ---

version:  ## Show current version
	@uv version --short

bump-patch:  ## Bump patch version, commit, and tag
	uv version --bump patch && \
	NEW_VERSION=$$(uv version --short) && \
	git add pyproject.toml && \
	git commit -m "release: v$$NEW_VERSION" && \
	git tag "v$$NEW_VERSION" && \
	git push && git push origin "v$$NEW_VERSION" && \
	echo "Released v$$NEW_VERSION. Tag pushed — release workflow will run on GitHub."

bump-minor:  ## Bump minor version, commit, and tag
	uv version --bump minor && \
	NEW_VERSION=$$(uv version --short) && \
	git add pyproject.toml && \
	git commit -m "release: v$$NEW_VERSION" && \
	git tag "v$$NEW_VERSION" && \
	git push && git push origin "v$$NEW_VERSION" && \
	echo "Released v$$NEW_VERSION. Tag pushed — release workflow will run on GitHub."

bump-major:  ## Bump major version, commit, and tag
	uv version --bump major && \
	NEW_VERSION=$$(uv version --short) && \
	git add pyproject.toml && \
	git commit -m "release: v$$NEW_VERSION" && \
	git tag "v$$NEW_VERSION" && \
	git push && git push origin "v$$NEW_VERSION" && \
	echo "Released v$$NEW_VERSION. Tag pushed — release workflow will run on GitHub."

release:  ## Push the current version tag to trigger the release workflow
	CURRENT_VERSION=$$(uv version --short) && \
	git push && git push origin "v$$CURRENT_VERSION" && \
	echo "Pushed v$$CURRENT_VERSION. Release workflow will run on GitHub."
