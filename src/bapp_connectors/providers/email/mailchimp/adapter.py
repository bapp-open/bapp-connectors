"""
Mailchimp Transactional (Mandrill) email adapter — implements EmailPort.

Uses the Mandrill API for transactional email sending, with support
for both raw messages and Mandrill templates.

Auth: API key injected into every JSON request body (not headers).
"""

from __future__ import annotations

from bapp_connectors.core.dto import (
    ConnectionTestResult,
    DeliveryReport,
    DeliveryStatus,
    OutboundMessage,
)
from bapp_connectors.core.http import NoAuth, ResilientHttpClient
from bapp_connectors.core.ports import EmailPort
from bapp_connectors.providers.email.mailchimp.client import MandrillApiClient
from bapp_connectors.providers.email.mailchimp.manifest import manifest
from bapp_connectors.providers.email.mailchimp.mappers import (
    mandrill_result_to_report,
    outbound_to_mandrill,
)


class MailchimpEmailAdapter(EmailPort):
    """
    Mailchimp Transactional (Mandrill) email adapter.

    Implements:
    - EmailPort: send, send_bulk

    Supports via OutboundMessage:
    - Plain text and HTML email (``body`` / ``html_body``)
    - CC/BCC recipients (``extra["cc"]``, ``extra["bcc"]``)
    - Attachments (``attachments`` list with ``filename``, ``content``, ``content_type``)
    - Mandrill templates (set ``template_id`` and optionally ``template_vars``)
    - Reply-To header (``extra["reply_to"]``)
    - Tags / metadata (``extra["tags"]``, ``extra["metadata"]``)
    """

    manifest = manifest

    def __init__(
        self,
        credentials: dict,
        http_client: ResilientHttpClient | None = None,
        config: dict | None = None,
        **kwargs,
    ):
        self.credentials = credentials
        self._config = config or {}

        api_key = credentials.get("api_key", "")
        self._default_from_email = credentials.get("from_email", "")
        self._default_from_name = credentials.get("from_name", "")

        if http_client is None:
            http_client = ResilientHttpClient(
                base_url=manifest.base_url,
                auth=NoAuth(),
                provider_name="mailchimp",
            )

        self.client = MandrillApiClient(http_client=http_client, api_key=api_key)

    # ── BasePort ──

    def validate_credentials(self) -> bool:
        missing = self.manifest.auth.validate_credentials(self.credentials)
        return len(missing) == 0

    def test_connection(self) -> ConnectionTestResult:
        try:
            success = self.client.test_auth()
            if success:
                return ConnectionTestResult(
                    success=True,
                    message="Mandrill API: OK",
                )
            return ConnectionTestResult(
                success=False,
                message="Mandrill authentication failed",
            )
        except Exception as e:
            return ConnectionTestResult(success=False, message=str(e))

    # ── EmailPort ──

    def send(self, message: OutboundMessage) -> DeliveryReport:
        """Send a single email via Mandrill.

        If ``message.template_id`` is set, sends using a Mandrill template.
        Otherwise sends a raw message.
        """
        try:
            mandrill_msg = outbound_to_mandrill(
                message,
                default_from_email=self._default_from_email,
                default_from_name=self._default_from_name,
            )

            if message.template_id:
                # Build template_content from template_vars (editable regions)
                template_content = [{"name": k, "content": v} for k, v in (message.template_vars or {}).items()]
                result = self.client.send_template(
                    template_name=message.template_id,
                    template_content=template_content,
                    message=mandrill_msg,
                )
            else:
                result = self.client.send_message(mandrill_msg)

            return mandrill_result_to_report(result, message.message_id)

        except Exception as e:
            return DeliveryReport(
                message_id=message.message_id,
                status=DeliveryStatus.FAILED,
                error=str(e),
            )

    def send_bulk(self, messages: list[OutboundMessage]) -> list[DeliveryReport]:
        """Send multiple emails sequentially.

        Mandrill supports batch sending via ``messages/send.json`` with
        multiple ``to`` entries, but to keep per-message error handling
        consistent with other providers we send one at a time.
        """
        return [self.send(message) for message in messages]
