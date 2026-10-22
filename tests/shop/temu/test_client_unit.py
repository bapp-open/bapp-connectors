import pytest
import requests

from bapp_connectors.core.errors import (
    AuthenticationError,
    ConnectorError,
    RateLimitError,
    UnsupportedFeatureError,
    ValidationError,
)
from bapp_connectors.providers.shop.temu.client import ROUTERS, TemuApiClient
from bapp_connectors.providers.shop.temu.errors import TemuError
from tests.shop.temu.conftest import err, ok


def test_call_posts_signed_json_to_regional_router(client, fake):
    fake.add("POST", "openapi/router", ok({"mallId": 1}))
    assert client.call("bg.local.mall.info.get") == {"mallId": 1}
    call = fake.last_call()
    assert call.path == ROUTERS["eu"]
    body = call.kwargs["json"]
    assert body["type"] == "bg.local.mall.info.get" and body["access_token"] == "tok"
    assert body["app_key"] == "f9d5cc9313893a20d5aa85c654e8f503"
    assert body["sign_method"] == "md5" and body["data_type"] == "JSON" and body["timestamp"].isdigit()
    assert len(body["sign"]) == 32 and body["sign"].isupper()
    assert call.kwargs["headers"]["Content-Type"] == "application/json"


def test_region_selects_router():
    assert TemuApiClient("k", "s", "t", region="global").base_url == ROUTERS["global"]
    assert TemuApiClient("k", "s", "t", region="us").base_url == ROUTERS["us"]
    with pytest.raises(ValueError):
        TemuApiClient("k", "s", "t", region="mars")


@pytest.mark.parametrize(
    "code,exc",
    [
        (3000030, AuthenticationError),
        (3000032, AuthenticationError),
        (130010001, ValidationError),
        (150010003, ValidationError),
        (200040005, UnsupportedFeatureError),
        (200030004, UnsupportedFeatureError),
        (150010005, RateLimitError),
    ],
)
def test_call_raises_on_success_false_mapped(client, fake, code, exc):
    fake.add("POST", "openapi/router", err(code, "boom"))
    with pytest.raises(exc):
        client.call("x")


def test_call_raises_on_success_false_unknown_code(client, fake):
    fake.add("POST", "openapi/router", err(7000000, "BUSINESS_SERVICE_ERROR"))
    with pytest.raises(TemuError) as e:
        client.call("x")
    assert e.value.error_code == 7000000 and e.value.request_id == "eu-2"
    assert "BUSINESS_SERVICE_ERROR" in str(e.value) and "x" in str(e.value)


def test_call_raises_on_non_dict_response(client, fake):
    fake.add("POST", "openapi/router", "<html>nope</html>")
    with pytest.raises(ConnectorError):
        client.call("x")


def test_list_goods_always_sends_search_filters(client, fake):
    fake.add("POST", "openapi/router", ok(None))
    assert client.list_goods(page_no=1) is None
    body = fake.last_call().kwargs["json"]
    assert body["type"] == "bg.local.goods.list.query"
    assert body["goodsSearchType"] == 1 and body["statusFilterType"] == 1
    assert body["pageNo"] == 1 and body["pageSize"] == 50


def test_non_idempotent_calls_disable_retry(client, fake):
    fake.add("POST", "openapi/router", ok({"goodsId": 1}))
    client.add_goods_v3({"goodsBasic": {}})
    assert fake.last_call().kwargs.get("retry") is False
    fake.add("POST", "openapi/router", ok({}))
    client.token_info()
    assert "retry" not in fake.last_call().kwargs or fake.last_call().kwargs["retry"] is True


def test_transport_error_is_wrapped(client, fake):
    def boom(method, path, kwargs):
        raise requests.ConnectionError("dns")

    fake.add("POST", "openapi/router", boom)
    with pytest.raises(ConnectorError) as e:
        client.call("x")
    assert not isinstance(e.value, requests.RequestException)


def test_download_signed_uses_toa_headers(client, fake):
    class Resp:
        content = b"%PDF-1.4"

    def route(method, path, kwargs):
        assert method == "GET"
        return Resp()

    fake.add("GET", "files.example.test", route)
    assert client.download_signed("https://files.example.test/label.pdf") == b"%PDF-1.4"
    assert fake.last_call().kwargs["direct_response"] is True
    headers = fake.last_call().kwargs["headers"]
    assert set(headers) >= {"toa-app-key", "toa-access-token", "toa-random", "toa-timestamp", "toa-sign"}
    assert headers["toa-app-key"] == "f9d5cc9313893a20d5aa85c654e8f503" and headers["toa-access-token"] == "tok"
