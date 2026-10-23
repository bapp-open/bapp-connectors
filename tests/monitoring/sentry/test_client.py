import pytest
import requests

from bapp_connectors.core.errors import AuthenticationError, ProviderError, RateLimitError
from bapp_connectors.providers.monitoring.sentry.client import SentryClient, parse_next_cursor
from bapp_connectors.providers.monitoring.sentry.errors import (
    SentryError,
    SentryNotFoundError,
    SentryUnreachableError,
    reject_internal_error,
)
from tests.fake_http import FakeHttpClient, fake_response

PREV = '<https://s/api/0/projects/o/p/issues/?cursor=1:0:1>; rel="previous"; results="false"; cursor="1:0:1"'
NEXT = '<https://s/api/0/projects/o/p/issues/?cursor=1:100:0>; rel="next"; results="{}"; cursor="1:100:0"'
LINK_MORE = f"{PREV}, {NEXT.format('true')}"
LINK_END = f"{PREV}, {NEXT.format('false')}"


def make(http):
    return SentryClient(http, host="sentry.example.net", organization="example-org", token="t")


def test_parse_next_cursor_true():
    link = (
        '<https://s/api/0/projects/o/p/issues/?cursor=1:0:1>; rel="previous"; results="false"; cursor="1:0:1", '
        '<https://s/api/0/projects/o/p/issues/?cursor=1:100:0>; rel="next"; results="true"; cursor="1:100:0"'
    )
    assert parse_next_cursor(link) == "1:100:0"


def test_parse_next_cursor_false():
    assert parse_next_cursor(LINK_END) is None


@pytest.mark.parametrize("link", ["", None, PREV])
def test_parse_next_cursor_missing(link):
    assert parse_next_cursor(link) is None


def test_paged_passes_cursor_and_bearer():
    http = FakeHttpClient()
    http.add("GET", "/projects/", fake_response([{"id": "1"}], {"Link": LINK_MORE}))
    items, nxt = make(http).paged("organizations/example-org/projects/", {"query": None}, "1:0:0")
    assert items == [{"id": "1"}] and nxt == "1:100:0"
    call = http.calls[0]
    assert call.kwargs["params"] == {"cursor": "1:0:0"}
    assert call.kwargs["headers"]["Authorization"] == "Bearer t"
    assert call.path.startswith("https://sentry.example.net/api/0/")
    assert call.kwargs["direct_response"] is True


def test_paged_last_page_and_lowercase_header():
    http = FakeHttpClient()
    http.add("GET", "/projects/", fake_response([], {"link": LINK_END}))
    items, nxt = make(http).list_projects(None)
    assert items == [] and nxt is None
    assert "cursor" not in http.calls[0].kwargs["params"]


def test_list_issues_params():
    http = FakeHttpClient()
    http.add("GET", "/issues/", fake_response([{"id": "9"}], {"Link": LINK_END}))
    items, _ = make(http).list_issues("aio", "is:unresolved", "14d", "date", "", None)
    call = http.calls[0]
    assert call.path == "https://sentry.example.net/api/0/projects/example-org/aio/issues/"
    assert call.kwargs["params"] == {"query": "is:unresolved", "statsPeriod": "14d", "sort": "date"}
    assert items == [{"id": "9"}]


def test_list_issues_passes_environment():
    http = FakeHttpClient()
    http.add("GET", "/issues/", fake_response([], {"Link": LINK_END}))
    make(http).list_issues("aio", "is:unresolved", "24h", "freq", "production", "1:100:0")
    params = http.calls[0].kwargs["params"]
    assert params["environment"] == "production" and params["cursor"] == "1:100:0"


def test_endpoint_paths():
    http = FakeHttpClient()
    http.add("GET", "/", fake_response({"id": "1"}))
    client = make(http)
    client.get_organization()
    client.get_project("aio")
    client.get_issue("42")
    assert [c.path for c in http.calls] == [
        "https://sentry.example.net/api/0/organizations/example-org/",
        "https://sentry.example.net/api/0/projects/example-org/aio/",
        "https://sentry.example.net/api/0/issues/42/",
    ]


def test_update_issue_puts_json():
    http = FakeHttpClient()
    http.add("PUT", "/issues/42/", fake_response({"id": "42", "status": "resolved"}))
    assert make(http).update_issue("42", {"status": "resolved"}) == {"id": "42", "status": "resolved"}
    assert http.calls[0].kwargs["json"] == {"status": "resolved"}


def test_project_stats_params():
    http = FakeHttpClient()
    http.add("GET", "/stats_v2/", fake_response({"groups": []}))
    assert make(http).project_stats(7, "24h") == {"groups": []}
    call = http.calls[0]
    assert call.path == "https://sentry.example.net/api/0/organizations/example-org/stats_v2/"
    assert call.kwargs["params"] == {
        "field": "sum(quantity)",
        "groupBy": "outcome",
        "category": "error",
        "project": 7,
        "statsPeriod": "24h",
    }


def test_reject_internal_error():
    reject_internal_error([{"detail": "Internal Error"}], "u")  # a list is a normal payload
    reject_internal_error({"detail": "Not found"}, "u")
    with pytest.raises(SentryError):
        reject_internal_error({"detail": "Internal Error"}, "u")


def test_internal_error_is_provider_error():
    http = FakeHttpClient()
    http.add("GET", "/issues/", fake_response({"detail": "Internal Error"}))
    with pytest.raises(SentryError) as info:
        make(http).list_issues("aio", "is:unresolved", "14d", "date", "", None)
    assert isinstance(info.value, ProviderError)


def test_401_is_authentication_error():
    http = FakeHttpClient()
    http.add("GET", "/organizations/", fake_response({"detail": "Invalid token"}, status=401))
    with pytest.raises(AuthenticationError):
        make(http).get_organization()


@pytest.mark.parametrize(
    ("status", "exc"),
    [(403, SentryNotFoundError), (404, SentryNotFoundError), (429, RateLimitError), (502, SentryError)],
)
def test_status_mapping(status, exc):
    http = FakeHttpClient()
    http.add("GET", "/issues/", fake_response({"detail": "x"}, status=status))
    with pytest.raises(exc):
        make(http).get_issue("1")


def test_non_json_body_is_sentry_error():
    from types import SimpleNamespace

    def bad_json():
        raise ValueError("not json")

    http = FakeHttpClient()
    http.add("GET", "/issues/", SimpleNamespace(status_code=200, headers={}, text="<html>", json=bad_json))
    with pytest.raises(SentryError):
        make(http).get_issue("1")


def test_transport_error_is_unreachable():
    def boom(method, path, kwargs):
        raise requests.ConnectionError("refused")

    http = FakeHttpClient()
    http.add("GET", "/organizations/", boom)
    with pytest.raises(SentryUnreachableError):
        make(http).get_organization()


def test_http_error_raised_by_transport_still_maps_status():
    def boom(method, path, kwargs):
        raise requests.HTTPError("nope", response=fake_response({"detail": "401"}, status=401))

    http = FakeHttpClient()
    http.add("GET", "/organizations/", boom)
    with pytest.raises(AuthenticationError):
        make(http).get_organization()


def _retrying_http():
    from bapp_connectors.core.http.retry import RetryPolicy
    from bapp_connectors.core.types import BackoffStrategy

    http = FakeHttpClient()
    http.retry_policy = RetryPolicy(max_retries=3, backoff=BackoffStrategy.NONE)
    return http


def _sequence(*responses):
    queue = list(responses)

    def respond(method, path, kwargs):
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    return respond


def test_502_then_200_is_retried_by_the_policy():
    http = _retrying_http()
    http.add("GET", "/organizations/", _sequence(fake_response({"m": "bad"}, status=502), fake_response({"id": "1"})))
    assert make(http).get_organization() == {"id": "1"}
    assert len(http.calls) == 2
    assert all(c.kwargs["retry"] is False for c in http.calls)  # the HTTP client never retries on its own


def test_401_is_not_retried():
    http = _retrying_http()
    http.add("GET", "/organizations/", fake_response({"detail": "401"}, status=401))
    with pytest.raises(AuthenticationError):
        make(http).get_organization()
    assert len(http.calls) == 1


def test_internal_error_body_is_retried():
    http = _retrying_http()
    http.add(
        "GET",
        "/issues/",
        _sequence(fake_response({"detail": "Internal Error"}), fake_response([{"id": "9"}], {"Link": LINK_END})),
    )
    items, nxt = make(http).list_issues("aio", "is:unresolved", "14d", "date", "", None)
    assert items == [{"id": "9"}] and nxt is None
    assert len(http.calls) == 2
