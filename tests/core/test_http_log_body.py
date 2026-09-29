"""The http client hands loggers what they need to keep a call's bodies.

`log_body=True` marks a call whose 2xx answer is worth keeping (a refund whose
answer is not documented, Netopia errors that come back as 200); the raw
response rides in `ResponseContext.extra` so a logger can decode it only then.
"""

from __future__ import annotations

import responses

from bapp_connectors.core.http import NoAuth, ResilientHttpClient

URL = "https://api.example.test/pay"


def _client():
    seen = {}
    client = ResilientHttpClient(base_url="https://api.example.test/", auth=NoAuth())
    client.middleware.add_on_response(lambda ctx: seen.setdefault("ctx", ctx))
    return client, seen


@responses.activate
def test_log_body_reaches_the_logger_and_not_requests():
    responses.add(responses.POST, URL, body="1", status=200)
    client, seen = _client()
    response = client.call("POST", URL, data={"A": "1"}, log_body=True, direct_response=True)
    assert response.text == "1"  # requests would have raised on an unknown log_body kwarg
    assert seen["ctx"].request.extra["log_body"] is True


@responses.activate
def test_calls_are_unflagged_by_default():
    responses.add(responses.POST, URL, json={"ok": True}, status=200)
    client, seen = _client()
    client.call("POST", URL, json={})
    assert seen["ctx"].request.extra["log_body"] is False


@responses.activate
def test_the_raw_response_is_available_to_loggers():
    responses.add(responses.POST, URL, body="Tranzactie procesata", status=200)
    client, seen = _client()
    client.call("POST", URL, data={}, direct_response=True)
    assert seen["ctx"].extra["response"].text == "Tranzactie procesata"


@responses.activate
def test_log_body_survives_retries():
    responses.add(responses.POST, URL, status=503)
    responses.add(responses.POST, URL, body="1", status=200)
    from bapp_connectors.core.http import RetryPolicy

    client, seen = _client()
    client.retry_policy = RetryPolicy(max_retries=2, base_delay=0, max_delay=0)
    seen.clear()
    flags = []
    client.middleware.add_on_response(lambda ctx: flags.append(ctx.request.extra["log_body"]))
    client.call("POST", URL, data={}, log_body=True)
    assert flags == [True, True]
