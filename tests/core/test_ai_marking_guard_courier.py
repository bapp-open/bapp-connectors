"""Guard on the ``@ai_method`` markers of the courier provider clients.

A method marked ``read`` is callable by an external AI agent, server-side, with the company's
courier credentials. Every one of them was read down to its HTTP request; the lists below are
that review. Labels (PDF bytes, or label data inside a dict) are never marked; AWB creation and
cancellation are ``write``. Price quotes sent as POST are ``read`` only because they book nothing.
"""

from __future__ import annotations

import pytest

from bapp_connectors.core.ai import ai_methods
from tests.core import ai_guard

FAMILY = "courier"
COURIER_PROVIDERS = ai_guard.family_providers(FAMILY)

REVIEWED_READ_METHODS: dict[str, set[str]] = {
    "cargus": {
        "awbs_by_date",
        "pickup_locations",
        "trace",
    },
    "colete_online": {
        "get_addresses",
        "get_balance",
        "get_order_status",
        "get_price",  # POST order/price: an estimate, no order is created
        "get_services",
        "get_shipping_points_list",  # POST: listing for a shipment body
        "get_shipping_points_localities",  # POST: listing for a shipment body
        "search_city",
        "search_location",
    },
    "dpd": {
        "contract_clients",
        "find_sites",
        "find_streets",
        "own_client_id",
        "track",
    },
    "ecolet": {
        "address_book",
        "list_orders",
        "order",
        "order_to_send",
        "reload_form",  # POST v2/add-parcel/reload-form: prices and slots, books nothing
        "search_localities",
        "services",
        "statuses_by_awb",  # POST, read-only lookup
    },
    "fancourier": {
        "awb_report",
        "branches",
        "services",
        "tracking",
    },
    "gls": {
        "get_parcel_list",
        "get_parcel_list_statuses",
        "get_parcel_status",
    },
    "sameday": {
        "get_awb_list",
        "get_parcel_status",
        "get_pickup_points",
    },
}

REVIEWED_READ_EXTRA: dict[tuple[str, str], dict[str, str]] = {
    ("sameday", "get_awb_list"): {"params": "flat"},
}

# Public client methods deliberately left without any mark (never offered to an agent).
UNMARKED_ON_PURPOSE: dict[tuple[str, str], str] = {
    ("cargus", "awb_documents"): "label PDF bytes",
    ("colete_online", "download_awb"): "label PDF bytes",
    ("colete_online", "test_auth"): "authenticates; not data",
    ("dpd", "print_labels"): "label PDF bytes",
    ("ecolet", "download_waybill"): "label bytes",
    ("ecolet", "me"): "the whole account user object; fields not reviewed, nothing an agent needs",
    ("fancourier", "label"): "label PDF bytes",
    ("gls", "test_auth"): "connection test",
    ("gls", "get_printed_labels"): "label data inside the dict",
    ("gls", "get_delivery_points"): "gzip-compressed byte array, unusable as JSON",
    ("sameday", "download_awb"): "label PDF bytes",
    ("sameday", "test_auth"): "authenticates; not data",
}

# No courier needs free text: search strings either go into a URL path (BAPP's path check must
# stay) or are short names.
REVIEWED_FREE_TEXT: set[tuple[str, str, str]] = set()

# Providers of the family with no client to mark (provider -> reason).
NOT_MARKED: dict[str, str] = {}


def test_every_courier_provider_is_reviewed_or_not_marked():
    ai_guard.check_family_coverage(FAMILY, REVIEWED_READ_METHODS, NOT_MARKED)


_CHECKED = [p for p in COURIER_PROVIDERS if p not in NOT_MARKED]


@pytest.mark.parametrize("check", ai_guard.GENERIC_CHECKS, ids=lambda c: c.__name__)
@pytest.mark.parametrize("provider", _CHECKED)
def test_courier_marks(provider, check):
    kwargs = {"free_text": REVIEWED_FREE_TEXT} if check is ai_guard.check_free_text_reviewed else {}
    check(FAMILY, provider, REVIEWED_READ_METHODS, REVIEWED_READ_EXTRA, **kwargs)


@pytest.mark.parametrize("provider", _CHECKED)
def test_every_public_method_is_marked_or_left_out_on_purpose(provider):
    """A new public client method fails here until it is marked or listed as unmarked."""
    cls = ai_guard.client_cls(FAMILY, provider)
    marked = set(ai_methods(cls))
    public = {
        name
        for name, value in vars(cls).items()
        if not name.startswith("_") and callable(value) and not isinstance(value, (staticmethod, classmethod))
    }
    unmarked = public - marked
    assert unmarked == {m for p, m in UNMARKED_ON_PURPOSE if p == provider}


def test_sameday_awb_list_params_cannot_override_paging_or_transport():
    from bapp_connectors.providers.courier.sameday.client import SamedayApiClient

    allowed = ai_methods(SamedayApiClient)["get_awb_list"].allowed_keys["params"]
    assert set(allowed) == {"startTimestamp", "endTimestamp", "isPrinted"}


# ── colete_online: the environment (staging / production) belongs to the connection ──


def test_colete_marked_methods_take_no_staging_argument():
    import inspect

    from bapp_connectors.providers.courier.colete_online.client import ColeteOnlineApiClient

    for name in ai_methods(ColeteOnlineApiClient):
        params = inspect.signature(getattr(ColeteOnlineApiClient, name)).parameters
        assert "staging" not in params, f"colete_online.{name} lets the caller pick the environment"


@pytest.mark.parametrize(("staging", "prefix"), [(True, "staging/"), (False, "")])
def test_colete_uses_the_connection_environment(staging, prefix):
    from bapp_connectors.providers.courier.colete_online.adapter import ColeteOnlineCourierAdapter

    class Http:
        def __init__(self):
            self.paths = []

        def call(self, method, path, **kwargs):
            if path.startswith("https://auth."):
                return {"access_token": "t", "expires_in": 3600}
            self.paths.append((method, path))
            return {}

    http = Http()
    adapter = ColeteOnlineCourierAdapter(
        credentials={"client_id": "i", "client_secret": "s"}, http_client=http, config={"staging": staging}
    )
    adapter.client.get_order_status("ABC")
    adapter.client.create_order({"sender": {}})
    assert http.paths == [("GET", f"{prefix}order/status/ABC"), ("POST", f"{prefix}order")]
