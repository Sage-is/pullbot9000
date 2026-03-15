"""Lightweight settings for API-only mode.

Telegram fields are given harmless defaults so that the existing Settings
infrastructure (approved_directory, claude_*, database_url, etc.) can be
reused without requiring a Telegram bot token.
"""

from pydantic import Field, SecretStr

from .settings import Settings


class APISettings(Settings):
    """Settings for API-only mode -- Telegram fields not required."""

    telegram_bot_token: SecretStr = Field(default=SecretStr("unused"))
    telegram_bot_username: str = Field(default="unused")
