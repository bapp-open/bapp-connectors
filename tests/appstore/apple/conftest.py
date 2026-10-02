"""Testele Apple care semneaza JWT / verifica x5c cer extra-ul `appstore` (PyJWT + cryptography)."""

from __future__ import annotations

import importlib.util

_HAS_JWT = importlib.util.find_spec("jwt") is not None and importlib.util.find_spec("cryptography") is not None
collect_ignore = [] if _HAS_JWT else ["test_auth.py", "test_jws.py"]
