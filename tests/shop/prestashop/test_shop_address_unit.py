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
    # produsele intii (dovada cheii), apoi radacina (drepturile) — ambele la magazin
    assert built.recording.urls[0] == f"{SHOP}/api/products"
    assert all(url.startswith(SHOP) for url in built.recording.urls)


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
    assert built.recording.urls[0] == f"{SHOP}/api/products"


def test_a_trailing_slash_does_not_change_the_address():
    built = adapter(domain=f"{SHOP}/")
    built.client.test_auth()
    assert built.recording.urls[0] == f"{SHOP}/api/products"


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
    assert built.recording.urls[0] == f"{SHOP}/api/products"


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


# ── drepturile cheii, citite de la magazin ───────────────────────────────────────────────────

RESOURCE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<prestashop xmlns:xlink="http://www.w3.org/1999/xlink">
 <api shop_name="Sogest">
  <products xlink:href="https://sogest.ro/api/products" get="true"/>
  <orders xlink:href="https://sogest.ro/api/orders" get="true"/>
  <addresses xlink:href="https://sogest.ro/api/addresses" get="true"/>
 </api>
</prestashop>"""


class _Response:
    def __init__(self, text):
        self.text = text


class ResourceClient(RecordingClient):
    """Radacina webservice-ului raspunde XML; restul, ca la un magazin normal."""

    def __init__(self, root_text=RESOURCE_XML, **kwargs):
        super().__init__(**kwargs)
        self.root_text = root_text

    def _execute_request(self, method, path, direct_response=False, headers=None, **kwargs):
        url = self._build_url(path)
        self.urls.append(url)
        if url.rstrip("/").endswith("/api"):
            return _Response(self.root_text)
        return PRODUCTS


def _with_root(root_text=RESOURCE_XML):
    http = ResourceClient(root_text=root_text, base_url=manifest.base_url, auth=NoAuth(),
                          provider_name=manifest.name)
    built = PrestaShopShopAdapter(credentials={"domain": SHOP, "token": "cheie"}, http_client=http)
    built.recording = http  # type: ignore[attr-defined]
    return built


def test_the_permissions_come_from_the_shop_not_from_a_hardcoded_list():
    built = _with_root()
    assert built.client.api_resources() == {"products", "orders", "addresses"}


def test_a_key_without_orders_is_reported_as_missing_that_permission():
    built = _with_root()
    result = built.test_connection()
    assert result.success is False
    assert "orders" not in result.message          # orders EXISTA in XML-ul de mai sus
    assert "countries" in result.message           # astea lipsesc cu adevarat


def test_a_shop_whose_root_does_not_answer_is_still_a_good_connection():
    """Pe unele magazine radacina crapa (bug de randare); o cheie care merge ramine buna."""
    built = _with_root(root_text="Fatal error: Uncaught TypeError ...")
    result = built.test_connection()
    assert result.success is True


# ── pozele produselor, ca adrese publice ─────────────────────────────────────────────────────

PRODUCT_WITH_IMAGES = {
    "id": "52928",
    "reference": "TL-CLE-165",
    "name": "Cleste",
    "id_default_image": "120764",
    "associations": {"images": [{"id": "120763"}, {"id": "120764"}]},
}


def test_the_photos_are_public_urls_of_the_shop():
    """Verificat pe un magazin real: `/img/p/<cifre>/<id>.jpg` raspunde 200 fara autentificare."""
    from bapp_connectors.providers.shop.prestashop.mappers import product_from_prestashop

    product = product_from_prestashop(PRODUCT_WITH_IMAGES, SHOP)
    assert [photo.url for photo in product.photos] == [
        f"{SHOP}/img/p/1/2/0/7/6/4/120764.jpg",   # imaginea implicita, prima
        f"{SHOP}/img/p/1/2/0/7/6/3/120763.jpg",
    ]


def test_the_webservice_image_path_is_not_used():
    """Adresa din `/api/images/...` cere cheia, deci ar fi o poza rupta in orice `<img src>`."""
    from bapp_connectors.providers.shop.prestashop.mappers import product_from_prestashop

    product = product_from_prestashop(PRODUCT_WITH_IMAGES, SHOP)
    assert all("/api/" not in photo.url for photo in product.photos)


def test_one_image_comes_back_as_a_dict_not_a_list():
    """PrestaShop colapseaza lista de un element; fara asta produsul ar ramine fara poza."""
    from bapp_connectors.providers.shop.prestashop.mappers import product_from_prestashop

    data = dict(PRODUCT_WITH_IMAGES, associations={"images": {"id": "999"}}, id_default_image="")
    product = product_from_prestashop(data, SHOP)
    assert [photo.url for photo in product.photos] == [f"{SHOP}/img/p/9/9/9/999.jpg"]


def test_a_product_without_images_has_no_photos():
    from bapp_connectors.providers.shop.prestashop.mappers import product_from_prestashop

    data = {"id": "1", "reference": "X", "associations": {}, "id_default_image": ""}
    assert product_from_prestashop(data, SHOP).photos == []


def test_without_a_shop_url_no_photo_is_invented():
    from bapp_connectors.providers.shop.prestashop.mappers import product_from_prestashop

    assert product_from_prestashop(PRODUCT_WITH_IMAGES, "").photos == []


def test_the_listing_passes_the_shop_url_down():
    built = adapter()
    built.recording.urls.clear()

    class _Client(RecordingClient):
        pass

    built.client.http._execute_request = lambda *a, **k: {"products": [PRODUCT_WITH_IMAGES]}  # type: ignore[method-assign]
    page = built.get_products()
    assert [photo.url for photo in page.items[0].photos] == [
        f"{SHOP}/img/p/1/2/0/7/6/4/120764.jpg",
        f"{SHOP}/img/p/1/2/0/7/6/3/120763.jpg",
    ]
