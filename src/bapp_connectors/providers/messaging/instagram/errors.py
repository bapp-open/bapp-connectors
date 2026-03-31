"""
Instagram Messaging error mapping.
"""

from __future__ import annotations

# Same error codes as Messenger (shared Meta Graph API)
INSTAGRAM_ERROR_MAP: dict[int, str] = {
    2: "Internal server error",
    4: "Too many API calls",
    10: "Permission denied",
    100: "Invalid parameter",
    190: "Access token expired or invalid",
    200: "Permission denied for Send API",
    551: "User is not available",
    1200: "Temporary send message failure",
    2534021: "Message failed to send — user may have blocked DMs or account is restricted",
}


def get_error_message(code: int, default: str = "Unknown Instagram error") -> str:
    """Map an Instagram error code to a human-readable message."""
    return INSTAGRAM_ERROR_MAP.get(code, default)
