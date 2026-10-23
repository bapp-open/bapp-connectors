"""GitLab adapter tests against the scrubbed REST captures."""

import json

import pytest

from bapp_connectors.core.capabilities import IssueManagementCapability, WebhookCapability
from bapp_connectors.core.dto import Issue, IssueComment, IssueDraft, Repository, WebhookEventType
from bapp_connectors.core.errors import ValidationError
from bapp_connectors.core.http import ResilientHttpClient
from bapp_connectors.core.registry import registry
from bapp_connectors.providers.devops.gitlab.adapter import GitLabAdapter
from tests.devops.contract import DevOpsContractTests
from tests.devops.gitlab.conftest import load
from tests.fake_http import FakeHttpClient, fake_response

CREDENTIALS = {"host": "gitlab.example.net", "token": "not-a-real-token"}
LAST = {"X-Next-Page": ""}


def build_http() -> FakeHttpClient:
    """Rules are substring-matched in order: the most specific paths come first."""
    http = FakeHttpClient()
    http.add("GET", "/user", fake_response(load("user")))
    http.add("GET", "/version", fake_response({"version": "17.5.0"}))
    http.add("GET", "/projects/382/issues/16", fake_response(load("issues")[0]))
    http.add("GET", "/projects/382/issues", fake_response(load("issues"), LAST))
    http.add("GET", "/projects/382/merge_requests", fake_response(load("merge_requests"), LAST))
    http.add("GET", "/projects/382/repository/commits", fake_response(load("commits"), LAST))
    http.add("GET", "/projects/382/pipelines", fake_response(load("pipelines"), LAST))
    http.add("GET", "/projects/382", fake_response(load("project")))
    http.add("GET", "/projects", fake_response(load("projects"), {"X-Next-Page": "2", "X-Total": "150"}))
    return http


@pytest.fixture
def http():
    return build_http()


@pytest.fixture
def adapter(http):
    return GitLabAdapter(credentials=CREDENTIALS, http_client=http, config={})


class TestGitLabContract(DevOpsContractTests):
    project_ref = "382"

    @pytest.fixture
    def adapter(self):
        return GitLabAdapter(credentials=CREDENTIALS, http_client=build_http(), config={})


# ── construction ──


def test_builds_its_own_http_client_when_none_injected():
    adapter = GitLabAdapter(credentials=CREDENTIALS)
    assert isinstance(adapter.http_client, ResilientHttpClient)
    assert adapter.client.http is adapter.http_client


def test_injected_http_client_is_exposed(adapter, http):
    assert adapter.http_client is http


def test_config_parsing():
    adapter = GitLabAdapter(
        credentials=CREDENTIALS,
        http_client=FakeHttpClient(),
        config={"groups": " a, ,b/c ,", "include_archived": True, "verify_ssl": False, "timeout": 5},
    )
    assert adapter.groups == ["a", "b/c"]
    assert adapter.include_archived is True
    assert adapter.client.verify_ssl is False and adapter.client.timeout == 5


def test_validate_credentials_missing_token(http):
    assert GitLabAdapter(credentials={"host": "gitlab.example.net"}, http_client=http).validate_credentials() is False


# ── connection ──


def test_test_connection_reports_user(adapter):
    result = adapter.test_connection()
    assert result.success is True and result.message == "Connected."
    assert result.details == {"username": "exampleuser", "name": "Example User"}


def test_test_connection_falls_back_to_version():
    http = FakeHttpClient()
    http.add("GET", "/user", fake_response({"message": "403 Forbidden"}, status=403))
    http.add("GET", "/version", fake_response({"version": "17.5.0"}))
    adapter = GitLabAdapter(credentials=CREDENTIALS, http_client=http)
    result = adapter.test_connection()
    assert result.success is True
    assert result.details == {"version": "17.5.0"}


def test_test_connection_bad_token():
    http = FakeHttpClient()
    http.add("GET", "/user", fake_response({"message": "401 Unauthorized"}, status=401))
    result = GitLabAdapter(credentials=CREDENTIALS, http_client=http).test_connection()
    assert result.success is False and result.message


# ── reads ──


def test_list_projects_without_groups(adapter, http):
    result = adapter.list_projects(search="aio")
    assert all(isinstance(r, Repository) for r in result.items)
    assert result.cursor == "2" and result.has_more is True and result.total == 150
    assert http.calls[0].kwargs["params"]["search"] == "aio"
    adapter.list_projects(cursor="2")
    assert http.calls[-1].kwargs["params"]["page"] == "2"


def test_list_projects_groups_cursor():
    http = FakeHttpClient()
    http.add("GET", "groups/a/projects", fake_response(load("projects"), LAST))
    http.add("GET", "groups/b/projects", fake_response(load("projects"), {**LAST, "X-Total": "4"}))
    adapter = GitLabAdapter(credentials=CREDENTIALS, http_client=http, config={"groups": "a,b"})

    first = adapter.list_projects()
    assert first.cursor == "1:1" and first.has_more is True and first.total is None

    second = adapter.list_projects(cursor=first.cursor)
    assert "groups/b/projects" in http.calls[-1].path
    assert second.cursor is None and second.has_more is False and second.total is None


def test_list_projects_empty_group_still_has_more():
    http = FakeHttpClient()
    http.add("GET", "groups/a/projects", fake_response([], LAST))
    adapter = GitLabAdapter(credentials=CREDENTIALS, http_client=http, config={"groups": "a,b"})
    result = adapter.list_projects()
    assert result.items == [] and result.has_more is True and result.cursor == "1:1"


def test_get_project_by_path(adapter, http):
    http.responses.insert(0, ("GET", "projects/bapp-cloud%2Fapplication%2Faio-backend", fake_response(load("project"))))
    repo = adapter.get_project("bapp-cloud/application/aio-backend")
    assert repo.ref == "382"


def test_get_issue(adapter):
    issue = adapter.get_issue("382", 16)
    assert isinstance(issue, Issue) and issue.number == 16 and issue.ref == "382"


def test_list_issues_passes_filters(adapter, http):
    result = adapter.list_issues("382", state="closed", cursor="3")
    assert result.has_more is False and result.cursor is None
    params = http.last_call().kwargs["params"]
    assert params["state"] == "closed" and params["page"] == "3"


def test_list_merge_requests(adapter):
    result = adapter.list_merge_requests("382")
    assert result.items and all(mr.ref == "382" for mr in result.items)


def test_list_commits_and_pipelines_carry_ref(adapter, http):
    commits = adapter.list_commits("382", branch="main")
    assert commits.items and all(c.ref == "382" for c in commits.items)
    assert http.last_call().kwargs["params"]["ref_name"] == "main"
    pipelines = adapter.list_pipelines("382", branch="main")
    assert pipelines.items and all(p.ref == "382" for p in pipelines.items)
    assert http.last_call().kwargs["params"]["ref"] == "main"


def test_list_pipelines_by_path_reports_numeric_ref(adapter, http):
    path = "bapp-cloud%2Fapplication%2Faio-backend"
    http.responses.insert(0, ("GET", f"projects/{path}/pipelines", fake_response(load("pipelines"), LAST)))
    http.responses.insert(1, ("GET", f"projects/{path}", fake_response(load("project"))))
    result = adapter.list_pipelines("bapp-cloud/application/aio-backend")
    assert result.items and all(p.ref == "382" for p in result.items)


# ── issue management ──


def test_create_issue_posts_payload(adapter, http):
    http.add("POST", "/projects/382/issues", fake_response(load("issues")[0], status=201))
    issue = adapter.create_issue("382", IssueDraft(title="Down", description="x", labels=["ops", "p1"]))
    assert isinstance(issue, Issue)
    body = http.last_call().kwargs["json"]
    assert body["title"] == "Down" and body["labels"] == "ops,p1"


def test_update_issue_puts_payload(adapter, http):
    http.add("PUT", "/projects/382/issues/16", fake_response(load("issues")[0]))
    adapter.update_issue("382", 16, IssueDraft(title="New"))
    assert http.last_call().method == "PUT" and http.last_call().kwargs["json"]["title"] == "New"


@pytest.mark.parametrize(("method", "event"), [("close_issue", "close"), ("reopen_issue", "reopen")])
def test_close_and_reopen(adapter, http, method, event):
    http.add("PUT", "/projects/382/issues/16", fake_response(load("issues")[0]))
    assert isinstance(getattr(adapter, method)("382", 16), Issue)
    assert http.last_call().kwargs["json"] == {"state_event": event}


def test_add_issue_comment(adapter, http):
    note = {"id": 9, "body": "seen", "author": {"username": "exampleuser"}, "created_at": "2026-10-23T08:00:00Z"}
    http.add("POST", "/projects/382/issues/16/notes", fake_response(note, status=201))
    comment = adapter.add_issue_comment("382", 16, "seen")
    assert isinstance(comment, IssueComment) and comment.body == "seen"
    assert http.last_call().kwargs["json"] == {"body": "seen"}


# ── webhooks ──


def test_verify_webhook_plain_token(http):
    adapter = GitLabAdapter(credentials={**CREDENTIALS, "webhook_secret": "s3"}, http_client=http)
    assert adapter.verify_webhook({"X-Gitlab-Token": "s3"}, b"{}") is True
    assert adapter.verify_webhook({"x-gitlab-token": "nope"}, b"{}") is False
    assert adapter.verify_webhook({}, b"{}") is False
    assert (
        GitLabAdapter(credentials=CREDENTIALS, http_client=http).verify_webhook({"X-Gitlab-Token": ""}, b"{}") is False
    )


def test_verify_webhook_explicit_secret_wins(adapter):
    assert adapter.verify_webhook({"x-gitlab-token": "given"}, b"{}", secret="given") is True


def test_parse_webhook(adapter):
    body = json.dumps(load("hook_push")).encode()
    event = adapter.parse_webhook({"X-Gitlab-Event": "Push Hook"}, body)
    assert event.event_type == WebhookEventType.REPOSITORY_PUSH and event.provider == "gitlab"


def test_register_webhook(http):
    adapter = GitLabAdapter(
        credentials={**CREDENTIALS, "webhook_secret": "s3"}, http_client=http, config={"verify_ssl": False}
    )
    http.add("POST", "/projects/382/hooks", fake_response({"id": 77, "url": "https://hooks.example.net/x"}, status=201))
    result = adapter.register_webhook("https://hooks.example.net/x", ref="382")
    assert result["id"] == 77
    assert http.last_call().kwargs["json"] == {
        "url": "https://hooks.example.net/x",
        "token": "s3",
        "push_events": True,
        "issues_events": True,
        "merge_requests_events": True,
        "pipeline_events": True,
        "note_events": True,
        "enable_ssl_verification": False,
    }


def test_list_webhooks(adapter, http):
    http.add("GET", "/projects/382/hooks", fake_response([{"id": 77}]))
    http.responses.insert(0, http.responses.pop())
    assert adapter.list_webhooks(ref="382") == [{"id": 77}]


def test_webhook_registration_requires_ref(adapter):
    with pytest.raises(ValidationError, match="ref is required"):
        adapter.register_webhook("https://hooks.example.net/x")
    with pytest.raises(ValidationError, match="ref is required"):
        adapter.list_webhooks()


# ── registry ──


def test_registry():
    import bapp_connectors.providers.devops.gitlab  # noqa: F401

    assert registry.is_registered("devops", "gitlab")
    assert any(m.name == "gitlab" for m in registry.list_providers(capability=IssueManagementCapability))
    assert any(m.name == "gitlab" for m in registry.list_providers(capability=WebhookCapability))
