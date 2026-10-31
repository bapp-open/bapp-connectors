"""
Meta provider unit tests — one Meta login, Facebook pages + Instagram accounts
as publish destinations. No network: canned Graph responses via FakeHttpClient.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from bapp_connectors.core.capabilities import OAuthCapability, SocialDestinationsCapability
from bapp_connectors.core.errors import AuthenticationError
from bapp_connectors.providers.social.meta.adapter import MetaAdapter
from bapp_connectors.providers.social.meta.manifest import manifest
from tests.fake_http import FakeHttpClient

APP_CREDENTIALS = {"app_id": "app_123", "app_secret": "secret_456"}

META_SCOPES = [
    "pages_show_list",
    "pages_read_engagement",
    "pages_manage_posts",
    "read_insights",
    "business_management",
    "instagram_basic",
    "instagram_content_publish",
    "catalog_management",
    "instagram_shopping_tag_products",
]


def make_adapter(fake: FakeHttpClient, **credentials) -> MetaAdapter:
    return MetaAdapter(credentials={**APP_CREDENTIALS, **credentials}, http_client=fake)


def _token_exchange(method, path, kwargs):
    """Answer the code exchange with a short token and fb_exchange_token with a long one."""
    params = kwargs["params"]
    if params.get("grant_type") == "fb_exchange_token":
        return {"access_token": "long", "token_type": "bearer", "expires_in": 5183944}
    return {"access_token": "short", "token_type": "bearer", "expires_in": 3600}


# ── Manifest / registry ──


def test_registered_in_registry():
    import bapp_connectors.providers.social.meta  # noqa: F401 — triggers registration
    from bapp_connectors.core.registry import registry

    assert registry.get_manifest("social", "meta").name == "meta"
    assert registry.get_adapter_class("social", "meta") is MetaAdapter


def test_manifest():
    assert manifest.display_name == "Meta (Facebook + Instagram)"
    assert manifest.capabilities == [OAuthCapability, SocialDestinationsCapability]
    assert manifest.auth.oauth.display_name == "Conectează cu Meta"
    assert manifest.auth.oauth.scopes == META_SCOPES
    fields = {f.name: f for f in manifest.auth.required_fields}
    assert set(fields) == {"app_id", "app_secret", "token"}
    assert fields["token"].required is False
    assert fields["token"].sensitive is True
    assert fields["app_secret"].sensitive is True


def test_validate_credentials():
    assert MetaAdapter(credentials=APP_CREDENTIALS).validate_credentials() is True
    assert MetaAdapter(credentials={"token": "t"}).validate_credentials() is True
    assert MetaAdapter(credentials={}).validate_credentials() is False


# ── OAuth ──


def test_get_authorize_url():
    url = make_adapter(FakeHttpClient()).get_authorize_url("https://x/cb", state="st")
    assert url.startswith("https://www.facebook.com/v19.0/dialog/oauth?")
    query = parse_qs(urlparse(url).query)
    assert query["client_id"] == ["app_123"]
    assert query["redirect_uri"] == ["https://x/cb"]
    assert query["state"] == ["st"]
    assert query["scope"] == [",".join(META_SCOPES)]


def test_exchange_returns_long_lived_token_without_expiry():
    fake = FakeHttpClient()
    fake.add("GET", "oauth/access_token", _token_exchange)
    tokens = make_adapter(fake).exchange_code_for_token("code", "https://x/cb")

    assert tokens.access_token == "long"
    assert tokens.refresh_token == ""
    assert tokens.extra["credentials"] == {"token": "long"}
    assert tokens.expires_in is None

    code_params = fake.calls[0].kwargs["params"]
    assert code_params["code"] == "code"
    assert code_params["redirect_uri"] == "https://x/cb"
    assert code_params["client_id"] == "app_123"
    assert code_params["client_secret"] == "secret_456"
    exchange_params = fake.calls[1].kwargs["params"]
    assert exchange_params["grant_type"] == "fb_exchange_token"
    assert exchange_params["fb_exchange_token"] == "short"
    assert len(fake.calls) == 2


def test_refresh_token_without_expiry():
    fake = FakeHttpClient()
    fake.add("GET", "oauth/access_token", _token_exchange)
    tokens = make_adapter(fake).refresh_token("current")

    assert tokens.access_token == "long"
    assert tokens.extra["credentials"] == {"token": "long"}
    assert tokens.expires_in is None
    assert fake.last_call().kwargs["params"]["fb_exchange_token"] == "current"


def test_exchange_raises_on_graph_error():
    fake = FakeHttpClient()
    fake.add("GET", "oauth/access_token", {"error": {"code": 190, "message": "bad code"}})
    with pytest.raises(AuthenticationError):
        make_adapter(fake).exchange_code_for_token("code", "https://x/cb")


# ── Destinations ──


def test_list_destinations_pages_and_instagram():
    fake = FakeHttpClient()
    fake.add(
        "GET",
        "me/accounts",
        {
            "data": [
                {
                    "id": "P1",
                    "name": "Pagina 1",
                    "username": "pagina1",
                    "picture": {"data": {"url": "https://cdn/p1.jpg"}},
                    "access_token": "pt1",
                    "instagram_business_account": {
                        "id": "IG1",
                        "username": "ig_one",
                        "name": "IG One",
                        "profile_picture_url": "https://cdn/ig1.jpg",
                    },
                },
                {"id": "P2", "name": "Pagina 2", "access_token": "pt2"},
            ]
        },
    )
    dests = make_adapter(fake, token="user_token").list_destinations()

    assert [(d.provider, d.id, d.kind) for d in dests] == [
        ("facebook", "P1", "facebook_page"),
        ("instagram", "IG1", "instagram_account"),
        ("facebook", "P2", "facebook_page"),
    ]
    assert dests[0].credentials == {"token": "pt1", "page_id": "P1"}
    assert dests[0].name == "Pagina 1"
    assert dests[0].username == "pagina1"
    assert dests[0].avatar_url == "https://cdn/p1.jpg"
    assert dests[1].credentials == {"token": "pt1", "ig_user_id": "IG1"}
    assert dests[1].name == "IG One"
    assert dests[1].username == "ig_one"
    assert dests[1].avatar_url == "https://cdn/ig1.jpg"
    assert dests[2].credentials == {"token": "pt2", "page_id": "P2"}

    call = fake.calls[0]
    assert call.path == "me/accounts"
    assert call.kwargs["params"]["fields"] == (
        "id,name,username,picture{url},access_token,instagram_business_account{id,username,name,profile_picture_url}"
    )


def test_list_destinations_instagram_name_falls_back_to_username():
    fake = FakeHttpClient()
    fake.add(
        "GET",
        "me/accounts",
        {
            "data": [
                {
                    "id": "P1",
                    "name": "P",
                    "access_token": "pt",
                    "instagram_business_account": {"id": "IG", "username": "u"},
                }
            ]
        },
    )
    dests = make_adapter(fake, token="t").list_destinations()
    assert dests[1].name == "u"


def test_list_destinations_follows_paging():
    def accounts(method, path, kwargs):
        if kwargs["params"].get("after") == "CUR2":
            return {
                "data": [{"id": "P2", "name": "Pagina 2", "access_token": "pt2"}],
                "paging": {"cursors": {"after": "CUR3"}},
            }
        return {
            "data": [{"id": "P1", "name": "Pagina 1", "access_token": "pt1"}],
            "paging": {"cursors": {"after": "CUR2"}, "next": "https://graph.facebook.com/v19.0/me/accounts?after=CUR2"},
        }

    fake = FakeHttpClient()
    fake.add("GET", "me/accounts", accounts)
    dests = make_adapter(fake, token="t").list_destinations()

    assert [d.id for d in dests] == ["P1", "P2"]
    assert len(fake.calls) == 2
    assert "after" not in fake.calls[0].kwargs["params"]
    assert fake.calls[1].kwargs["params"]["after"] == "CUR2"


def test_list_destinations_raises_on_graph_error():
    fake = FakeHttpClient()
    fake.add("GET", "me/accounts", {"error": {"code": 190, "message": "expired"}})
    with pytest.raises(AuthenticationError):
        make_adapter(fake, token="t").list_destinations()


# ── Connection test ──


def test_test_connection():
    fake = FakeHttpClient()
    fake.add("GET", "me", {"id": "U1", "name": "Ion Popescu"})
    result = make_adapter(fake, token="t").test_connection()

    assert result.success is True
    assert "Ion Popescu" in result.message
    assert fake.last_call().path == "me"
    assert fake.last_call().kwargs["params"] == {"fields": "id,name"}


def test_test_connection_failure():
    fake = FakeHttpClient()
    fake.add("GET", "me", {"error": {"code": 190, "message": "expired"}})
    result = make_adapter(fake, token="t").test_connection()
    assert result.success is False
