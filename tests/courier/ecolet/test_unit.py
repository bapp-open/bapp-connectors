"""eColet adapter — the whole booking flow against the spec's endpoints (mocked HTTP)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
import responses

from bapp_connectors.core.dto import Address, Parcel, Shipment, ShipmentStatus
from bapp_connectors.core.errors import AuthenticationError, ProviderError, ValidationError
from bapp_connectors.core.http import NoAuth, ResilientHttpClient
from bapp_connectors.providers.courier.ecolet.adapter import EcoletCourierAdapter
from bapp_connectors.providers.courier.ecolet.manifest import manifest
from bapp_connectors.providers.courier.ecolet.mappers import _price, choose_service, map_status

API = "https://panel.ecolet.ro/api/"
CREDS = {"client_id": "7", "client_secret": "s", "username": "u@x.ro", "password": "p"}

SENDER = Address(street="Str. Fabricii", city="Iasi", region="Iasi", postal_code="700001", country="RO",
                 extra={"name": "Shop SRL", "phone": "0722 111 222", "email": "s@shop.ro", "number": "3"})
RECIPIENT = Address(street="Bd. Unirii", city="Bucuresti", region="Bucuresti", postal_code="030119", country="RO",
                    extra={"name": "Ion Pop", "phone": "0733333333", "email": "ion@x.ro", "number": "10"})

FORM = {
    "statuses": {"dpd_standard": True, "sameday_standard": True, "cargus_standard": False},
    "prices_gross": {"dpd_standard": "18,50", "sameday_standard": "16,28", "cargus_standard": "12,00"},
    "pickup_dates": {"sameday_standard": {"day": "Thursday", "date": "2026-10-01", "hours": ["10:00", "12:00"]},
                     "dpd_standard": {"date": "2026-10-01", "hours": ["11:00"]}},
    "errors": [],
}
ORDER = {"id": 991, "awb": "80438360579", "price": 16.28, "waybill_extension": "pdf",
         "service": {"slug": "sameday_standard", "courier_slug": "sameday", "courier_name": "Sameday"}}


def _token():
    responses.add(responses.POST, API + "v1/oauth/token",
                  json={"token_type": "Bearer", "expires_in": 3600, "access_token": "AT", "refresh_token": "RT"})


def _localities():
    responses.add(responses.GET, API + "v1/locations/ro/localities/Iasi",
                  json={"localities": [{"id": 11, "name": "Iasi", "county": {"name": "Iasi"}}]})
    responses.add(responses.GET, API + "v1/locations/ro/localities/Bucuresti",
                  json={"localities": [{"id": 22, "name": "Bucuresti", "county": {"name": "Bucuresti"}}]})


def _adapter(**config) -> EcoletCourierAdapter:
    return EcoletCourierAdapter(credentials=CREDS, config={"awb_wait_seconds": 0, **config})


def _shipment(**extra) -> Shipment:
    return Shipment(sender=SENDER, recipient=RECIPIENT, parcels=[Parcel(weight=1.4, length=30, width=20, height=10.5)],
                    extra={"content": "Carti", **extra})


def _booking(order_to_send_status="ordered"):
    _token()
    _localities()
    responses.add(responses.POST, API + "v2/add-parcel/reload-form", json={"form": FORM})
    responses.add(responses.POST, API + "v2/add-parcel/send-order", json={"order_to_send_id": 55})
    responses.add(responses.GET, API + "v1/order-to-send/55",
                  json={"order_to_send": {"id": 55, "status": order_to_send_status, "order_id": 991,
                                          "error": "Curier indisponibil"}})
    responses.add(responses.GET, API + "v1/order/991", json={"data": ORDER})
    responses.add(responses.GET, API + "v1/order/991/download-waybill", body=b"%PDF-1.4 x",
                  content_type="application/pdf")


def _sent_body() -> dict:
    return json.loads(next(c.request.body for c in responses.calls if c.request.url.endswith("send-order")))


class TestGenerateAwb:

    @responses.activate
    def test_cheapest_available_service_is_booked_and_awb_returned(self):
        _booking()
        label = _adapter().generate_awb(_shipment())
        assert label.tracking_number == "80438360579"
        assert label.label_pdf.startswith(b"%PDF")
        assert label.cost == 16.28
        assert label.extra["courier"] == "sameday"
        body = _sent_body()
        # cargus is cheaper but not available for this shipment
        assert body["courier"]["service"] == "sameday_standard"
        assert body["courier"]["pickup"] == {"type": "courier", "date": "2026-10-01", "time": "10:00"}

    @responses.activate
    def test_order_body_follows_the_spec(self):
        _booking()
        _adapter().generate_awb(_shipment(cod_amount=120.5, declared_value=200))
        body = _sent_body()
        assert body["receiver"]["locality_id"] == 22 and body["sender"]["locality_id"] == 11
        assert body["receiver"]["country"] == "ro"
        assert body["sender"]["phone"] == "0722111222"
        assert body["parcels"][0]["weight"] == 2  # whole kg, rounded up
        assert body["parcels"][0]["dimensions"] == {"length": 30, "width": 20, "height": 11}
        assert body["additional_services"]["cod"] == {"status": True, "amount": 120.5}
        assert body["parcels"][0]["declared_value"] == 200.0

    @responses.activate
    def test_configured_service_is_used(self):
        _booking()
        _adapter(service="dpd_standard").generate_awb(_shipment())
        assert _sent_body()["courier"]["service"] == "dpd_standard"

    @responses.activate
    def test_unavailable_configured_service_is_refused_before_booking(self):
        _token()
        _localities()
        responses.add(responses.POST, API + "v2/add-parcel/reload-form", json={"form": FORM})
        with pytest.raises(ValidationError, match="cargus_standard"):
            _adapter(service="cargus_standard").generate_awb(_shipment())
        assert not any(c.request.url.endswith("send-order") for c in responses.calls)

    @responses.activate
    def test_booking_error_from_the_courier_raises(self):
        _booking(order_to_send_status="error")
        with pytest.raises(ProviderError, match="Curier indisponibil"):
            _adapter().generate_awb(_shipment())

    @responses.activate
    def test_still_pending_after_the_wait_says_to_check_the_panel(self):
        _booking(order_to_send_status="new")
        with pytest.raises(ProviderError, match="check the eColet panel"):
            _adapter().generate_awb(_shipment())

    @responses.activate
    def test_send_order_is_never_retried(self):
        """A retried booking could book the courier twice."""
        _token()
        _localities()
        responses.add(responses.POST, API + "v2/add-parcel/reload-form", json={"form": FORM})
        responses.add(responses.POST, API + "v2/add-parcel/send-order", status=503)
        http = ResilientHttpClient(base_url=manifest.base_url, auth=NoAuth())
        from bapp_connectors.core.http import RetryPolicy

        http.retry_policy = RetryPolicy(max_retries=3, base_delay=0, max_delay=0)
        adapter = EcoletCourierAdapter(credentials=CREDS, http_client=http, config={"awb_wait_seconds": 0})
        with pytest.raises(ProviderError):
            adapter.generate_awb(_shipment())
        assert sum(c.request.url.endswith("send-order") for c in responses.calls) == 1


class TestAuth:

    @responses.activate
    def test_bad_credentials(self):
        responses.add(responses.POST, API + "v1/oauth/token", status=401,
                      json={"error": "invalid_client", "message": "Client authentication failed"})
        with pytest.raises(AuthenticationError, match="Client authentication failed"):
            _adapter().client.me()

    @responses.activate
    def test_me_200_unauthenticated_quirk(self):
        _token()
        responses.add(responses.GET, API + "v1/me", json={"unauthenticated": True})
        assert _adapter().test_connection().success is False

    @responses.activate
    def test_token_is_reused(self):
        _token()
        responses.add(responses.GET, API + "v1/services", json={"services": []})
        a = _adapter()
        a.client.services()
        a.client.services()
        assert sum(c.request.url.endswith("oauth/token") for c in responses.calls) == 1

    @responses.activate
    def test_staging_host(self):
        responses.add(responses.POST, "https://staging.ecolet.ro/api/v1/oauth/token",
                      json={"access_token": "AT", "expires_in": 60})
        responses.add(responses.GET, "https://staging.ecolet.ro/api/v1/me", json={"user": {"email": "s@x"}})
        a = EcoletCourierAdapter(credentials={**CREDS, "staging": "true"})
        assert a.test_connection().success is True


class TestTrackingAndCancel:

    @responses.activate
    def test_tracking_events_oldest_first_and_mapped(self):
        _token()
        responses.add(responses.POST, API + "v1/order/get-statuses-for-many-orders", json={"data": [{
            "id": 991, "awb": "80438360579", "statuses": [
                {"name": "delivered", "real_name": "Livrat", "created_at": "2026-10-02T12:00:00Z"},
                {"name": "new", "real_name": "Shipment data received", "created_at": "2026-10-01T09:00:00Z"},
            ]}]})
        events = _adapter().get_tracking("80438360579")
        assert [e.status for e in events] == [ShipmentStatus.CREATED, ShipmentStatus.DELIVERED]
        assert events[1].timestamp == datetime(2026, 10, 2, 12, tzinfo=UTC)

    @responses.activate
    def test_cancel_resolves_the_order_id_from_the_awb(self):
        _token()
        responses.add(responses.POST, API + "v1/order/get-statuses-for-many-orders",
                      json={"data": [{"id": 991, "awb": "80438360579", "statuses": []}]})
        responses.add(responses.DELETE, API + "v1/order/991", json={"data": ["Order succesfully canceled"]})
        assert _adapter().cancel_shipment("80438360579") is True

    @responses.activate
    def test_cancel_unknown_awb(self):
        _token()
        responses.add(responses.POST, API + "v1/order/get-statuses-for-many-orders", json={"data": []})
        assert _adapter().cancel_shipment("000") is False


class TestMappers:

    @pytest.mark.parametrize("slug,status", [
        ("delivered", ShipmentStatus.DELIVERED), ("canceled", ShipmentStatus.CANCELLED),
        ("returned", ShipmentStatus.RETURNED), ("delivered to sender", ShipmentStatus.RETURNED),
        ("delivering", ShipmentStatus.OUT_FOR_DELIVERY), ("something-new", ShipmentStatus.IN_TRANSIT),
    ])
    def test_status_map(self, slug, status):
        assert map_status(slug) == status

    def test_price_with_comma_decimals(self):
        assert _price("16,28") == 16.28 and _price("1.234,50") == 1234.5

    def test_no_service_available(self):
        with pytest.raises(ValueError, match="no service"):
            choose_service({"statuses": {"x": False}, "errors": {"receiver.phone": ["invalid"]}})

    def test_self_pickup(self):
        from bapp_connectors.providers.courier.ecolet.mappers import pickup_slot

        assert pickup_slot(FORM, "dpd_standard", "self") == {"type": "self"}
