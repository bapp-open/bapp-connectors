"""
Inbox poll service — fetch email, emit email_received per message, and apply
the first returned InboxAction (delete / move / mark_read).

This package provides the building blocks only; consuming projects decide when
to poll and own the time window (since/until) and any deduplication.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from bapp_connectors.core.dto import (
    EmailDetail,
    EmailSummary,
    InboxAction,
    InboxActionType,
)
from django_bapp_connectors.signals import email_received

if TYPE_CHECKING:
    from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class InboxPollRecord:
    """Outcome for a single polled message."""

    email: EmailDetail | EmailSummary
    action: InboxAction | None = None
    applied: bool = False
    error: str = ""


@dataclass
class InboxPollResult:
    """Aggregate outcome of one poll() call."""

    folder: str
    fetched: int
    records: list[InboxPollRecord] = field(default_factory=list)


class InboxPollService:
    """Poll a connection's mailbox and dispatch email_received per message."""

    def __init__(self, connection):
        self.connection = connection

    def poll(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        folder: str = "INBOX",
        limit: int = 50,
    ) -> InboxPollResult:
        adapter = self.connection.get_adapter()
        summaries = adapter.fetch_messages(
            since=since, until=until, folder=folder, limit=limit
        )
        records: list[InboxPollRecord] = []
        for summary in summaries:
            try:
                email = adapter.get_message(summary.message_id, folder=folder)
            except Exception as e:
                logger.warning(
                    "Inbox hydrate failed for %s: %s", summary.message_id, e
                )
                records.append(
                    InboxPollRecord(email=summary, applied=False, error=str(e))
                )
                continue
            action = self._dispatch(email, folder)
            applied, err = self._apply(adapter, email, folder, action)
            records.append(
                InboxPollRecord(email=email, action=action, applied=applied, error=err)
            )
        return InboxPollResult(folder=folder, fetched=len(summaries), records=records)

    def _dispatch(self, email, folder) -> InboxAction | None:
        responses = email_received.send_robust(
            sender=type(self.connection),
            connection=self.connection,
            email=email,
            folder=folder,
            provider_family=getattr(self.connection, "provider_family", ""),
            provider_name=getattr(self.connection, "provider_name", ""),
        )
        for receiver, response in responses:
            if isinstance(response, Exception):
                logger.warning(
                    "email_received receiver %r raised: %s", receiver, response
                )
                continue
            if isinstance(response, InboxAction) and response.type != InboxActionType.NONE:
                return response
        return None

    def _apply(self, adapter, email, folder, action) -> tuple[bool, str]:
        if action is None:
            return False, ""
        try:
            if action.type == InboxActionType.DELETE:
                adapter.delete_message(email.message_id, folder=folder)
            elif action.type == InboxActionType.MOVE:
                adapter.move_message(email.message_id, action.folder, folder=folder)
            elif action.type == InboxActionType.MARK_READ:
                adapter.mark_read(email.message_id, read=action.read, folder=folder)
            else:
                return False, ""
            return True, ""
        except Exception as e:
            logger.warning(
                "Inbox action %s failed for %s: %s", action.type, email.message_id, e
            )
            return False, str(e)
