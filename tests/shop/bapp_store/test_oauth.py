"""OAuth handshake tests for the bapp_store provider: authorize URL and credential handback."""
import json

from bapp_connectors.providers.shop.bapp_store.adapter import BappStoreShopAdapter


def _adapter():
    return BappStoreShopAdapter(credentials={"token": "t"})


def test_the_authorize_url_points_at_the_store_and_carries_the_framework_values():
    from urllib.parse import parse_qs, urlparse

    url = _adapter().get_authorize_url("https://panel.bapp.ro/api/webhooks/oauth/callback/381/bapp_store/", "abc")
    parsed = urlparse(url)
    assert parsed.scheme == "https"
    assert parsed.netloc == "store.bapp.ro"
    query = parse_qs(parsed.query)
    assert query["state"] == ["abc"]
    assert query["callback_url"] == ["https://panel.bapp.ro/api/webhooks/oauth/callback/381/bapp_store/"]
    # the store refuses the request unless all five are present
    for name in ("app_name", "scope", "state", "return_url", "callback_url"):
        assert name in query, name


def test_the_return_url_is_the_callback_with_a_success_marker():
    from urllib.parse import parse_qs, urlparse

    callback = "https://panel.bapp.ro/api/webhooks/oauth/callback/381/bapp_store/"
    query = parse_qs(urlparse(_adapter().get_authorize_url(callback, "abc")).query)
    # the framework treats a GET with no code as the browser bouncing back, and
    # redirects to the connection list, so this is where the operator should land
    assert query["return_url"][0].startswith(callback)
    assert "success=1" in query["return_url"][0]


def test_the_exchange_hands_back_what_the_store_posted_without_calling_anything():
    posted = json.dumps({"token": "tok-1", "tenant_id": "40", "store_name": "Al meu"})
    tokens = _adapter().exchange_code_for_token(posted, "https://panel.bapp.ro/cb/", "abc")
    assert tokens.extra["credentials"]["token"] == "tok-1"
    assert tokens.extra["credentials"]["tenant_id"] == "40"


def test_a_body_that_is_not_an_object_yields_no_credentials_rather_than_crashing():
    for body in ("[1,2]", "null", "not json at all", ""):
        tokens = _adapter().exchange_code_for_token(body, "https://panel.bapp.ro/cb/", "abc")
        assert tokens.extra["credentials"] == {}, body
