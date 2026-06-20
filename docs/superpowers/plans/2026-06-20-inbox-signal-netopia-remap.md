# Inbox `email_received` Signal + Netopia Payment Remap — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remap Netopia IPN webhooks to `payment.*` events, and ship reusable building blocks (mailbox delete/move/mark-read operations, an `InboxAction` DTO, an `email_received` Django signal, and an `InboxPollService`) so consuming projects can react to each fetched email and instruct a termination action.

**Architecture:** Core (`bapp-connectors`, Django-free) gains the `InboxAction` DTO, three new `InboxCapability` operations implemented by the IMAP/SMTP and Gmail adapters, and a new `PAYMENT_PENDING` webhook event. The Django package (`django-bapp-connectors`) gains an `email_received` signal and an `InboxPollService` that hydrates each fetched summary to a full `EmailDetail`, fires the signal via `send_robust`, and applies the first returned `InboxAction` to the mailbox.

**Tech Stack:** Python 3.13, Pydantic DTOs (`BaseDTO`), `imaplib` (IMAP), Gmail REST API v1, Django signals (`django.dispatch`), pytest.

## Global Constraints

- Core package (`src/bapp_connectors/**`) MUST stay Django-free — no Django imports.
- Adapter `__init__` signature stays `(credentials: dict, http_client=None, config=None, **kwargs)`.
- All Django signal emission uses `send_robust()` (receiver errors never break framework ops).
- Commit messages: **no `Co-Authored-By` trailer.**
- Run `ruff` before any push; bump **both** `bapp-connectors` and `django-bapp-connectors` versions together.
- Core unit tests: `uv run --extra dev pytest tests/ -v` (run from repo root `packages/connectors/`).
- Django unit tests: `cd packages/django && uv run --extra dev pytest tests/ -v`.
- The pre-commit hook regenerates `README.md`; let it run, do not hand-edit the providers table.

---

### Task 1: Netopia IPN → payment-event remap

**Files:**
- Modify: `src/bapp_connectors/core/dto/webhook.py:29-32` (add `PAYMENT_PENDING`)
- Modify: `src/bapp_connectors/providers/payment/netopia/mappers.py:148-153` (remap)
- Test: `tests/payment/netopia/test_unit.py`

**Interfaces:**
- Produces: `WebhookEventType.PAYMENT_PENDING = "payment.pending"`; `webhook_event_from_netopia(data: dict) -> WebhookEvent` now returns `payment.*` event types.

- [ ] **Step 1: Write the failing test** — append to `tests/payment/netopia/test_unit.py`

Add these imports near the top of the file (after the existing imports):

```python
from bapp_connectors.core.dto.webhook import WebhookEventType
from bapp_connectors.providers.payment.netopia.mappers import webhook_event_from_netopia
```

Add this test class at the end of the file:

```python
class TestNetopiaWebhookMapping:
    @pytest.mark.parametrize(
        "status_code,expected",
        [
            (0, WebhookEventType.PAYMENT_PENDING),    # pending
            (3, WebhookEventType.PAYMENT_PENDING),    # paid_pending
            (5, WebhookEventType.PAYMENT_COMPLETED),  # confirmed
            (12, WebhookEventType.PAYMENT_FAILED),    # cancelled
            (15, WebhookEventType.PAYMENT_REFUNDED),  # credit
        ],
    )
    def test_ipn_status_maps_to_payment_event(self, status_code, expected):
        event = webhook_event_from_netopia(
            {"status": status_code, "payment": {"ntpID": "NTP1"}}
        )
        assert event.event_type == expected
        assert event.provider == "netopia"
        assert event.event_id == "NTP1"
        assert event.provider_event_type.startswith("payment.")

    def test_unknown_status_is_unknown(self):
        event = webhook_event_from_netopia({"status": 999})
        assert event.event_type == WebhookEventType.UNKNOWN
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/payment/netopia/test_unit.py::TestNetopiaWebhookMapping -v`
Expected: FAIL — `status=5` currently maps to `ORDER_UPDATED`, and `PAYMENT_PENDING` does not exist yet (ImportError/AttributeError).

- [ ] **Step 3: Add the enum value** — `src/bapp_connectors/core/dto/webhook.py`

Change the Payments block (lines 29-32) from:

```python
    # Payments
    PAYMENT_COMPLETED = "payment.completed"
    PAYMENT_FAILED = "payment.failed"
    PAYMENT_REFUNDED = "payment.refunded"
```

to:

```python
    # Payments
    PAYMENT_PENDING = "payment.pending"
    PAYMENT_COMPLETED = "payment.completed"
    PAYMENT_FAILED = "payment.failed"
    PAYMENT_REFUNDED = "payment.refunded"
```

- [ ] **Step 4: Remap the IPN event map** — `src/bapp_connectors/providers/payment/netopia/mappers.py`

Replace the `NETOPIA_IPN_EVENT_MAP` (lines 148-153):

```python
NETOPIA_IPN_EVENT_MAP: dict[str, WebhookEventType] = {
    "confirmed": WebhookEventType.ORDER_UPDATED,
    "paid_pending": WebhookEventType.ORDER_UPDATED,
    "cancelled": WebhookEventType.ORDER_CANCELLED,
    "credit": WebhookEventType.ORDER_UPDATED,
}
```

with:

```python
NETOPIA_IPN_EVENT_MAP: dict[str, WebhookEventType] = {
    "pending": WebhookEventType.PAYMENT_PENDING,        # status 0
    "paid_pending": WebhookEventType.PAYMENT_PENDING,   # status 3
    "confirmed": WebhookEventType.PAYMENT_COMPLETED,    # status 5
    "cancelled": WebhookEventType.PAYMENT_FAILED,       # status 12
    "credit": WebhookEventType.PAYMENT_REFUNDED,        # status 15 (refund)
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/payment/netopia/test_unit.py -v`
Expected: PASS (all parametrized cases + unknown).

- [ ] **Step 6: Commit**

```bash
git add src/bapp_connectors/core/dto/webhook.py \
        src/bapp_connectors/providers/payment/netopia/mappers.py \
        tests/payment/netopia/test_unit.py
git commit -m "fix(netopia): map IPN statuses to payment.* events (confirmed -> payment.completed)"
```

---

### Task 2: `InboxAction` DTO (core)

**Files:**
- Modify: `src/bapp_connectors/core/dto/email.py` (add `InboxActionType`, `InboxAction`)
- Modify: `src/bapp_connectors/core/dto/__init__.py` (export both)
- Test: `tests/core/test_inbox_action.py` (create)

**Interfaces:**
- Produces:
  - `class InboxActionType(StrEnum)` with members `NONE="none"`, `DELETE="delete"`, `MOVE="move"`, `MARK_READ="mark_read"`.
  - `class InboxAction(BaseDTO)` fields `type: InboxActionType = NONE`, `folder: str = ""`, `read: bool = True`; classmethods `delete()`, `move(folder)`, `mark_read(read=True)`, `none()`.

- [ ] **Step 1: Write the failing test** — create `tests/core/test_inbox_action.py`

```python
"""Unit tests for the InboxAction DTO."""

from __future__ import annotations

from bapp_connectors.core.dto import InboxAction, InboxActionType


def test_default_is_none():
    action = InboxAction()
    assert action.type == InboxActionType.NONE
    assert action.folder == ""
    assert action.read is True


def test_delete_factory():
    action = InboxAction.delete()
    assert action.type == InboxActionType.DELETE


def test_move_factory():
    action = InboxAction.move("Archive")
    assert action.type == InboxActionType.MOVE
    assert action.folder == "Archive"


def test_mark_read_factory():
    assert InboxAction.mark_read().type == InboxActionType.MARK_READ
    assert InboxAction.mark_read().read is True
    assert InboxAction.mark_read(read=False).read is False


def test_none_factory():
    assert InboxAction.none().type == InboxActionType.NONE
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/core/test_inbox_action.py -v`
Expected: FAIL — `ImportError: cannot import name 'InboxAction'`.

- [ ] **Step 3: Add the DTO** — `src/bapp_connectors/core/dto/email.py`

At the top of the file, add `StrEnum` to imports. The current header is:

```python
from __future__ import annotations

from datetime import datetime

from .base import BaseDTO
```

Change it to:

```python
from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from .base import BaseDTO
```

At the **end** of the file, append:

```python
class InboxActionType(StrEnum):
    """Termination action a receiver may request for a fetched email."""

    NONE = "none"
    DELETE = "delete"
    MOVE = "move"
    MARK_READ = "mark_read"


class InboxAction(BaseDTO):
    """Instruction returned by an email_received receiver.

    Maps 1:1 to InboxCapability operations. Use the factory classmethods
    rather than constructing directly.
    """

    type: InboxActionType = InboxActionType.NONE
    folder: str = ""      # target folder for MOVE
    read: bool = True     # desired read state for MARK_READ

    @classmethod
    def delete(cls) -> "InboxAction":
        return cls(type=InboxActionType.DELETE)

    @classmethod
    def move(cls, folder: str) -> "InboxAction":
        return cls(type=InboxActionType.MOVE, folder=folder)

    @classmethod
    def mark_read(cls, read: bool = True) -> "InboxAction":
        return cls(type=InboxActionType.MARK_READ, read=read)

    @classmethod
    def none(cls) -> "InboxAction":
        return cls(type=InboxActionType.NONE)
```

- [ ] **Step 4: Export the DTO** — `src/bapp_connectors/core/dto/__init__.py`

Change the email import line (line 6):

```python
from .email import EmailAddress, EmailAttachmentContent, EmailAttachmentInfo, EmailDetail, EmailSummary
```

to:

```python
from .email import (
    EmailAddress,
    EmailAttachmentContent,
    EmailAttachmentInfo,
    EmailDetail,
    EmailSummary,
    InboxAction,
    InboxActionType,
)
```

In the `__all__` list, add (keep it alphabetical-ish, next to the Email entries):

```python
    "InboxAction",
    "InboxActionType",
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/core/test_inbox_action.py -v`
Expected: PASS (5 tests).

- [ ] **Step 6: Commit**

```bash
git add src/bapp_connectors/core/dto/email.py \
        src/bapp_connectors/core/dto/__init__.py \
        tests/core/test_inbox_action.py
git commit -m "feat(core): add InboxAction DTO for inbox termination actions"
```

---

### Task 3: IMAP/SMTP mailbox operations (delete / move / mark_read)

**Files:**
- Modify: `src/bapp_connectors/providers/email/smtp/client.py` (add `delete_uid`, `move_uid`, `set_seen` to `IMAPClient`)
- Modify: `src/bapp_connectors/providers/email/smtp/adapter.py` (add `delete_message`, `move_message`, `mark_read`)
- Test: `tests/email/smtp/test_inbox.py`

**Interfaces:**
- Consumes: nothing from prior tasks.
- Produces (on `SMTPEmailAdapter`):
  - `delete_message(message_id: str, *, folder: str = "INBOX") -> None`
  - `move_message(message_id: str, target_folder: str, *, folder: str = "INBOX") -> None`
  - `mark_read(message_id: str, *, read: bool = True, folder: str = "INBOX") -> None`
- Produces (on `IMAPClient`): `delete_uid(uid, *, folder)`, `move_uid(uid, target_folder, *, folder)`, `set_seen(uid, *, seen=True, folder)`.

> Note: do **not** add the abstract methods to `InboxCapability` yet — that happens in Task 5, after both adapters implement them, so the build stays green.

- [ ] **Step 1: Write the failing adapter test** — append to `tests/email/smtp/test_inbox.py`

```python
class TestSMTPInboxActions:
    def _adapter(self):
        from bapp_connectors.providers.email.smtp.adapter import SMTPEmailAdapter

        adapter = SMTPEmailAdapter(
            credentials={"username": "u@example.com", "password": "p", "imap_host": "imap.example.com"}
        )
        adapter.imap_client = MagicMock()
        return adapter

    def test_delete_message_delegates_to_client(self):
        adapter = self._adapter()
        adapter.delete_message("42", folder="INBOX")
        adapter.imap_client.delete_uid.assert_called_once_with("42", folder="INBOX")

    def test_move_message_delegates_to_client(self):
        adapter = self._adapter()
        adapter.move_message("42", "Archive", folder="INBOX")
        adapter.imap_client.move_uid.assert_called_once_with("42", "Archive", folder="INBOX")

    def test_mark_read_delegates_to_client(self):
        adapter = self._adapter()
        adapter.mark_read("42", read=True, folder="INBOX")
        adapter.imap_client.set_seen.assert_called_once_with("42", seen=True, folder="INBOX")

    def test_actions_without_imap_raise(self):
        from bapp_connectors.providers.email.smtp.adapter import SMTPEmailAdapter

        adapter = SMTPEmailAdapter(credentials={"username": "u@example.com", "password": "p"})
        adapter.imap_client = None
        with pytest.raises(Exception):
            adapter.delete_message("1")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/email/smtp/test_inbox.py::TestSMTPInboxActions -v`
Expected: FAIL — `AttributeError: 'SMTPEmailAdapter' object has no attribute 'delete_message'`.

- [ ] **Step 3: Add IMAP write methods** — `src/bapp_connectors/providers/email/smtp/client.py`

Insert these methods into `IMAPClient`, immediately after `fetch_message` (after line 336, before the `class IMAPFolderError` definition):

```python
    def set_seen(self, uid: str, *, seen: bool = True, folder: str = "INBOX") -> None:
        """Add or remove the \\Seen flag on a message."""
        conn = self._connect()
        try:
            conn.select(folder, readonly=False)
            op = "+FLAGS" if seen else "-FLAGS"
            conn.uid("store", uid, op, "(\\Seen)")
        finally:
            with contextlib.suppress(Exception):
                conn.logout()

    def delete_uid(self, uid: str, *, folder: str = "INBOX") -> None:
        """Delete a message: flag \\Deleted then expunge."""
        conn = self._connect()
        try:
            conn.select(folder, readonly=False)
            conn.uid("store", uid, "+FLAGS", "(\\Deleted)")
            conn.expunge()
        finally:
            with contextlib.suppress(Exception):
                conn.logout()

    def move_uid(self, uid: str, target_folder: str, *, folder: str = "INBOX") -> None:
        """Move a message to another folder.

        Uses server-side UID MOVE when advertised; otherwise falls back to
        COPY + \\Deleted + EXPUNGE.
        """
        conn = self._connect()
        try:
            conn.select(folder, readonly=False)
            capabilities = getattr(conn, "capabilities", ())
            if "MOVE" in capabilities:
                conn.uid("move", uid, target_folder)
            else:
                conn.uid("copy", uid, target_folder)
                conn.uid("store", uid, "+FLAGS", "(\\Deleted)")
                conn.expunge()
        finally:
            with contextlib.suppress(Exception):
                conn.logout()
```

- [ ] **Step 4: Add adapter methods** — `src/bapp_connectors/providers/email/smtp/adapter.py`

Insert after `download_attachment` (after line 216, end of the `# ── InboxCapability ──` section):

```python
    def delete_message(self, message_id: str, *, folder: str = "INBOX") -> None:
        """Delete a message from the mailbox (flag \\Deleted + expunge)."""
        imap = self._require_imap()
        try:
            imap.delete_uid(message_id, folder=folder)
        except Exception as e:
            raise classify_imap_error(e) from e

    def move_message(self, message_id: str, target_folder: str, *, folder: str = "INBOX") -> None:
        """Move a message to another folder."""
        imap = self._require_imap()
        try:
            imap.move_uid(message_id, target_folder, folder=folder)
        except Exception as e:
            raise classify_imap_error(e) from e

    def mark_read(self, message_id: str, *, read: bool = True, folder: str = "INBOX") -> None:
        """Mark a message as read (read=True) or unread (read=False)."""
        imap = self._require_imap()
        try:
            imap.set_seen(message_id, seen=read, folder=folder)
        except Exception as e:
            raise classify_imap_error(e) from e
```

- [ ] **Step 5: Add a client-level test for the IMAP commands** — append to `tests/email/smtp/test_inbox.py`

```python
class TestIMAPClientWrites:
    def _client_with_mock_conn(self, capabilities=()):
        from bapp_connectors.providers.email.smtp.client import IMAPClient

        client = IMAPClient(host="imap.example.com", username="u", password="p")
        conn = MagicMock()
        conn.capabilities = capabilities
        client._connect = MagicMock(return_value=conn)
        return client, conn

    def test_delete_uid_flags_and_expunges(self):
        client, conn = self._client_with_mock_conn()
        client.delete_uid("42", folder="INBOX")
        conn.select.assert_called_once_with("INBOX", readonly=False)
        conn.uid.assert_called_once_with("store", "42", "+FLAGS", "(\\Deleted)")
        conn.expunge.assert_called_once()

    def test_move_uid_uses_server_move_when_supported(self):
        client, conn = self._client_with_mock_conn(capabilities=("MOVE",))
        client.move_uid("42", "Archive", folder="INBOX")
        conn.uid.assert_called_once_with("move", "42", "Archive")

    def test_move_uid_falls_back_to_copy(self):
        client, conn = self._client_with_mock_conn(capabilities=())
        client.move_uid("42", "Archive", folder="INBOX")
        conn.uid.assert_any_call("copy", "42", "Archive")
        conn.uid.assert_any_call("store", "42", "+FLAGS", "(\\Deleted)")
        conn.expunge.assert_called_once()

    def test_set_seen_adds_flag(self):
        client, conn = self._client_with_mock_conn()
        client.set_seen("42", seen=True, folder="INBOX")
        conn.uid.assert_called_once_with("store", "42", "+FLAGS", "(\\Seen)")
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run --extra dev pytest tests/email/smtp/test_inbox.py -v`
Expected: PASS (existing tests + `TestSMTPInboxActions` + `TestIMAPClientWrites`).

- [ ] **Step 7: Commit**

```bash
git add src/bapp_connectors/providers/email/smtp/client.py \
        src/bapp_connectors/providers/email/smtp/adapter.py \
        tests/email/smtp/test_inbox.py
git commit -m "feat(smtp): add IMAP delete/move/mark_read inbox operations"
```

---

### Task 4: Gmail mailbox operations (delete / move / mark_read)

**Files:**
- Modify: `src/bapp_connectors/providers/email/gmail/client.py` (add `modify_labels`, `trash_message` to `GmailApiClient`)
- Modify: `src/bapp_connectors/providers/email/gmail/adapter.py` (add `delete_message`, `move_message`, `mark_read`)
- Test: `tests/email/gmail/test_gmail.py`

**Interfaces:**
- Produces (on `GmailEmailAdapter`): same three method signatures as Task 3's `SMTPEmailAdapter`.
- Produces (on `GmailApiClient`): `modify_labels(message_id, *, add=None, remove=None) -> dict`, `trash_message(message_id) -> dict`.
- Semantics: delete → Gmail **Trash** (recoverable, not permanent); move → swap labels (`_folder_to_label(target)` added, `_folder_to_label(folder)` removed); mark_read → remove/add the `UNREAD` label.

- [ ] **Step 1: Write the failing test** — append to `tests/email/gmail/test_gmail.py`

```python
class TestGmailInboxActions:
    def _adapter(self):
        from bapp_connectors.providers.email.gmail.adapter import GmailEmailAdapter

        a = GmailEmailAdapter(credentials={"access_token": "tok"}, http_client=MagicMock())
        a.client = MagicMock()
        return a

    def test_delete_message_trashes(self):
        adapter = self._adapter()
        adapter.delete_message("m1", folder="INBOX")
        adapter.client.trash_message.assert_called_once_with("m1")

    def test_move_message_swaps_labels(self):
        adapter = self._adapter()
        adapter.move_message("m1", "Archive", folder="INBOX")
        adapter.client.modify_labels.assert_called_once_with(
            "m1", add=["Archive"], remove=["INBOX"]
        )

    def test_mark_read_removes_unread_label(self):
        adapter = self._adapter()
        adapter.mark_read("m1", read=True, folder="INBOX")
        adapter.client.modify_labels.assert_called_once_with("m1", remove=["UNREAD"])

    def test_mark_unread_adds_unread_label(self):
        adapter = self._adapter()
        adapter.mark_read("m1", read=False, folder="INBOX")
        adapter.client.modify_labels.assert_called_once_with("m1", add=["UNREAD"])
```

> `_folder_to_label("INBOX")` and `_folder_to_label("Archive")` return `"INBOX"` / `"Archive"` (the map returns the input when not a known alias), so the asserted label ids match.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/email/gmail/test_gmail.py::TestGmailInboxActions -v`
Expected: FAIL — `AttributeError: ... has no attribute 'delete_message'`.

- [ ] **Step 3: Add Gmail client methods** — `src/bapp_connectors/providers/email/gmail/client.py`

Insert into `GmailApiClient`, after `get_attachment` (the last method):

```python
    def modify_labels(
        self,
        message_id: str,
        *,
        add: list[str] | None = None,
        remove: list[str] | None = None,
    ) -> dict:
        """Add/remove labels on a message (Gmail messages.modify)."""
        body: dict = {}
        if add:
            body["addLabelIds"] = add
        if remove:
            body["removeLabelIds"] = remove
        return self.http.post(f"messages/{message_id}/modify", json=body)

    def trash_message(self, message_id: str) -> dict:
        """Move a message to Trash (Gmail messages.trash) — recoverable."""
        return self.http.post(f"messages/{message_id}/trash", json={})
```

- [ ] **Step 4: Add adapter methods** — `src/bapp_connectors/providers/email/gmail/adapter.py`

Insert after `download_attachment` (end of the `# ── InboxCapability ──` section):

```python
    def delete_message(self, message_id: str, *, folder: str = "INBOX") -> None:
        """Delete a message by moving it to Trash (recoverable; not permanent)."""
        try:
            self.client.trash_message(message_id)
        except Exception as e:
            raise classify_gmail_error(e) from e

    def move_message(self, message_id: str, target_folder: str, *, folder: str = "INBOX") -> None:
        """Move a message by swapping its folder labels."""
        try:
            self.client.modify_labels(
                message_id,
                add=[_folder_to_label(target_folder)],
                remove=[_folder_to_label(folder)],
            )
        except Exception as e:
            raise classify_gmail_error(e) from e

    def mark_read(self, message_id: str, *, read: bool = True, folder: str = "INBOX") -> None:
        """Mark a message read (remove UNREAD) or unread (add UNREAD)."""
        try:
            if read:
                self.client.modify_labels(message_id, remove=["UNREAD"])
            else:
                self.client.modify_labels(message_id, add=["UNREAD"])
        except Exception as e:
            raise classify_gmail_error(e) from e
```

> `_folder_to_label` and `classify_gmail_error` are already imported at the top of this adapter (lines 26-35) — no new imports needed.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/email/gmail/test_gmail.py -v`
Expected: PASS (existing tests + `TestGmailInboxActions`).

- [ ] **Step 6: Commit**

```bash
git add src/bapp_connectors/providers/email/gmail/client.py \
        src/bapp_connectors/providers/email/gmail/adapter.py \
        tests/email/gmail/test_gmail.py
git commit -m "feat(gmail): add delete(trash)/move/mark_read inbox operations"
```

---

### Task 5: Formalize `InboxCapability` abstract methods

**Files:**
- Modify: `src/bapp_connectors/core/capabilities/inbox.py` (add 3 abstract methods)
- Test: `tests/core/test_inbox_capability.py` (create)

**Interfaces:**
- Produces: `InboxCapability` now declares `delete_message`, `move_message`, `mark_read` as `@abstractmethod`. Both `SMTPEmailAdapter` and `GmailEmailAdapter` already implement them (Tasks 3 & 4), so they remain instantiable.

- [ ] **Step 1: Write the failing test** — create `tests/core/test_inbox_capability.py`

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/core/test_inbox_capability.py -v`
Expected: `test_incomplete_subclass_cannot_instantiate` FAILS (no `TypeError` raised — the methods aren't abstract yet).

- [ ] **Step 3: Add abstract methods** — `src/bapp_connectors/core/capabilities/inbox.py`

Append inside the `InboxCapability` class (after `download_attachment`):

```python
    @abstractmethod
    def delete_message(self, message_id: str, *, folder: str = "INBOX") -> None:
        """
        Delete a message from the mailbox.

        Semantics are provider-defined (IMAP: flag \\Deleted + expunge;
        Gmail: move to Trash).
        """
        ...

    @abstractmethod
    def move_message(
        self, message_id: str, target_folder: str, *, folder: str = "INBOX"
    ) -> None:
        """Move a message from ``folder`` to ``target_folder``."""
        ...

    @abstractmethod
    def mark_read(
        self, message_id: str, *, read: bool = True, folder: str = "INBOX"
    ) -> None:
        """Mark a message as read (``read=True``) or unread (``read=False``)."""
        ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --extra dev pytest tests/core/test_inbox_capability.py tests/email/ -v`
Expected: PASS — incomplete subclass now raises `TypeError`; both adapters still instantiate and all email tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/bapp_connectors/core/capabilities/inbox.py \
        tests/core/test_inbox_capability.py
git commit -m "feat(core): make delete/move/mark_read part of the InboxCapability contract"
```

---

### Task 6: `email_received` Django signal

**Files:**
- Modify: `packages/django/src/django_bapp_connectors/signals.py` (add `email_received`)
- Test: `packages/django/tests/test_signals.py`

**Interfaces:**
- Produces: `email_received = Signal()`. Emitted with kwargs `sender` (Connection model class), `connection`, `email` (`EmailDetail`), `folder`, `provider_family`, `provider_name`. Receivers may return an `InboxAction`.

- [ ] **Step 1: Write the failing test** — append to `packages/django/tests/test_signals.py`

```python
# ── email_received ──


class TestEmailReceivedSignal:
    def test_dispatch_collects_return_values(self):
        from bapp_connectors.core.dto import InboxAction
        from django_bapp_connectors.signals import email_received

        def handler(sender, **kwargs):
            assert kwargs["folder"] == "INBOX"
            assert kwargs["email"] == "EMAIL_SENTINEL"
            return InboxAction.delete()

        email_received.connect(handler)
        try:
            responses = email_received.send_robust(
                sender=Connection,
                connection=None,
                email="EMAIL_SENTINEL",
                folder="INBOX",
                provider_family="email",
                provider_name="gmail",
            )
            actions = [r for _, r in responses if isinstance(r, InboxAction)]
            assert len(actions) == 1
            assert actions[0].type.value == "delete"
        finally:
            email_received.disconnect(handler)

    def test_raising_receiver_is_isolated(self):
        from django_bapp_connectors.signals import email_received

        def broken(sender, **kwargs):
            raise RuntimeError("boom")

        email_received.connect(broken)
        try:
            responses = email_received.send_robust(
                sender=Connection, connection=None, email="x", folder="INBOX",
                provider_family="email", provider_name="gmail",
            )
            # send_robust returns the exception as the receiver's response
            assert any(isinstance(r, Exception) for _, r in responses)
        finally:
            email_received.disconnect(broken)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/django && uv run --extra dev pytest tests/test_signals.py::TestEmailReceivedSignal -v`
Expected: FAIL — `ImportError: cannot import name 'email_received'`.

- [ ] **Step 3: Add the signal** — `packages/django/src/django_bapp_connectors/signals.py`

Append at the end of the file:

```python
# ── Email signals ──

email_received = Signal()
"""
Fired once per email fetched during an inbox poll (see services.InboxPollService).

A receiver MAY return a bapp_connectors.core.dto.InboxAction (delete / move /
mark_read). The first non-None action returned by any receiver (in receiver
registration order) is applied to the message; other returned actions are
ignored. Receivers that raise are logged and skipped (send_robust).

Kwargs:
    sender: The concrete Connection model class.
    connection: The Connection model instance.
    email: bapp_connectors.core.dto.EmailDetail — the fully-hydrated message
           (body, headers, attachment manifest). Attachment bytes are fetched
           on demand via connection.get_adapter().download_attachment(...).
    folder: str — the mailbox folder polled.
    provider_family: str ("email").
    provider_name: str (e.g. "gmail", "smtp").
"""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd packages/django && uv run --extra dev pytest tests/test_signals.py::TestEmailReceivedSignal -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add packages/django/src/django_bapp_connectors/signals.py \
        packages/django/tests/test_signals.py
git commit -m "feat(django): add email_received signal"
```

---

### Task 7: `InboxPollService` + result dataclasses + exports

**Files:**
- Create: `packages/django/src/django_bapp_connectors/services/inbox.py`
- Modify: `packages/django/src/django_bapp_connectors/services/__init__.py` (export)
- Test: `packages/django/tests/test_inbox_service.py` (create)

**Interfaces:**
- Consumes: `email_received` (Task 6); `InboxAction`/`InboxActionType` (Task 2); adapter methods `fetch_messages`, `get_message`, `delete_message`, `move_message`, `mark_read` (Tasks 3-5).
- Produces:
  - `@dataclass InboxPollRecord(email, action=None, applied=False, error="")`
  - `@dataclass InboxPollResult(folder, fetched, records=[])`
  - `class InboxPollService(connection)` with `poll(*, since=None, until=None, folder="INBOX", limit=50) -> InboxPollResult`.

- [ ] **Step 1: Write the failing test** — create `packages/django/tests/test_inbox_service.py`

```python
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
        return None

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
        return None

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/django && uv run --extra dev pytest tests/test_inbox_service.py -v`
Expected: FAIL — `ModuleNotFoundError: ... services.inbox`.

- [ ] **Step 3: Create the service** — `packages/django/src/django_bapp_connectors/services/inbox.py`

```python
"""
Inbox poll service — fetch email, emit email_received per message, and apply
the first returned InboxAction (delete / move / mark_read).

This package provides the building blocks only; consuming projects decide when
to poll and own the time window (since/until) and any deduplication.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from bapp_connectors.core.dto import (
    EmailDetail,
    EmailSummary,
    InboxAction,
    InboxActionType,
)

from django_bapp_connectors.signals import email_received

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
            except Exception as e:  # noqa: BLE001 — one bad message must not abort the poll
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
        except Exception as e:  # noqa: BLE001 — surface on the record, keep polling
            logger.warning(
                "Inbox action %s failed for %s: %s", action.type, email.message_id, e
            )
            return False, str(e)
```

- [ ] **Step 4: Export from the services package** — `packages/django/src/django_bapp_connectors/services/__init__.py`

Replace the file contents with:

```python
from .connection import ConnectionService
from .inbox import InboxPollRecord, InboxPollResult, InboxPollService
from .sync import SyncService
from .webhook import WebhookService

__all__ = [
    "ConnectionService",
    "InboxPollRecord",
    "InboxPollResult",
    "InboxPollService",
    "SyncService",
    "WebhookService",
]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd packages/django && uv run --extra dev pytest tests/test_inbox_service.py -v`
Expected: PASS (7 tests).

- [ ] **Step 6: Commit**

```bash
git add packages/django/src/django_bapp_connectors/services/inbox.py \
        packages/django/src/django_bapp_connectors/services/__init__.py \
        packages/django/tests/test_inbox_service.py
git commit -m "feat(django): add InboxPollService for email_received dispatch + actions"
```

---

### Task 8: Version bump, lint, and full verification

**Files:**
- Modify: `pyproject.toml:3` (`0.25.0` → `0.26.0`)
- Modify: `packages/django/pyproject.toml:3` (`0.21.0` → `0.22.0`)

**Interfaces:** none (release bookkeeping).

- [ ] **Step 1: Bump the core version** — `pyproject.toml`

Change `version = "0.25.0"` to `version = "0.26.0"`.

- [ ] **Step 2: Bump the django version** — `packages/django/pyproject.toml`

Change `version = "0.21.0"` to `version = "0.22.0"`.

- [ ] **Step 3: Lint**

Run: `uv run --extra dev ruff check .`
Expected: no errors. Fix any reported issues before continuing.

- [ ] **Step 4: Run the full core test suite**

Run: `uv run --extra dev pytest tests/ -v`
Expected: all pass (integration tests auto-skipped via `addopts = "-m 'not integration'"`).

- [ ] **Step 5: Run the full django test suite**

Run: `cd packages/django && uv run --extra dev pytest tests/ -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml packages/django/pyproject.toml
git commit -m "chore: v0.26.0 / django v0.22.0 — inbox email_received signal + Netopia payment remap"
```

---

## Self-Review

**Spec coverage:**
- Netopia remap (confirmed→completed + full payment.* map, `PAYMENT_PENDING`) → Task 1. ✓
- `InboxAction` DTO in core → Task 2. ✓
- Three mailbox ops on IMAP/SMTP → Task 3; on Gmail (trash/labels) → Task 4. ✓
- Ops promoted to `InboxCapability` contract → Task 5. ✓
- `email_received` signal with `EmailDetail` payload (body, headers, attachment manifest), `send_robust` → Task 6. ✓
- `InboxPollService` (caller-managed window, hydrate via `get_message`, first-action-wins, raising-receiver skipped, apply errors recorded) → Task 7. ✓
- Both version bumps + ruff + full suites → Task 8. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code; every test step shows the assertions.

**Type consistency:** Adapter method names (`delete_message`/`move_message`/`mark_read`) are identical across the abstract base (Task 5), SMTP (Task 3), Gmail (Task 4), and the service's `_apply` (Task 7). `InboxAction` factories (`delete`/`move`/`mark_read`/`none`) and `InboxActionType` members are referenced consistently in Tasks 2, 6, 7. `InboxPollRecord`/`InboxPollResult` field names match between Task 7's definition, its tests, and the spec.
