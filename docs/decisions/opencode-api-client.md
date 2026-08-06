# OpenCode API Client — SDK-to-HTTP Mapping

## Mapping

| Pullbot (claude-agent-sdk) | OpenCode HTTP API | Notes |
|---|---|---|
| `ClaudeSDKClient(options)` | `POST /session` | Creates session. No dynamic system_prompt. |
| `client.connect()` | N/A | HTTP is stateless. |
| `client.query(prompt)` | `POST /session/:id/message` | Body: `{ parts: [{type: "text", text: prompt}] }` |
| `receive_messages()` async gen | `GET /event` (SSE) | Different event types. Parse `event.type` for content deltas, tool use, thinking, completion. |
| `client.disconnect()` | `DELETE /session/:id` | Optional cleanup. |
| `options.resume = session_id` | `POST /session` with `parentID` | Fork, not true resume. New session ID created. |
| `can_use_tool` callback | Static config in `.opencode.json` | **Gap.** No runtime callback. |
| `ResultMessage.total_cost_usd` | Aggregate from message `.cost` fields | **Gap.** Must sum manually. |
| `ResultMessage.session_id` | Response from `POST /session` | Available. |
| `ResultMessage.num_turns` | Count messages manually | **Gap.** |
| `options.allowed_tools` | `.opencode.json` tool config | Static only. |
| `options.thinking` | Server-side config | Not per-request. |
| `options.mcp_servers` | `POST /mcp` or static config | Must register before session. |
| `options.sandbox` | No HTTP equivalent | **Gap.** |
| Structured output | `format: { type: "json_schema", schema: {...} }` in prompt body | Works. |

## Gaps and Mitigations

1. **Tool permission callback** — Pullbot validates file paths and bash commands at runtime.
   OpenCode has no built-in dynamic callback over HTTP. Mitigation: implement a stream
   interceptor that watches SSE tool-use-start events and validates via SecurityValidator,
   or implement as an MCP permission server. The logic from `monitor.py` is preserved.

2. **Session resume vs fork** — Pullbot resumes sessions by ID. OpenCode forks from a parent.
   Mitigation: treat fork as resume. Map user+directory to latest session. Accept new session IDs.

3. **Aggregate metrics** — Pullbot gets cost/turns from ResultMessage. OpenCode provides per-message
   cost. Mitigation: accumulate in the Python client layer.

4. **System prompt** — Cannot set per-request. Mitigation: set once in server config or prepend
   to user prompt.
