"""Tests for django_bapp_connectors.settings.get_setting."""

from __future__ import annotations

import pytest

from django.test import override_settings

from django_bapp_connectors.settings import get_setting


class TestGetSetting:
    @override_settings()
    def test_returns_default_when_bapp_connectors_not_set(self, settings):
        # Remove BAPP_CONNECTORS entirely from settings
        if hasattr(settings, "BAPP_CONNECTORS"):
            delattr(settings, "BAPP_CONNECTORS")

        result = get_setting("DEFAULT_TIMEOUT")
        assert result == 10

    @override_settings(BAPP_CONNECTORS={"ENCRYPTION_KEY": "test-key"})
    def test_returns_default_when_key_not_in_bapp_connectors(self):
        result = get_setting("DEFAULT_TIMEOUT")
        assert result == 10

    @override_settings(BAPP_CONNECTORS={"DEFAULT_TIMEOUT": 30})
    def test_returns_user_override_when_key_in_bapp_connectors(self):
        result = get_setting("DEFAULT_TIMEOUT")
        assert result == 30

    @override_settings(BAPP_CONNECTORS={})
    def test_returns_none_for_unknown_key_not_in_defaults(self):
        result = get_setting("NONEXISTENT_SETTING_XYZ")
        assert result is None
