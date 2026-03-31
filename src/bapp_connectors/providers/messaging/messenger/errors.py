"""
Facebook Messenger error mapping — maps Messenger API errors to framework error hierarchy.
"""

from __future__ import annotations

# https://developers.facebook.com/docs/messenger-platform/error-codes
MESSENGER_ERROR_MAP: dict[int, str] = {
    2: "Internal server error",
    4: "Too many API calls",
    10: "Permission denied",
    100: "Invalid parameter",
    190: "Access token expired or invalid",
    200: "Permission denied for Send API",
    551: "User is not available (blocked the page or deactivated)",
    1200: "Temporary send message failure",
}


def get_error_message(code: int, default: str = "Unknown Messenger error") -> str:
    """Map a Messenger error code to a human-readable message."""
    return MESSENGER_ERROR_MAP.get(code, default)
