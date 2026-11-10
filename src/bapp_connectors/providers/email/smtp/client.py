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
from email.header import decode_header
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator
    from datetime import datetime

logger = logging.getLogger(__name__)


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

        Returns:
            True if email was sent successfully.
        """
        sender = from_email or self.from_email

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = formataddr((from_name or self.from_name, sender))
        msg["To"] = ", ".join(to)
        msg["Date"] = formatdate(localtime=True)

        if cc:
            msg["Cc"] = ", ".join(cc)

        # Add body parts
        if body:
            msg.attach(MIMEText(body, "plain", "utf-8"))
        if html_body:
            msg.attach(MIMEText(html_body, "html", "utf-8"))
        elif not body:
            # At least one body part is needed
            msg.attach(MIMEText("", "plain", "utf-8"))

        # Add attachments
        if attachments:
            for attachment in attachments:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(attachment.get("content", b""))
                from email.encoders import encode_base64

                encode_base64(part)
                part.add_header(
                    "Content-Disposition",
                    "attachment",
                    filename=attachment.get("filename", "attachment"),
                )
                msg.attach(part)

        # Build recipient list
        all_recipients = list(to)
        if cc:
            all_recipients.extend(cc)
        if bcc:
            all_recipients.extend(bcc)

        connection = self._connect()
        try:
            connection.sendmail(sender, all_recipients, msg.as_string())
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
