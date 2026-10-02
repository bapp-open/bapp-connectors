"""Apple si Google se inregistreaza doar cu PyJWT instalat; Steam mereu."""

from __future__ import annotations

import builtins
import importlib
import sys

import pytest

from bapp_connectors.core.registry import registry


def test_all_three_registered_with_jwt():
    pytest.importorskip("jwt")
    import bapp_connectors.providers.appstore.apple
    import bapp_connectors.providers.appstore.google_play
    import bapp_connectors.providers.appstore.steam  # noqa: F401

    assert {m.name for m in registry.list_providers(family="appstore")} >= {"apple", "google_play", "steam"}


def test_apple_and_google_skip_registration_without_jwt(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "jwt" or name.startswith("jwt."):
            raise ImportError("no jwt")
        return real_import(name, *args, **kwargs)

    registered: list[type] = []
    monkeypatch.setattr(registry, "register", lambda cls: registered.append(cls))
    monkeypatch.setattr(builtins, "__import__", fake_import)
    for module in ("bapp_connectors.providers.appstore.apple", "bapp_connectors.providers.appstore.google_play", "bapp_connectors.providers.appstore.steam"):
        sys.modules.pop(module, None)
        importlib.import_module(module)
    assert [cls.__name__ for cls in registered] == ["SteamAdapter"]
