"""Tests for OpenCodeManager — HTTP client for the OpenCode backend."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.backend.exceptions import ClaudeProcessError, ClaudeTimeoutError
from src.backend.opencode_integration import OpenCodeManager
from src.backend.sdk_integration import ClaudeResponse
from src.config.settings import Settings


def _make_config(tmp_path: Path, **overrides: Any) -> Settings:
    defaults = dict(
        telegram_bot_token="test:token",
        telegram_bot_username="testbot",
        approved_directory=str(tmp_path),
        backend="opencode",
        opencode_server_port=14096,
        opencode_server_host="127.0.0.1",
    )
    defaults.update(overrides)
    return Settings(**defaults)


def _sse_lines(events: List[Dict[str, Any]], done: bool = True) -> str:
    """Build a raw SSE response body from a list of event dicts."""
    lines = []
    for ev in events:
        lines.append(f"data: {json.dumps(ev)}\n\n")
    if done:
        lines.append("data: [DONE]\n\n")
    return "".join(lines)


def _session_response(session_id: str = "oc-session-1") -> httpx.Response:
    return httpx.Response(
        200,
        json={"id": session_id},
    )


def _message_accepted() -> httpx.Response:
    return httpx.Response(202, json={"ok": True})


class TestOpenCodeManagerInit:

    def test_default_base_url(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        mgr = OpenCodeManager(config)
        assert mgr._base_url == "http://127.0.0.1:14096"

    def test_custom_base_url(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        mgr = OpenCodeManager(config, base_url="http://other:9999")
        assert mgr._base_url == "http://other:9999"

    def test_auth_set_when_password_configured(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path, opencode_server_password="secret")
        mgr = OpenCodeManager(config)
        assert mgr._auth is not None

    def test_no_auth_without_password(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        mgr = OpenCodeManager(config)
        assert mgr._auth is None


class TestGetOrCreateSession:

    async def test_creates_new_session(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        mgr = OpenCodeManager(config)

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=_session_response("new-123"))

        session_id = await mgr._get_or_create_session(
            mock_client, session_id=None, continue_session=False
        )
        assert session_id == "new-123"
        mock_client.post.assert_called_once_with("/session", json={})

    async def test_forks_from_parent(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        mgr = OpenCodeManager(config)

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=_session_response("fork-456"))

        session_id = await mgr._get_or_create_session(
            mock_client, session_id="parent-789", continue_session=True
        )
        assert session_id == "fork-456"
        mock_client.post.assert_called_once_with(
            "/session", json={"parentID": "parent-789"}
        )

    async def test_raises_on_error_status(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        mgr = OpenCodeManager(config)

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )

        with pytest.raises(ClaudeProcessError, match="500"):
            await mgr._get_or_create_session(
                mock_client, session_id=None, continue_session=False
            )

    async def test_raises_on_missing_id(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        mgr = OpenCodeManager(config)

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            return_value=httpx.Response(200, json={"status": "ok"})
        )

        with pytest.raises(ClaudeProcessError, match="missing ID"):
            await mgr._get_or_create_session(
                mock_client, session_id=None, continue_session=False
            )


class TestProcessEvent:

    def setup_method(self, tmp_path: Path = Path("/tmp")) -> None:
        self.working_dir = Path("/tmp/project")

    def test_content_delta(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        mgr = OpenCodeManager(config)
        finished, text, tool, cost = mgr._process_event(
            "content.delta",
            {"properties": {"delta": "Hello world"}},
            self.working_dir,
        )
        assert not finished
        assert text == "Hello world"
        assert tool is None
        assert cost is None

    def test_content_done_not_finished(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        mgr = OpenCodeManager(config)
        finished, text, tool, cost = mgr._process_event(
            "content.done", {}, self.working_dir
        )
        assert not finished

    def test_tool_use_start(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        mgr = OpenCodeManager(config)
        finished, text, tool, cost = mgr._process_event(
            "tool_use.start",
            {
                "properties": {
                    "name": "Grep",
                    "input": {"pattern": "foo"},
                    "id": "tool-1",
                }
            },
            self.working_dir,
        )
        assert not finished
        assert tool is not None
        assert tool["name"] == "Grep"
        assert tool["id"] == "tool-1"

    def test_thinking_delta(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        mgr = OpenCodeManager(config)
        finished, text, tool, cost = mgr._process_event(
            "thinking.delta",
            {"properties": {"delta": "Let me think..."}},
            self.working_dir,
        )
        assert not finished
        assert text == "<thinking>Let me think...</thinking>"

    def test_message_complete(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        mgr = OpenCodeManager(config)
        finished, text, tool, cost = mgr._process_event(
            "message.complete",
            {"properties": {"cost": 0.05, "result": "Done."}},
            self.working_dir,
        )
        assert finished
        assert text == "Done."
        assert cost == 0.05

    def test_result_event(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        mgr = OpenCodeManager(config)
        finished, text, tool, cost = mgr._process_event(
            "result",
            {"properties": {"total_cost_usd": 0.12, "text": "Final answer"}},
            self.working_dir,
        )
        assert finished
        assert text == "Final answer"
        assert cost == 0.12

    def test_error_event_raises(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        mgr = OpenCodeManager(config)
        with pytest.raises(ClaudeProcessError, match="Something broke"):
            mgr._process_event(
                "error",
                {"properties": {"message": "Something broke"}},
                self.working_dir,
            )


class TestValidateTool:

    def test_no_validator_passes(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        mgr = OpenCodeManager(config, security_validator=None)
        mgr._validate_tool("Write", {"file_path": "/etc/passwd"}, tmp_path)

    def test_file_tool_outside_approved_dir_blocked(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        validator = MagicMock()
        validator.validate_path.return_value = (False, None, "path outside approved dir")
        mgr = OpenCodeManager(config, security_validator=validator)

        with pytest.raises(ClaudeProcessError, match="denied"):
            mgr._validate_tool(
                "Write", {"file_path": "/etc/passwd"}, tmp_path
            )

    def test_file_tool_inside_approved_dir_passes(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        validator = MagicMock()
        validator.validate_path.return_value = (True, tmp_path / "file.py", None)
        mgr = OpenCodeManager(config, security_validator=validator)

        mgr._validate_tool(
            "Edit", {"file_path": str(tmp_path / "file.py")}, tmp_path
        )

    def test_bash_tool_boundary_violation_blocked(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        validator = MagicMock()
        mgr = OpenCodeManager(config, security_validator=validator)

        with patch(
            "src.backend.opencode_integration.check_bash_directory_boundary",
            return_value=(False, "directory boundary violation: /tmp/evil"),
        ):
            with pytest.raises(ClaudeProcessError, match="denied"):
                mgr._validate_tool(
                    "Bash", {"command": "rm /tmp/evil"}, tmp_path
                )

    def test_bash_tool_inside_boundary_passes(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        validator = MagicMock()
        mgr = OpenCodeManager(config, security_validator=validator)

        with patch(
            "src.backend.opencode_integration.check_bash_directory_boundary",
            return_value=(True, None),
        ):
            mgr._validate_tool(
                "Bash", {"command": "ls -la"}, tmp_path
            )

    def test_claude_internal_path_allowed(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        validator = MagicMock()
        mgr = OpenCodeManager(config, security_validator=validator)

        with patch(
            "src.backend.opencode_integration._is_claude_internal_path",
            return_value=True,
        ):
            mgr._validate_tool(
                "Read",
                {"file_path": str(tmp_path / ".claude/plans/plan.md")},
                tmp_path,
            )
            validator.validate_path.assert_not_called()


class TestExecuteCommand:

    async def test_returns_claude_response(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        mgr = OpenCodeManager(config)

        with patch.object(
            mgr,
            "_get_or_create_session",
            return_value="oc-session-1",
        ), patch.object(
            mgr,
            "_send_and_stream",
            return_value=("Hello from OpenCode", [], 0.03, 2),
        ):
            result = await mgr.execute_command(
                prompt="say hello",
                working_directory=tmp_path,
                session_id=None,
            )

        assert isinstance(result, ClaudeResponse)
        assert result.content == "Hello from OpenCode"
        assert result.session_id == "oc-session-1"
        assert result.cost == 0.03
        assert result.num_turns == 2

    async def test_timeout_raises_claude_timeout_error(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        mgr = OpenCodeManager(config)

        with patch.object(
            mgr, "_client"
        ) as mock_client_ctx:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(side_effect=httpx.TimeoutException("read timeout"))
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_ctx.return_value = mock_client

            with pytest.raises(ClaudeTimeoutError, match="timed out"):
                await mgr.execute_command(
                    prompt="slow query",
                    working_directory=tmp_path,
                )

    async def test_connect_error_raises_process_error(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        mgr = OpenCodeManager(config)

        with patch.object(
            mgr, "_client"
        ) as mock_client_ctx:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(
                side_effect=httpx.ConnectError("connection refused")
            )
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_ctx.return_value = mock_client

            with pytest.raises(ClaudeProcessError, match="Cannot connect"):
                await mgr.execute_command(
                    prompt="hello",
                    working_directory=tmp_path,
                )

    async def test_stream_callback_invoked(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        mgr = OpenCodeManager(config)
        callback = AsyncMock()

        with patch.object(
            mgr,
            "_get_or_create_session",
            return_value="oc-session-1",
        ), patch.object(
            mgr,
            "_send_and_stream",
            return_value=("response", [], 0.01, 1),
        ) as mock_stream:
            await mgr.execute_command(
                prompt="hello",
                working_directory=tmp_path,
                stream_callback=callback,
            )
            _, kwargs = mock_stream.call_args
            assert "stream_callback" in kwargs or callback in mock_stream.call_args[0]

    async def test_active_process_count_always_zero(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        mgr = OpenCodeManager(config)
        assert mgr.get_active_process_count() == 0
