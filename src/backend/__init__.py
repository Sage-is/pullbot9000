"""Claude Code / OpenCode integration module."""

from .exceptions import (
    ClaudeError,
    ClaudeParsingError,
    ClaudeProcessError,
    ClaudeSessionError,
    ClaudeTimeoutError,
)
from .facade import ClaudeIntegration
from .opencode_integration import OpenCodeManager
from .opencode_server import OpenCodeServer
from .sdk_integration import ClaudeResponse, ClaudeSDKManager, StreamUpdate
from .session import (
    ClaudeSession,
    InMemorySessionStorage,
    SessionManager,
    SessionStorage,
)

__all__ = [
    # Exceptions
    "ClaudeError",
    "ClaudeParsingError",
    "ClaudeProcessError",
    "ClaudeSessionError",
    "ClaudeTimeoutError",
    # Main integration
    "ClaudeIntegration",
    # Core components
    "ClaudeSDKManager",
    "OpenCodeManager",
    "OpenCodeServer",
    "ClaudeResponse",
    "StreamUpdate",
    "SessionManager",
    "SessionStorage",
    "InMemorySessionStorage",
    "ClaudeSession",
]
