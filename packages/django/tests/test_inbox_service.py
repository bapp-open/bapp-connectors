"""Tests for InboxPollService."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from bapp_connectors.core.dto import EmailDetail, EmailSummary, InboxAction
from django_bapp_connectors.signals import email_received

from .testapp.models import Connection


class FakeInboxAdapter:
    def __init__(self, summaries, *, hydrate_error_ids=()):
        self._summaries = summaries
        self._hydrate_error_ids = set(hydrate_error_ids)
        self.deleted: list[str] = []
        self.moved: list[tuple[str, str]] = []
        self.marked: list[tuple[str, bool]] = []

    def fetch_messages(self, *, since=None, until=None, folder="INBOX", limit=50):
        return self._summaries

    def get_message(self, message_id, *, folder="INBOX"):
        if message_id in self._hydrate_error_ids:
            raise RuntimeError("hydrate failed")
        return EmailDetail(message_id=message_id, folder=folder, subject=f"subj-{message_id}")

    def delete_message(self, message_id, *, folder="INBOX"):
        self.deleted.append(message_id)

    def move_message(self, message_id, target_folder, *, folder="INBOX"):
        self.moved.append((message_id, target_folder))

    def mark_read(self, message_id, *, read=True, folder="INBOX"):
        self.marked.append((message_id, read))


@pytest.fixture
def connection(db):
    return Connection.objects.create(
        provider_family="email",
        provider_name="gmail",
        display_name="Mail",
        is_enabled=True,
        is_connected=True,
    )


def _service(connection, adapter):
    from django_bapp_connectors.services.inbox import InboxPollService

    connection.get_adapter = MagicMock(return_value=adapter)
    return InboxPollService(connection)


def test_signal_fires_with_hydrated_detail(connection):
    adapter = FakeInboxAdapter([EmailSummary(message_id="1")])
    seen = []

    def handler(sender, **kwargs):
        seen.append(kwargs["email"])
        return

    email_received.connect(handler)
    try:
        result = _service(connection, adapter).poll(folder="INBOX")
    finally:
        email_received.disconnect(handler)

    assert result.fetched == 1
    assert isinstance(seen[0], EmailDetail)
    assert seen[0].subject == "subj-1"


def test_delete_action_applied(connection):
    adapter = FakeInboxAdapter([EmailSummary(message_id="1")])

    def handler(sender, **kwargs):
        return InboxAction.delete()

    email_received.connect(handler)
    try:
        result = _service(connection, adapter).poll()
    finally:
        email_received.disconnect(handler)

    assert adapter.deleted == ["1"]
    assert result.records[0].applied is True


def test_move_action_applied(connection):
    adapter = FakeInboxAdapter([EmailSummary(message_id="9")])

    def handler(sender, **kwargs):
        return InboxAction.move("Archive")

    email_received.connect(handler)
    try:
        _service(connection, adapter).poll()
    finally:
        email_received.disconnect(handler)

    assert adapter.moved == [("9", "Archive")]


def test_first_registered_action_wins(connection):
    adapter = FakeInboxAdapter([EmailSummary(message_id="1")])

    def first(sender, **kwargs):
        return InboxAction.move("Archive")

    def second(sender, **kwargs):
        return InboxAction.delete()

    email_received.connect(first)
    email_received.connect(second)
    try:
        _service(connection, adapter).poll()
    finally:
        email_received.disconnect(first)
        email_received.disconnect(second)

    assert adapter.moved == [("1", "Archive")]
    assert adapter.deleted == []


def test_raising_receiver_is_skipped(connection):
    adapter = FakeInboxAdapter([EmailSummary(message_id="1")])

    def broken(sender, **kwargs):
        raise RuntimeError("boom")

    def good(sender, **kwargs):
        return InboxAction.mark_read()

    email_received.connect(broken)
    email_received.connect(good)
    try:
        result = _service(connection, adapter).poll()
    finally:
        email_received.disconnect(broken)
        email_received.disconnect(good)

    assert adapter.marked == [("1", True)]
    assert result.records[0].applied is True


def test_hydration_failure_records_error_and_continues(connection):
    adapter = FakeInboxAdapter(
        [EmailSummary(message_id="bad"), EmailSummary(message_id="ok")],
        hydrate_error_ids=("bad",),
    )
    calls = []

    def handler(sender, **kwargs):
        calls.append(kwargs["email"].message_id)
        return

    email_received.connect(handler)
    try:
        result = _service(connection, adapter).poll()
    finally:
        email_received.disconnect(handler)

    assert result.fetched == 2
    assert calls == ["ok"]                 # signal not fired for the failed one
    assert result.records[0].error != ""   # 'bad' carries the error
    assert result.records[0].applied is False


def test_no_action_applies_nothing(connection):
    adapter = FakeInboxAdapter([EmailSummary(message_id="1")])
    result = _service(connection, adapter).poll()
    assert adapter.deleted == [] and adapter.moved == [] and adapter.marked == []
    assert result.records[0].applied is False
