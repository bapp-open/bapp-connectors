"""Cererile pleacă spre magazinul clientului, nu spre hostul placeholder din manifest.

Bug-ul pe care îl apără fișierul ăsta a stat în producție: `registry.create_adapter` injectează
ÎNTOTDEAUNA un `ResilientHttpClient` construit din `manifest.base_url`
(`https://placeholder.prestashop.com/api/`), iar clientul PrestaShop trimitea căi relative. Așa
că fiecare cerere pleca spre placeholder, eșua din DNS, iar `test_connection` raporta
„Authentication failed" — omul și-a refăcut degeaba cheia de webservice.

Testele vechi n-aveau cum: toate injectează un fake care potrivește răspunsurile după o bucată
din cale, deci hostul nu conta. De asta testul ăsta construiește adapterul exact ca registry-ul
și se uită la URL-ul care ar pleca pe fir.
"""

from __future__ import annotations

import pytest

from bapp_connectors.core.errors import ConfigurationError
from bapp_connectors.core.http import NoAuth, ResilientHttpClient
from bapp_connectors.providers.shop.prestashop.adapter import PrestaShopShopAdapter
from bapp_connectors.providers.shop.prestashop.manifest import manifest

SHOP = "https://sogest.ro"
PRODUCTS = {"products": [{"id": "1"}]}


class RecordingClient(ResilientHttpClient):
    """Clientul injectat de registry, cu fir tăiat: reține URL-ul final, nu trimite nimic."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.urls: list[str] = []

    def _execute_request(self, method, path, direct_response=False, headers=None, **kwargs):
        self.urls.append(self._build_url(path))
        return PRODUCTS


def registry_style_client() -> RecordingClient:
    """Exact ce construiește `registry.create_adapter` pentru un provider cu auth CUSTOM."""
    return RecordingClient(base_url=manifest.base_url, auth=NoAuth(), provider_name=manifest.name)


def adapter(domain: str = SHOP, **config) -> PrestaShopShopAdapter:
    http = registry_style_client()
    built = PrestaShopShopAdapter(
        credentials={"domain": domain, "token": "cheie"},
        http_client=http,
        config=config or None,
    )
    built.recording = http  # type: ignore[attr-defined]
    return built


def test_the_manifest_base_url_is_a_placeholder_not_a_shop():
    """Dacă asta se schimbă, restul testului nu mai dovedește nimic."""
    assert "placeholder" in manifest.base_url


def test_a_call_goes_to_the_shop_address():
    built = adapter()
    built.client.test_auth()
    assert built.recording.urls == [f"{SHOP}/api/products"]


def test_the_injected_client_is_moved_onto_the_shop_as_well():
    """Chiar daca cineva scrie mai tirziu o cale relativa, nu mai are cum sa ajunga la placeholder."""
    built = adapter()
    assert built.recording.base_url == f"{SHOP}/api/"
    assert built.recording._build_url("orders") == f"{SHOP}/api/orders"


def test_nothing_goes_to_the_placeholder_host():
    built = adapter()
    built.client.test_auth()
    assert not any("placeholder" in url for url in built.recording.urls)


def test_a_shop_url_that_already_ends_in_api_is_not_doubled():
    built = adapter(domain=f"{SHOP}/api")
    built.client.test_auth()
    assert built.recording.urls == [f"{SHOP}/api/products"]


def test_a_trailing_slash_does_not_change_the_address():
    built = adapter(domain=f"{SHOP}/")
    built.client.test_auth()
    assert built.recording.urls == [f"{SHOP}/api/products"]


def test_a_connection_without_a_shop_address_says_so():
    """Fără adresă, mai bine o eroare care spune ce lipsește decât o cerere spre nicăieri."""
    built = adapter(domain="")
    with pytest.raises(ConfigurationError) as error:
        built.client.test_auth()
    assert "shop address" in str(error.value).lower()
    assert built.recording.urls == []


def test_the_query_auth_variant_goes_to_the_shop_too():
    built = adapter(use_query_auth=True)
    built.client.test_auth()
    assert built.recording.urls == [f"{SHOP}/api/products"]


def test_test_connection_reports_what_really_failed():
    """Un DNS căzut nu mai iese ca «authentication failed»."""

    class BrokenClient(RecordingClient):
        def _execute_request(self, method, path, direct_response=False, headers=None, **kwargs):
            raise OSError("Max retries exceeded with url: /api/products")

    http = BrokenClient(base_url=manifest.base_url, auth=NoAuth(), provider_name=manifest.name)
    built = PrestaShopShopAdapter(credentials={"domain": SHOP, "token": "cheie"}, http_client=http)
    result = built.test_connection()
    assert result.success is False
    assert "Max retries" in result.message
    assert "Authentication failed" not in result.message
