from bapp_connectors.core.capabilities import OrderLookupCapability
from bapp_connectors.providers.shop.gomag.adapter import GomagShopAdapter
from bapp_connectors.providers.shop.gomag.manifest import manifest
from tests.fake_http import FakeHttpClient


def _adapter(fake):
    return GomagShopAdapter(credentials={"token": "t", "shop_site": "https://s.ro"}, http_client=fake)


def test_declares_capability():
    assert OrderLookupCapability in manifest.capabilities


def test_finds_by_number():
    fake = FakeHttpClient()
    fake.add("GET", "order/read/json", {"orders": {"55": {"id": "55", "number": "2045", "email": "a@b.ro"}}})
    order = _adapter(fake).find_order_by_reference("2045")
    assert order is not None and order.order_id == "2045"


def test_empty_response_is_none():
    fake = FakeHttpClient()
    fake.add("GET", "order/read/json", {"orders": []})
    assert _adapter(fake).find_order_by_reference("2045") is None


def test_one_order_is_asked_for_by_its_number(monkeypatch):
    """Gomag filtreaza dupa `number`. Cu orice alta cheie ignora filtrul si intoarce
    pagina de comenzi recente, iar cautarea concluziona ca nu exista comanda."""
    sent: dict = {}

    class FakeHttp:
        def call(self, method, path, **kwargs):
            sent.update(method=method, path=path, params=kwargs.get("params"))
            return {"orders": {}}

    from bapp_connectors.providers.shop.gomag.client import GomagApiClient

    GomagApiClient(http_client=FakeHttp()).get_order("1354673")

    assert sent["path"] == "order/read/json"
    assert sent["params"] == {"number": "1354673"}
