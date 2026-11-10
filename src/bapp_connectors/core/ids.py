"""Validators for ids an AI agent sends that end up in a request path."""

from __future__ import annotations

import re

from bapp_connectors.core.errors import ValidationError

_PLAIN_ID = re.compile(r"[A-Za-z0-9_-]+")


def plain_id(value: str, what: str) -> str:
    """An id going into a URL path: letters, digits, ``_`` and ``-`` only.

    Refuses ``/``, ``.``, ``?``, ``&``, ``%``, ``,``, spaces and the empty string, so the id
    cannot change the path, add query parameters or turn a get-one into a list.
    """
    if not isinstance(value, str) or not _PLAIN_ID.fullmatch(value):
        raise ValidationError(f"{what} must contain only letters, digits, '_' and '-'.")
    return value
