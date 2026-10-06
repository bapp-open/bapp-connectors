"""Gomag must authenticate on the client the registry injects, not only on its own.

`registry.create_adapter` ALWAYS builds a `ResilientHttpClient` and passes it in, and for
`AuthStrategy.CUSTOM` it builds it with `NoAuth` — the comment in the registry says "adapter
handles its own auth". The Gomag adapter set its two headers only in the `http_client is
None` branch, which is the test path: in production every call went out unauthenticated and
Gomag answered `{"error": 100, "message": "Missing Api User"}`. The withdrawal page reported
that as "order not found", on a shop that was connected and working.

Same shape as the PrestaShop placeholder-host bug; this test pins the Gomag half of it.
"""

from bapp_connectors.core.http import NoAuth, ResilientHttpClient
from bapp_connectors.core.registry import registry
from bapp_connectors.providers.shop.gomag.adapter import GomagShopAdapter

CREDENTIALS = {"token": "cheie-secreta", "shop_site": "https://www.exemplu.ro"}


def _headers(adapter: GomagShopAdapter) -> dict:
    return adapter.client.http.auth.apply_to_headers({})


def test_the_adapter_authenticates_the_client_it_is_given():
    injected = ResilientHttpClient(base_url="https://api.gomag.ro/api/v1/", auth=NoAuth())

    adapter = GomagShopAdapter(CREDENTIALS, http_client=injected)

    assert _headers(adapter) == {
        "ApiShop": "https://www.exemplu.ro",
        "Apikey": "cheie-secreta",
        "User-Agent": "BappConnectors/1.0",
        "Accept": "*/*",
    }


def test_the_adapter_still_builds_its_own_client_when_given_none():
    adapter = GomagShopAdapter(CREDENTIALS)

    assert adapter.client.http.base_url == "https://api.gomag.ro/api/v1/"
    assert _headers(adapter)["Apikey"] == "cheie-secreta"


def test_an_adapter_built_the_way_production_builds_it_is_authenticated():
    """The real path: through the registry, which injects the client."""
    adapter = registry.create_adapter("shop", "gomag", CREDENTIALS)
    assert isinstance(adapter, GomagShopAdapter)

    assert type(adapter.client.http.auth).__name__ != "NoAuth"
    assert _headers(adapter)["ApiShop"] == "https://www.exemplu.ro"
