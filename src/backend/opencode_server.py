"""OpenCode server sidecar lifecycle manager.

Starts, monitors, and stops the OpenCode server process.
"""

import asyncio
import os
import shutil
import signal
import subprocess
from typing import Optional

import httpx
import structlog

from ..config.settings import Settings

logger = structlog.get_logger()


def find_opencode_cli(cli_path: Optional[str] = None) -> Optional[str]:
    """Find the opencode CLI binary."""
    if cli_path and os.path.exists(cli_path) and os.access(cli_path, os.X_OK):
        return cli_path

    env_path = os.environ.get("OPENCODE_CLI_PATH")
    if env_path and os.path.exists(env_path) and os.access(env_path, os.X_OK):
        return env_path

    return shutil.which("opencode")


class OpenCodeServer:
    """Manages the OpenCode server sidecar process."""

    def __init__(self, config: Settings):
        self.config = config
        self._process: Optional[subprocess.Popen] = None  # type: ignore[type-arg]
        self._host = config.opencode_server_host
        self._port = config.opencode_server_port
        self._password = config.opencode_server_password
        self._base_url = f"http://{self._host}:{self._port}"
        self._started = False

    @property
    def base_url(self) -> str:
        return self._base_url

    async def start(self) -> None:
        """Start the OpenCode server process."""
        if self._started:
            return

        if await self._is_healthy():
            logger.info(
                "OpenCode server already running",
                url=self._base_url,
            )
            self._started = True
            return

        cli_path = find_opencode_cli(self.config.opencode_cli_path)
        if not cli_path:
            raise RuntimeError(
                "opencode CLI not found. Install it or set OPENCODE_CLI_PATH."
            )

        env = os.environ.copy()
        if self._password:
            env["OPENCODE_SERVER_PASSWORD"] = self._password

        cmd = [
            cli_path,
            "serve",
            "--port",
            str(self._port),
            "--hostname",
            self._host,
        ]

        logger.info("Starting OpenCode server", cmd=" ".join(cmd))

        self._process = subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(self.config.approved_directory),
        )

        if not await self._wait_for_healthy(timeout=15.0):
            self.stop()
            raise RuntimeError(
                f"OpenCode server failed to start on {self._base_url}"
            )

        self._started = True
        logger.info(
            "OpenCode server started",
            pid=self._process.pid,
            url=self._base_url,
        )

    def stop(self) -> None:
        """Stop the OpenCode server process."""
        if self._process and self._process.poll() is None:
            logger.info("Stopping OpenCode server", pid=self._process.pid)
            self._process.send_signal(signal.SIGTERM)
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=2)
            logger.info("OpenCode server stopped")
        self._process = None
        self._started = False

    async def _is_healthy(self) -> bool:
        """Check server health endpoint."""
        try:
            auth = None
            if self._password:
                auth = httpx.BasicAuth("opencode", self._password)
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{self._base_url}/global/health",
                    auth=auth,
                    timeout=3.0,
                )
                return resp.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException):
            return False

    async def _wait_for_healthy(self, timeout: float = 15.0) -> bool:
        """Poll health endpoint until server is ready."""
        interval = 0.5
        elapsed = 0.0
        while elapsed < timeout:
            if self._process and self._process.poll() is not None:
                logger.error(
                    "OpenCode server process exited",
                    returncode=self._process.returncode,
                )
                return False
            if await self._is_healthy():
                return True
            await asyncio.sleep(interval)
            elapsed += interval
        return False

    async def ensure_running(self) -> None:
        """Restart the server if it has died."""
        if not self._started:
            return
        if self._process and self._process.poll() is not None:
            logger.warning("OpenCode server died, restarting")
            self._started = False
            await self.start()
