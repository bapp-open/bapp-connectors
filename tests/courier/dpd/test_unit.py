"""DPD Romania adapter against the documented endpoints (mocked HTTP).

Shapes from https://api.dpd.ro/api/docs/ and recorded RO traffic; the error shape
(HTTP 200 + {"error": {...}}) was confirmed against the live host.
"""

from __future__ import annotations

import json

import pytest
import responses

from bapp_connectors.core.dto import Address, Parcel, Shipment, ShipmentStatus
from bapp_connectors.core.errors import AuthenticationError, ValidationError
from bapp_connectors.providers.courier.dpd.adapter import DpdCourierAdapter
from bapp_connectors.providers.courier.dpd.mappers import map_operation, split_street

API = "https://api.dpd.ro/v1/"
CREDS = {"username": "user", "password": "pass", "client_id": "123456789"}
RECIPIENT = Address(street="Str. Paris 9", city="București", region="Bucuresti", postal_code="011815", country="RO",
                    extra={"name": "Ion Popescu", "phone": "+40 722 123 456", "email": "ion@x.ro", "block": "A1",
                           "flat": "12"})
CREATED = {"id": "80147286562", "parcels": [{"id": "80147286562", "seqNo": 1}], "pickupDate": "2026-10-01",
           "price": {"total": 14.48, "currency": "RON"}, "deliveryDeadline": "2026-10-02T19:00:00+0300"}


def _nomenclators(sites=None, streets=None):
    responses.add(responses.POST, API + "location/site",
                  json={"sites": sites if sites is not None else [{"id": 642279132, "name": "BUCURESTI"}]})
    responses.add(responses.POST, API + "location/street",
                  json={"streets": streets if streets is not None else [{"id": 642076636, "type": "str.", "name": "PARIS"}]})


def _create(created=CREATED):
    responses.add(responses.POST, API + "shipment", json=created)
    responses.add(responses.POST, API + "print", body=b"%PDF-1.4 dpd", content_type="application/pdf")


def _shipment(**extra):
    return Shipment(recipient=RECIPIENT, parcels=[Parcel(weight=1.2, length=30, width=20, height=10)],
                    extra={"content": "Haine", "reference": "CMD-10023", **extra})


def _sent(path: str) -> dict:
    return json.loads(next(c.request.body for c in responses.calls if c.request.url == API + path))


class TestGenerateAwb:

    @responses.activate
    def test_shipment_and_label(self):
        _nomenclators()
        _create()
        label = DpdCourierAdapter(credentials=CREDS).generate_awb(_shipment())
        assert label.tracking_number == "80147286562"
        assert label.label_pdf.startswith(b"%PDF")
        assert label.cost == 14.48
        printed = _sent("print")
        assert printed["parcels"] == [{"parcel": {"id": "80147286562"}}] and printed["paperSize"] == "A6"

    @responses.activate
    def test_body_follows_the_reference(self):
        _nomenclators()
        _create()
        DpdCourierAdapter(credentials=CREDS).generate_awb(_shipment(cod_amount=199.9, declared_value=300))
        body = _sent("shipment")
        assert body["userName"] == "user" and body["password"] == "pass"  # credentials in every body
        assert body["sender"] == {"clientId": 123456789}
        rec = body["recipient"]
        assert rec["privatePerson"] is True and "contactName" not in rec  # forbidden for private persons
        assert rec["phone1"] == {"number": "+40722123456"}
        assert rec["address"] == {"countryId": 642, "siteId": 642279132, "streetId": 642076636, "streetNo": "9",
                                  "blockNo": "A1", "apartmentNo": "12"}
        assert body["service"]["serviceId"] == 2505 and body["service"]["autoAdjustPickupDate"] is True
        assert body["service"]["additionalServices"]["cod"] == {"amount": 199.9, "currencyCode": "RON",
                                                                "processingType": "CASH"}
        assert body["content"]["parcels"][0] == {"seqNo": 1, "weight": 1.2,
                                                 "size": {"width": 20, "depth": 30, "height": 10}}
        assert body["payment"] == {"courierServicePayer": "SENDER"} and body["ref1"] == "CMD-10023"

    @responses.activate
    def test_company_recipient_gets_contact_name(self):
        _nomenclators()
        _create()
        rec = RECIPIENT.model_copy(update={"extra": {**RECIPIENT.extra, "company": "Client SRL"}})
        DpdCourierAdapter(credentials=CREDS).generate_awb(Shipment(recipient=rec, extra={"content": "x"}))
        r = _sent("shipment")["recipient"]
        assert (r["privatePerson"], r["clientName"], r["contactName"]) == (False, "Client SRL", "Ion Popescu")

    @responses.activate
    def test_unmatched_street_goes_to_address_note(self):
        _nomenclators(streets=[])
        _create()
        DpdCourierAdapter(credentials=CREDS).generate_awb(_shipment())
        address = _sent("shipment")["recipient"]["address"]
        assert "streetId" not in address and address["addressNote"].startswith("Str. Paris")

    @responses.activate
    def test_unknown_site_is_sent_by_name_and_postcode(self):
        _nomenclators(sites=[])
        _create()
        DpdCourierAdapter(credentials=CREDS).generate_awb(_shipment())
        address = _sent("shipment")["recipient"]["address"]
        assert (address["siteName"], address["postCode"]) == ("Bucuresti", "011815")  # no diacritics

    @responses.activate
    def test_locker_uses_pickup_office_without_address(self):
        _create()
        rec = RECIPIENT.model_copy(update={"extra": {**RECIPIENT.extra, "pickup_point_id": "8765"}})
        DpdCourierAdapter(credentials=CREDS).generate_awb(Shipment(recipient=rec, extra={"content": "x"}))
        r = _sent("shipment")["recipient"]
        assert r["pickupOfficeId"] == 8765 and "address" not in r

    @responses.activate
    def test_business_error_with_http_200_is_a_validation_error(self):
        _nomenclators()
        responses.add(responses.POST, API + "shipment", json={"error": {
            "context": "receiver.phone-1.num.invalid_phone", "message": "Invalid phone (EE1)", "code": 100}})
        with pytest.raises(ValidationError, match="Invalid phone"):
            DpdCourierAdapter(credentials=CREDS).generate_awb(_shipment())

    @responses.activate
    def test_bad_credentials(self):
        responses.add(responses.POST, API + "client", json={"error": {
            "message": "Unable to find user to authenticate! (EE2)", "code": 1}})
        result = DpdCourierAdapter(credentials=CREDS).test_connection()
        assert result.success is False and "authenticate" in result.message

    @responses.activate
    def test_auth_error_type(self):
        responses.add(responses.POST, API + "client", json={"error": {
            "message": "Nu s-a putut găsi utilizatorul pentru autentificare! (EE3)", "code": 1}})
        with pytest.raises(AuthenticationError):
            DpdCourierAdapter(credentials=CREDS).client.own_client_id()

    @responses.activate
    def test_create_is_sent_once(self):
        from bapp_connectors.core.errors import ProviderError
        from bapp_connectors.core.http import NoAuth, ResilientHttpClient, RetryPolicy

        _nomenclators()
        responses.add(responses.POST, API + "shipment", status=503, body="busy")
        http = ResilientHttpClient(base_url=API, auth=NoAuth())
        http.retry_policy = RetryPolicy(max_retries=3, base_delay=0, max_delay=0)
        with pytest.raises(ProviderError):
            DpdCourierAdapter(credentials=CREDS, http_client=http).generate_awb(_shipment())
        assert sum(c.request.url == API + "shipment" for c in responses.calls) == 1


class TestTrackingCancel:

    @responses.activate
    def test_tracking(self):
        responses.add(responses.POST, API + "track", json={"parcels": [{"parcelId": "80147286562", "operations": [
            {"dateTime": "2026-10-02T13:10:00+0300", "operationCode": -14, "place": "Bucuresti", "description": "Delivered"},
            {"dateTime": "2026-10-01T09:00:00+0300", "operationCode": 148, "description": "Shipment data received"},
        ]}]})
        events = DpdCourierAdapter(credentials=CREDS).get_tracking("80147286562")
        assert [e.status for e in events] == [ShipmentStatus.CREATED, ShipmentStatus.DELIVERED]

    @responses.activate
    def test_tracking_per_parcel_error_is_empty(self):
        responses.add(responses.POST, API + "track", json={"parcels": [{"parcelId": "1", "error": {"message": "no longer available"}}]})
        assert DpdCourierAdapter(credentials=CREDS).get_tracking("1") == []

    @responses.activate
    def test_cancel(self):
        responses.add(responses.POST, API + "shipment/cancel", json={})
        assert DpdCourierAdapter(credentials=CREDS).cancel_shipment("80147286562") is True
        assert _sent("shipment/cancel")["comment"]

    @responses.activate
    def test_cancel_after_pickup_fails(self):
        responses.add(responses.POST, API + "shipment/cancel", json={"error": {"message": "Shipment is ordered"}})
        assert DpdCourierAdapter(credentials=CREDS).cancel_shipment("1") is False


class TestMappers:

    @pytest.mark.parametrize("code,status", [
        (-14, ShipmentStatus.DELIVERED), (124, ShipmentStatus.RETURNED), (128, ShipmentStatus.CANCELLED),
        (12, ShipmentStatus.OUT_FOR_DELIVERY), (2, ShipmentStatus.IN_TRANSIT), ("-14", ShipmentStatus.DELIVERED),
    ])
    def test_operation_map(self, code, status):
        assert map_operation(code) == status

    @pytest.mark.parametrize("street,number,expected", [
        ("Str. Lunga 3", "", ("Lunga", "3")), ("Bd. Unirii nr. 10A", "", ("Unirii", "10A")),
        ("Șoseaua Ștefan cel Mare, 12", "", ("Stefan cel Mare", "12")), ("Strada Mare", "7", ("Mare", "7")),
    ])
    def test_split_street(self, street, number, expected):
        assert split_street(street, number) == expected
