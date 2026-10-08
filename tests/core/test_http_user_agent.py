"""Every call names itself, because an anonymous one gets blocked.

Without a `User-Agent`, requests sends `python-requests/x.y`. A WooCommerce store behind a
firewall answered every such call with a 403 HTML page, while the very same credentials
returned 200 from a client that named itself — measured against a live shop: `python-requests`
403, `BappConnectors/…` 200. The failure reads as "Authentication failed", so it costs an hour
to find; the fix is one header.
"""

from __future__ import annotations

import responses

from bapp_connectors.core.http import NoAuth, ResilientHttpClient
from bapp_connectors.core.http.client import DEFAULT_USER_AGENT

URL = "https://api.example.test/ping"


def _client(**kwargs):
    return ResilientHttpClient(base_url="https://api.example.test/", auth=NoAuth(), **kwargs)


def test_the_default_agent_names_us_and_never_leaves_it_to_requests():
    assert DEFAULT_USER_AGENT.startswith("BappConnectors")
    assert "python-requests" not in DEFAULT_USER_AGENT


@responses.activate
def test_it_goes_out_on_a_real_call():
    responses.add(responses.GET, URL, json={}, status=200)
    _client().call("GET", URL)
    assert responses.calls[0].request.headers["User-Agent"] == DEFAULT_USER_AGENT


@responses.activate
def test_a_provider_whose_api_demands_its_own_agent_still_wins():
    """Trendyol cere `{seller_id} - BappConnectors`, Okazii al lui — ale lor trec peste al nostru."""
    responses.add(responses.GET, URL, json={}, status=200)
    _client().call("GET", URL, headers={"User-Agent": "123 - BappConnectors"})
    assert responses.calls[0].request.headers["User-Agent"] == "123 - BappConnectors"


@responses.activate
def test_a_client_can_be_built_with_its_own_agent():
    responses.add(responses.GET, URL, json={}, status=200)
    _client(user_agent="Custom/1").call("GET", URL)
    assert responses.calls[0].request.headers["User-Agent"] == "Custom/1"


@responses.activate
def test_naming_ourselves_does_not_cost_the_auth_header():
    """`apply_to_headers` primește acum un dict care nu mai e gol: nu are voie să-l înlocuiască."""

    class Bearer(NoAuth):
        def apply_to_headers(self, headers):
            return {**headers, "Authorization": "Bearer t"}

    responses.add(responses.GET, URL, json={}, status=200)
    ResilientHttpClient(base_url="https://api.example.test/", auth=Bearer()).call("GET", URL)
    sent = responses.calls[0].request.headers
    assert sent["Authorization"] == "Bearer t"
    assert sent["User-Agent"] == DEFAULT_USER_AGENT
