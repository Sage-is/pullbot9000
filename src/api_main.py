"""Standalone entry point for API-only mode.

Bootstraps only the components needed to serve the OpenAI-compatible API
(no Telegram bot, EventBus, scheduler, etc.).

Usage:
    uv run claude-api-server
    uv run claude-api-server --debug
"""

import argparse
import asyncio
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Any

import structlog

from src import __version__
from src.api.server import create_api_app
from src.backend import ClaudeIntegration, SessionManager
from src.backend.sdk_integration import ClaudeSDKManager
from src.backend.opencode_integration import OpenCodeManager
from src.backend.opencode_server import OpenCodeServer
from src.config.api_settings import APISettings
from src.security.validators import SecurityValidator
from src.storage.facade import Storage
from src.storage.session_storage import SQLiteSessionStorage


def setup_logging(debug: bool = False) -> None:
    """Configure structured logging."""
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(level=level, format="%(message)s", stream=sys.stdout)
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            (
                structlog.processors.JSONRenderer()
                if not debug
                else structlog.dev.ConsoleRenderer()
            ),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Claude Code API Server (OpenAI-compatible)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"Claude Code API Server {__version__}",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument(
        "--config-file", type=Path, help="Path to .env configuration file"
    )
    return parser.parse_args()


async def main() -> None:
    """Main application entry point for API-only mode."""
    import uvicorn
    from dotenv import load_dotenv

    args = parse_args()
    setup_logging(debug=args.debug)
    log = structlog.get_logger()

    # Load .env
    env_file = args.config_file or Path(".env")
    if env_file.exists():
        load_dotenv(env_file)

    log.info("Starting Claude Code API Server", version=__version__)

    # Load settings (Telegram fields are optional via APISettings)
    config = APISettings()  # type: ignore[call-arg]
    if args.debug:
        config.debug = True

    # Initialize storage
    storage = Storage(config.database_url)
    await storage.initialize()

    # Security
    security_validator = SecurityValidator(
        config.approved_directory,
        disable_security_patterns=config.disable_security_patterns,
    )

    # Backend integration
    opencode_server = None
    if getattr(config, "backend", "claude") == "opencode":
        log.info("Using OpenCode HTTP API backend")
        if getattr(config, "opencode_auto_start", True):
            opencode_server = OpenCodeServer(config)
            await opencode_server.start()
        sdk_manager = OpenCodeManager(config, security_validator=security_validator)
    else:
        log.info("Using Claude Python SDK backend")
        sdk_manager = ClaudeSDKManager(config, security_validator=security_validator)

    session_storage = SQLiteSessionStorage(storage.db_manager)
    session_manager = SessionManager(config, session_storage)
    claude_integration = ClaudeIntegration(
        config=config,
        sdk_manager=sdk_manager,
        session_manager=session_manager,
    )

    # Build FastAPI app (event_bus=None disables webhook routes)
    app = create_api_app(
        event_bus=None,
        settings=config,
        db_manager=storage.db_manager,
        claude_integration=claude_integration,
        storage=storage,
    )

    log.info("API server starting", port=config.api_server_port)

    # Graceful shutdown
    shutdown_event = asyncio.Event()

    def signal_handler(signum: int, frame: Any) -> None:
        log.info("Shutdown signal received", signal=signum)
        shutdown_event.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    server = uvicorn.Server(
        uvicorn.Config(
            app=app,
            host=config.api_server_host,
            port=config.api_server_port,
            log_level="debug" if config.debug else "info",
        )
    )

    try:
        server_task = asyncio.create_task(server.serve())

        port_file = os.environ.get("API_PORT_FILE")
        if port_file:
            while not server.started:
                await asyncio.sleep(0.1)
            actual_port = server.servers[0].sockets[0].getsockname()[1]
            Path(port_file).write_text(str(actual_port))
            log.info("port_file_written", path=port_file, port=actual_port)

        shutdown_task = asyncio.create_task(shutdown_event.wait())

        done, pending = await asyncio.wait(
            [server_task, shutdown_task], return_when=asyncio.FIRST_COMPLETED
        )

        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    finally:
        log.info("Shutting down API server")
        await claude_integration.shutdown()
        if opencode_server:
            opencode_server.stop()
        await storage.close()
        log.info("API server shutdown complete")


def run() -> None:
    """Synchronous entry point for setuptools."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown requested by user")
        sys.exit(0)


if __name__ == "__main__":
    run()
