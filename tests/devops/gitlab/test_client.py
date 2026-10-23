import pytest
import requests

from bapp_connectors.core.errors import AuthenticationError, RateLimitError
from bapp_connectors.providers.devops.gitlab.client import GitLabClient
from bapp_connectors.providers.devops.gitlab.errors import (
    GitLabError,
    GitLabNotFoundError,
    GitLabUnreachableError,
)
from tests.fake_http import FakeHttpClient, fake_response


def make(http):
    return GitLabClient(http, host="gitlab.example.net", token="t")


def test_paged_reads_next_page():
    http = FakeHttpClient()
    http.add("GET", "/projects", fake_response([{"id": 1}], {"X-Next-Page": "2", "X-Total": "150"}))
    items, nxt = make(http).paged("projects", {})
    assert items == [{"id": 1}] and nxt == "2"
    assert http.calls[0].kwargs["headers"]["PRIVATE-TOKEN"] == "t"
    assert http.calls[0].path.startswith("https://gitlab.example.net/api/v4/projects")
    assert http.calls[0].kwargs["direct_response"] is True
    assert http.calls[0].kwargs["params"]["per_page"] == 100


def test_paged_last_page():
    http = FakeHttpClient()
    http.add("GET", "/projects", fake_response([{"id": 1}], {"X-Next-Page": ""}))
    _, nxt = make(http).paged("projects", {})
    assert nxt is None


def test_group_path_is_encoded():
    http = FakeHttpClient()
    http.add("GET", "/groups/", fake_response([{"id": 7}], {"X-Next-Page": ""}))
    items, nxt = make(http).list_projects(None, None, ["bapp-cloud/application"], False)
    assert "groups/bapp-cloud%2Fapplication/projects" in http.calls[0].path
    assert http.calls[0].kwargs["params"]["include_subgroups"] == "true"
    assert http.calls[0].kwargs["params"]["archived"] == "false"
    assert items == [{"id": 7}] and nxt is None


def test_list_projects_without_groups_uses_membership_and_omits_archived_when_included():
    http = FakeHttpClient()
    http.add("GET", "/projects", fake_response([], {"X-Next-Page": "3"}))
    _, nxt = make(http).list_projects("2", "api", [], True)
    params = http.calls[0].kwargs["params"]
    assert http.calls[0].path == "https://gitlab.example.net/api/v4/projects"
    assert params["membership"] == "true" and params["page"] == "2" and params["search"] == "api"
    assert "archived" not in params
    assert nxt == "3"


def test_group_cursor_moves_to_next_group():
    http = FakeHttpClient()
    http.add("GET", "groups/a/projects", fake_response([{"id": 1}], {"X-Next-Page": ""}))
    http.add("GET", "groups/b/projects", fake_response([{"id": 2}], {"X-Next-Page": "2"}))
    client = make(http)
    items, nxt = client.list_projects(None, None, ["a", "b"], False)
    assert items == [{"id": 1}] and nxt == "1:1"
    items, nxt = client.list_projects(nxt, None, ["a", "b"], False)
    assert items == [{"id": 2}] and nxt == "1:2"
    assert http.calls[-1].kwargs["params"]["page"] == "1"


def test_last_group_last_page_ends():
    http = FakeHttpClient()
    http.add("GET", "groups/b/projects", fake_response([{"id": 2}], {"X-Next-Page": ""}))
    _, nxt = make(http).list_projects("1:4", None, ["a", "b"], False)
    assert nxt is None


def test_project_ref_is_encoded():
    http = FakeHttpClient()
    http.add("GET", "/projects/", fake_response({"id": 5}))
    assert make(http).get_project("grp/sub/app") == {"id": 5}
    assert http.calls[0].path.endswith("projects/grp%2Fsub%2Fapp")


def test_list_issues_params():
    http = FakeHttpClient()
    http.add("GET", "/issues", fake_response([], {"X-Next-Page": ""}))
    from datetime import UTC, datetime

    make(http).list_issues(5, "opened", datetime(2026, 1, 2, tzinfo=UTC), None)
    params = http.calls[0].kwargs["params"]
    assert http.calls[0].path.endswith("projects/5/issues")
    assert params["state"] == "opened" and params["updated_after"].startswith("2026-01-02T00:00:00")
    assert params["order_by"] == "updated_at" and params["sort"] == "desc"


def test_create_note_posts_body():
    http = FakeHttpClient()
    http.add("POST", "/notes", fake_response({"id": 9}, status=201))
    assert make(http).create_issue_note("g/p", 3, "hi") == {"id": 9}
    assert http.calls[0].path.endswith("projects/g%2Fp/issues/3/notes")
    assert http.calls[0].kwargs["json"] == {"body": "hi"}


def test_401_maps_to_authentication_error():
    http = FakeHttpClient()
    http.add("GET", "/user", fake_response({"message": "401 Unauthorized"}, status=401))
    with pytest.raises(AuthenticationError):
        make(http).get_user()


@pytest.mark.parametrize(
    ("status", "exc"),
    [(403, GitLabNotFoundError), (404, GitLabNotFoundError), (429, RateLimitError), (502, GitLabError)],
)
def test_status_mapping(status, exc):
    http = FakeHttpClient()
    http.add("GET", "/version", fake_response({"message": "x"}, status=status))
    with pytest.raises(exc):
        make(http).get_version()


def test_transport_error_is_unreachable():
    def boom(method, path, kwargs):
        raise requests.ConnectionError("refused")

    http = FakeHttpClient()
    http.add("GET", "/user", boom)
    with pytest.raises(GitLabUnreachableError):
        make(http).get_user()


def test_http_error_raised_by_transport_still_maps_status():
    def boom(method, path, kwargs):
        raise requests.HTTPError("nope", response=fake_response({"message": "401"}, status=401))

    http = FakeHttpClient()
    http.add("GET", "/user", boom)
    with pytest.raises(AuthenticationError):
        make(http).get_user()
