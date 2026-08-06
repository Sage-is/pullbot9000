# Sage.is Integration Scope

**Decision:** Bidirectional — existing OpenAI-compat API is the surface. No new integration work needed.

## Context

The bot already serves as a backend for both Telegram and Sage.is AI-UI spaces via
its OpenAI-compatible API endpoint with SSE streaming. This is working today with
Claude Code as the harness.

## Implication

The Sage.is integration is not a new feature for this fork. The fork's scope is
replacing the Claude Code harness with OpenCode. The API surface stays the same.
Sage.is spaces continue to call the same endpoint — only the engine behind it changes.
