"""
Discord error mapping — maps Discord API errors to framework error hierarchy.
"""

from __future__ import annotations

DISCORD_ERROR_MAP: dict[int, str] = {
    10003: "Unknown channel",
    10008: "Unknown message",
    30001: "Maximum number of guilds reached",
    40001: "Unauthorized",
    50001: "Missing access",
    50013: "Missing permissions",
    50035: "Invalid form body",
}


def get_error_message(code: int, default: str = "Unknown Discord error") -> str:
    """Map a Discord error code to a human-readable message."""
    return DISCORD_ERROR_MAP.get(code, default)
