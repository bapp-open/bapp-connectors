"""
SMTP / IMAP email client — uses Python's smtplib and imaplib directly
(not ResilientHttpClient).

Handles SMTP sending and IMAP inbox reading.
"""

from __future__ import annotations

import contextlib
import email as email_lib
import imaplib
import logging
import re
import smtplib
from email import policy
from email.header import decode_header
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator
    from datetime import datetime

logger = logging.getLogger(__name__)


def _validate_header(value: str, name: str) -> str:
    """Reject controls before formatting, parsing or serializing header values."""
    if not isinstance(value, str) or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError(f"Invalid {name}: expected a string without control characters")
    return value


def resolve_message_id(value: str = "") -> str:
    """Generate an RFC Message-ID, or validate an explicitly supplied one."""
    _validate_header(value, "Message-ID")
    if not value:
        return make_msgid()
    value = value.strip()
    parsed = policy.SMTP.header_factory("Message-ID", value)
    if not value.isascii() or not value.startswith("<") or not value.endswith(">") or parsed.defects:
        raise ValueError("Invalid Message-ID: expected one bracketed RFC message identifier")
    return value


def _reference_ids(value: list[str] | str | None) -> list[str]:
    """Accept the inbox DTO's list format and a space-separated References value."""
    if value is None:
        return []
    if isinstance(value, str):
        value = _validate_header(value, "References").split()
    if not isinstance(value, list):
        raise ValueError("Invalid References: expected a list of IDs or a space-separated string")
    ids = []
    for item in value:
        if not _validate_header(item, "References").strip():
            raise ValueError("Invalid References: empty message identifier")
        ids.append(resolve_message_id(item))
    return ids


class SMTPClient:
    """
    Low-level SMTP client.

    This class only handles SMTP connection and email sending.
    """

    def __init__(
        self,
        host: str,
        port: int = 587,
        username: str = "",
        password: str = "",
        use_tls: bool = True,
        use_ssl: bool = False,
        timeout: int = 30,
        from_email: str = "",
        from_name: str = "",
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_tls = use_tls
        self.use_ssl = use_ssl
        self.timeout = timeout
        self.from_email = from_email or username
        self.from_name = from_name

    def _connect(self) -> smtplib.SMTP | smtplib.SMTP_SSL:
        """Create and authenticate an SMTP connection."""
        if self.use_ssl:
            connection = smtplib.SMTP_SSL(self.host, self.port, timeout=self.timeout)
        else:
            connection = smtplib.SMTP(self.host, self.port, timeout=self.timeout)

        if self.use_tls and not self.use_ssl:
            connection.starttls()

        if self.username and self.password:
            connection.login(self.username, self.password)

        return connection

    # ── Auth / Connection Test ──

    def test_auth(self) -> bool:
        """Test SMTP authentication by opening a connection."""
        try:
            connection = self._connect()
            connection.quit()
            return True
        except Exception:
            return False

    # ── Email ──

    def send_email(
        self,
        to: list[str],
        subject: str,
        body: str = "",
        html_body: str = "",
        from_email: str = "",
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        attachments: list[dict] | None = None,
        from_name: str = "",
        *,
        message_id: str = "",
        in_reply_to: str = "",
        references: list[str] | str | None = None,
        reply_to: str = "",
    ) -> bool:
        """
        Send a single email.

        Args:
            to: List of recipient email addresses.
            subject: Email subject.
            body: Plain text body.
            html_body: HTML body.
            from_email: Sender email (overrides default).
            from_name: Display name for the From header (overrides default);
                the header becomes `Name <email>`, or just the address when empty.
            cc: CC recipients.
            bcc: BCC recipients.
            attachments: List of dicts with keys: filename, content (bytes), content_type.
            message_id: RFC Message-ID, generated if empty (not an application correlation ID).
            in_reply_to: RFC ID of the parent message, not a reply address.
            references: Parent's References chain; in_reply_to is appended if needed.
            reply_to: Reply-To email address, separate from in_reply_to.

        Returns:
            True if SMTP accepted all recipients, without confirming delivery.
            SMTP errors (including partial recipient refusals) are raised.
        """
        sender = from_email or self.from_email
        sender_name = from_name or self.from_name
        for name, value in [("From", sender), ("From name", sender_name), ("Subject", subject), ("Reply-To", reply_to)]:
            _validate_header(value, name)
        for name, addresses in [("To", to), ("Cc", cc), ("Bcc", bcc)]:
            if addresses is not None:
                if not isinstance(addresses, list):
                    raise ValueError(f"Invalid {name}: expected a list of addresses")
                for address in addresses:
                    _validate_header(address, name)

        rfc_message_id = resolve_message_id(message_id)
        parent_id = resolve_message_id(in_reply_to) if _validate_header(in_reply_to, "In-Reply-To") else ""
        reference_ids = _reference_ids(references)
        if parent_id and (not reference_ids or reference_ids[-1] != parent_id):
            reference_ids.append(parent_id)

        msg = EmailMessage(policy=policy.SMTP)
        if body:
            msg.set_content(body, charset="utf-8", cte="base64")
            if html_body:
                msg.add_alternative(html_body, subtype="html", charset="utf-8", cte="base64")
        elif html_body:
            msg.set_content(html_body, subtype="html", charset="utf-8", cte="base64")
        elif not attachments:
            msg.set_content("", charset="utf-8", cte="base64")

        if "MIME-Version" not in msg:
            msg["MIME-Version"] = "1.0"
        msg["Subject"] = subject
        msg["From"] = formataddr((sender_name, sender))
        msg["To"] = ", ".join(to)
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = rfc_message_id
        if parent_id:
            msg["In-Reply-To"] = parent_id
        if reference_ids:
            msg["References"] = " ".join(reference_ids)
        if reply_to:
            msg["Reply-To"] = reply_to

        if cc:
            msg["Cc"] = ", ".join(cc)

        if attachments:
            for attachment in attachments:
                filename = _validate_header(attachment.get("filename", "attachment"), "attachment filename")
                content_type = _validate_header(
                    attachment.get("content_type", "application/octet-stream"), "attachment Content-Type"
                )
                parsed_type = policy.SMTP.header_factory("Content-Type", content_type)
                if parsed_type.defects:
                    raise ValueError("Invalid attachment Content-Type")
                content = attachment.get("content", b"")
                if isinstance(content, str):
                    content = content.encode("utf-8")
                msg.add_attachment(
                    content,
                    maintype=parsed_type.maintype,
                    subtype=parsed_type.subtype,
                    params=dict(parsed_type.params),
                    filename=filename,
                    cte="base64",
                )

        # Build recipient list
        all_recipients = list(to)
        if cc:
            all_recipients.extend(cc)
        if bcc:
            all_recipients.extend(bcc)

        # Serialize before connecting so invalid headers never reach the transport.
        raw = msg.as_string()
        connection = self._connect()
        try:
            refused = connection.sendmail(sender, all_recipients, raw)
            if refused:
                raise smtplib.SMTPRecipientsRefused(refused)
            return True
        finally:
            with contextlib.suppress(Exception):
                connection.quit()


def _decode_bytes(data: bytes, charset: str | None) -> str:
    """Decode bytes with the charset a message declares, whatever it declares.

    The charset is free text written by the sending software. Python reports raw
    8-bit header bytes as ``unknown-8bit``, and mailers invent names of their own;
    ``bytes.decode`` raises LookupError for those, and one such message used to
    fail the fetch of the whole folder on every run.
    """
    try:
        return data.decode(charset or "utf-8", errors="replace")
    except LookupError:
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return data.decode("latin-1")


def _decode_header_value(value: str) -> str:
    """Decode an RFC 2047 encoded header into a plain string."""
    if not value:
        return ""
    parts = decode_header(value)
    decoded: list[str] = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(_decode_bytes(part, charset))
        else:
            decoded.append(part)
    return " ".join(decoded)


def _quote_mailbox(folder: str) -> str:
    """Return an IMAP mailbox name as a quoted string.

    imaplib concatenates command arguments verbatim -- it never quotes the
    mailbox itself -- so a folder containing a space is split by the server
    into two tokens and the command is rejected:

        EXAMINE Shared Folders/office@example.ro/Junk Mail
        -> BAD Unexpected value 'Folders/office@example.ro/Junk'

    A quoted string is always a valid mailbox (RFC 3501 astring), so quote
    unconditionally rather than guessing which names need it.
    """
    escaped = folder.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _parse_email_address(raw: str) -> tuple[str, str]:
    """Return (name, address) from a raw header value like 'Name <addr>'."""
    from email.utils import parseaddr

    name, addr = parseaddr(raw)
    return _decode_header_value(name), addr


class IMAPClient:
    """
    Low-level IMAP client for reading email.

    Returns raw email.message.Message objects — mapping to DTOs
    happens in mappers.py.
    """

    def __init__(
        self,
        host: str,
        port: int = 993,
        username: str = "",
        password: str = "",
        use_ssl: bool = True,
        timeout: int = 30,
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_ssl = use_ssl
        self.timeout = timeout

    def _connect(self) -> imaplib.IMAP4 | imaplib.IMAP4_SSL:
        """Create and authenticate an IMAP connection."""
        if self.use_ssl:
            conn = imaplib.IMAP4_SSL(self.host, self.port, timeout=self.timeout)
        else:
            conn = imaplib.IMAP4(self.host, self.port, timeout=self.timeout)

        conn.login(self.username, self.password)
        return conn

    def test_auth(self) -> bool:
        """Test IMAP authentication by logging in and out."""
        try:
            conn = self._connect()
            conn.logout()
            return True
        except Exception:
            return False

    def fetch_uids(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        folder: str = "INBOX",
        limit: int = 50,
    ) -> list[str]:
        """Search for message UIDs matching the date window."""
        conn = self._connect()
        try:
            status, _ = conn.select(_quote_mailbox(folder), readonly=True)
            if status != "OK":
                msg = f"Failed to select folder: {folder}"
                raise IMAPFolderError(msg)

            criteria: list[str] = []
            if since:
                criteria.append(f"SINCE {since.strftime('%d-%b-%Y')}")
            if until:
                criteria.append(f"BEFORE {until.strftime('%d-%b-%Y')}")
            search_str = " ".join(criteria) if criteria else "ALL"

            status, data = conn.uid("search", None, search_str)
            if status != "OK":
                return []

            uids = data[0].split() if data[0] else []
            # Return newest first, capped at limit
            uids = list(reversed(uids))[:limit]
            return [uid.decode() for uid in uids]
        finally:
            with contextlib.suppress(Exception):
                conn.logout()

    def fetch_headers(
        self,
        uids: list[str],
        *,
        folder: str = "INBOX",
    ) -> list[tuple[str, email_lib.message.Message, set[str], bool]]:
        """
        Fetch headers + flags for a list of UIDs.

        Returns list of (uid, email.message.Message, flags_set, has_attachments).
        Malformed/incomplete responses are logged and skipped; each valid UID
        is returned at most once.
        """
        if not uids:
            return []

        conn = self._connect()
        try:
            conn.select(_quote_mailbox(folder), readonly=True)
            uid_str = ",".join(uids)
            status, data = conn.uid("fetch", uid_str, "(FLAGS BODY[HEADER] BODYSTRUCTURE)")
            if status != "OK" or not data:
                return []

            results: list[tuple[str, email_lib.message.Message, set[str], bool]] = []
            seen_uids: set[str] = set()
            for attributes in _iter_fetch_attributes(data):
                uid = attributes.get("UID")
                raw_headers = attributes.get("BODY[HEADER]")
                flags = attributes.get("FLAGS", [])
                if (
                    not isinstance(uid, str)
                    or not re.fullmatch(r"[1-9][0-9]{0,9}", uid)
                    or int(uid) > 2**32 - 1
                    or not isinstance(raw_headers, bytes)
                    or not isinstance(flags, list)
                    or not all(isinstance(flag, str) for flag in flags)
                ):
                    logger.warning("Skipping IMAP FETCH response without valid UID, headers or flags")
                    continue
                if uid in seen_uids:
                    continue
                seen_uids.add(uid)
                msg = email_lib.message_from_bytes(raw_headers)
                has_attachments = _has_attachments_in_bodystructure(attributes.get("BODYSTRUCTURE", []))
                results.append((uid, msg, set(flags), has_attachments))

            return results
        finally:
            with contextlib.suppress(Exception):
                conn.logout()

    def fetch_message(
        self,
        uid: str,
        *,
        folder: str = "INBOX",
    ) -> email_lib.message.Message:
        """Fetch the full RFC822 message for a single UID."""
        conn = self._connect()
        try:
            conn.select(_quote_mailbox(folder), readonly=True)
            status, data = conn.uid("fetch", uid, "(FLAGS RFC822)")
            if status != "OK" or not data or data[0] is None:
                msg = f"Message {uid} not found in {folder}"
                raise IMAPMessageNotFoundError(msg)

            raw = data[0][1] if isinstance(data[0], tuple) else data[0]
            return email_lib.message_from_bytes(raw)
        finally:
            with contextlib.suppress(Exception):
                conn.logout()

    def _expunge_uid(self, conn, uid: str) -> None:
        """Expunge a single message by UID.

        Uses UID EXPUNGE (RFC 3502) when the server advertises UIDPLUS so only
        the target message is removed; otherwise falls back to a folder-wide
        EXPUNGE, which removes every message currently flagged \\Deleted.
        """
        capabilities = getattr(conn, "capabilities", ())
        if "UIDPLUS" in capabilities:
            conn.uid("expunge", uid)
        else:
            conn.expunge()

    def set_seen(self, uid: str, *, seen: bool = True, folder: str = "INBOX") -> None:
        """Add or remove the \\Seen flag on a message."""
        conn = self._connect()
        try:
            conn.select(_quote_mailbox(folder), readonly=False)
            op = "+FLAGS" if seen else "-FLAGS"
            conn.uid("store", uid, op, "(\\Seen)")
        finally:
            with contextlib.suppress(Exception):
                conn.logout()

    def delete_uid(self, uid: str, *, folder: str = "INBOX") -> None:
        """Delete a message: flag \\Deleted then expunge."""
        conn = self._connect()
        try:
            conn.select(_quote_mailbox(folder), readonly=False)
            conn.uid("store", uid, "+FLAGS", "(\\Deleted)")
            self._expunge_uid(conn, uid)
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
            conn.select(_quote_mailbox(folder), readonly=False)
            capabilities = getattr(conn, "capabilities", ())
            if "MOVE" in capabilities:
                conn.uid("move", uid, _quote_mailbox(target_folder))
            else:
                conn.uid("copy", uid, _quote_mailbox(target_folder))
                conn.uid("store", uid, "+FLAGS", "(\\Deleted)")
                self._expunge_uid(conn, uid)
        finally:
            with contextlib.suppress(Exception):
                conn.logout()


class IMAPFolderError(Exception):
    """Raised when an IMAP folder cannot be selected."""


class IMAPMessageNotFoundError(Exception):
    """Raised when a message UID is not found."""


_IMAPValue = str | bytes | list["_IMAPValue"]
_FETCH_START = re.compile(rb"[1-9][0-9]* \(")
_FETCH_TOKEN = re.compile(rb'\s+|[()]|"(?:[^"\\\r\n]|\\[^\r\n])*"|[^\s()"]+')


def _iter_fetch_attributes(data: list) -> Iterator[dict[str, _IMAPValue]]:
    """Group imaplib fragments by FETCH sequence number, not by literal.

    imaplib emits (metadata, literal) for *every* literal, followed by a bytes
    trailer. Only the first fragment starts with ``sequence-number (``. UID and
    FLAGS can occur in any fragment; literal contents must never become syntax.
    A new response also provides a recovery boundary after a truncated one.
    """
    parts: list = []
    for item in data:
        metadata = item[0] if isinstance(item, tuple) and item else item
        if isinstance(metadata, bytes) and _FETCH_START.match(metadata):
            if parts:
                attributes = _parse_fetch_attributes(parts)
                if attributes is not None:
                    yield attributes
            parts = []
        elif not parts:
            continue  # An orphan continuation is not a message.
        parts.append(item)
        if isinstance(item, bytes):
            # imaplib appends the final non-literal trailer as a bytes item.
            attributes = _parse_fetch_attributes(parts)
            if attributes is not None:
                yield attributes
            parts = []
    if parts:
        attributes = _parse_fetch_attributes(parts)
        if attributes is not None:
            yield attributes


def _parse_fetch_attributes(parts: list) -> dict[str, _IMAPValue] | None:
    """Parse one complete FETCH into top-level attributes.

    Lists preserve nesting; atoms are str, quoted strings and literals are bytes.
    This keeps a UID-like string in BODYSTRUCTURE from becoming a message UID,
    and associates BODY[HEADER] with its own literal even when it is not first.
    """
    root: list[_IMAPValue] = []
    stack = [root]
    for part in parts:
        literal = None
        if isinstance(part, tuple):
            if len(part) != 2 or not all(isinstance(value, bytes) for value in part):
                break
            metadata, literal = part
            marker = re.search(rb"\{([0-9]+)\}$", metadata)
            if marker is None or (marker[1].lstrip(b"0") or b"0") != str(len(literal)).encode():
                break
            metadata = metadata[: marker.start()]
        elif isinstance(part, bytes):
            metadata = part
        else:
            break

        offset = 0
        while offset < len(metadata):
            match = _FETCH_TOKEN.match(metadata, offset)
            if match is None:
                break
            token = match[0]
            offset = match.end()
            if token.isspace():
                continue
            if token == b"(":
                nested: list[_IMAPValue] = []
                stack[-1].append(nested)
                stack.append(nested)
            elif token == b")":
                if len(stack) == 1:
                    break
                stack.pop()
            elif token.startswith(b'"'):
                stack[-1].append(re.sub(rb"\\(.)", rb"\1", token[1:-1]))
            else:
                stack[-1].append(token.decode("ascii", errors="replace"))
        else:
            if literal is not None:
                if len(stack) < 2:
                    break
                stack[-1].append(literal)
            continue
        break
    else:
        if len(stack) == 1 and len(root) == 2 and isinstance(root[1], list):
            values = root[1]
            attributes: dict[str, _IMAPValue] = {}
            if len(values) % 2 == 0:
                for index in range(0, len(values), 2):
                    key = values[index]
                    if not isinstance(key, str) or key.upper() in attributes:
                        break
                    attributes[key.upper()] = values[index + 1]
                else:
                    return attributes
    # Do not include headers, literal contents or other server data in logs.
    logger.warning("Skipping malformed or incomplete IMAP FETCH response")
    return None


def _has_attachments_in_bodystructure(bodystructure: _IMAPValue) -> bool:
    """Keep attachment detection case-insensitive, including literal strings."""
    pending = [bodystructure]
    while pending:
        value = pending.pop()
        if isinstance(value, list):
            pending.extend(value)
        elif isinstance(value, bytes) and value.lower() == b"attachment":
            return True
    return False
