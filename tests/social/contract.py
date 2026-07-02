"""
Social port contract test suite.

Reusable tests that any SocialPort adapter must pass. Provider test modules
subclass SocialContractTests and provide an ``adapter`` fixture backed by a
FakeHttpClient with canned responses for the provider's endpoints.
"""

from __future__ import annotations

import pytest

from bapp_connectors.core.dto import PaginatedResult
from bapp_connectors.core.dto.social import (
    SocialAccount,
    SocialAccountStats,
    SocialPost,
    SocialPostStats,
)
from bapp_connectors.core.ports import SocialPort
from bapp_connectors.core.registry import registry
from bapp_connectors.core.types import ProviderFamily


class SocialContractTests:
    """Contract tests for SocialPort implementations."""

    @pytest.fixture
    def adapter(self) -> SocialPort:
        raise NotImplementedError

    def test_is_social_port_instance(self, adapter: SocialPort):
        assert isinstance(adapter, SocialPort)

    def test_manifest_valid(self, adapter: SocialPort):
        assert adapter.manifest.validate() == []
        assert adapter.manifest.family == ProviderFamily.SOCIAL

    def test_registered(self, adapter: SocialPort):
        assert registry.is_registered("social", adapter.manifest.name)

    def test_declared_capabilities_implemented(self, adapter: SocialPort):
        for capability in adapter.manifest.capabilities:
            assert adapter.supports(capability)

    def test_validate_credentials(self, adapter: SocialPort):
        assert adapter.validate_credentials() is True

    def test_get_account(self, adapter: SocialPort):
        account = adapter.get_account()
        assert isinstance(account, SocialAccount)
        assert account.id

    def test_list_posts(self, adapter: SocialPort):
        result = adapter.list_posts(limit=5)
        assert isinstance(result, PaginatedResult)
        assert result.items
        for post in result.items:
            assert isinstance(post, SocialPost)
            assert post.id

    def test_get_post(self, adapter: SocialPort, sample_post_id: str):
        post = adapter.get_post(sample_post_id)
        assert isinstance(post, SocialPost)
        assert post.id == sample_post_id

    def test_get_post_stats(self, adapter: SocialPort, sample_post_id: str):
        stats = adapter.get_post_stats(sample_post_id)
        assert isinstance(stats, SocialPostStats)
        assert stats.post_id == sample_post_id
        # Universal stats interface: at least one core metric must be mapped
        assert any(
            value is not None
            for value in (stats.views, stats.likes, stats.comments, stats.impressions)
        )

    def test_get_account_stats(self, adapter: SocialPort):
        stats = adapter.get_account_stats()
        assert isinstance(stats, SocialAccountStats)
        assert any(
            value is not None
            for value in (stats.followers_count, stats.total_views, stats.impressions, stats.posts_count)
        )
