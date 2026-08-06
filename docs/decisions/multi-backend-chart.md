# Multi-Backend Agent Harness — Chart

## Destination

Generalize the backend facade so adding a new agent harness is mechanical: write one
manager module, add one config value. Curated set of supported backends, each with its
own manager class behind `ClaudeIntegration` (or a renamed facade). No dynamic plugin
discovery — each backend is a known module wired through config.

Target harnesses beyond the existing two (Claude Code, OpenCode):
- **Pi** (Inflection) — conversational AI agent
- **Hermes** (Nous Research) — open-weight model family, needs agent wrapper
- **Downes** (Sage-is) — autonomous education agent, Python SDK + WebSocket

## Notes

Domain: Telegram bot, multiple AI backends, Sage.is platform.
Depends on: `feature/opencode-backend` (the toggle pattern this generalizes).
The existing `BACKEND` enum in `settings.py` grows per harness.
Current facade: `ClaudeIntegration` in `src/backend/facade.py`.

## In Progress

## TODO

- [ ] **Backend interface contract**: Define the abstract base class / protocol that every manager must implement. What methods? What return types? What lifecycle hooks (start/stop/health)? #task
- [ ] **Configuration pattern**: Per-backend settings without bloating `Settings`. Nested models? Prefixed env vars? Separate config classes? #task
- [ ] **Facade rename**: `ClaudeIntegration` no longer fits. Name the backend-neutral facade. #task
- [ ] **Pi integration surface** *(research)*: How does Pi expose agent capabilities? HTTP API? SDK? What's the consumer interface? #task
- [ ] **Hermes integration surface** *(research)*: Hermes is a model family, not an agent harness. What wraps it into an agent (LangChain? custom?)? What interface does that expose? #task
- [ ] **Downes manager**: Wrap `downes.agent.Agent` Python SDK as a backend manager. Map `execute_command()` to `Agent.run()`. Handle the multi-agent output (planning/action/validation/answer). #task

## Backlog

- Capability negotiation — not all backends support all features (tool use, streaming, session resume). How to degrade gracefully?
- Backend-specific tool mapping — each harness has different tool concepts. Normalize or pass through?
- Per-user backend routing — route different users or projects to different backends?
- Testing strategy — contract tests that validate any manager against the interface?
- Backend health dashboard — surface per-backend status in `/status` command?

## Out of scope

## Done
