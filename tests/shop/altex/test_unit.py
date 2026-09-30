"""Altex Marketplace adapter.

The signature vectors below were computed with PHP 8.5 exactly as the spec describes
(json_decode + http_build_query(..., '|', PHP_QUERY_RFC3986) + hash('sha512')), so they
pin the Python port to the server's canonicalisation. API responses are mocked from the
Swagger spec embedded in https://marketplace.altex.ro/api_doc.
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from urllib.parse import parse_qs, parse_qsl, urlparse

import pytest
import responses

from bapp_connectors.core.dto import OrderStatus, PaymentStatus, PaymentType
from bapp_connectors.core.errors import AuthenticationError, ValidationError
from bapp_connectors.providers.shop.altex.adapter import AltexShopAdapter
from bapp_connectors.providers.shop.altex.client import build_query, sign

API = "https://marketplace.altex.ro/v2.0/"
CREDS = {"public_key": "PUB", "private_key": "PRIV"}

PHP_BODY = {"0": {"offer_id": "17090", "price": 199.9, "selling_price": 19.0, "vat": 19, "status": True,
                  "promo": False, "note": None, "name": "Căști Bluetooth & mic",
                  "stock": [{"size": 42757, "quantity": 3}], "tags": ["a b", "c/d"]}}
PHP_BODY_QUERY = ("0%5Boffer_id%5D=17090|0%5Bprice%5D=199.9|0%5Bselling_price%5D=19|0%5Bvat%5D=19|0%5Bstatus%5D=1|"
                  "0%5Bpromo%5D=0|0%5Bname%5D=C%C4%83%C8%99ti%20Bluetooth%20%26%20mic|"
                  "0%5Bstock%5D%5B0%5D%5Bsize%5D=42757|0%5Bstock%5D%5B0%5D%5Bquantity%5D=3|"
                  "0%5Btags%5D%5B0%5D=a%20b|0%5Btags%5D%5B1%5D=c%2Fd")
PHP_BODY_SIGNATURE = ("3009722fbdeddc0ef64ed481c6d23471addf9bf95a8116764896a4b72004a4e858737164596b41e367c30562d7"
                      "4699d943d9684601ee9db9772201fbcf9339f61a70")
PHP_FORM = {"name": "Factura MERT107659", "invoice_number": "MERT107659", "products": ["11", "12"]}
PHP_FORM_SIGNATURE = ("3009dc50487c89cdb50c5fb2a80d691fe23abc04b586478d72aba46d770b25881d377d416180842c18e6b5af151d"
                      "5d5bcfe8b78ffd078da10d2d078c4af6a8bbcdad")

ORDER = {
    "order_id": 11408044, "order_code": "ATX000011408044-227", "status": 1, "delivery_mode": 5, "payment_mode": 1,
    "total_price": "219.90", "products_price": "199.90", "shipping_tax": "20.00", "payment_tax": "0.00",
    "order_date": "2026-09-29T10:47:04+00:00",
    "billing_customer_name": "Ion Pop", "billing_phone_number": "0722111222", "billing_country": "RO",
    "billing_address": "Str. Lunga 3", "billing_city": "Iasi", "billing_region": "IS",
    "billing_company_name": "Client SRL", "billing_company_code": "RO123456",
    "shipping_customer_name": "Ion Pop", "shipping_phone_number": "0722111222", "shipping_country": "RO",
    "shipping_address": "Str. Lunga 3", "shipping_city": "Iasi", "shipping_region": "IS",
    "products": [{"id": 5501, "seller_product_code": "SKU-1", "product_id": "65f0a1b2c3d4e5f6a7b8c9d0",
                  "name": "Casti", "catalog_price": "249.90", "selling_price": "199.90", "row_total": "199.90",
                  "quantity": 1, "status": 1, "vat": 19, "aditional_data": {"offer_id": 17090}}],
    "awbs": [], "invoices": [],
}


def _ok(data=None, status=200):
    return {"message": [], "status": "success", "data": data if data is not None else []}


class TestSignature:

    def test_query_string_matches_php_http_build_query(self):
        assert build_query(PHP_BODY) == PHP_BODY_QUERY

    def test_json_body_signature_matches_php(self):
        assert sign("PUBKEY123", "PRIVKEY456", PHP_BODY, datetime(2026, 9, 30)) == PHP_BODY_SIGNATURE

    def test_multipart_form_signature_matches_php(self):
        assert sign("PUBKEY123", "PRIVKEY456", PHP_FORM, datetime(2026, 9, 30)) == PHP_FORM_SIGNATURE

    @responses.activate
    def test_get_signs_the_query_params(self):
        responses.add(responses.GET, API + "sales/order/", json=_ok({"items": [], "current_page": 1, "total_pages": 1}))
        AltexShopAdapter(credentials=CREDS).client.list_orders(start_date="2026-09-01", page=2, per_page=50)
        req = responses.calls[0].request
        params = {"page_nr": 2, "items_per_page": 50, "start_date": "2026-09-01"}
        assert req.headers["X-Request-Public-Key"] == "PUB"
        assert req.headers["X-Request-Signature"][4:] == sign("PUB", "PRIV", params)[4:]
        assert parse_qs(urlparse(req.url).query)["page_nr"] == ["2"]  # the URL itself uses '&'


class TestOrders:

    @responses.activate
    def test_order_mapping(self):
        responses.add(responses.GET, API + "sales/order/11408044/", json=_ok(ORDER))
        order = AltexShopAdapter(credentials=CREDS).get_order("11408044")
        assert (order.order_id, order.external_id) == ("ATX000011408044-227", "11408044")
        assert order.status == OrderStatus.PENDING and order.raw_status == "1"
        assert order.payment_type == PaymentType.CASH_ON_DELIVERY and order.payment_status == PaymentStatus.UNPAID
        assert order.total == Decimal("219.90") and order.currency == "RON"
        assert (order.billing.company_name, order.billing.vat_id) == ("Client SRL", "RO123456")
        assert order.shipping_address.city == "Iasi" and order.shipping_address.region == "IS"
        item = order.items[0]
        assert (item.item_id, item.sku, item.unit_price, item.tax_rate) == ("5501", "SKU-1", Decimal("199.90"), Decimal("19"))
        assert item.extra["offer_id"] == 17090
        assert order.extra["shipping_tax"] == "20.00"

    @responses.activate
    def test_listing_reads_each_order_in_full(self):
        responses.add(responses.GET, API + "sales/order/", json=_ok({
            "current_page": 1, "total_pages": 2, "total_items": 101,
            "items": [{"order_id": 11408044, "order_code": "ATX000011408044-227", "status": 1}]}))
        responses.add(responses.GET, API + "sales/order/11408044/", json=_ok(ORDER))
        result = AltexShopAdapter(credentials=CREDS).get_orders(since=datetime(2026, 9, 1))
        assert result.items[0].items[0].sku == "SKU-1"
        assert result.cursor == "2" and result.has_more is True
        q = parse_qs(urlparse(responses.calls[0].request.url).query)
        assert q["start_date"] == ["2026-09-01"]

    @responses.activate
    def test_acknowledge_sets_in_progress(self):
        responses.add(responses.PUT, API + "sales/order/11408044/", status=202, json=_ok())
        responses.add(responses.GET, API + "sales/order/11408044/", json=_ok({**ORDER, "status": 2}))
        order = AltexShopAdapter(credentials=CREDS).acknowledge_order("11408044")
        assert json.loads(responses.calls[0].request.body) == {"status": 2}
        assert order.status == OrderStatus.ACCEPTED

    @responses.activate
    def test_cancel_carries_the_reason(self):
        responses.add(responses.PUT, API + "sales/order/1/", status=202, json=_ok())
        responses.add(responses.GET, API + "sales/order/1/", json=_ok({**ORDER, "status": 7}))
        AltexShopAdapter(credentials=CREDS).update_order_status("1", OrderStatus.CANCELLED, reason="out_of_stock")
        assert json.loads(responses.calls[0].request.body) == {"status": 7, "cancellationReason": 1}

    @responses.activate
    def test_invalid_transition_is_an_error(self):
        responses.add(responses.PUT, API + "sales/order/1/", status=400,
                      json={"message": ["One or more order products with invalid status"], "status": "error", "data": []})
        with pytest.raises(Exception, match="invalid status"):
            AltexShopAdapter(credentials=CREDS).update_order_status("1", OrderStatus.SHIPPED)

    @responses.activate
    def test_bad_keys(self):
        responses.add(responses.GET, API + "sales/order/", status=401,
                      json={"message": ["Access Denied."], "status": "error", "data": []})
        with pytest.raises(AuthenticationError, match="Access Denied"):
            AltexShopAdapter(credentials=CREDS).client.list_orders()
        assert AltexShopAdapter(credentials=CREDS).test_connection().success is False


class TestOffers:

    @responses.activate
    def test_offers_become_products(self):
        responses.add(responses.GET, API + "catalog/offer/", json=_ok({
            "current_page": 1, "total_pages": 1, "items": [
                {"id": "17090", "product_id": "65f0", "seller_product_code": "SKU-1", "status": 1, "price": "249.90",
                 "selling_price": "199.90", "stock": [{"quantity": 4}]}]}))
        product = AltexShopAdapter(credentials=CREDS).get_products().items[0]
        assert (product.product_id, product.sku, product.price, product.stock) == ("17090", "SKU-1", Decimal("199.90"), 4)

    @responses.activate
    def test_stock_update(self):
        responses.add(responses.PUT, API + "catalog/offer/17090/stock/", json=_ok())
        AltexShopAdapter(credentials=CREDS).update_product_stock("17090", 12)
        assert json.loads(responses.calls[0].request.body) == {"stock": 12}

    @responses.activate
    def test_price_update_sets_price_and_selling_price(self):
        responses.add(responses.PUT, API + "catalog/offer/17090/", json=_ok())
        AltexShopAdapter(credentials=CREDS).update_product_price("17090", Decimal("189.90"), "RON")
        assert json.loads(responses.calls[0].request.body) == {"price": 189.9, "selling_price": 189.9}

    def test_price_in_other_currency_is_refused(self):
        with pytest.raises(ValidationError):
            AltexShopAdapter(credentials=CREDS).update_product_price("1", Decimal("10"), "EUR")


class TestDocuments:

    @responses.activate
    def test_invoice_upload_uses_php_array_fields_and_signs_the_form(self):
        responses.add(responses.GET, API + "sales/order/11408044/", json=_ok(ORDER))
        responses.add(responses.POST, API + "sales/order/11408044/invoice/", status=202, json=_ok())
        AltexShopAdapter(credentials=CREDS).upload_invoice("11408044", b"%PDF-1.7", "MERT107659")
        req = responses.calls[1].request
        assert b'name="products[]"' in req.body and b'name="media"' in req.body
        form = {"name": "Factura MERT107659", "invoice_number": "MERT107659", "products": ["5501"]}
        assert req.headers["X-Request-Signature"][4:] == sign("PUB", "PRIV", form)[4:]

    @responses.activate
    def test_attach_awb_matches_courier_by_name(self):
        responses.add(responses.GET, API + "sales/courier/", json=_ok([{"id": 2, "name": "Fan Courier"},
                                                                       {"id": 7, "name": "Cargus"}]))
        responses.add(responses.POST, API + "sales/order/1/awb/", status=201, json=_ok({"awb": {"number": "123"}}))
        AltexShopAdapter(credentials=CREDS).attach_awb("1", b"%PDF", "2228300120233", "fancourier")
        assert b'name="courier_id"\r\n\r\n2' in responses.calls[1].request.body

    @responses.activate
    def test_unknown_courier(self):
        responses.add(responses.GET, API + "sales/courier/", json=_ok([{"id": 7, "name": "Cargus"}]))
        with pytest.raises(ValidationError, match="no courier"):
            AltexShopAdapter(credentials=CREDS).attach_awb("1", b"%PDF", "1", "dhl")


class TestReturns:

    RMA = {"rma_id": 258, "order_id": 1473, "rma_status": 4, "customer_name": "Popescu Ion",
           "customer_phone_number": "0765433321", "created_date": "2026-09-20T12:16:01+00:00",
           "customer_city": "Bucuresti", "bank_iban": "RO54INGB0000000000001111",
           "products": [{"name": "Casti", "id": "65f0a1b2c3d4e5f6a7b8c9d0", "action": 2, "reason": 7, "rma_line_id": 272}]}

    @responses.activate
    def test_returns_joined_to_the_order(self):
        from bapp_connectors.core.dto import ReturnKind, ReturnReason

        responses.add(responses.GET, API + "sales/rma/", json=_ok({
            "current_page": 1, "total_pages": 1, "items": [{"rma_id": 258, "order_id": 1473, "rma_status": 4}]}))
        responses.add(responses.GET, API + "sales/rma/258/", json=_ok(self.RMA))
        responses.add(responses.GET, API + "sales/order/1473/", json=_ok(ORDER))
        rets = AltexShopAdapter(credentials=CREDS).get_returns(datetime(2026, 9, 1), datetime(2026, 10, 1))
        assert len(rets) == 1
        ret = rets[0]
        assert (ret.external_id, ret.external_order_id, ret.kind) == ("258", "1473", ReturnKind.RETURN)
        assert ret.status_label == "Resolved"
        line = ret.lines[0]
        assert (line.external_line_id, line.sku, line.reason) == ("272", "SKU-1", ReturnReason.WRONG_ITEM)
        assert line.unit_price == Decimal("199.90")  # from the order line by product id
        assert ret.refund.amount == Decimal("199.90") and ret.refund.currency == "RON"
        q = parse_qs(urlparse(responses.calls[0].request.url).query)
        assert q["created_at"] == ["2026-09-01"]

    @responses.activate
    def test_rma_after_until_is_dropped(self):
        responses.add(responses.GET, API + "sales/rma/", json=_ok({
            "current_page": 1, "total_pages": 1, "items": [{"rma_id": 258}]}))
        responses.add(responses.GET, API + "sales/rma/258/", json=_ok(self.RMA))
        responses.add(responses.GET, API + "sales/order/1473/", json=_ok(ORDER))
        rets = AltexShopAdapter(credentials=CREDS).get_returns(datetime(2026, 9, 1), datetime(2026, 9, 10))
        assert rets == []

    @responses.activate
    def test_unix_created_date(self):
        from bapp_connectors.providers.shop.altex.returns import rma_date

        assert rma_date(1702383361).year == 2023


class TestGenerateAwb:

    @responses.activate
    def test_altex_books_the_courier_and_returns_the_label(self):
        import base64

        responses.add(responses.GET, API + "sales/courier/", json=_ok([{"id": 2, "name": "Fan Courier", "forGenerateAwb": True}]))
        responses.add(responses.POST, API + "sales/order/1/awb/generate", status=201, json=_ok({
            "awb_number": "1234567890", "document": base64.b64encode(b"%PDF-1.4").decode(), "document_type": "pdf"}))
        sender = {"address_id": 5, "name": "Depozit", "contact_person": "Ana", "phone": "0722 333 444",
                  "address": "Str. Fabricii 1", "county": "Iasi", "city": "Iasi", "postal_code": "700001"}
        label = AltexShopAdapter(credentials=CREDS).generate_awb("1", "fancourier", sender, weight=2.0,
                                                                 declared_value=199.9)
        assert label.tracking_number == "1234567890" and label.label_pdf == b"%PDF-1.4"
        # awb/generate has no file, so the form is url-encoded and signed as-is
        body = responses.calls[1].request.body
        form = dict(parse_qsl(body.decode() if isinstance(body, bytes) else body))
        assert form["courier_id"] == "2" and form["address_id"] == "5"
        assert form["sender_phone"] == "0722333444"  # 10 digits, no separators
        assert form["order_awb_format"] == "0"

    @responses.activate
    def test_courier_without_awb_support_is_refused(self):
        responses.add(responses.GET, API + "sales/courier/", json=_ok([{"id": 3, "name": "DHL", "forGenerateAwb": False}]))
        with pytest.raises(ValidationError, match="does not support AWB"):
            AltexShopAdapter(credentials=CREDS).generate_awb("1", "dhl", {"address_id": 1})

    @responses.activate
    def test_generate_is_sent_once(self):
        from bapp_connectors.core.http import NoAuth, ResilientHttpClient, RetryPolicy

        responses.add(responses.GET, API + "sales/courier/", json=_ok([{"id": 2, "name": "Fan Courier", "forGenerateAwb": True}]))
        responses.add(responses.POST, API + "sales/order/1/awb/generate", status=503, json=_ok())
        http = ResilientHttpClient(base_url=API, auth=NoAuth())
        http.retry_policy = RetryPolicy(max_retries=3, base_delay=0, max_delay=0)
        from bapp_connectors.core.errors import ProviderError
        with pytest.raises(ProviderError):
            AltexShopAdapter(credentials=CREDS, http_client=http).generate_awb("1", "fan", {"address_id": 1})
        assert sum(c.request.url.endswith("awb/generate") for c in responses.calls) == 1
