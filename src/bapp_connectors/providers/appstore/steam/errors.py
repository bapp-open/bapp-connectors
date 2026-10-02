"""Erorile Steamworks: raspunsurile vin ca JSON {"response": {...}}; 403 = cheie gresita sau IP neautorizat."""

from __future__ import annotations

from bapp_connectors.core.errors import PermanentProviderError


def check_steam_response(payload, *, what: str) -> dict:
    if not isinstance(payload, dict):
        raise PermanentProviderError(f"Steam {what}: raspuns neasteptat: {str(payload)[:200]}")
    response = payload.get("response")
    if response is None:
        raise PermanentProviderError(f"Steam {what}: lipseste `response`: {str(payload)[:200]}")
    return response


def steam_forbidden_hint() -> str:
    return "Steam a refuzat cheia (403): verifica cheia financiara si IP whitelist-ul din Steamworks (Financial API Group)."

