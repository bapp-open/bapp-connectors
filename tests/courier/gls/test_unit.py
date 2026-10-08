"""GLS (MyGLS API) adapter against the documented endpoints (mocked HTTP).

Shapes from the MyGLS API documentation (ver. 25.12.11, https://api.mygls.ro/index_en.html)
and its sample files; not yet run against the live or test host (no test account).
"""

from __future__ import annotations

import datetime
import gzip
import hashlib
import json

import pytest
import responses

from bapp_connectors.core.capabilities import BatchTrackingCapability
from bapp_connectors.core.dto import Address, Parcel, Shipment, ShipmentStatus
from bapp_connectors.core.errors import AuthenticationError, ProviderError, ValidationError
from bapp_connectors.core.registry import registry
from bapp_connectors.providers.courier.gls.adapter import GLSCourierAdapter
from bapp_connectors.providers.courier.gls.mappers import _parse_gls_date, international_phone

API = "https://api.mygls.ro/ParcelService.svc/json/"
CREDS = {"username": "api@shop.ro", "password": "secret", "client_number": "553001234", "country": "RO"}
SERVICES = {"service_sm1": True, "service_sm1_text": "Coletul #ParcelNr# a plecat", "service_sm2": True,
            "service_fds": True, "service_fss": True}
SENDER = Address(street="Str. Fabricii 1", city="Cluj-Napoca", postal_code="400001", country="RO",
                 extra={"name": "Depozit", "company": "Shop SRL", "contact_name": "Ana", "phone": "0744111222"})
RECIPIENT = Address(street="Str. Paris", city="Bucuresti", postal_code="011815", country="RO",
                    extra={"name": "Ion Popescu", "contact_name": "Ion Popescu", "phone": "0722 123 456",
                           "email": "ion@x.ro", "number": "9A"})
PRINTED = {"Labels": list(b"%PDF-1.4 gls"), "PrintLabelsErrorList": [],
           "PrintLabelsInfoList": [{"ClientReference": "CMD-1", "ParcelId": 9001, "ParcelNumber": 51234567890}]}


def _shipment(recipient=RECIPIENT, parcels=None, **extra):
    return Shipment(sender=SENDER, recipient=recipient, parcels=parcels or [Parcel(weight=1.5)],
                    extra={"content": "Comanda CMD-1", "reference": "CMD-1", **extra})


def _sent(url: str) -> dict:
    return json.loads(next(c.request.body for c in responses.calls if c.request.url == url))


def _parcel(url: str = API + "PrintLabels") -> dict:
    return _sent(url)["ParcelList"][0]


def _adapter(creds=None, config=None, **kwargs):
    return GLSCourierAdapter(credentials=creds or CREDS, config=config, **kwargs)


class TestGenerateAwb:

    @responses.activate
    def test_label_and_payload(self):
        responses.add(responses.POST, API + "PrintLabels", json=PRINTED)
        label = _adapter().generate_awb(_shipment())

        assert label.tracking_number == "51234567890"
        assert label.label_pdf == b"%PDF-1.4 gls"
        assert label.extra["parcel_id"] == 9001
        assert label.extra["parcels"][0]["ParcelId"] == 9001  # aio-backend cancels by these
        sent = _sent(API + "PrintLabels")
        assert sent["Username"] == "api@shop.ro"
        assert sent["Password"] == list(hashlib.sha512(b"secret").digest())
        assert sent["TypeOfPrinter"] == "Connect" and sent["WebshopEngine"] == "BAPP"
        parcel = sent["ParcelList"][0]
        assert parcel["ClientNumber"] == 553001234
        assert parcel["ClientReference"] == "CMD-1" and parcel["Content"] == "Comanda CMD-1"
        assert parcel["Count"] == 1
        assert parcel["DeliveryAddress"]["ContactPhone"] == "+40722123456"
        assert parcel["DeliveryAddress"]["HouseNumber"] == "9"
        assert parcel["PickupAddress"]["Name"] == "Shop SRL"
        assert parcel["PickupAddress"]["ContactPhone"] == "+40744111222"
        assert parcel["ParcelPropertyList"] == [{"Weight": 1.5, "Content": "Comanda CMD-1"}]
        assert parcel["ServiceList"] == []

    @responses.activate
    def test_cod(self):
        responses.add(responses.POST, API + "PrintLabels", json=PRINTED)
        _adapter().generate_awb(_shipment(cod_amount=149.999))
        parcel = _parcel()
        assert parcel["CODAmount"] == 150.0
        assert parcel["CODReference"] == "CMD-1"  # GLS pairs the COD payment by it
        assert parcel["CODCurrency"] == "RON"
        assert {"Code": "COD"} in parcel["ServiceList"]

    @responses.activate
    def test_notification_services(self):
        responses.add(responses.POST, API + "PrintLabels", json=PRINTED)
        _adapter(config=SERVICES).generate_awb(_shipment())
        services = {s["Code"]: s for s in _parcel()["ServiceList"]}
        assert services["SM1"]["SM1Parameter"]["Value"] == "+40722123456|Coletul #ParcelNr# a plecat"
        assert services["SM2"]["SM2Parameter"]["Value"] == "+40722123456"
        assert services["FDS"]["FDSParameter"]["Value"] == "ion@x.ro"
        assert services["FSS"]["FSSParameter"]["Value"] == "+40722123456"

    @responses.activate
    def test_fss_follows_fds_when_the_email_is_missing(self):
        responses.add(responses.POST, API + "PrintLabels", json=PRINTED)
        recipient = RECIPIENT.model_copy(update={"extra": {**RECIPIENT.extra, "email": ""}})
        _adapter(config=SERVICES).generate_awb(_shipment(recipient=recipient))
        codes = [s["Code"] for s in _parcel()["ServiceList"]]
        assert "FDS" not in codes and "FSS" not in codes  # FSS without FDS: GLS error 30
        assert "SM1" in codes

    def test_service_settings_are_validated(self):
        with pytest.raises(ValidationError, match="FSS"):
            _adapter(config={"service_fss": True}).generate_awb(_shipment())
        with pytest.raises(ValidationError, match="SMS text"):
            _adapter(config={"service_sm1": "true"}).generate_awb(_shipment())

    @responses.activate
    def test_parcel_shop_delivery(self):
        responses.add(responses.POST, API + "PrintLabels", json=PRINTED)
        recipient = RECIPIENT.model_copy(update={"extra": {**RECIPIENT.extra, "pickup_point_id": "1234"}})
        _adapter().generate_awb(_shipment(recipient=recipient))
        assert {"Code": "PSD", "PSDParameter": {"IntegerValue": 1234}} in _parcel()["ServiceList"]

    def test_parcel_shop_needs_the_full_contact(self):
        recipient = RECIPIENT.model_copy(update={"extra": {"name": "Ion", "phone": "0722123456",
                                                           "pickup_point_id": "RO-LOCKER-1"}})
        with pytest.raises(ValidationError, match="ContactEmail"):
            _adapter().generate_awb(_shipment(recipient=recipient))

    @responses.activate
    def test_several_parcels(self):
        responses.add(responses.POST, API + "PrintLabels", json=PRINTED)
        parcels = [Parcel(weight=2, length=40, width=30, height=20), Parcel(weight=1)]
        _adapter().generate_awb(_shipment(parcels=parcels))
        parcel = _parcel()
        assert parcel["Count"] == 2
        assert parcel["ParcelPropertyList"][0] == {"Weight": 2.0, "Length": 40, "Width": 30, "Height": 20,
                                                   "Content": "Comanda CMD-1"}

    @responses.activate
    def test_raw_services_and_hidden_phone(self):
        responses.add(responses.POST, API + "PrintLabels", json=PRINTED)
        _adapter(config={"hide_phone_on_label": True, "printer_type": "Thermo"}).generate_awb(
            _shipment(service_list=[{"Code": "SAT"}, {"Code": "COD"}], cod_amount=10))
        sent = _sent(API + "PrintLabels")
        assert sent["HidePhoneNumberOnLabels"] is True and sent["TypeOfPrinter"] == "Thermo"
        assert [s["Code"] for s in sent["ParcelList"][0]["ServiceList"]] == ["COD", "SAT"]

    @responses.activate
    def test_gls_errors_are_raised(self):
        responses.add(responses.POST, API + "PrintLabels", json={
            "Labels": None, "PrintLabelsInfoList": [],
            "PrintLabelsErrorList": [{"ErrorCode": 13, "ErrorDescription": "Parcel validation issue",
                                      "ClientReferenceList": ["CMD-1"], "ParcelIdList": []}]})
        with pytest.raises(ValidationError, match=r"\[13\] Parcel validation issue \(ref: CMD-1\)"):
            _adapter().generate_awb(_shipment())

    @responses.activate
    def test_bad_login_is_an_auth_error(self):
        responses.add(responses.POST, API + "PrintLabels", json={
            "PrintLabelsInfoList": [], "PrintLabelsErrorList": [{"ErrorCode": -1, "ErrorDescription": "Unauthorized."}]})
        with pytest.raises(AuthenticationError):
            _adapter().generate_awb(_shipment())

    @responses.activate
    def test_label_is_downloaded_when_missing(self):
        responses.add(responses.POST, API + "PrintLabels", json={**PRINTED, "Labels": None})
        responses.add(responses.POST, API + "GetPrintedLabels", json={"Labels": list(b"%PDF-again")})
        label = _adapter().generate_awb(_shipment())
        assert label.label_pdf == b"%PDF-again"
        assert _sent(API + "GetPrintedLabels")["ParcelIdList"] == [9001]

    @responses.activate
    def test_create_is_sent_once(self):
        from bapp_connectors.core.http import NoAuth, ResilientHttpClient, RetryPolicy

        responses.add(responses.POST, API + "PrintLabels", status=503, body="busy")
        http = ResilientHttpClient(base_url=API, auth=NoAuth())
        http.retry_policy = RetryPolicy(max_retries=3, base_delay=0, max_delay=0)
        with pytest.raises(ProviderError):
            _adapter(http_client=http).generate_awb(_shipment())
        assert sum(c.request.url == API + "PrintLabels" for c in responses.calls) == 1

    def test_sender_is_required(self):
        with pytest.raises(ValidationError, match="pickup"):
            _adapter().generate_awb(Shipment(recipient=RECIPIENT, extra={"reference": "CMD-1"}))


class TestHosts:

    @responses.activate
    def test_country_and_test_host_through_the_registry(self):
        """The registry injects a client bound to the RO manifest URL; the country must still win."""
        host = "https://api.test.mygls.hu/ParcelService.svc/json/"
        responses.add(responses.POST, host + "PrintLabels", json=PRINTED)
        adapter = registry.create_adapter(family="courier", provider="gls",
                                          credentials={**CREDS, "country": "HU", "test": "true"}, config={})
        adapter.generate_awb(_shipment())
        assert responses.calls[0].request.url == host + "PrintLabels"
        assert _parcel(host + "PrintLabels")["Count"] == 1

    def test_unknown_country(self):
        with pytest.raises(ValueError):
            _adapter(creds={**CREDS, "country": "DE"})


STATUSES = {"ClientReference": "CMD-1", "DeliveryCountryCode": "RO", "GetParcelStatusErrors": [],
            "ParcelNumber": 51234567890, "ParcelStatusList": [
                {"DepotCity": "Bucuresti", "DepotNumber": "RO99", "StatusCode": "05", "StatusDate": "/Date(1759917600000+0300)/",
                 "StatusDescription": "Livrat", "StatusInfo": ""},
                {"DepotCity": "Bucuresti", "DepotNumber": "RO99", "StatusCode": "04", "StatusDate": "/Date(1759903200000+0300)/",
                 "StatusDescription": "In livrare", "StatusInfo": ""},
                {"DepotCity": "Cluj", "DepotNumber": "RO40", "StatusCode": "01", "StatusDate": "/Date(1759831200000+0300)/",
                 "StatusDescription": "Predat la GLS", "StatusInfo": ""},
            ]}


class TestTracking:

    @responses.activate
    def test_events_oldest_first(self):
        responses.add(responses.POST, API + "GetParcelStatuses", json=STATUSES)
        events = _adapter().get_tracking("51234567890")
        assert [e.extra["code"] for e in events] == ["01", "04", "05"]
        assert events[-1].status == ShipmentStatus.DELIVERED  # callers read the last one as current
        assert events[0].location == "Cluj"
        sent = _sent(API + "GetParcelStatuses")
        assert sent["ParcelNumber"] == 51234567890 and sent["LanguageIsoCode"] == "RO"

    @responses.activate
    def test_unknown_parcel_is_no_tracking(self):
        responses.add(responses.POST, API + "GetParcelStatuses", json={
            "ParcelStatusList": [], "GetParcelStatusErrors": [{"ErrorCode": 9, "ErrorDescription": "Parcel number not exists"}]})
        assert _adapter().get_tracking("51234567890") == []

    @responses.activate
    def test_bad_login_does_not_stop_a_status_poller(self):
        responses.add(responses.POST, API + "GetParcelStatuses", json={
            "ParcelStatusList": [], "GetParcelStatusErrors": [{"ErrorCode": -1, "ErrorDescription": "Unauthorized."}]})
        assert _adapter().get_tracking("51234567890") == []

    @responses.activate
    def test_batch_bad_login_is_raised(self):
        responses.add(responses.POST, API + "GetParcelListStatuses", json={
            "ParcelList": [], "GetParcelListStatusesErrors": [{"ErrorCode": -1, "ErrorDescription": "Unauthorized."}]})
        with pytest.raises(AuthenticationError):
            _adapter().get_tracking_batch(["51234567890"])

    def test_dates(self):
        moment = _parse_gls_date("/Date(1759917600000+0300)/")
        assert moment.utcoffset() == datetime.timedelta(hours=3)
        assert moment.astimezone(datetime.UTC) == datetime.datetime(2025, 10, 8, 10, 0, tzinfo=datetime.UTC)
        assert _parse_gls_date("/Date(1759917600000-0130)/").utcoffset() == -datetime.timedelta(hours=1, minutes=30)
        assert _parse_gls_date("/Date(1759917600000)/").utcoffset() == datetime.timedelta(0)
        assert _parse_gls_date("") is None and _parse_gls_date("nonsense") is None

    @responses.activate
    def test_batch(self):
        def reply(request):
            numbers = json.loads(request.body)["ParcelNumberList"]
            return 200, {}, json.dumps({"GetParcelListStatusesErrors": [], "ParcelList": [
                {**STATUSES, "ParcelNumber": n} for n in numbers]})

        responses.add_callback(responses.POST, API + "GetParcelListStatuses", callback=reply)
        adapter = _adapter()
        assert isinstance(adapter, BatchTrackingCapability)
        numbers = [str(51000000000 + i) for i in range(150)] + ["51000000000", "not-a-number"]
        result = adapter.get_tracking_batch(numbers)
        assert len(responses.calls) == 2  # 100 + 50, duplicates and junk dropped
        assert len(result) == 150
        assert result["51000000149"][-1].status == ShipmentStatus.DELIVERED


class TestCancel:

    @responses.activate
    def test_cancel_by_parcel_id(self):
        responses.add(responses.POST, API + "DeleteLabels", json={
            "DeleteLabelsErrorList": [], "SuccessfullyDeletedList": [{"ClientReference": "CMD-1", "ParcelId": 9001}]})
        assert _adapter().cancel_shipment("9001") is True
        assert _sent(API + "DeleteLabels")["ParcelIdList"] == [9001]

    @responses.activate
    def test_cancel_error_is_raised(self):
        responses.add(responses.POST, API + "DeleteLabels", json={
            "SuccessfullyDeletedList": [],
            "DeleteLabelsErrorList": [{"ErrorCode": 6, "ErrorDescription": "Parcel with this ID has different status than PRINTED"}]})
        with pytest.raises(ValidationError, match="PRINTED"):
            _adapter().cancel_shipment("9001")

    def test_cancel_needs_a_parcel_id(self):
        with pytest.raises(ValidationError, match="ParcelId"):
            _adapter().cancel_shipment("ABC")

    @responses.activate
    def test_cancel_is_sent_once(self):
        from bapp_connectors.core.http import NoAuth, ResilientHttpClient, RetryPolicy

        responses.add(responses.POST, API + "DeleteLabels", status=503, body="busy")
        http = ResilientHttpClient(base_url=API, auth=NoAuth())
        http.retry_policy = RetryPolicy(max_retries=3, base_delay=0, max_delay=0)
        with pytest.raises(ProviderError):
            _adapter(http_client=http).cancel_shipment("9001")
        assert len(responses.calls) == 1


class TestDeliveryPoints:

    @responses.activate
    def test_points_are_unpacked(self):
        points = [{"Id": 1234, "Matchcode": "RO-CLJ-01", "DeliveryPointType": 2}]
        responses.add(responses.POST, "https://api.mygls.ro/MasterDataService.svc/json/GetDeliveryPoints", json={
            "ErrorCode": 0, "IsChanged": True, "Data": list(gzip.compress(json.dumps(points).encode()))})
        assert _adapter().get_delivery_points() == points
        assert json.loads(responses.calls[0].request.body)["CountryIsoCode"] == "RO"


class TestPhones:

    @pytest.mark.parametrize(("raw", "country", "expected"), [
        ("0722 123 456", "RO", "+40722123456"),
        ("+40 722-123-456", "RO", "+40722123456"),
        ("0040722123456", "RO", "+40722123456"),
        ("40722123456", "RO", "+40722123456"),
        ("06 30 123 4567", "HU", "+36301234567"),
        ("", "RO", ""),
    ])
    def test_international(self, raw, country, expected):
        assert international_phone(raw, country) == expected
