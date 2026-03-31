"""
Matrix error mapping — maps Matrix API errors to framework error hierarchy.
"""

from __future__ import annotations

MATRIX_ERROR_MAP: dict[str, str] = {
    "M_FORBIDDEN": "Forbidden: insufficient permissions",
    "M_UNKNOWN_TOKEN": "Access token is invalid or expired",
    "M_MISSING_TOKEN": "No access token provided",
    "M_LIMIT_EXCEEDED": "Rate limit exceeded",
    "M_NOT_FOUND": "Resource not found",
    "M_ROOM_IN_USE": "Room alias already in use",
    "M_UNKNOWN": "Unknown server error",
}


def get_error_message(errcode: str, default: str = "Unknown Matrix error") -> str:
    """Map a Matrix errcode to a human-readable message."""
    return MATRIX_ERROR_MAP.get(errcode, default)
