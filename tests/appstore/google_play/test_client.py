"""Clientul Google Play: GCS JSON API si Android Publisher."""

from __future__ import annotations

import pytest

from bapp_connectors.core.errors import AuthenticationError
from bapp_connectors.providers.appstore.google_play.client import GooglePlayApiClient
from tests.appstore.conftest import FakeResponse
from tests.fake_http import FakeHttpClient


@pytest.fixture
def fake_http():
    return FakeHttpClient(base_url="https://storage.googleapis.com/storage/v1/")


@pytest.fixture
def client(fake_http):
    return GooglePlayApiClient(http_client=fake_http, bucket="pubsite_prod_rev_123")


def test_list_objects_follows_page_tokens(fake_http, client):
    def respond(method, path, kwargs):
        if kwargs["params"].get("pageToken") == "p2":
            return {"items": [{"name": "earnings/earnings_202609_2.zip"}]}
        return {"items": [{"name": "earnings/earnings_202609_1.zip"}], "nextPageToken": "p2"}

    fake_http.add("GET", "b/pubsite_prod_rev_123/o", respond)
    names = [o["name"] for o in client.list_objects("earnings/")]
    assert names == ["earnings/earnings_202609_1.zip", "earnings/earnings_202609_2.zip"]
    assert fake_http.calls[0].kwargs["params"]["prefix"] == "earnings/"


def test_download_object_url_encodes_name(fake_http, client):
    fake_http.add("GET", "b/pubsite_prod_rev_123/o/earnings%2Fearnings_202609.zip", FakeResponse(content=b"zip"))
    assert client.download_object("earnings/earnings_202609.zip") == b"zip"
    assert fake_http.last_call().kwargs["params"] == {"alt": "media"}


def test_download_auth_error(fake_http, client):
    fake_http.add("GET", "b/pubsite_prod_rev_123/o/", FakeResponse(status_code=403, text="forbidden"))
    with pytest.raises(AuthenticationError):
        client.download_object("earnings/x.zip")


def test_android_publisher_absolute_urls(fake_http, client):
    fake_http.add("GET", "androidpublisher.googleapis.com/androidpublisher/v3/applications/ro.cbsoft.app/reviews", {"reviews": []})
    client.list_reviews("ro.cbsoft.app")
    path = fake_http.last_call().path
    assert path.startswith("https://androidpublisher.googleapis.com/androidpublisher/v3/applications/ro.cbsoft.app/reviews")

    fake_http.add("POST", "/reviews/gp:1:reply", {"result": {"replyText": "Mersi"}})
    client.reply_review("ro.cbsoft.app", "gp:1", "Mersi")
    assert fake_http.last_call().kwargs["json"] == {"replyText": "Mersi"}

    fake_http.add("GET", "purchases/voidedpurchases", {"voidedPurchases": []})
    client.list_voided_purchases("ro.cbsoft.app", 1, 2)
    assert fake_http.last_call().kwargs["params"] == {"startTime": "1", "endTime": "2", "type": "1", "maxResults": "1000"}

    fake_http.add("GET", "purchases/subscriptionsv2/tokens/tok", {"subscriptionState": "SUBSCRIPTION_STATE_ACTIVE"})
    assert client.get_subscription_v2("ro.cbsoft.app", "tok")["subscriptionState"] == "SUBSCRIPTION_STATE_ACTIVE"
