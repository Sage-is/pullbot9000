"""OpenAI-compatible /v1/chat/completions endpoint.

Allows any OpenAI client (curl, Python openai library, IDEs) to talk to the
same Claude Code backend used by the Telegram bot.
"""

import asyncio
import re
import time
import uuid
from typing import Any, AsyncIterator, List, Optional

import structlog
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..claude.facade import ClaudeIntegration
from ..claude.sdk_integration import StreamUpdate
from ..config.settings import Settings

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------


class ChatMessage(BaseModel):
    """A single message in the conversation."""

    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    """OpenAI-compatible chat completion request."""

    model: str = "claude-sonnet-4-20250514"
    messages: List[ChatMessage] = Field(..., min_length=1)
    stream: bool = False
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None


class ChoiceMessage(BaseModel):
    """Message inside a non-streaming choice."""

    role: str = "assistant"
    content: str


class Choice(BaseModel):
    """A single completion choice."""

    index: int = 0
    message: ChoiceMessage
    finish_reason: str = "stop"


class Usage(BaseModel):
    """Token usage (best-effort; not always available from SDK)."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatCompletionResponse(BaseModel):
    """OpenAI-compatible chat completion response."""

    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[Choice]
    usage: Usage = Field(default_factory=Usage)


class DeltaContent(BaseModel):
    """Delta content in a streaming chunk."""

    role: Optional[str] = None
    content: Optional[str] = None
    reasoning_content: Optional[str] = None


class StreamChoice(BaseModel):
    """A single streaming choice."""

    index: int = 0
    delta: DeltaContent
    finish_reason: Optional[str] = None


class ChatCompletionChunk(BaseModel):
    """OpenAI-compatible streaming chunk."""

    id: str
    object: str = "chat.completion.chunk"
    created: int
    model: str
    choices: List[StreamChoice]


class ModelInfo(BaseModel):
    """Model metadata for /v1/models."""

    id: str
    object: str = "model"
    created: int = 0
    owned_by: str = "anthropic"


class ModelListResponse(BaseModel):
    """Response for GET /v1/models."""

    object: str = "list"
    data: List[ModelInfo]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_THINKING_RE = re.compile(r"<thinking>(.*?)</thinking>\n?", re.DOTALL)


def _extract_thinking(text: str) -> tuple[list[str], str]:
    """Separate thinking blocks from text content.

    Returns (thinking_parts, stripped_text) where thinking_parts is a list
    of the raw thinking content (without tags) and stripped_text is the
    remaining text with thinking blocks removed.
    """
    thinking_parts = _THINKING_RE.findall(text)
    stripped = _THINKING_RE.sub("", text).strip()
    return thinking_parts, stripped


def _extract_prompt(messages: List[ChatMessage]) -> str:
    """Extract the prompt to send to Claude from the message list.

    Uses the last user message.  If the conversation has system/assistant
    context we prepend it so Claude has the full picture.
    """
    # Build context from all messages except the last user message
    last_user_idx = None
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].role == "user":
            last_user_idx = i
            break

    if last_user_idx is None:
        raise HTTPException(
            status_code=400, detail="messages must contain at least one user message"
        )

    # If there's only one message and it's the user's, return it directly
    if len(messages) == 1:
        return messages[0].content

    # Build context from preceding messages
    context_parts: List[str] = []
    for msg in messages[:last_user_idx]:
        if msg.role == "system":
            context_parts.append(f"[System]: {msg.content}")
        elif msg.role == "assistant":
            context_parts.append(f"[Assistant]: {msg.content}")
        elif msg.role == "user":
            context_parts.append(f"[User]: {msg.content}")

    user_prompt = messages[last_user_idx].content

    if context_parts:
        context = "\n".join(context_parts)
        return f"{context}\n\n[User]: {user_prompt}"

    return user_prompt


def _verify_bearer_token(
    authorization: Optional[str], expected_secret: Optional[str]
) -> None:
    """Validate Bearer token.  No-op when secret is not configured."""
    if not expected_secret:
        return  # Auth disabled — local dev convenience
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or parts[1] != expected_secret:
        raise HTTPException(status_code=401, detail="Invalid bearer token")


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------


def create_openai_router(
    claude_integration: ClaudeIntegration,
    settings: Settings,
) -> APIRouter:
    """Create a FastAPI router with OpenAI-compatible endpoints."""

    router = APIRouter()

    # ------------------------------------------------------------------
    # POST /v1/chat/completions
    # ------------------------------------------------------------------
    @router.post("/v1/chat/completions")
    async def chat_completions(
        request: ChatCompletionRequest,
        authorization: Optional[str] = Header(None),
    ) -> Any:
        _verify_bearer_token(authorization, settings.webhook_api_secret)

        prompt = _extract_prompt(request.messages)
        completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"

        if request.stream:
            return StreamingResponse(
                _stream_response(
                    prompt=prompt,
                    completion_id=completion_id,
                    model=request.model,
                    claude_integration=claude_integration,
                    settings=settings,
                ),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )

        # --- Non-streaming path ---
        response = await claude_integration.run_command(
            prompt=prompt,
            working_directory=settings.approved_directory,
            user_id=0,
        )

        return ChatCompletionResponse(
            id=completion_id,
            created=int(time.time()),
            model=request.model,
            choices=[
                Choice(
                    message=ChoiceMessage(
                        content=_extract_thinking(response.content)[1]
                    ),
                    finish_reason="stop",
                )
            ],
            usage=Usage(),
        )

    # ------------------------------------------------------------------
    # GET /v1/models
    # ------------------------------------------------------------------
    @router.get("/v1/models")
    async def list_models(
        authorization: Optional[str] = Header(None),
    ) -> ModelListResponse:
        _verify_bearer_token(authorization, settings.webhook_api_secret)
        return ModelListResponse(
            data=[
                ModelInfo(id=settings.claude_model),
            ]
        )

    return router


# ---------------------------------------------------------------------------
# Streaming helper
# ---------------------------------------------------------------------------


async def _stream_response(
    prompt: str,
    completion_id: str,
    model: str,
    claude_integration: ClaudeIntegration,
    settings: Settings,
) -> AsyncIterator[str]:
    """Bridge Claude's push-based streaming to SSE chunks."""

    queue: asyncio.Queue[Optional[StreamUpdate]] = asyncio.Queue()

    def on_stream(update: StreamUpdate) -> None:
        queue.put_nowait(update)

    task = asyncio.create_task(
        claude_integration.run_command(
            prompt=prompt,
            working_directory=settings.approved_directory,
            user_id=0,
            on_stream=on_stream,
        )
    )

    created = int(time.time())

    # Emit initial chunk with role
    initial_chunk = ChatCompletionChunk(
        id=completion_id,
        created=created,
        model=model,
        choices=[
            StreamChoice(delta=DeltaContent(role="assistant")),
        ],
    )
    yield f"data: {initial_chunk.model_dump_json(exclude_none=True)}\n\n"

    # Deduplication state for delta-only streaming.
    # The SDK may emit the same AssistantMessage content in multiple raw
    # events, and each StreamUpdate contains the full text of that message
    # (not an incremental delta).  We track everything we've yielded so far
    # (`total_sent_text`) plus a set of exact content strings we've seen
    # (`seen_exact`) so we never send the same text twice.
    #
    # Thinking blocks are always separated from text for delta tracking.
    # When API_STREAM_THINKING is enabled they are emitted as their own
    # chunks (wrapped in <thinking> tags); otherwise they are dropped.
    total_sent_text = ""
    seen_exact: set[str] = set()
    seen_thinking: set[str] = set()
    stream_thinking = settings.api_stream_thinking

    def _make_chunk(
        content: Optional[str] = None,
        reasoning_content: Optional[str] = None,
    ) -> str:
        """Format a content delta as an SSE chunk."""
        c = ChatCompletionChunk(
            id=completion_id,
            created=created,
            model=model,
            choices=[
                StreamChoice(
                    delta=DeltaContent(
                        content=content,
                        reasoning_content=reasoning_content,
                    )
                ),
            ],
        )
        return f"data: {c.model_dump_json(exclude_none=True)}\n\n"

    try:
        while True:
            try:
                update = await asyncio.wait_for(queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                if task.done():
                    break
                continue

            if update is None:
                break

            if update.type == "assistant" and update.content:
                raw_content = update.content
                thinking_parts, text_only = _extract_thinking(raw_content)

                logger.debug(
                    "stream_update_received",
                    raw_len=len(raw_content),
                    raw_preview=raw_content[:200],
                    thinking_count=len(thinking_parts),
                    text_only_preview=text_only[:200] if text_only else "",
                    total_sent_len=len(total_sent_text),
                )

                # --- Thinking: emit via both reasoning_content and
                # <think> tags in content for broad client compat ---
                if stream_thinking:
                    for thought in thinking_parts:
                        if thought not in seen_thinking:
                            seen_thinking.add(thought)
                            yield _make_chunk(
                                content=f"<think>{thought}</think>\n",
                                reasoning_content=thought,
                            )

                if not text_only:
                    continue  # Nothing left after stripping thinking

                # --- Text deduplication ---
                delta_text = ""
                if text_only in seen_exact:
                    logger.debug("stream_skip_exact_dup", text=text_only[:100])
                elif text_only.startswith(total_sent_text):
                    delta_text = text_only[len(total_sent_text) :]
                    total_sent_text = text_only
                    seen_exact.add(text_only)
                elif total_sent_text and text_only in total_sent_text:
                    logger.debug(
                        "stream_skip_substring", text=text_only[:100]
                    )
                else:
                    delta_text = (
                        ("\n" + text_only) if total_sent_text else text_only
                    )
                    total_sent_text += delta_text
                    seen_exact.add(text_only)

                if delta_text:
                    logger.debug(
                        "stream_yielding_delta",
                        delta_len=len(delta_text),
                        delta_preview=delta_text[:200],
                    )
                    yield _make_chunk(content=delta_text)

    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        else:
            # Propagate any exception from the task
            exc = task.exception()
            if exc is not None:
                logger.error(
                    "Claude streaming task failed",
                    error=str(exc),
                )

    # Final chunk with finish_reason
    final_chunk = ChatCompletionChunk(
        id=completion_id,
        created=created,
        model=model,
        choices=[
            StreamChoice(
                delta=DeltaContent(),
                finish_reason="stop",
            ),
        ],
    )
    yield f"data: {final_chunk.model_dump_json(exclude_none=True)}\n\n"
    yield "data: [DONE]\n\n"
