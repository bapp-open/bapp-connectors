"""
SMTP email provider manifest — declares capabilities, auth, and configuration.
"""

from bapp_connectors.core.capabilities import InboxCapability
from bapp_connectors.core.manifest import (
    AuthConfig,
    CredentialField,
    ProviderManifest,
    RateLimitConfig,
    RetryConfig,
)
from bapp_connectors.core.ports import EmailPort
from bapp_connectors.core.types import AuthStrategy, BackoffStrategy, ProviderFamily

SERVER = "SMTP server"
SENDER = "Sender"
IMAP = "IMAP (inbox)"

manifest = ProviderManifest(
    name="smtp",
    family=ProviderFamily.EMAIL,
    display_name="SMTP Email",
    description="SMTP email integration for sending and receiving email messages.",
    base_url="smtp://localhost",
    auth=AuthConfig(
        strategy=AuthStrategy.CUSTOM,
        required_fields=[
            # ── SMTP server ──
            CredentialField(name="host", label="SMTP Host", sensitive=False, group=SERVER, colspan=16),
            CredentialField(name="port", label="SMTP Port", sensitive=False, default="587", group=SERVER, colspan=8),
            CredentialField(name="username", label="Username", sensitive=False, group=SERVER, colspan=12),
            CredentialField(name="password", label="Password", sensitive=True, group=SERVER, colspan=12),
            CredentialField(
                name="use_tls",
                label="Use TLS",
                sensitive=False,
                required=False,
                default="true",
                choices=["true", "false"],
                group=SERVER,
                colspan=8,
            ),
            CredentialField(
                name="use_ssl",
                label="Use SSL",
                sensitive=False,
                required=False,
                default="false",
                choices=["true", "false"],
                group=SERVER,
                colspan=8,
            ),
            CredentialField(
                name="timeout",
                label="Timeout (seconds)",
                sensitive=False,
                required=False,
                default="30",
                group=SERVER,
                colspan=8,
            ),
            # ── Sender ──
            CredentialField(
                name="from_email",
                label="From Email",
                sensitive=False,
                required=False,
                help_text="Defaults to username if not set.",
                group=SENDER,
                colspan=12,
            ),
            CredentialField(
                name="from_name",
                label="From Name",
                sensitive=False,
                required=False,
                help_text="Shown to recipients as `From Name <from email>`; empty = just the address.",
                group=SENDER,
                colspan=12,
            ),
            # ── IMAP (inbox) ──
            CredentialField(
                name="imap_enabled",
                label="IMAP (inbox)",
                sensitive=False,
                required=False,
                default="true",
                choices=["true", "false"],
                help_text="Turn off for send-only relays without IMAP (e.g. Amazon SES): "
                "the connection test then checks SMTP only.",
                group=IMAP,
            ),
            CredentialField(
                name="imap_host",
                label="IMAP Host",
                sensitive=False,
                required=False,
                help_text="Required for inbox capabilities. Defaults to SMTP host if not set.",
                group=IMAP,
                colspan=12,
            ),
            CredentialField(
                name="imap_port",
                label="IMAP Port",
                sensitive=False,
                required=False,
                default="993",
                group=IMAP,
                colspan=6,
            ),
            CredentialField(
                name="imap_use_ssl",
                label="IMAP Use SSL",
                sensitive=False,
                required=False,
                default="true",
                choices=["true", "false"],
                group=IMAP,
                colspan=6,
            ),
        ],
    ),
    capabilities=[EmailPort, InboxCapability],
    rate_limit=RateLimitConfig(
        requests_per_second=10,
        burst=20,
    ),
    retry=RetryConfig(
        max_retries=2,
        backoff=BackoffStrategy.EXPONENTIAL,
        retryable_status_codes=[],
        non_retryable_status_codes=[],
    ),
)
