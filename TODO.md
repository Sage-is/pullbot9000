# OpenAI API Streaming Improvements

- [x] **Delta-only streaming** — Track previously sent content and only yield the new suffix in each SSE chunk. Currently each `StreamUpdate` contains the full assistant message text, but OpenAI clients expect incremental deltas and concatenate them, causing duplicated/ballooning text. Fix in `_stream_response` by diffing against `sent_content`.

- [ ] **Keep-alive comments during tool execution** — Send SSE comments (`: keepalive\n\n`) when no assistant text has been emitted for several seconds (e.g. while Claude runs bash commands or reads files). Prevents proxy and client timeouts without producing data events.

- [ ] **Tool call streaming** — Stream `tool_calls` in deltas following the OpenAI format (function name chunk, then argument chunks). Currently tool calls from `StreamUpdate` are silently dropped at the `if update.type == "assistant" and update.content` check. Clients using function calling get nothing until the final response.

- [ ] **Streaming error events** — If the Claude task fails mid-stream, emit a chunk with `finish_reason: "error"` or an SSE error event so clients can surface meaningful errors instead of seeing a silent truncation.

- [ ] **Usage in final chunk** — Support `stream_options: {"include_usage": true}` and forward token counts from the SDK's `ResultMessage` in the last chunk.

- [ ] **`stop` vs `length` finish reason** — Set `finish_reason` to `"length"` when the response was truncated due to max tokens, rather than always returning `"stop"`.
