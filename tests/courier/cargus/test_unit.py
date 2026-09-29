"""Cargus adapter against the UrgentOnlineAPI OpenAPI export (mocked HTTP).

The host and the gateway's 401 shape were confirmed live; authenticated calls were not
(no subscription key).
"""

from __future__ import annotations

import base64
import json
from urllib.parse import parse_qs, urlparse

import pytest
import responses

from bapp_connectors.core.dto import Address, Parcel, Shipment, ShipmentStatus
from bapp_connectors.core.errors import AuthenticationError, ProviderError, ValidationError
from bapp_connectors.providers.courier.cargus.adapter import CargusCourierAdapter
from bapp_connectors.providers.courier.cargus.mappers import map_event

API = "https://urgentcargus.azure-api.net/api/"
CREDS = {"subscription_key": "k" * 32, "username": "u", "password": "p", "pickup_location_id": "201266091"}
RECIPIENT = Address(street="Str 11 Iunie", city="Iasi", region="Iasi", postal_code="700259", country="RO",
                    extra={"name": "Ion Pop", "phone": "0740 123 123", "email": "x@y.ro", "number": "14", "flat": "3"})


def _login():
    responses.add(responses.POST, API + "LoginUser", json="TOKEN123")


def _create(barcode="1234567890"):
    responses.add(responses.POST, API + "Awbs/WithGetAwb", json=[{
        "BarCode": barcode, "ParcelCodes": [{"Code": barcode + "001"}], "ShippingCost": {"GrandTotal": 17.85}}])
    responses.add(responses.GET, API + "AwbDocuments", json=base64.b64encode(b"%PDF-1.4 cargus").decode())


def _shipment(**extra):
    return Shipment(recipient=RECIPIENT, parcels=[Parcel(weight=1.3, length=20, width=20, height=10)],
                    extra={"content": "Carti", "reference": "CMD-1", **extra})


def _body() -> dict:
    return json.loads(next(c.request.body for c in responses.calls if c.request.url.endswith("WithGetAwb")))


class TestGenerateAwb:

    @responses.activate
    def test_awb_and_base64_label(self):
        _login()
        _create()
        label = CargusCourierAdapter(credentials=CREDS).generate_awb(_shipment())
        assert label.tracking_number == "1234567890"
        assert label.label_pdf == b"%PDF-1.4 cargus"
        assert label.cost == 17.85
        doc = next(c for c in responses.calls if "AwbDocuments" in c.request.url)
        q = parse_qs(urlparse(doc.request.url).query)
        assert json.loads(q["barCodes"][0]) == ["1234567890"] and q["type"] == ["PDF"]

    @responses.activate
    def test_every_call_carries_key_and_token(self):
        _login()
        _create()
        CargusCourierAdapter(credentials=CREDS).generate_awb(_shipment())
        login, create = responses.calls[0].request, responses.calls[1].request
        assert login.headers["Ocp-Apim-Subscription-Key"] == "k" * 32 and "Authorization" not in login.headers
        assert json.loads(login.body) == {"UserName": "u", "Password": "p"}
        assert create.headers["Authorization"] == "Bearer TOKEN123"

    @responses.activate
    def test_body_follows_the_schema(self):
        _login()
        _create()
        CargusCourierAdapter(credentials=CREDS).generate_awb(_shipment(cod_amount=250, declared_value=100))
        body = _body()
        assert body["Sender"] == {"LocationId": 201266091}
        r = body["Recipient"]
        assert (r["CountyName"], r["LocalityName"], r["BuildingNumber"], r["CodPostal"]) == ("Iasi", "Iasi", "14", "700259")
        assert r["PhoneNumber"] == "0740123123" and "ap. 3" in r["AddressText"]
        assert (body["Parcels"], body["Envelopes"], body["TotalWeight"]) == (1, 0, 2)  # 1.3 kg -> 2 (int)
        assert body["ServiceId"] == 34 and body["ShipmentPayer"] == 1
        assert (body["BankRepayment"], body["CashRepayment"]) == (250.0, 0)
        assert body["ParcelCodes"][0] == {"Code": "0", "Type": 1, "Weight": 1.3, "Length": 20, "Width": 20,
                                          "Height": 10, "ParcelContent": "Carti"}
        assert body["CustomString"] == "CMD-1"

    @responses.activate
    def test_cash_repayment_when_bank_transfer_is_off(self):
        _login()
        _create()
        CargusCourierAdapter(credentials=CREDS, config={"cod_to_bank_account": False}).generate_awb(
            _shipment(cod_amount=250))
        assert (_body()["CashRepayment"], _body()["BankRepayment"]) == (250.0, 0)

    @responses.activate
    def test_ship_and_go_point_forces_service_38_without_cod(self):
        _login()
        _create()
        rec = RECIPIENT.model_copy(update={"extra": {**RECIPIENT.extra, "pickup_point_id": "5512"}})
        CargusCourierAdapter(credentials=CREDS).generate_awb(Shipment(recipient=rec, extra={"cod_amount": 10}))
        body = _body()
        assert (body["DeliveryPudoPoint"], body["ServiceId"], body["CashRepayment"]) == (5512, 38, 0)

    @responses.activate
    def test_first_pickup_point_when_not_configured(self):
        _login()
        responses.add(responses.GET, API + "PickupLocations", json=[{"LocationId": 77}])
        _create()
        CargusCourierAdapter(credentials={**CREDS, "pickup_location_id": ""}).generate_awb(_shipment())
        assert _body()["Sender"] == {"LocationId": 77}

    @responses.activate
    @pytest.mark.parametrize("error_body", [["Localitate invalida"], {"Error": "Localitate invalida"}])
    def test_refusal_shapes_become_validation_errors(self, error_body):
        _login()
        responses.add(responses.POST, API + "Awbs/WithGetAwb", status=400, json=error_body)
        with pytest.raises(ValidationError, match="Localitate invalida"):
            CargusCourierAdapter(credentials=CREDS).generate_awb(_shipment())

    @responses.activate
    def test_create_is_sent_once(self):
        from bapp_connectors.core.http import NoAuth, ResilientHttpClient, RetryPolicy

        _login()
        responses.add(responses.POST, API + "Awbs/WithGetAwb", status=503, json="busy")
        http = ResilientHttpClient(base_url=API, auth=NoAuth())
        http.retry_policy = RetryPolicy(max_retries=3, base_delay=0, max_delay=0)
        with pytest.raises(ProviderError):
            CargusCourierAdapter(credentials=CREDS, http_client=http).generate_awb(_shipment())
        assert sum(c.request.url.endswith("WithGetAwb") for c in responses.calls) == 1


class TestAuth:

    @responses.activate
    def test_expired_token_relogs_once(self):
        _login()
        responses.add(responses.GET, API + "PickupLocations", json="Failed to authenticate!")
        _login()
        responses.add(responses.GET, API + "PickupLocations", json=[{"LocationId": 1}])
        assert CargusCourierAdapter(credentials=CREDS).client.pickup_locations() == [{"LocationId": 1}]
        assert sum(c.request.url.endswith("LoginUser") for c in responses.calls) == 2

    @responses.activate
    def test_bad_login(self):
        responses.add(responses.POST, API + "LoginUser", status=401,
                      json={"statusCode": 401, "message": "Access denied due to invalid subscription key."})
        with pytest.raises(AuthenticationError, match="subscription key"):
            CargusCourierAdapter(credentials=CREDS).client.pickup_locations()

    @responses.activate
    def test_test_environment_host(self):
        responses.add(responses.POST, "https://urgentcargusapitest.azure-api.net/api/LoginUser", json="T")
        responses.add(responses.GET, "https://urgentcargusapitest.azure-api.net/api/PickupLocations",
                      json=[{"LocationId": 201266091}])
        assert CargusCourierAdapter(credentials={**CREDS, "test": "true"}).test_connection().success is True


class TestTrackingCancelList:

    @responses.activate
    def test_tracking(self):
        _login()
        responses.add(responses.GET, API + "AwbTrace", json=[{"Code": "1234567890", "Event": [
            {"Date": "2026-10-02T12:00:00", "EventId": 21, "Description": "Livrat", "LocalityName": "Iasi"},
            {"Date": "2026-10-01T09:00:00", "EventId": 234, "Description": "Preluat"}]}])
        events = CargusCourierAdapter(credentials=CREDS).get_tracking("1234567890")
        assert [e.status for e in events] == [ShipmentStatus.PICKED_UP, ShipmentStatus.DELIVERED]
        call = next(c for c in responses.calls if "AwbTrace" in c.request.url)
        assert json.loads(parse_qs(urlparse(call.request.url).query)["barCode"][0]) == ["1234567890"]

    @responses.activate
    def test_cancel(self):
        _login()
        responses.add(responses.DELETE, API + "Awbs", json=True)
        assert CargusCourierAdapter(credentials=CREDS).cancel_shipment("1234567890") is True

    @responses.activate
    def test_cancel_after_first_scan(self):
        _login()
        responses.add(responses.DELETE, API + "Awbs", json=False)
        assert CargusCourierAdapter(credentials=CREDS).cancel_shipment("1") is False

    @responses.activate
    def test_listing_pages_until_short_page(self):
        _login()
        responses.add(responses.GET, API + "Awbs/GetByDate", json=[{"BarCode": "9", "TotalWeight": 2, "Status": "Tiparit"}])
        result = CargusCourierAdapter(credentials=CREDS).get_shipments()
        assert result.items[0].tracking_number == "9" and result.has_more is False


@pytest.mark.parametrize("event,status", [
    (21, ShipmentStatus.DELIVERED), (196, ShipmentStatus.RETURNED), (153, ShipmentStatus.FAILED_DELIVERY),
    (234, ShipmentStatus.PICKED_UP), (5, ShipmentStatus.OUT_FOR_DELIVERY), (10, ShipmentStatus.IN_TRANSIT),
])
def test_event_map(event, status):
    assert map_event(event) == status
