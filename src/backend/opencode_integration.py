"""OpenCode HTTP API integration.

Drop-in replacement for ClaudeSDKManager. Calls the OpenCode server's
REST + SSE API instead of the Claude Agent SDK.
"""

import asyncio
import json
import time
from dataclasses import field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import httpx
import structlog

from ..config.settings import Settings
from ..security.validators import SecurityValidator
from .exceptions import (
    ClaudeParsingError,
    ClaudeProcessError,
    ClaudeTimeoutError,
)
from .monitor import _is_claude_internal_path, check_bash_directory_boundary
from .sdk_integration import ClaudeResponse, StreamUpdate

logger = structlog.get_logger()

_FILE_TOOLS = {"Write", "Edit", "Read", "create_file", "edit_file", "read_file"}
_BASH_TOOLS = {"Bash", "bash", "shell"}


class OpenCodeManager:
    """Manage OpenCode HTTP API integration.

    Same execute_command() interface as ClaudeSDKManager so the facade
    can swap between them.
    """

    def __init__(
        self,
        config: Settings,
        security_validator: Optional[SecurityValidator] = None,
        base_url: Optional[str] = None,
    ):
        self.config = config
        self.security_validator = security_validator
        self._base_url = (
            base_url
            or f"http://{config.opencode_server_host}:{config.opencode_server_port}"
        )
        self._auth: Optional[httpx.BasicAuth] = None
        if config.opencode_server_password:
            self._auth = httpx.BasicAuth("opencode", config.opencode_server_password)

    def _client(self, timeout: float = 30.0) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base_url,
            auth=self._auth,
            timeout=timeout,
        )

    async def execute_command(
        self,
        prompt: str,
        working_directory: Path,
        session_id: Optional[str] = None,
        continue_session: bool = False,
        stream_callback: Optional[Callable[[StreamUpdate], None]] = None,
    ) -> ClaudeResponse:
        """Execute a prompt via the OpenCode HTTP API."""
        start_time = time.monotonic()

        logger.info(
            "Starting OpenCode command",
            working_directory=str(working_directory),
            session_id=session_id,
            continue_session=continue_session,
        )

        try:
            async with self._client(
                timeout=float(self.config.claude_timeout_seconds)
            ) as client:
                oc_session_id = await self._get_or_create_session(
                    client, session_id, continue_session
                )

                content, tools_used, total_cost, num_turns = (
                    await self._send_and_stream(
                        client,
                        oc_session_id,
                        prompt,
                        working_directory,
                        stream_callback,
                    )
                )

                duration_ms = int((time.monotonic() - start_time) * 1000)

                return ClaudeResponse(
                    content=content,
                    session_id=oc_session_id,
                    cost=total_cost,
                    duration_ms=duration_ms,
                    num_turns=num_turns,
                    tools_used=tools_used,
                )

        except httpx.TimeoutException:
            raise ClaudeTimeoutError(
                f"OpenCode timed out after {self.config.claude_timeout_seconds}s"
            )
        except httpx.ConnectError as e:
            raise ClaudeProcessError(
                f"Cannot connect to OpenCode server at {self._base_url}: {e}"
            )
        except (ClaudeTimeoutError, ClaudeProcessError, ClaudeParsingError):
            raise
        except Exception as e:
            logger.error(
                "Unexpected OpenCode error",
                error=str(e),
                error_type=type(e).__name__,
            )
            raise ClaudeProcessError(f"OpenCode error: {e}")

    async def _get_or_create_session(
        self,
        client: httpx.AsyncClient,
        session_id: Optional[str],
        continue_session: bool,
    ) -> str:
        """Create a new session or fork from an existing one."""
        body: Dict[str, Any] = {}

        if session_id and continue_session:
            body["parentID"] = session_id
            logger.info("Forking from parent session", parent_id=session_id)

        resp = await client.post("/session", json=body)

        if resp.status_code not in (200, 201):
            raise ClaudeProcessError(
                f"Failed to create OpenCode session: {resp.status_code} {resp.text}"
            )

        data = resp.json()
        new_id = data.get("id") or data.get("sessionId") or data.get("session_id", "")
        if not new_id:
            raise ClaudeProcessError(
                f"OpenCode session response missing ID: {data}"
            )

        logger.info("OpenCode session ready", session_id=new_id)
        return new_id

    async def _send_and_stream(
        self,
        client: httpx.AsyncClient,
        session_id: str,
        prompt: str,
        working_directory: Path,
        stream_callback: Optional[Callable[[StreamUpdate], None]],
    ) -> tuple:
        """Send prompt and stream progress via SSE.

        Subscribes to /api/event SSE for real-time progress while the
        blocking POST /session/{id}/message runs concurrently.  The SSE
        listener fires stream_callback with tool and text events as they
        arrive — giving Telegram users live feedback instead of silence.

        Returns (content, tools_used, total_cost, num_turns).
        """
        body: Dict[str, Any] = {
            "parts": [{"type": "text", "text": prompt}],
        }

        sse_task: Optional[asyncio.Task] = None
        if stream_callback:
            sse_task = asyncio.create_task(
                self._listen_sse(
                    session_id, working_directory, stream_callback
                )
            )
            await asyncio.sleep(0.1)

        try:
            resp = await client.post(
                f"/session/{session_id}/message",
                json=body,
            )
        finally:
            if sse_task and not sse_task.done():
                sse_task.cancel()
                try:
                    await sse_task
                except asyncio.CancelledError:
                    pass

        if resp.status_code not in (200, 201, 202):
            raise ClaudeProcessError(
                f"OpenCode message failed: {resp.status_code} {resp.text}"
            )

        data = resp.json()
        info = data.get("info", {})
        parts = data.get("parts", [])

        content_parts: List[str] = []
        tools_used: List[Dict[str, Any]] = []
        total_cost = info.get("cost", 0.0) or 0.0
        num_turns = 1

        for part in parts:
            part_type = part.get("type", "")

            if part_type == "text":
                text = part.get("text", "")
                if text:
                    content_parts.append(text)

            elif part_type == "tool-use":
                tool_name = part.get("name", "unknown")
                tool_input = part.get("input", {})
                self._validate_tool(tool_name, tool_input, working_directory)
                tools_used.append({
                    "name": tool_name,
                    "input": tool_input,
                    "id": part.get("id"),
                    "timestamp": time.monotonic(),
                })

            elif part_type == "step-finish":
                step_cost = part.get("cost")
                if step_cost:
                    total_cost = max(total_cost, step_cost)

        content = "\n".join(content_parts) if content_parts else ""

        return content, tools_used, total_cost, num_turns

    async def _listen_sse(
        self,
        session_id: str,
        working_directory: Path,
        stream_callback: Callable[[StreamUpdate], None],
    ) -> None:
        """Subscribe to /api/event SSE and fire stream_callback for
        events belonging to our session.
        """
        timeout = httpx.Timeout(
            connect=5.0,
            read=float(self.config.claude_timeout_seconds),
            write=5.0,
            pool=5.0,
        )
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url, auth=self._auth, timeout=timeout
            ) as sse_client:
                async with sse_client.stream(
                    "GET",
                    "/api/event",
                    headers={"Accept": "text/event-stream"},
                ) as response:
                    buf = ""
                    async for chunk in response.aiter_text():
                        buf += chunk
                        while "\n" in buf:
                            line, buf = buf.split("\n", 1)
                            line = line.strip()
                            if not line or line.startswith(":"):
                                continue
                            if not line.startswith("data: "):
                                continue
                            raw = line[6:]
                            await self._handle_sse_data(
                                raw,
                                session_id,
                                working_directory,
                                stream_callback,
                            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.debug("SSE listener ended", reason=str(e))

    async def _handle_sse_data(
        self,
        raw: str,
        session_id: str,
        working_directory: Path,
        stream_callback: Callable[[StreamUpdate], None],
    ) -> None:
        """Parse one SSE data line and fire callback if relevant."""
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            return

        event_data = event.get("data", {})
        if event_data.get("sessionID") != session_id:
            return

        event_type = event.get("type", "")
        finished, text, tool, cost = self._process_event(
            event_type, event_data, working_directory
        )

        if text:
            try:
                await stream_callback(
                    StreamUpdate(type="assistant", content=text)
                )
            except Exception as cb_err:
                logger.warning("Stream callback error", error=str(cb_err))

        if tool:
            try:
                await stream_callback(
                    StreamUpdate(type="assistant", content=None, tool_calls=[tool])
                )
            except Exception as cb_err:
                logger.warning("Stream callback error", error=str(cb_err))

    def _process_event(
        self,
        event_type: str,
        event_data: Dict[str, Any],
        working_directory: Path,
    ) -> tuple:
        """Process a single OpenCode SSE event.

        Event types: message.part.delta, message.part.updated,
        session.idle, session.status.

        Returns (finished, text, tool_dict, cost).
        """
        text: Optional[str] = None
        tool: Optional[Dict[str, Any]] = None
        cost: Optional[float] = None
        finished = False

        if event_type == "message.part.delta":
            delta = event_data.get("delta", "")
            if delta:
                text = delta

        elif event_type == "message.part.updated":
            part = event_data.get("part", {})
            part_type = part.get("type", "")

            if part_type == "text":
                part_text = part.get("text", "")
                if part_text:
                    text = part_text

            elif part_type == "tool-use":
                tool_name = part.get("name", "unknown")
                tool_input = part.get("input", {})
                self._validate_tool(tool_name, tool_input, working_directory)
                tool = {
                    "name": tool_name,
                    "input": tool_input,
                    "id": part.get("id"),
                    "timestamp": time.monotonic(),
                }

            elif part_type == "step-finish":
                step_cost = part.get("cost")
                if step_cost:
                    cost = step_cost

        elif event_type == "session.idle":
            finished = True

        elif event_type == "session.updated":
            info = event_data.get("info", {})
            status = info.get("status")
            if status == "idle":
                finished = True

        return finished, text, tool, cost

    def _validate_tool(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
        working_directory: Path,
    ) -> None:
        """Validate tool use against security rules.

        Raises ClaudeProcessError if validation fails.
        """
        if not self.security_validator:
            return

        if tool_name in _FILE_TOOLS:
            file_path = tool_input.get("file_path") or tool_input.get("path")
            if file_path:
                if _is_claude_internal_path(file_path):
                    return
                valid, _resolved, error = self.security_validator.validate_path(
                    file_path, working_directory
                )
                if not valid:
                    logger.warning(
                        "OpenCode tool denied: file path",
                        tool=tool_name,
                        path=file_path,
                        error=error,
                    )
                    raise ClaudeProcessError(
                        f"Tool '{tool_name}' denied: {error}"
                    )

        if tool_name in _BASH_TOOLS:
            command = tool_input.get("command", "")
            if command:
                valid, error = check_bash_directory_boundary(
                    command, working_directory, self.config.approved_directory
                )
                if not valid:
                    logger.warning(
                        "OpenCode tool denied: bash boundary",
                        tool=tool_name,
                        command=command,
                        error=error,
                    )
                    raise ClaudeProcessError(
                        f"Tool '{tool_name}' denied: {error}"
                    )

    def get_active_process_count(self) -> int:
        return 0
