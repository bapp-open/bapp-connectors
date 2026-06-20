# Design: Inbox `email_received` signal + Netopia payment remap

Date: 2026-06-20
Status: Approved

## Summary

Two related changes to the connectors framework:

1. **Netopia webhook remap** — fix the bug where a *confirmed* online payment is
   reported as `order.updated` instead of `payment.completed`, and remap the
   remaining IPN statuses to `payment.*` events.
2. **Inbox `email_received` signal + poll tooling** — provide reusable building
   blocks so consuming projects can be notified for each fetched email and
   instruct the framework to take a *termination action* (delete, move to
   another folder, or mark as read).

The framework provides **tools only**. There is no scheduler and no Celery task
in this package — consuming projects decide when to poll and how to react.

## Scope / non-goals

- No Celery task and no periodic-poll scheduling in this package. Hosts call the
  poll service themselves.
- No watermark/dedup persistence (no `SyncState` usage). The caller owns the
  time window (`since`/`until`) and is responsible for not double-processing.
- Only the two existing `InboxCapability` implementers are touched: SMTP/IMAP and
  Gmail. (Microsoft Graph is referenced in docstrings but not implemented.)

---

## Part 1 — Netopia webhook remap

### Core enum change

`src/bapp_connectors/core/dto/webhook.py` — add one value to the Payments group:

```python
PAYMENT_PENDING = "payment.pending"
```

### Mapper change

`src/bapp_connectors/providers/payment/netopia/mappers.py` — replace
`NETOPIA_IPN_EVENT_MAP`. Netopia status codes (from `NETOPIA_STATUS_MAP`):
`0=pending`, `3=paid_pending`, `5=confirmed`, `12=cancelled`, `15=credit`.

```python
NETOPIA_IPN_EVENT_MAP: dict[str, WebhookEventType] = {
    "pending":      WebhookEventType.PAYMENT_PENDING,    # 0  (was unmapped -> UNKNOWN)
    "paid_pending": WebhookEventType.PAYMENT_PENDING,    # 3  (was ORDER_UPDATED)
    "confirmed":    WebhookEventType.PAYMENT_COMPLETED,  # 5  (was ORDER_UPDATED) <- the bug
    "cancelled":    WebhookEventType.PAYMENT_FAILED,     # 12 (was ORDER_CANCELLED)
    "credit":       WebhookEventType.PAYMENT_REFUNDED,   # 15 (was ORDER_UPDATED)
}
```

`webhook_event_from_netopia()` is otherwise unchanged; `provider_event_type`
stays `f"payment.{raw_status}"`. The synchronous `get_payment_status()` path
(`payment_result_from_netopia`, which already maps `confirmed -> "completed"`)
is unchanged.

### Tests

Update the existing Netopia webhook mapper test to assert the new event types,
including a `paid_pending`/`pending` case returning `PAYMENT_PENDING` and
`credit` returning `PAYMENT_REFUNDED`.

---

## Part 2 — Mailbox operations (core, zero Django deps)

Add three abstract methods to `InboxCapability`
(`src/bapp_connectors/core/capabilities/inbox.py`):

```python
def delete_message(self, message_id: str, *, folder: str = "INBOX") -> None: ...
def move_message(self, message_id: str, target_folder: str, *, folder: str = "INBOX") -> None: ...
def mark_read(self, message_id: str, *, read: bool = True, folder: str = "INBOX") -> None: ...
```

Both implementers gain concrete implementations (adding abstract methods to the
ABC forces this — there are no other implementers):

### SMTP / IMAP (`providers/email/smtp/`)

`client.py` (`IMAPClient`, raw `imaplib`):
- `delete_uid(uid, folder)` — select folder, `UID STORE <uid> +FLAGS (\Deleted)`, `EXPUNGE`.
- `move_uid(uid, target_folder, folder)` — prefer `UID MOVE` when the server
  advertises the `MOVE` capability; otherwise `UID COPY` -> `+FLAGS (\Deleted)` -> `EXPUNGE`.
- `store_flag(uid, flag, folder, add=True)` — `UID STORE <uid> (+/-)FLAGS (<flag>)`.

`adapter.py` — implement the three capability methods by translating
`message_id` -> IMAP UID and delegating to the client (`mark_read` toggles the
`\Seen` flag).

### Gmail (`providers/email/gmail/`)

- `delete_message` -> `users().messages().trash()` (recoverable; **not** permanent
  delete — documented in the method docstring).
- `move_message` -> `users().messages().modify(addLabelIds=[target], removeLabelIds=[folder])`
  (Gmail "folders" are labels).
- `mark_read` -> `users().messages().modify(removeLabelIds=["UNREAD"])`
  (or `addLabelIds=["UNREAD"]` when `read=False`).

### Tests

Unit tests with mocked IMAP/Gmail clients asserting the right underlying calls
for each of delete/move/mark_read. Live IMAP/Gmail coverage stays behind the
existing `-m integration` gate.

---

## Part 3 — Action protocol (`InboxAction` DTO, core)

New normalized return contract in `src/bapp_connectors/core/dto/email.py`,
exported from `core/dto/__init__.py`. Receivers return this instead of a loose
string/dict, so the contract is typed, validated, and maps 1:1 to the capability
methods.

```python
class InboxActionType(StrEnum):
    NONE = "none"
    DELETE = "delete"
    MOVE = "move"
    MARK_READ = "mark_read"

class InboxAction(BaseDTO):
    type: InboxActionType = InboxActionType.NONE
    folder: str = ""      # target folder for MOVE
    read: bool = True     # for MARK_READ

    @classmethod
    def delete(cls) -> "InboxAction": ...
    @classmethod
    def move(cls, folder: str) -> "InboxAction": ...
    @classmethod
    def mark_read(cls, read: bool = True) -> "InboxAction": ...
    @classmethod
    def none(cls) -> "InboxAction": ...
```

Rationale: typed DTO over stringly-typed returns; lives in core (not Django)
because it is provider-agnostic — the Django service is only a translator.

### Tests

Unit tests for the factory methods and default values.

---

## Part 4 — Signal + poll service (django package)

### Signal

`packages/django/src/django_bapp_connectors/signals.py` — add `email_received`:

```python
email_received = Signal()
"""
Fired once per email fetched during an inbox poll.

A receiver MAY return a bapp_connectors.core.dto.InboxAction (delete / move /
mark_read). The first non-None action returned by any receiver (in receiver
registration order) is applied to the message; other returned actions are
ignored. Receivers that raise are logged and skipped (send_robust).

Kwargs:
    sender: The concrete Connection model class.
    connection: The Connection model instance.
    email: bapp_connectors.core.dto.EmailDetail — the fully-hydrated message
           (subject, sender, to/cc/bcc, text_body, html_body, headers,
           in_reply_to, references, and the attachment manifest
           `attachments: list[EmailAttachmentInfo]`). Attachment *bytes* are NOT
           embedded — a receiver downloads them on demand via
           `connection.get_adapter().download_attachment(email.message_id,
           att.attachment_id, folder=folder)`.
    folder: str — the mailbox folder polled.
    provider_family: str ("email").
    provider_name: str (e.g. "gmail", "smtp").
"""
```

**Payload note.** The signal carries the full `EmailDetail` (body + headers +
attachment manifest), not the lightweight `EmailSummary`. `fetch_messages`
returns summaries, so the poll service hydrates each one to `EmailDetail` via
`get_message` before firing the signal. This is the deliberate cost of putting
the full payload in the signal: **one extra `get_message` round-trip per polled
message**. Attachment file bytes are still lazy (downloaded only if a receiver
asks).

### Poll service

`packages/django/src/django_bapp_connectors/services/inbox.py` — new
`InboxPollService`, styled after `services/webhook.py`:

```python
class InboxPollService:
    def __init__(self, connection):
        self.connection = connection

    def poll(self, *, since=None, until=None, folder="INBOX", limit=50) -> InboxPollResult:
        adapter = self.connection.get_adapter()
        # guard: adapter must support fetch_messages + get_message (InboxCapability)
        summaries = adapter.fetch_messages(since=since, until=until, folder=folder, limit=limit)
        records = []
        for summary in summaries:
            try:
                email = adapter.get_message(summary.message_id, folder=folder)  # -> EmailDetail
            except Exception as e:                          # hydration failed: record, skip dispatch
                records.append(InboxPollRecord(email=summary, action=None, applied=False, error=str(e)))
                continue
            action = self._dispatch(email, folder)          # email_received.send_robust(...)
            applied, err = self._apply(adapter, email, folder, action)
            records.append(InboxPollRecord(email=email, action=action, applied=applied, error=err))
        return InboxPollResult(folder=folder, fetched=len(summaries), records=records)
```

- `_dispatch` calls `email_received.send_robust(...)`, iterates the
  `(receiver, response)` pairs, logs+skips any `Exception` response, and returns
  the first `InboxAction` whose `type != NONE` (or `None`).
- `_apply` translates the action to `adapter.delete_message` / `move_message` /
  `mark_read`; returns whether an action was applied. Adapter errors during apply
  are caught, logged, and recorded in the record's `error` field (they do not
  abort the remaining messages).

`InboxPollResult` / `InboxPollRecord` are lightweight dataclasses, exported from
the package so callers can inspect outcomes:
- `InboxPollRecord(email: EmailDetail | EmailSummary, action: InboxAction | None, applied: bool, error: str = "")`
  (holds the `EmailDetail` normally; the `EmailSummary` when hydration failed)
- `InboxPollResult(folder: str, fetched: int, records: list[InboxPollRecord])`

### Exports

`email_received` and `InboxPollService` (+ result dataclasses) exported from the
package's public surface (`services/__init__.py` and/or top-level `__init__.py`),
consistent with how `webhook`/signals are exposed today.

### Data flow

```
host project calls InboxPollService.poll(since=..., folder=...)
  -> adapter.fetch_messages(...)            # list[EmailSummary]
  -> for each summary:
       adapter.get_message(summary.message_id)   # hydrate -> EmailDetail (body, headers, attachments)
       email_received.send_robust(connection, email=EmailDetail, folder, ...)
       -> first returned InboxAction (or None)
       -> adapter.delete_message / move_message / mark_read
       (receiver may also adapter.download_attachment(...) for bytes)
  -> InboxPollResult(fetched, records)
```

### Tests

Django-package unit tests using a fake adapter (returns summaries from
`fetch_messages`, hydrates to `EmailDetail` from `get_message`) and a registered
test receiver:
- each summary is hydrated via `get_message` and the receiver sees an
  `EmailDetail` carrying body, `headers`, and the attachment manifest;
- delete / move / mark_read each translate to the correct adapter call;
- conflicting actions from two receivers -> first-registered wins;
- a receiver that raises is logged and skipped, poll still completes;
- a `get_message` hydration failure -> record carries the summary + error, no
  signal fired for that message, poll continues;
- no action returned -> nothing applied, record reflects it.

Note: `EmailDetail` already includes `headers: dict[str, str]` (plus
`in_reply_to` / `references`); no DTO change is needed to expose headers.

---

## Versioning & release

Per project convention, bump **both** `bapp-connectors` and
`django-bapp-connectors` versions together (currently `0.25.0` / `0.21.0`) as a
single feature release. Run `ruff check` before any push. Committing/pushing/
releasing is a separate, explicitly-requested step.

## Affected files

Core (`bapp-connectors`):
- `core/dto/webhook.py` (+`PAYMENT_PENDING`)
- `core/dto/email.py` (+`InboxAction`, `InboxActionType`)
- `core/dto/__init__.py` (exports)
- `core/capabilities/inbox.py` (+3 abstract methods)
- `providers/payment/netopia/mappers.py` (remap)
- `providers/email/smtp/{client.py,adapter.py}` (delete/move/mark_read)
- `providers/email/gmail/{client or adapter}.py` (delete/move/mark_read)
- tests for the above

Django (`django-bapp-connectors`):
- `signals.py` (+`email_received`)
- `services/inbox.py` (new `InboxPollService`, result dataclasses)
- `services/__init__.py` / `__init__.py` (exports)
- tests for dispatch + action application
