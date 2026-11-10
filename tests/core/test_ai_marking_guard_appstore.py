"""Guard on the ``@ai_method`` markers of the appstore provider clients.

A method marked ``read`` is callable by an external AI agent, server-side, with the company's
store credentials. Every one of them was read down to its HTTP request; the lists below are
that review. Replying to a review is ``write``.

Not read: report downloads (gzip/CSV bytes), a reviews call that follows an agent-given
``next_url``, purchase-token lookups. Pagination cursors are handed out as ``next_cursor``
(Apple: the ``cursor`` of ``links.next``; Google: ``tokenPagination.nextPageToken``, which BAPP
would redact because the key contains "token").
"""

from __future__ import annotations

import inspect
import json
from unittest.mock import MagicMock

import pytest

from bapp_connectors.core.ai import ai_methods
from bapp_connectors.core.errors import ValidationError
from tests.core import ai_guard

FAMILY = "appstore"
APPSTORE_PROVIDERS = ai_guard.family_providers(FAMILY)

REVIEWED_READ_METHODS: dict[str, set[str]] = {
    "apple": {
        "list_app_reviews",  # GET apps/{id}/customerReviews, cursor in the query string
        "list_app_versions",  # GET apps/{id}/appStoreVersions, fixed fields
        "list_apps",  # GET apps (follows Apple's own links.next)
    },
    "google_play": {
        "list_app_reviews",  # GET androidpublisher .../{package}/reviews, package name regex-checked
    },
    "steam": {
        "get_app_details",  # public store API
        "get_changed_dates",  # partner financials; the highwatermark is the caller's, nothing acknowledged
        "get_current_players",  # public API
        "get_detailed_sales",
        "get_reviews",  # public store API, cursor in the query string
        "get_wishlist_reporting",
    },
}

REVIEWED_READ_EXTRA: dict[tuple[str, str], dict[str, str]] = {}

# Opaque pagination cursors: they only reach a query string.
REVIEWED_FREE_TEXT: set[tuple[str, str, str]] = {
    ("apple", "list_app_reviews", "cursor"),
    ("apple", "list_app_versions", "cursor"),
    ("google_play", "list_app_reviews", "cursor"),
    ("steam", "get_reviews", "cursor"),
}

# Public client methods deliberately left without any mark (never offered to an agent).
UNMARKED_ON_PURPOSE: dict[tuple[str, str], str] = {
    ("apple", "test_auth"): "connection test",
    ("apple", "download_sales_report"): "gzip bytes",
    ("apple", "download_finance_report"): "gzip bytes",
    ("apple", "list_reviews"): "GETs an agent-given next_url; the agent uses list_app_reviews",
    ("google_play", "test_auth"): "connection test",
    ("google_play", "list_objects"): "report file listing, only useful with download_object (bytes)",
    ("google_play", "download_object"): "bytes",
    ("google_play", "list_reviews"): "takes a 'token' and returns tokenPagination (redacted); wrapped",
    ("google_play", "list_voided_purchases"): "returns purchase tokens",
    ("google_play", "get_subscription_v2"): "takes a purchase token",
}

NOT_MARKED: dict[str, str] = {}


@pytest.fixture(autouse=True, scope="module")
def _parseable_service_account():
    """Google Play parses ``service_account_json`` in __init__ (no network): give it a JSON object.

    ``ai_guard.adapter`` caches, so the adapter is built once, inside this patch."""
    real = ai_guard._dummy_credentials

    def credentials(manifest):
        creds = real(manifest)
        if "service_account_json" in creds:
            creds["service_account_json"] = json.dumps({"client_email": "a@b.iam", "private_key": "dummy"})
        return creds

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ai_guard, "_dummy_credentials", credentials)
        yield


def test_every_appstore_provider_is_reviewed_or_not_marked():
    ai_guard.check_family_coverage(FAMILY, REVIEWED_READ_METHODS, NOT_MARKED)


_CHECKED = [p for p in APPSTORE_PROVIDERS if p not in NOT_MARKED]


@pytest.mark.parametrize("check", ai_guard.GENERIC_CHECKS, ids=lambda c: c.__name__)
@pytest.mark.parametrize("provider", _CHECKED)
def test_appstore_marks(provider, check):
    kwargs = {"free_text": REVIEWED_FREE_TEXT} if check is ai_guard.check_free_text_reviewed else {}
    check(FAMILY, provider, REVIEWED_READ_METHODS, REVIEWED_READ_EXTRA, **kwargs)


@pytest.mark.parametrize("provider", _CHECKED)
def test_every_public_method_is_marked_or_left_out_on_purpose(provider):
    """A new public client method fails here until it is marked or listed as unmarked."""
    cls = ai_guard.client_cls(FAMILY, provider)
    marked = set(ai_methods(cls))
    public = {
        name
        for name, value in vars(cls).items()
        if not name.startswith("_") and callable(value) and not isinstance(value, (staticmethod, classmethod))
    }
    assert public - marked == {m for p, m in UNMARKED_ON_PURPOSE if p == provider}


@pytest.mark.parametrize("provider", _CHECKED)
def test_no_read_takes_a_url_or_token(provider):
    blocked = {"url", "next_url", "host", "base_url", "version", "path", "token", "purchase_token", "bucket"}
    for name, fn, _info in ai_guard.read_methods(FAMILY, provider):
        assert not set(inspect.signature(fn).parameters) & blocked, name


# ── Apple ──


def _apple(response):
    from bapp_connectors.providers.appstore.apple.client import AppleApiClient

    http = MagicMock()
    http.call.return_value = response
    return AppleApiClient(http, vendor_number="v1"), http


def test_apple_reviews_hand_out_the_next_cursor():
    client, http = _apple(
        {
            "data": [{"id": "r1"}],
            "included": [{"id": "resp1"}],
            "links": {
                "next": "https://api.appstoreconnect.apple.com/v1/apps/1/customerReviews?cursor=AQ.x%2By&limit=2"
            },
        }
    )
    page = client.list_app_reviews("123", cursor="PREV", limit=500)
    assert page == {"data": [{"id": "r1"}], "included": [{"id": "resp1"}], "next_cursor": "AQ.x+y"}
    call = http.call.call_args
    assert call.args == ("GET", "apps/123/customerReviews")
    assert call.kwargs["params"]["cursor"] == "PREV"
    assert call.kwargs["params"]["limit"] == "200"


def test_apple_versions_last_page():
    client, http = _apple({"data": [], "links": {"self": "x"}})
    assert client.list_app_versions("123") == {"data": [], "next_cursor": None}
    call = http.call.call_args
    assert call.args == ("GET", "apps/123/appStoreVersions")
    assert "versionString" in call.kwargs["params"]["fields[appStoreVersions]"]


# ── Google Play ──


def _google_play():
    from bapp_connectors.providers.appstore.google_play.client import GooglePlayApiClient

    http = MagicMock()
    http.call.return_value = {"reviews": [{"reviewId": "a"}], "tokenPagination": {"nextPageToken": "NEXT"}}
    return GooglePlayApiClient(http, bucket="pubsite_prod_rev_1"), http


def test_google_play_reviews_rename_the_page_token():
    client, http = _google_play()
    page = client.list_app_reviews("com.example.app", cursor="CUR")
    assert page == {"reviews": [{"reviewId": "a"}], "next_cursor": "NEXT"}
    call = http.call.call_args
    assert (
        call.args[1]
        == "https://androidpublisher.googleapis.com/androidpublisher/v3/applications/com.example.app/reviews"
    )
    assert call.kwargs["params"]["token"] == "CUR"


@pytest.mark.parametrize("package", ["com.example.app@evil.com", "com", "com.example.app%2F..", "1com.x", ""])
def test_google_play_reviews_refuse_a_non_package_name(package):
    client, http = _google_play()
    with pytest.raises(ValidationError):
        client.list_app_reviews(package)
    http.call.assert_not_called()


# ── Steam ──


def test_steam_reviews_cursor_stays_in_the_query():
    from bapp_connectors.providers.appstore.steam.client import SteamApiClient

    http = MagicMock()
    http.call.return_value = {"success": 1, "reviews": []}
    client = SteamApiClient(http, api_key="k" * 32)
    client.get_reviews("570", cursor="AoJ/abc+=")
    call = http.call.call_args
    assert call.args == ("GET", "https://store.steampowered.com/appreviews/570")
    assert call.kwargs["params"]["cursor"] == "AoJ/abc+="
