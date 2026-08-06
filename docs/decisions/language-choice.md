# Language Choice

**Decision:** Python + HTTP

Keep the existing Python codebase. Call the OpenCode server's REST API directly
over HTTP + SSE on port 4096. No TypeScript SDK dependency. No hybrid sidecar.

## Rationale

- 17K lines of working Python with tests, middleware, security, and streaming.
- OpenCode server (`opencode serve`) exposes the full API over HTTP + SSE.
- The TypeScript SDK is a typed client for that same HTTP API — no exclusive features.
- Avoids a full rewrite and a second runtime.

## Implications

- Replace `claude-agent-sdk` with an HTTP client (`httpx` or `aiohttp`) targeting OpenCode's REST API.
- OpenCode server runs as a sidecar process alongside the bot.
- Session management calls go to `POST /session`, `POST /session/:id/message`.
- Streaming uses SSE from the `/event` endpoint.
- Structured output uses `format.type: "json_schema"` in prompt requests.
- No changes to Telegram integration, middleware, or storage layers.
