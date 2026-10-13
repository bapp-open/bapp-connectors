"""Expeditorul cu nume: `from_name` in credentiale, antetul From ca `Nume <email>`.

Pana acum From era doar adresa, iar utilizatorul nu avea unde sa puna numele
firmei si nici nu stia cum se compune antetul. Manifestul grupeaza campurile
(server SMTP, expeditor, IMAP) prin `CredentialField.group`, un singur atribut
optional pe care interfata il poate transforma in separatoare.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from bapp_connectors.core.dto import OutboundMessage
from bapp_connectors.core.manifest import CredentialField
from bapp_connectors.providers.email.smtp.adapter import SMTPEmailAdapter
from bapp_connectors.providers.email.smtp.client import SMTPClient
from bapp_connectors.providers.email.smtp.manifest import manifest as smtp_manifest

CREDS = {"host": "smtp.example.com", "port": "587", "username": "office@example.com", "password": "x"}


def _sent_message(client: SMTPClient) -> tuple[str, str]:
    conn = MagicMock()
    with patch.object(client, "_connect", return_value=conn):
        client.send_email(to=["dest@example.com"], subject="Salut", body="text")
    sender, _recipients, raw = conn.sendmail.call_args.args
    return sender, raw


def test_from_header_is_name_and_email():
    client = SMTPClient(
        host="h", port=587, username="u", password="p", from_email="office@example.com", from_name="AZ Store"
    )
    sender, raw = _sent_message(client)
    assert sender == "office@example.com"
    assert "From: AZ Store <office@example.com>" in raw


def test_from_header_without_a_name_stays_the_bare_address():
    client = SMTPClient(host="h", port=587, username="u", password="p", from_email="office@example.com")
    _sender, raw = _sent_message(client)
    assert "From: office@example.com" in raw


def test_adapter_reads_from_name_from_credentials():
    adapter = SMTPEmailAdapter({**CREDS, "from_email": "office@example.com", "from_name": "AZ Store"})
    assert adapter.client.from_name == "AZ Store"


def test_adapter_send_lets_the_message_override_the_name():
    adapter = SMTPEmailAdapter({**CREDS, "from_name": "AZ Store"})
    with patch.object(adapter.client, "send_email", return_value=True) as send:
        adapter.send(
            OutboundMessage(
                channel="email", to="dest@example.com", subject="s", body="b", extra={"from_name": "Suport"}
            )
        )
    assert send.call_args.kwargs["from_name"] == "Suport"


def test_manifest_has_from_name_next_to_from_email():
    names = [f.name for f in smtp_manifest.auth.required_fields]
    assert names.index("from_name") == names.index("from_email") + 1
    field = next(f for f in smtp_manifest.auth.required_fields if f.name == "from_name")
    assert field.required is False
    assert "<" in field.help_text  # arata forma `Nume <email>`


def test_credential_field_group_is_optional():
    assert CredentialField(name="x").group == ""


def test_manifest_groups_server_sender_and_imap():
    groups = {f.name: f.group for f in smtp_manifest.auth.required_fields}
    assert groups["host"] == groups["password"] == groups["timeout"] == "SMTP server"
    assert groups["from_email"] == groups["from_name"] == "Sender"
    assert groups["imap_enabled"] == groups["imap_host"] == groups["imap_use_ssl"] == "IMAP (inbox)"
