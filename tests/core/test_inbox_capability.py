"""Contract tests for the InboxCapability ABC."""

from __future__ import annotations

import pytest

from bapp_connectors.core.capabilities import InboxCapability


def test_incomplete_subclass_cannot_instantiate():
    class Incomplete(InboxCapability):
        def fetch_messages(self, *, since=None, until=None, folder="INBOX", limit=50):
            return []

        def get_message(self, message_id, *, folder="INBOX"):
            return None

        def download_attachment(self, message_id, attachment_id, *, folder="INBOX"):
            return None

        # delete_message / move_message / mark_read intentionally missing

    with pytest.raises(TypeError):
        Incomplete()


def test_email_adapters_still_instantiate():
    from bapp_connectors.providers.email.gmail.adapter import GmailEmailAdapter
    from bapp_connectors.providers.email.smtp.adapter import SMTPEmailAdapter
    from unittest.mock import MagicMock

    smtp = SMTPEmailAdapter(
        credentials={"username": "u@example.com", "password": "p", "imap_host": "imap.example.com"}
    )
    gmail = GmailEmailAdapter(credentials={"access_token": "t"}, http_client=MagicMock())
    assert isinstance(smtp, InboxCapability)
    assert isinstance(gmail, InboxCapability)
