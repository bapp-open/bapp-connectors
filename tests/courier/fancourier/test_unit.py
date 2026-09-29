"""FAN Courier adapter — API v2 flow against the documented endpoints (mocked HTTP).

Response shapes are the ones in the official PDF (September 2025); the live API was
not reachable from the build machine.
"""

from __future__ import annotations

import json
from datetime import datetime
from urllib.parse import parse_qs, urlparse

import pytest
import responses

from bapp_connectors.core.dto import Address, Parcel, Shipment, ShipmentStatus
from bapp_connectors.core.errors import AuthenticationError, ProviderError, ValidationError
from bapp_connectors.providers.courier.fancourier.adapter import FanCourierAdapter
from bapp_connectors.providers.courier.fancourier.mappers import map_event, resolve_service

API = "https://api.fancourier.ro/"
CREDS = {"username": "clienttest", "password": "testing", "client_id": "7032158"}
RECIPIENT = Address(street="Fabrica de Glucoza", city="Bucuresti", region="Bucuresti", postal_code="020331",
                    country="RO", extra={"name": "Ion Pop", "phone": "0723 456 789", "email": "ion@x.ro",
                                         "number": "11C", "block": "46", "flat": "51"})


def _login(expires="2099-01-01 06:00:55"):
    responses.add(responses.POST, API + "login",
                  json={"status": "success", "data": {"token": "48980806|abc", "expiresAt": expires}})


def _create(awb=2228300120233):
    responses.add(responses.POST, API + "intern-awb", json={"response": [{
        "awbNumber": awb, "tariff": 29.7, "vat": 5.64, "packages": 1, "routingCode": "1181",
        "office": "Bucuresti", "estimatedDeliveryTime": 24, "errors": None}]})
    responses.add(responses.GET, API + "awb/label", body=b"%PDF-1.7 label", content_type="application/pdf")


def _shipment(**extra) -> Shipment:
    return Shipment(recipient=RECIPIENT, parcels=[Parcel(weight=1.2, length=30, width=20, height=10),
                                                  Parcel(weight=0.5, length=10, width=10, height=5)],
                    extra={"content": "Order #346", **extra})


def _body() -> dict:
    return json.loads(next(c.request.body for c in responses.calls if c.request.url.endswith("intern-awb")))


class TestGenerateAwb:

    @responses.activate
    def test_awb_and_pdf_label(self):
        _login()
        _create()
        label = FanCourierAdapter(credentials=CREDS).generate_awb(_shipment())
        assert label.tracking_number == "2228300120233"  # an int in the API, a string here
        assert label.label_pdf.startswith(b"%PDF")
        assert label.cost == 29.7
        label_call = next(c for c in responses.calls if "/awb/label" in c.request.url)
        q = parse_qs(urlparse(label_call.request.url).query)
        assert q["awbs[]"] == ["2228300120233"] and q["pdf"] == ["1"] and q["clientId"] == ["7032158"]

    @responses.activate
    def test_body_follows_the_documented_schema(self):
        _login()
        _create()
        FanCourierAdapter(credentials=CREDS).generate_awb(_shipment(declared_value=150))
        body = _body()
        assert body["clientId"] == 7032158
        info = body["shipments"][0]["info"]
        assert info["service"] == "Standard"
        assert info["packages"] == {"parcel": 2, "envelope": 0}
        assert info["weight"] == 2  # 1.7 kg rounded up
        assert info["dimensions"] == {"length": 30, "height": 10, "width": 20}  # the largest parcel
        assert info["payment"] == "sender" and info["declaredValue"] == 150.0
        rec = body["shipments"][0]["recipient"]
        assert rec["phone"] == "0723456789"
        assert rec["address"]["streetNo"] == "11C" and rec["address"]["building"] == "46"
        assert rec["address"]["apartment"] == "51"

    @responses.activate
    def test_cash_on_delivery_switches_to_cont_colector(self):
        _login()
        _create()
        FanCourierAdapter(credentials=CREDS).generate_awb(_shipment(cod_amount=199.9))
        info = _body()["shipments"][0]["info"]
        assert (info["service"], info["cod"]) == ("Cont Colector", 199.9)

    @responses.activate
    def test_cash_returned_on_awb_when_bank_transfer_is_off(self):
        _login()
        _create()
        FanCourierAdapter(credentials=CREDS, config={"cod_to_bank_account": False}).generate_awb(
            _shipment(cod_amount=10))
        assert _body()["shipments"][0]["info"]["service"] == "Standard"

    @responses.activate
    def test_fanbox_locker(self):
        _login()
        _create()
        rec = RECIPIENT.model_copy(update={"extra": {**RECIPIENT.extra, "pickup_point_id": "F1011137"}})
        FanCourierAdapter(credentials=CREDS).generate_awb(
            Shipment(recipient=rec, extra={"service": "FANbox", "options": ["V"]}))
        body = _body()["shipments"][0]
        assert body["recipient"]["address"]["pickupLocationId"] == "F1011137"
        assert body["info"]["options"] == ["V"]

    @responses.activate
    def test_per_shipment_error_is_a_validation_error(self):
        _login()
        responses.add(responses.POST, API + "intern-awb", json={"response": [
            {"awbNumber": None, "success": False, "errors": {"info.parcels": "At least one envelope or parcel is required"}}]})
        with pytest.raises(ValidationError, match="At least one envelope"):
            FanCourierAdapter(credentials=CREDS).generate_awb(_shipment())

    @responses.activate
    def test_missing_client_id_uses_the_first_branch(self):
        _login()
        responses.add(responses.GET, API + "reports/branches", json={"status": "success", "data": [{"id": 999}]})
        _create()
        FanCourierAdapter(credentials={**CREDS, "client_id": ""}).generate_awb(_shipment())
        assert _body()["clientId"] == 999

    @responses.activate
    def test_create_is_sent_once(self):
        from bapp_connectors.core.http import NoAuth, ResilientHttpClient, RetryPolicy

        _login()
        responses.add(responses.POST, API + "intern-awb", status=503)
        http = ResilientHttpClient(base_url=API, auth=NoAuth())
        http.retry_policy = RetryPolicy(max_retries=3, base_delay=0, max_delay=0)
        with pytest.raises(ProviderError):
            FanCourierAdapter(credentials=CREDS, http_client=http).generate_awb(_shipment())
        assert sum(c.request.url.endswith("intern-awb") for c in responses.calls) == 1


class TestAuth:

    @responses.activate
    def test_login_uses_query_params_and_token_is_reused(self):
        _login()
        responses.add(responses.GET, API + "reports/services", json={"status": "success", "data": []})
        a = FanCourierAdapter(credentials=CREDS)
        a.client.services()
        a.client.services()
        logins = [c for c in responses.calls if "/login" in c.request.url]
        assert len(logins) == 1
        assert parse_qs(urlparse(logins[0].request.url).query) == {"username": ["clienttest"], "password": ["testing"]}
        assert responses.calls[1].request.headers["Authorization"] == "Bearer 48980806|abc"

    @responses.activate
    def test_expired_token_logs_in_again(self):
        _login(expires="2000-01-01 00:00:00")
        _login()
        responses.add(responses.GET, API + "reports/services", json={"status": "success", "data": []})
        a = FanCourierAdapter(credentials=CREDS)
        a.client.services()
        a.client.services()
        assert sum("/login" in c.request.url for c in responses.calls) == 2

    @responses.activate
    def test_401_triggers_one_relogin(self):
        _login()
        responses.add(responses.GET, API + "reports/services", status=401, json={"message": "Unauthenticated."})
        responses.add(responses.GET, API + "reports/services", json={"status": "success", "data": [{"id": 1}]})
        assert FanCourierAdapter(credentials=CREDS).client.services() == [{"id": 1}]

    @responses.activate
    def test_bad_login(self):
        responses.add(responses.POST, API + "login", json={"status": "fail", "message": "Invalid credentials"})
        with pytest.raises(AuthenticationError, match="Invalid credentials"):
            FanCourierAdapter(credentials=CREDS).client.services()

    @responses.activate
    def test_connection_checks_the_client_id_is_a_branch(self):
        _login()
        responses.add(responses.GET, API + "reports/branches", json={"status": "success", "data": [{"id": 1}]})
        assert FanCourierAdapter(credentials=CREDS).test_connection().success is False


class TestTrackingCancelList:

    @responses.activate
    def test_tracking(self):
        _login()
        responses.add(responses.GET, API + "reports/awb/tracking", json={"status": "success", "data": [{
            "awbNumber": "2228300120233", "returnAwbNumber": None, "events": [
                {"id": "C0", "name": " Ridicat", "location": "Bucuresti", "date": "2026-10-01 10:00:00"},
                {"id": "S2", "name": "Livrat", "location": "Iasi", "date": "2026-10-02 13:58:43"}]}]})
        events = FanCourierAdapter(credentials=CREDS).get_tracking("2228300120233")
        assert [e.status for e in events] == [ShipmentStatus.PICKED_UP, ShipmentStatus.DELIVERED]
        assert events[0].description == "Ridicat"
        call = next(c for c in responses.calls if "tracking" in c.request.url)
        assert parse_qs(urlparse(call.request.url).query)["awb[]"] == ["2228300120233"]

    @responses.activate
    def test_return_awb_marks_returned(self):
        _login()
        responses.add(responses.GET, API + "reports/awb/tracking", json={"status": "success", "data": [{
            "awbNumber": "1", "returnAwbNumber": 777, "events": [{"id": "S6", "name": "Refuz", "date": "2026-10-02 10:00:00"}]}]})
        assert FanCourierAdapter(credentials=CREDS).get_tracking("1")[-1].status == ShipmentStatus.RETURNED

    @responses.activate
    def test_cancel(self):
        _login()
        responses.add(responses.DELETE, API + "awb", json={"status": "success", "data": "The AWB was successfully deleted"})
        assert FanCourierAdapter(credentials=CREDS).cancel_shipment("2228300120233") is True

    @responses.activate
    def test_cancel_refused(self):
        _login()
        responses.add(responses.DELETE, API + "awb", json={"status": "fail", "message": "AWB already picked up"})
        assert FanCourierAdapter(credentials=CREDS).cancel_shipment("1") is False

    @responses.activate
    def test_listing_walks_day_by_day(self):
        _login()
        responses.add(responses.GET, API + "reports/awb", json={
            "status": "success", "perPage": 1, "currentPage": 1, "total": 2,
            "data": [{"info": {"awbNumber": 5, "weight": 1, "service": "Standard"}}]})
        a = FanCourierAdapter(credentials=CREDS)
        first = a.get_shipments(since=datetime(2026, 9, 1))
        assert first.items[0].tracking_number == "5"
        assert first.cursor == "2026-09-01:2"


class TestMappers:

    @pytest.mark.parametrize("code,status", [
        ("S2", ShipmentStatus.DELIVERED), ("S43", ShipmentStatus.RETURNED), ("S16", ShipmentStatus.RETURNED),
        ("C1", ShipmentStatus.OUT_FOR_DELIVERY), ("H3", ShipmentStatus.IN_TRANSIT), ("S15", ShipmentStatus.FAILED_DELIVERY),
    ])
    def test_event_map(self, code, status):
        assert map_event(code) == status

    @pytest.mark.parametrize("service,cont", [
        ("Standard", "Cont Colector"), ("RedCode", "Red code-Cont Colector"), ("FANbox", "FANbox Cont Colector"),
        ("Cont Colector", "Cont Colector"),
    ])
    def test_cont_colector_variant(self, service, cont):
        assert resolve_service(service, 10, True) == cont
