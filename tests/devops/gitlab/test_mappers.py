"""GitLab mappers against the anonymized REST captures and hand-written webhook payloads."""

from datetime import UTC, datetime

import pytest

from bapp_connectors.core.dto import WebhookEventType
from bapp_connectors.core.dto.devops import IssueDraft
from bapp_connectors.providers.devops.gitlab.mappers import (
    issue_draft_to_payload,
    map_commit,
    map_issue,
    map_issue_comment,
    map_merge_request,
    map_pipeline,
    map_repository,
    webhook_event_from_gitlab,
)

# ── Repositories ──


def test_map_repository(projects_raw):
    raw = projects_raw[0]
    repo = map_repository(raw)
    assert repo.ref == str(raw["id"]) and repo.full_path == raw["path_with_namespace"]
    assert repo.name == raw["name"]
    assert repo.namespace == raw["namespace"]["full_path"]
    assert repo.last_activity_at is not None and repo.last_activity_at.tzinfo is not None
    assert repo.extra == {"star_count": raw["star_count"], "forks_count": raw["forks_count"]}


def test_map_repository_single_project(project_raw):
    repo = map_repository(project_raw)
    assert repo.ref == "382"
    assert repo.full_path == "bapp-cloud/application/aio-backend"
    assert repo.default_branch == "master"
    assert repo.visibility == "private"
    assert repo.archived is False
    assert repo.open_issues_count == 0
    assert repo.web_url.startswith("https://gitlab.example.net/")


def test_map_repository_tolerates_minimal_payload():
    repo = map_repository({"id": 7, "name": "x", "path_with_namespace": "g/x", "description": None})
    assert repo.ref == "7" and repo.description == "" and repo.namespace == ""
    assert repo.last_activity_at is None and repo.open_issues_count is None and repo.extra == {}


# ── Issues ──


def test_map_issue(issues_raw):
    raw = issues_raw[0]
    issue = map_issue(raw)
    assert issue.number == raw["iid"]
    assert issue.ref == str(raw["project_id"])
    assert isinstance(issue.labels, list)
    assert issue.state == "closed"
    assert issue.author == "Example User"
    assert issue.closed_at is not None and issue.closed_at.tzinfo is not None
    assert issue.extra["author_username"] == "exampleuser"


def test_map_issue_assignees_and_labels(issues_raw):
    raw = {**issues_raw[1], "labels": ["bug", "monitoring"], "state": "opened"}
    issue = map_issue(raw)
    assert issue.state == "opened"
    assert issue.labels == ["bug", "monitoring"]
    assert issue.assignees == ["Example User"]
    assert issue.extra["assignee_ids"] == [18]
    assert issue.extra["milestone"] is None


def test_map_issue_tolerates_missing_people():
    issue = map_issue({"id": 1, "iid": 2, "project_id": 3, "title": "t", "description": None})
    assert issue.author == "" and issue.assignees == [] and issue.description == ""
    assert issue.extra == {"author_username": "", "assignee_ids": [], "milestone": None}


# ── Merge requests, commits, pipelines, comments ──


def test_map_merge_request(merge_requests_raw):
    merged = map_merge_request(merge_requests_raw[1])
    assert merged.number == 12 and merged.state == "merged"
    assert merged.ref == "382"
    assert merged.source_branch == "feature/reception-scan-increment" and merged.target_branch == "master"
    assert merged.merged_at == datetime(2026, 5, 26, 4, 57, 55, 555000, tzinfo=UTC)
    assert map_merge_request(merge_requests_raw[0]).merged_at is None


def test_map_commit(commits_raw):
    raw = commits_raw[0]
    commit = map_commit(raw, "382")
    assert commit.ref == "382" and commit.sha == raw["id"]
    assert commit.title == raw["title"]
    assert commit.author_name == "Example User" and commit.author_email == "user@example.com"
    assert commit.authored_at is not None and commit.authored_at.utcoffset().total_seconds() == 3 * 3600


def test_map_pipeline(pipelines_raw):
    raw = pipelines_raw[0]
    pipeline = map_pipeline(raw, "382")
    assert pipeline.id == str(raw["id"]) and pipeline.ref == "382"
    assert pipeline.status == "success"
    assert pipeline.branch == raw["ref"] == "master"
    assert pipeline.sha == raw["sha"]
    assert pipeline.created_at is not None and pipeline.finished_at is None


def test_map_pipeline_finished_at():
    pipeline = map_pipeline({"id": 1, "status": "failed", "finished_at": "2026-10-20T10:11:12.345Z"}, "9")
    assert pipeline.finished_at == datetime(2026, 10, 20, 10, 11, 12, 345000, tzinfo=UTC)


def test_map_issue_comment():
    comment = map_issue_comment(
        {"id": 71234, "body": "hello", "author": {"name": "Example User"}, "created_at": "2026-10-20T10:11:12+00:00"}
    )
    assert comment.id == "71234" and comment.body == "hello" and comment.author == "Example User"
    assert comment.created_at == datetime(2026, 10, 20, 10, 11, 12, tzinfo=UTC)


def test_bad_datetime_is_none():
    assert map_pipeline({"id": 1, "status": "x", "created_at": "not a date"}, "9").created_at is None


# ── Issue drafts ──


def test_issue_draft_payload():
    draft = IssueDraft(title="t", labels=["a", "b"], assignee_ids=["7"])
    assert issue_draft_to_payload(draft) == {"title": "t", "description": "", "labels": "a,b", "assignee_ids": [7]}


# ── Webhooks ──


def test_webhook_push(hook_push):
    event = webhook_event_from_gitlab({"X-Gitlab-Event": "Push Hook"}, hook_push)
    assert event.event_type == WebhookEventType.REPOSITORY_PUSH
    assert event.provider == "gitlab"
    assert event.provider_event_type == "Push Hook:"
    assert event.idempotency_key == f"push:{hook_push['project']['id']}:{hook_push['checkout_sha']}"
    assert event.payload == hook_push
    assert event.received_at is not None and event.received_at.tzinfo is not None


def test_webhook_issue_close(hook_issue):
    event = webhook_event_from_gitlab({"x-gitlab-event": "Issue Hook"}, hook_issue)
    assert event.event_type == WebhookEventType.ISSUE_CLOSED
    assert event.provider_event_type == "Issue Hook:close"
    assert event.idempotency_key == "issue:962:2021-05-07T11:35:48.069Z"


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        ("open", WebhookEventType.ISSUE_OPENED),
        ("update", WebhookEventType.ISSUE_UPDATED),
        ("reopen", WebhookEventType.ISSUE_REOPENED),
        ("move", WebhookEventType.UNKNOWN),
    ],
)
def test_webhook_issue_actions(hook_issue, action, expected):
    payload = {**hook_issue, "object_attributes": {**hook_issue["object_attributes"], "action": action}}
    assert webhook_event_from_gitlab({"X-Gitlab-Event": "Issue Hook"}, payload).event_type == expected


def test_webhook_note_on_issue(hook_note):
    event = webhook_event_from_gitlab({"X-Gitlab-Event": "Note Hook"}, hook_note)
    assert event.event_type == WebhookEventType.ISSUE_COMMENTED
    assert event.idempotency_key == "note:71234:2021-05-07T11:34:01.512Z"


def test_webhook_note_on_merge_request_is_unknown(hook_note):
    payload = {**hook_note, "object_attributes": {**hook_note["object_attributes"], "noteable_type": "MergeRequest"}}
    assert webhook_event_from_gitlab({"X-Gitlab-Event": "Note Hook"}, payload).event_type == WebhookEventType.UNKNOWN


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        ("open", WebhookEventType.MERGE_REQUEST_OPENED),
        ("merge", WebhookEventType.MERGE_REQUEST_MERGED),
        ("close", WebhookEventType.MERGE_REQUEST_CLOSED),
        ("approved", WebhookEventType.UNKNOWN),
    ],
)
def test_webhook_merge_request(hook_merge_request, action, expected):
    payload = {
        **hook_merge_request,
        "object_attributes": {**hook_merge_request["object_attributes"], "action": action},
    }
    event = webhook_event_from_gitlab({"X-Gitlab-Event": "Merge Request Hook"}, payload)
    assert event.event_type == expected
    assert event.provider_event_type == f"Merge Request Hook:{action}"


def test_webhook_merge_request_key(hook_merge_request):
    event = webhook_event_from_gitlab({"X-Gitlab-Event": "Merge Request Hook"}, hook_merge_request)
    assert event.idempotency_key == "merge_request:4512:2026-05-26T04:57:55.601Z"


def test_webhook_pipeline_failed(hook_pipeline):
    event = webhook_event_from_gitlab({"X-Gitlab-Event": "Pipeline Hook"}, hook_pipeline)
    assert event.event_type == WebhookEventType.PIPELINE_FAILED
    assert event.provider_event_type == "Pipeline Hook:failed"
    assert event.idempotency_key == "pipeline:52866:2026-10-23 06:51:31 UTC"


@pytest.mark.parametrize(
    ("status", "expected"),
    [("success", WebhookEventType.PIPELINE_SUCCEEDED), ("running", WebhookEventType.UNKNOWN)],
)
def test_webhook_pipeline_statuses(hook_pipeline, status, expected):
    payload = {**hook_pipeline, "object_attributes": {**hook_pipeline["object_attributes"], "status": status}}
    assert webhook_event_from_gitlab({"X-Gitlab-Event": "Pipeline Hook"}, payload).event_type == expected


def test_webhook_unknown():
    event = webhook_event_from_gitlab({"X-Gitlab-Event": "Wiki Page Hook"}, {"object_kind": "wiki_page"})
    assert event.event_type == WebhookEventType.UNKNOWN
    assert event.provider == "gitlab"
    assert event.provider_event_type == "Wiki Page Hook:"
    assert event.idempotency_key == "wiki_page::"


@pytest.mark.parametrize(
    "value",
    ["2026-10-23 06:51:31 UTC", "2026-10-23T06:51:31Z", "2026-10-23T09:51:31+03:00", "2026-10-23 09:51:31 +0300"],
)
def test_dt_parses_rest_and_webhook_timestamps(value):
    from bapp_connectors.providers.devops.gitlab.mappers import _dt

    assert _dt(value) == datetime(2026, 10, 23, 6, 51, 31, tzinfo=UTC)


def test_dt_rejects_garbage():
    from bapp_connectors.providers.devops.gitlab.mappers import _dt

    assert _dt("yesterday UTC") is None
