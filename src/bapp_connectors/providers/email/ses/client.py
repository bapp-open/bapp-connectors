"""
Amazon SES v2 email client — uses boto3 for all SES operations.

Does NOT use ResilientHttpClient — boto3 handles auth (SigV4), retries, and
connection pooling internally.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:
    boto3 = None  # type: ignore[assignment]
    ClientError = Exception  # type: ignore[assignment, misc]


def _require_boto3():
    if boto3 is None:
        raise ImportError(
            "boto3 is required for Amazon SES. "
            "Install it with: pip install boto3"
        )


class SESClient:
    """
    Low-level Amazon SES v2 client using boto3.

    Handles: send_simple_email, send_raw_email, test_auth.
    """

    def __init__(
        self,
        access_key_id: str,
        secret_access_key: str,
        region: str = "us-east-1",
        configuration_set: str = "",
    ):
        _require_boto3()
        self.configuration_set = configuration_set

        session = boto3.session.Session(
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region,
        )

        self.ses = session.client("sesv2")

    # ── Auth / Connection Test ──

    def test_auth(self) -> bool:
        """Verify credentials by calling GetAccount."""
        try:
            self.ses.get_account()
            return True
        except Exception:
            return False

    # ── Simple Email ──

    def send_simple_email(
        self,
        from_email: str,
        to: list[str],
        subject: str,
        body_text: str = "",
        body_html: str = "",
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        reply_to: list[str] | None = None,
        configuration_set: str | None = None,
    ) -> dict[str, Any]:
        """
        Send a simple email via SES v2 SendEmail with Content.Simple.

        Returns the raw SES response dict.
        """
        body: dict[str, Any] = {}
        if body_text:
            body["Text"] = {"Data": body_text}
        if body_html:
            body["Html"] = {"Data": body_html}
        if not body:
            body["Text"] = {"Data": ""}

        destination: dict[str, Any] = {"ToAddresses": to}
        if cc:
            destination["CcAddresses"] = cc
        if bcc:
            destination["BccAddresses"] = bcc

        kwargs: dict[str, Any] = {
            "FromEmailAddress": from_email,
            "Destination": destination,
            "Content": {
                "Simple": {
                    "Subject": {"Data": subject},
                    "Body": body,
                },
            },
        }

        if reply_to:
            kwargs["ReplyToAddresses"] = reply_to

        config_set = configuration_set or self.configuration_set
        if config_set:
            kwargs["ConfigurationSetName"] = config_set

        return self.ses.send_email(**kwargs)

    # ── Raw Email ──

    def send_raw_email(
        self,
        from_email: str,
        raw_message: bytes,
        configuration_set: str | None = None,
    ) -> dict[str, Any]:
        """
        Send a raw MIME email via SES v2 SendEmail with Content.Raw.

        Returns the raw SES response dict.
        """
        kwargs: dict[str, Any] = {
            "FromEmailAddress": from_email,
            "Content": {
                "Raw": {
                    "Data": raw_message,
                },
            },
        }

        config_set = configuration_set or self.configuration_set
        if config_set:
            kwargs["ConfigurationSetName"] = config_set

        return self.ses.send_email(**kwargs)
