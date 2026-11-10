"""Guard on the ``@ai_method`` markers of the payment provider clients.

A method marked ``read`` is callable by an external AI agent, server-side, with the company's
payment credentials. Every one of them was read down to its HTTP request; the lists below are
that review. Refunds, captures, voids and checkout/payment creation are ``write`` (or unmarked);
nothing that returns a secret is ``read``: Stripe's raw payment-intent getters (``client_secret``)
and the ``expand`` getters (which could pull one back in) are unmarked, the agent gets the
``*_redacted`` wrappers instead. No read method takes a host/sandbox switch: the environment
comes from the connection's credentials/config only.
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock

import pytest

from bapp_connectors.core.ai import ai_methods
from tests.core import ai_guard

FAMILY = "payment"
PAYMENT_PROVIDERS = ai_guard.family_providers(FAMILY)

REVIEWED_READ_METHODS: dict[str, set[str]] = {
    "euplatesc": {
        "check_status",  # POST CHECK_STATUS, form body: a lookup
        "get_captured_total",  # POST CAPTURED_TOTAL: a report
        "get_invoice_list",  # POST INVOICES: settlement invoices
        "get_invoice_transactions",  # POST INVOICE: transactions of one settlement invoice
    },
    "netopia": {
        "get_status",  # POST operation/status: a lookup
    },
    "paypal": {
        "get_balances",
        "get_order",
        "list_transactions",
    },
    "stripe": {
        "get_charge_redacted",
        "get_customer_redacted",
        "get_payout_redacted",
        "get_payment_intent_redacted",
        "get_subscription_redacted",
        "list_balance_transactions_redacted",
        "list_payment_intents_redacted",
        "list_payment_methods_redacted",
        "list_payouts_redacted",
    },
}

REVIEWED_READ_EXTRA: dict[tuple[str, str], dict[str, str]] = {}

# Public client methods deliberately left without any mark (never offered to an agent).
UNMARKED_ON_PURPOSE: dict[tuple[str, str], str] = {
    ("euplatesc", "check_mid"): "merchant configuration check; response not reviewed, nothing an agent needs",
    ("euplatesc", "get_saved_cards"): "Click2Pay saved cards; response format undocumented here",
    ("netopia", "test_auth"): "connection test",
    ("netopia", "start_payment"): "starts a payment with raw card data (instrument) and agent-set notify/redirect URLs",
    ("netopia", "verify_auth"): "3-D Secure step of a customer's payment",
    ("netopia", "start_bnpl_payment"): "starts a payment; **kwargs",
    ("netopia", "bnpl_return"): "step of a customer's BNPL payment",
    ("netopia", "applepay_merchant_check"): "Apple Pay merchant validation; **kwargs posted as the body",
    ("netopia", "get_payment_options"): "takes card data (instrument); nothing an agent needs",
    ("paypal", "test_auth"): "fetches an OAuth token",
    ("stripe", "test_auth"): "connection test",
    ("stripe", "get_payment_intent"): "response carries client_secret; agent uses get_payment_intent_redacted",
    ("stripe", "list_payment_intents"): "responses carry client_secret; agent uses list_payment_intents_redacted",
    ("stripe", "list_balance_transactions"): "expand[] can pull a client_secret in; agent uses the _redacted one",
    ("stripe", "get_customer"): "legacy sources carry client_secret / redirect URLs; agent uses get_customer_redacted",
    ("stripe", "get_charge"): "expand[] can pull a client_secret in; agent uses get_charge_redacted",
    ("stripe", "get_subscription"): "raw response for the adapter; agent uses get_subscription_redacted",
    ("stripe", "list_payment_methods"): "raw response for the adapter; agent uses list_payment_methods_redacted",
    ("stripe", "list_payouts"): "raw response for the adapter; agent uses list_payouts_redacted",
    ("stripe", "get_payout"): "raw response for the adapter; agent uses get_payout_redacted",
    ("stripe", "update_subscription"): "**data posted as-is",
    ("stripe", "update_customer"): "**data posted as-is",
    ("stripe", "create_payment_intent"): "charges a saved card off-session",
}

REVIEWED_FREE_TEXT: set[tuple[str, str, str]] = set()

# Providers of the family with no client to mark (provider -> reason).
NOT_MARKED: dict[str, str] = {
    "cardinity": "form-based checkout: module-level signing helpers, no HTTP client",
    "librapay": "form-based checkout and refund forms: module-level helpers, no HTTP client",
    "mobilpay": "encrypted XML form checkout: module-level helpers, no HTTP client",
    "utrust": "the client only creates orders (checkout); no read endpoint",
}


def test_every_payment_provider_is_reviewed_or_not_marked():
    ai_guard.check_family_coverage(FAMILY, REVIEWED_READ_METHODS, NOT_MARKED)


_CHECKED = [p for p in PAYMENT_PROVIDERS if p not in NOT_MARKED]


@pytest.mark.parametrize("check", ai_guard.GENERIC_CHECKS, ids=lambda c: c.__name__)
@pytest.mark.parametrize("provider", _CHECKED)
def test_payment_marks(provider, check):
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


@pytest.mark.parametrize("provider", _CHECKED)
def test_no_read_takes_an_environment_switch(provider):
    """The host (sandbox or live) comes from the connection, never from the agent."""
    for name, fn, _info in ai_guard.read_methods(FAMILY, provider):
        params = set(inspect.signature(fn).parameters)
        assert not params & {"sandbox", "live", "base_url", "url", "host", "environment", "env"}, name


def test_paypal_agent_client_is_the_api_client():
    from bapp_connectors.providers.payment.paypal.client import PayPalApiClient

    assert isinstance(ai_guard.adapter(FAMILY, "paypal").get_ai_client(), PayPalApiClient)


def _stripe_client(response):
    from bapp_connectors.providers.payment.stripe.client import StripeApiClient

    http = MagicMock()
    http.call.return_value = response
    return StripeApiClient(http), http


def test_stripe_redacted_reads_drop_client_secret_at_any_depth():
    pi = {"id": "pi_1", "status": "succeeded", "client_secret": "pi_1_secret_x", "nested": [{"client_secret": "y"}]}
    client, _http = _stripe_client(pi)
    assert client.get_payment_intent_redacted("pi_1") == {"id": "pi_1", "status": "succeeded", "nested": [{}]}

    client, _http = _stripe_client({"data": [dict(pi)], "has_more": False})
    out = client.list_payment_intents_redacted(limit=2)
    assert "client_secret" not in repr(out)
    assert out["data"][0]["id"] == "pi_1"


@pytest.mark.parametrize(
    "read",
    [
        lambda c: c.get_subscription_redacted("sub_1"),
        lambda c: c.list_payment_methods_redacted("cus_1"),
        lambda c: c.list_payouts_redacted(limit=2),
        lambda c: c.get_payout_redacted("po_1"),
    ],
    ids=["get_subscription", "list_payment_methods", "list_payouts", "get_payout"],
)
def test_stripe_other_reads_are_redacted_too(read):
    secret = "pi_9Zz_secret_Q1"
    body = {
        "id": "x_1",
        "data": [{"id": "pm_1", "client_secret": secret}],
        "latest_invoice": {"payment_intent": {"id": "pi_9Zz", "client_secret": secret}},
        "note": f"see {secret}",
    }
    client, http = _stripe_client(body)
    out = read(client)
    assert secret not in repr(out)
    assert out["id"] == "x_1"
    assert out["latest_invoice"]["payment_intent"]["id"] == "pi_9Zz"
    http.call.assert_called_once()


def test_stripe_redacted_reads_send_no_expand():
    client, http = _stripe_client({"data": []})
    client.list_balance_transactions_redacted(payout="po_1")
    client.get_charge_redacted("ch_1")
    client.get_subscription_redacted("sub_1")
    client.list_payment_methods_redacted("cus_1")
    client.list_payouts_redacted()
    client.get_payout_redacted("po_1")
    for call in http.call.call_args_list:
        params = call.kwargs.get("params") or {}
        assert not any(k.startswith("expand") for k in params), call


_PI_SECRET = "pi_3Abc123_secret_XyZ789"
_REQUIRES_ACTION_PI = {
    "id": "pi_3Abc123",
    "object": "payment_intent",
    "status": "requires_action",
    "client_secret": _PI_SECRET,
    "next_action": {
        "type": "redirect_to_url",
        "redirect_to_url": {
            "return_url": "https://shop.example.com/return",
            "url": "https://hooks.stripe.com/3d_secure_2/hosted?merchant=acct_1&payment_intent=pi_3Abc123"
            f"&payment_intent_client_secret={_PI_SECRET}&publishable_key=pk_test_abc&source=payatt_1",
        },
    },
}
_SDK_PI = {
    "id": "pi_3Abc123",
    "status": "requires_action",
    "next_action": {
        "type": "use_stripe_sdk",
        "use_stripe_sdk": {
            "type": "three_d_secure_redirect",
            "stripe_js": f"https://hooks.stripe.com/redirect/authenticate/src_1?client_secret={_PI_SECRET}"
            "&source_redirect_slug=test_x",
        },
    },
}


@pytest.mark.parametrize("pi", [_REQUIRES_ACTION_PI, _SDK_PI], ids=["redirect_to_url", "use_stripe_sdk"])
def test_stripe_redacted_payment_intent_drops_next_action_secrets(pi):
    client, _http = _stripe_client(pi)
    out = client.get_payment_intent_redacted("pi_3Abc123")
    assert "_secret_" not in repr(out)
    assert out["next_action"] == {"type": pi["next_action"]["type"]}
    assert out["status"] == "requires_action"

    client, _http = _stripe_client({"data": [pi], "has_more": False})
    assert "_secret_" not in repr(client.list_payment_intents_redacted())


def test_stripe_redaction_scrubs_secret_strings_anywhere():
    from bapp_connectors.providers.payment.stripe.client import _redacted

    data = {
        "description": f"retry {_PI_SECRET} please",
        "notes": ["seti_1Ab_secret_Cd2", "src_client_secret_Q9w8e7", "sk_live_51Hxyz", "rk_test_51Habc", "whsec_9f8e"],
        "publishable": "pk_live_51Hpub",
        "plain": "pi_3Abc123",
    }
    out = _redacted(data)
    assert out["description"] == "retry [redacted] please"
    assert out["notes"] == ["[redacted]"] * 5
    assert out["publishable"] == "pk_live_51Hpub"
    assert out["plain"] == "pi_3Abc123"


def test_stripe_customer_redacted_scrubs_legacy_sources():
    customer = {
        "id": "cus_1",
        "email": "a@example.com",
        "sources": {
            "data": [
                {
                    "id": "src_1",
                    "object": "source",
                    "client_secret": "src_client_secret_Abc123",
                    "redirect": {
                        "url": "https://hooks.stripe.com/redirect/authenticate/src_1"
                        "?client_secret=src_client_secret_Abc123",
                        "status": "pending",
                    },
                }
            ]
        },
    }
    client, http = _stripe_client(customer)
    out = client.get_customer_redacted("cus_1")
    assert "client_secret_" not in repr(out)
    assert "client_secret" not in out["sources"]["data"][0]
    assert out["email"] == "a@example.com"
    # the raw method is unchanged for existing callers
    assert client.get_customer("cus_1") == customer
    assert http.call.call_args.args == ("GET", "customers/cus_1")
