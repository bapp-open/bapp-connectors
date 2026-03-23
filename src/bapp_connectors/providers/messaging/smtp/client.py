"""
SMTP email client — uses Python's smtplib directly (not ResilientHttpClient).

Handles connection management and email sending.
"""

from __future__ import annotations

import contextlib
import logging
import smtplib
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate

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
