"""Temu primește factura doar din galeria lui: PDF-ul se urcă întâi acolo (semnătură
`temu.pay.tax.get.galerie.signature` + `/api/galerie/general_file`), apoi linkul din galerie
merge în `temu.pay.tax.merchant.upload.invoice`. Cu un link extern Temu răspunde 7000000."""
import pytest

from bapp_connectors.core.errors import ProviderError
from bapp_connectors.providers.shop.temu.adapter import TemuShopAdapter
from tests.fake_http import fake_response
from tests.shop.temu.conftest import CREDS, ok

GALERIE_URL = "https://openapi-b-eu.temu.com/e-tax-merchant-external/21ae/abc.pdf"



class _PdfResponse:
    status_code, ok, content, headers = 200, True, b"%PDF-1.4 test", {"content-type": "application/pdf"}


def _setup(fake, upload_answer=None):
    fake.add("GET", "portal.example.test", lambda m, p, k: _PdfResponse())
    fake.add("POST", "/api/galerie/general_file",
             lambda m, p, k: fake_response(upload_answer or {"url": GALERIE_URL, "md5": "0x1"}))

    def router(method, path, kwargs):
        if kwargs["json"]["type"] == "temu.pay.tax.get.galerie.signature":
            return ok({"signature": "SIG"})
        return ok({"success": True})
    fake.add("POST", "openapi/router", router)


def test_invoice_pdf_goes_through_the_temu_galerie(fake):
    _setup(fake)
    adapter = TemuShopAdapter(CREDS, http_client=fake, config={})
    assert adapter.attach_invoice("PO-1", "https://portal.example.test/f/abc?format=file", name="FF 074558") is True
    upload = next(c for c in fake.calls if "/api/galerie/general_file" in c.path)
    assert upload.path == "https://openapi-b-eu.temu.com/api/galerie/general_file"
    assert upload.kwargs["data"] == {"sign": "SIG"}
    assert upload.kwargs["files"]["file"] == ("FF 074558.pdf", b"%PDF-1.4 test", "application/pdf")
    body = fake.last_call().kwargs["json"]
    assert body["type"] == "temu.pay.tax.merchant.upload.invoice" and body["fileUrl"] == GALERIE_URL


def test_a_galerie_url_is_sent_as_is(fake):
    _setup(fake)
    adapter = TemuShopAdapter(CREDS, http_client=fake, config={})
    adapter.attach_invoice("PO-1", GALERIE_URL, name="FF 1")
    assert not any("/api/galerie/general_file" in c.path for c in fake.calls)
    assert fake.last_call().kwargs["json"]["fileUrl"] == GALERIE_URL


def test_galerie_refusal_is_an_error(fake):
    _setup(fake, upload_answer={"error_code": 4001})
    adapter = TemuShopAdapter(CREDS, http_client=fake, config={})
    with pytest.raises(ProviderError):
        adapter.attach_invoice("PO-1", "https://portal.example.test/f/abc?format=file", name="FF 1")
    assert not any(c.kwargs.get("json", {}).get("type") == "temu.pay.tax.merchant.upload.invoice" for c in fake.calls)
