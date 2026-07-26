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
import smtplib
from email.header import decode_header
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate
from typing import TYPE_CHECKING

if TYPE_CHECKING:
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
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_tls = use_tls
        self.use_ssl = use_ssl
        self.timeout = timeout
        self.from_email = from_email or username

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
    ) -> bool:
        """
        Send a single email.

        Args:
            to: List of recipient email addresses.
            subject: Email subject.
            body: Plain text body.
            html_body: HTML body.
            from_email: Sender email (overrides default).
            cc: CC recipients.
            bcc: BCC recipients.
            attachments: List of dicts with keys: filename, content (bytes), content_type.

        Returns:
            True if email was sent successfully.
        """
        sender = from_email or self.from_email

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = formataddr(("", sender))
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


def _decode_header_value(value: str) -> str:
    """Decode an RFC 2047 encoded header into a plain string."""
    if not value:
        return ""
    parts = decode_header(value)
    decoded: list[str] = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
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
                criteria.append(f'SINCE {since.strftime("%d-%b-%Y")}')
            if until:
                criteria.append(f'BEFORE {until.strftime("%d-%b-%Y")}')
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
        """
        if not uids:
            return []

        conn = self._connect()
        try:
            conn.select(_quote_mailbox(folder), readonly=True)
            uid_str = ",".join(uids)
            status, data = conn.uid(
                "fetch", uid_str, "(FLAGS BODY[HEADER] BODYSTRUCTURE)"
            )
            if status != "OK":
                return []

            results: list[tuple[str, email_lib.message.Message, set[str], bool]] = []
            i = 0
            while i < len(data):
                item = data[i]
                if isinstance(item, tuple) and len(item) == 2:
                    meta_line = item[0].decode(errors="replace")
                    raw_headers = item[1]

                    # BODYSTRUCTURE may be in the next data item (bytes)
                    bodystructure_raw = meta_line
                    if i + 1 < len(data) and isinstance(data[i + 1], bytes):
                        bodystructure_raw += data[i + 1].decode(errors="replace")
                        i += 1  # skip the BODYSTRUCTURE item

                    # Extract UID from meta
                    uid = _extract_uid(meta_line)
                    # Extract flags
                    flags = _extract_flags(meta_line)
                    # Detect attachments from BODYSTRUCTURE
                    has_attachments = _has_attachments_in_bodystructure(
                        bodystructure_raw
                    )

                    msg = email_lib.message_from_bytes(raw_headers)
                    results.append((uid, msg, flags, has_attachments))
                i += 1

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


def _extract_uid(meta_line: str) -> str:
    """Extract UID value from an IMAP FETCH response line."""
    import re

    match = re.search(r"UID (\d+)", meta_line)
    return match.group(1) if match else ""


def _extract_flags(meta_line: str) -> set[str]:
    """Extract FLAGS from an IMAP FETCH response line."""
    import re

    match = re.search(r"FLAGS \(([^)]*)\)", meta_line)
    if match:
        return set(match.group(1).split())
    return set()


def _has_attachments_in_bodystructure(raw_response: str) -> bool:
    """Detect attachments from the raw IMAP BODYSTRUCTURE response.

    BODYSTRUCTURE includes disposition info like ("attachment" ...) for
    parts that are attachments. We check case-insensitively.
    """
    return '"attachment"' in raw_response.lower()
