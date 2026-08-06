"""Tests for OpenCodeServer — sidecar lifecycle manager."""

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.backend.opencode_server import OpenCodeServer, find_opencode_cli
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


class TestFindOpencodeCli:

    def test_explicit_path_valid(self, tmp_path: Path) -> None:
        fake_bin = tmp_path / "opencode"
        fake_bin.write_text("#!/bin/sh\n")
        fake_bin.chmod(0o755)
        assert find_opencode_cli(str(fake_bin)) == str(fake_bin)

    def test_explicit_path_not_executable(self, tmp_path: Path) -> None:
        fake_bin = tmp_path / "opencode"
        fake_bin.write_text("not executable")
        fake_bin.chmod(0o644)
        result = find_opencode_cli(str(fake_bin))
        assert result is None or result != str(fake_bin)

    def test_env_var_fallback(self, tmp_path: Path) -> None:
        fake_bin = tmp_path / "opencode"
        fake_bin.write_text("#!/bin/sh\n")
        fake_bin.chmod(0o755)
        with patch.dict("os.environ", {"OPENCODE_CLI_PATH": str(fake_bin)}):
            assert find_opencode_cli(None) == str(fake_bin)

    def test_which_fallback(self) -> None:
        with patch("shutil.which", return_value="/usr/local/bin/opencode"):
            assert find_opencode_cli(None) == "/usr/local/bin/opencode"

    def test_nothing_found(self) -> None:
        with patch.dict("os.environ", {}, clear=True), \
             patch("shutil.which", return_value=None):
            assert find_opencode_cli(None) is None


class TestOpenCodeServerInit:

    def test_base_url(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        server = OpenCodeServer(config)
        assert server.base_url == "http://127.0.0.1:14096"

    def test_not_started(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        server = OpenCodeServer(config)
        assert not server._started


class TestOpenCodeServerStart:

    async def test_already_started_noop(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        server = OpenCodeServer(config)
        server._started = True

        with patch.object(server, "_is_healthy") as mock_health:
            await server.start()
            mock_health.assert_not_called()

    async def test_server_already_running_externally(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        server = OpenCodeServer(config)

        with patch.object(server, "_is_healthy", return_value=True):
            await server.start()
            assert server._started

    async def test_cli_not_found_raises(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        server = OpenCodeServer(config)

        with patch.object(server, "_is_healthy", return_value=False), \
             patch(
                 "src.backend.opencode_server.find_opencode_cli",
                 return_value=None,
             ):
            with pytest.raises(RuntimeError, match="opencode CLI not found"):
                await server.start()

    async def test_start_launches_process(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        server = OpenCodeServer(config)

        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.poll.return_value = None

        with patch.object(server, "_is_healthy", return_value=False), \
             patch(
                 "src.backend.opencode_server.find_opencode_cli",
                 return_value="/usr/local/bin/opencode",
             ), \
             patch("subprocess.Popen", return_value=mock_proc) as mock_popen, \
             patch.object(server, "_wait_for_healthy", return_value=True):

            await server.start()

            assert server._started
            mock_popen.assert_called_once()
            cmd = mock_popen.call_args[0][0]
            assert "/usr/local/bin/opencode" in cmd
            assert "serve" in cmd

    async def test_start_fails_if_unhealthy(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        server = OpenCodeServer(config)

        mock_proc = MagicMock()
        mock_proc.pid = 99
        mock_proc.poll.return_value = None

        with patch.object(server, "_is_healthy", return_value=False), \
             patch(
                 "src.backend.opencode_server.find_opencode_cli",
                 return_value="/usr/local/bin/opencode",
             ), \
             patch("subprocess.Popen", return_value=mock_proc), \
             patch.object(server, "_wait_for_healthy", return_value=False):

            with pytest.raises(RuntimeError, match="failed to start"):
                await server.start()


class TestOpenCodeServerStop:

    def test_stop_sends_sigterm(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        server = OpenCodeServer(config)

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        server._process = mock_proc
        server._started = True

        server.stop()

        mock_proc.send_signal.assert_called_once()
        assert not server._started
        assert server._process is None

    def test_stop_kills_after_timeout(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        server = OpenCodeServer(config)

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.wait.side_effect = [subprocess.TimeoutExpired("opencode", 5), None]
        server._process = mock_proc
        server._started = True

        server.stop()

        mock_proc.kill.assert_called_once()

    def test_stop_no_process_noop(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        server = OpenCodeServer(config)
        server.stop()


class TestEnsureRunning:

    async def test_noop_if_not_started(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        server = OpenCodeServer(config)

        with patch.object(server, "start") as mock_start:
            await server.ensure_running()
            mock_start.assert_not_called()

    async def test_restarts_if_process_died(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        server = OpenCodeServer(config)
        server._started = True

        mock_proc = MagicMock()
        mock_proc.poll.return_value = 1
        server._process = mock_proc

        with patch.object(server, "start", new_callable=AsyncMock) as mock_start:
            await server.ensure_running()
            mock_start.assert_called_once()
