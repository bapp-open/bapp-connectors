"""Settings detection capability — read the store's own configuration."""

from __future__ import annotations

from abc import ABC, abstractmethod


class SettingsDetectionCapability(ABC):
    """Adapter can read the provider's own configuration and propose values for its
    manifest settings (e.g. prices_include_vat, vat_rate for a shop).

    Keys in the returned dict MUST match manifest ``settings`` field names, so a
    caller can prefill a connection's config with them. Only confidently detected
    keys are returned; anything unreadable is simply omitted.
    """

    @abstractmethod
    def detect_settings(self) -> dict:
        """Return detected settings as {manifest_setting_name: value}."""
        ...
