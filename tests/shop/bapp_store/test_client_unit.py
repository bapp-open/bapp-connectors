from bapp_connectors.providers.shop.bapp_store.models import SyncItemResult, SyncTaskResponse


def test_sync_task_response_parses_positional_results():
    parsed = SyncTaskResponse.model_validate(
        {
            "categories": [{"index": 0, "id": "12", "status": "created", "error": "", "code": ""}],
            "products": [
                {"index": 0, "id": "501", "status": "updated"},
                {"index": 1, "id": "502", "status": "error", "error": "unknown category 99", "code": "unknown_category"},
            ],
            "rules_applied": True,
        }
    )
    assert parsed.categories == [SyncItemResult(index=0, id="12", status="created")]
    assert parsed.products[1].code == "unknown_category"
    assert parsed.rules_applied is True and parsed.webhook_applied is False


def test_sync_task_response_defaults_to_empty():
    assert SyncTaskResponse.model_validate({}) == SyncTaskResponse()


import pytest  # noqa: E402
import requests  # noqa: E402

from bapp_connectors.core.errors import AuthenticationError, PermanentProviderError, ProviderError  # noqa: E402
from bapp_connectors.providers.shop.bapp_store.client import (  # noqa: E402
    CATEGORY_PATH,
    ORDER_EXPORT_PATH,
    ORDERS_EXPORT_PATH,
    PRODUCT_PATH,
    SYNC_TASK_PATH,
    BappStoreClient,
)
from tests.fake_http import FakeHttpClient  # noqa: E402
from tests.shop.bapp_store.fake_response import FakeResponse  # noqa: E402

STORE = "https://acme-st.sites.bapp.ro/"
HEADERS = {"Authorization": "Token s3cret", "X-App-Slug": "sync"}


@pytest.fixture
def http():
    return FakeHttpClient()


@pytest.fixture
def client(http):
    return BappStoreClient(STORE, "s3cret", http_client=http)


def test_base_url_and_headers(client, http):
    assert client.base_url == "https://acme-st.sites.bapp.ro/api/"
    assert http.base_url == client.base_url
    http.add("GET", CATEGORY_PATH, {"count": 0, "next": None, "previous": None, "results": []})
    client.test_auth()
    assert http.last_call().kwargs["headers"] == HEADERS


def test_builds_its_own_http_client_when_none_given():
    client = BappStoreClient("https://acme-st.sites.bapp.ro", "s3cret")
    assert client.http.base_url == "https://acme-st.sites.bapp.ro/api/"
    assert client.http.provider_name == "bapp_store"


def test_test_auth(client, http):
    http.add("GET", CATEGORY_PATH, {"count": 0, "next": None, "previous": None, "results": []})
    assert client.test_auth() is True
    assert http.last_call().kwargs["params"] == {"page_size": 1}

    def reject(method, path, kwargs):
        raise AuthenticationError("401", status_code=401)

    http.responses.clear()
    http.add("GET", CATEGORY_PATH, reject)
    assert client.test_auth() is False


def test_test_auth_only_swallows_authentication_failures(client, http):
    # A 503 or a timeout is not "bad credentials"; test_auth must let it surface, not report False.
    def server_error(method, path, kwargs):
        raise ProviderError("Company Store server error 503: maintenance", retryable=True, status_code=503)

    http.add("GET", CATEGORY_PATH, server_error)
    with pytest.raises(ProviderError):
        client.test_auth()


def test_sync_task_posts_payload_without_retry(client, http):
    http.add("POST", SYNC_TASK_PATH, FakeResponse(200, {"products": [], "categories": [], "rules_applied": False, "webhook_applied": False}))
    result = client.sync_task({"products": [{"id": "1"}]})
    assert result["rules_applied"] is False
    call = http.last_call()
    assert call.method == "POST" and call.path == SYNC_TASK_PATH
    assert call.kwargs["json"] == {"products": [{"id": "1"}]}
    # FakeHttpClient.call takes direct_response as a named parameter, so it is not in the recorded kwargs.
    assert call.kwargs["retry"] is False
    assert call.kwargs["timeout"] == BappStoreClient.SYNC_TIMEOUT


class _DirectResponseProbe:
    """
    Records the actual value passed for direct_response, unlike FakeHttpClient which consumes it as a
    named parameter and never surfaces it in the recorded kwargs -- so a plain FakeHttpClient-based
    assertion cannot catch direct_response=True being dropped from sync_task.
    """

    def __init__(self):
        self.direct_response = None
        self.base_url = STORE + "api/"

    def call(self, method, path, direct_response=False, headers=None, **kwargs):
        self.direct_response = direct_response
        return FakeResponse(200, {"products": [], "categories": [], "rules_applied": True, "webhook_applied": False})


def test_sync_task_requests_the_raw_response():
    # The real client hands raise_for_status a dict (not a Response) without direct_response=True,
    # which fails on .ok -- a regression FakeHttpClient's own dropped-kwarg quirk cannot catch.
    probe = _DirectResponseProbe()
    client = BappStoreClient(STORE, "s3cret", http_client=probe)
    client.sync_task({"products": []})
    assert probe.direct_response is True


def test_sync_task_maps_error_status(client, http):
    http.add("POST", SYNC_TASK_PATH, FakeResponse(413, text="over 100 products"))
    with pytest.raises(PermanentProviderError, match="over 100 products"):
        client.sync_task({"products": []})


def test_transport_failure_is_a_retryable_provider_error(client, http):
    def time_out(method, path, kwargs):
        raise requests.ReadTimeout("read timed out")

    http.add("POST", SYNC_TASK_PATH, time_out)
    with pytest.raises(ProviderError) as excinfo:
        client.sync_task({"products": []})
    assert excinfo.value.retryable is True


def test_list_categories_follows_next_pages(client, http):
    first = {"count": 3, "next": STORE + "api/" + CATEGORY_PATH + "?page=2&page_size=100", "previous": None, "results": [{"id": 1}, {"id": 2}]}
    second = {"count": 3, "next": None, "previous": "x", "results": [{"id": 3}]}
    pages = iter([first, second])
    http.add("GET", CATEGORY_PATH, lambda method, path, kwargs: next(pages))
    assert client.list_categories() == [{"id": 1}, {"id": 2}, {"id": 3}]
    assert http.calls[0].kwargs["params"] == {"page_size": 100}
    assert http.calls[1].path == first["next"]


def test_find_products_by_code_and_page(client, http):
    http.add("GET", PRODUCT_PATH, {"count": 1, "next": None, "previous": None, "results": [{"code": "SKU-1"}]})
    assert client.find_products(code="SKU-1")["results"] == [{"code": "SKU-1"}]
    assert http.last_call().kwargs["params"] == {"page_size": 100, "page": 1, "code": "SKU-1"}
    client.find_products(page=3)
    assert http.last_call().kwargs["params"] == {"page_size": 100, "page": 3}


def test_export_orders_omits_empty_filters(client, http):
    http.add("GET", ORDERS_EXPORT_PATH, {"results": [], "next_cursor": None})
    client.export_orders(since=None, cursor=None)
    assert http.last_call().kwargs["params"] == {"limit": 50}
    client.export_orders(since="2026-09-01T00:00:00Z", cursor="ORD-000123", limit=10)
    assert http.last_call().kwargs["params"] == {"limit": 10, "since": "2026-09-01T00:00:00Z", "cursor": "ORD-000123"}


def test_export_order_by_number(client, http):
    http.add("GET", ORDER_EXPORT_PATH, {"number": "ORD-000123"})
    assert client.export_order("ORD-000123") == {"number": "ORD-000123"}
    assert http.last_call().kwargs["params"] == {"number": "ORD-000123"}


def test_set_webhook_is_a_sync_task(client, http):
    http.add("POST", SYNC_TASK_PATH, FakeResponse(200, {"webhook_applied": True}))
    assert client.set_webhook("https://panel.bapp.ro/api/webhooks/1/2/order.created/", "abc")["webhook_applied"] is True
    assert http.last_call().kwargs["json"] == {"webhook": {"url": "https://panel.bapp.ro/api/webhooks/1/2/order.created/", "secret": "abc"}}
