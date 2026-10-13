"""IMAP se poate opri din credentiale: `imap_enabled=false`.

Fara `imap_host`, adaptorul cade pe hostul SMTP si pentru IMAP. La un relay care
nu are IMAP (Amazon SES: `email-smtp.eu-central-1.amazonaws.com`) conectarea pe
993 expira dupa ~90 s, iar „Test Connection" din interfata e taiat de ingress la
60 s si arata o eroare generica, desi SMTP-ul e in regula. Cu bifa oprita nu se
creeaza clientul IMAP deloc: nici la test, nici pentru inbox.
"""

from __future__ import annotations

from unittest.mock import patch

from bapp_connectors.providers.email.smtp.adapter import SMTPEmailAdapter
from bapp_connectors.providers.email.smtp.manifest import manifest as smtp_manifest

BASE = {
    "host": "email-smtp.eu-central-1.amazonaws.com",
    "port": "587",
    "username": "AKIA-user",
    "password": "secret",
}


def test_imap_disabled_creates_no_imap_client():
    adapter = SMTPEmailAdapter({**BASE, "imap_enabled": "false"})
    assert adapter.imap_client is None


def test_imap_disabled_tests_only_smtp():
    adapter = SMTPEmailAdapter({**BASE, "imap_enabled": "false"})
    with (
        patch.object(adapter.client, "test_auth", return_value=True),
        patch("bapp_connectors.providers.email.smtp.adapter.IMAPClient.test_auth") as imap_auth,
    ):
        result = adapter.test_connection()
    assert result.success
    assert result.message == "SMTP: OK"
    imap_auth.assert_not_called()


def test_imap_enabled_by_default_keeps_the_smtp_host_fallback():
    """Conexiunile existente n-au cheia: raman cu inbox-ul pe hostul SMTP, ca pana acum."""
    adapter = SMTPEmailAdapter(dict(BASE))
    assert adapter.imap_client is not None
    assert adapter.imap_client.host == BASE["host"]


def test_imap_disabled_wins_over_an_explicit_imap_host():
    adapter = SMTPEmailAdapter({**BASE, "imap_enabled": "false", "imap_host": "imap.example.com"})
    assert adapter.imap_client is None


def test_manifest_exposes_the_switch_before_the_imap_fields():
    names = [f.name for f in smtp_manifest.auth.required_fields]
    assert "imap_enabled" in names
    assert names.index("imap_enabled") < names.index("imap_host")
    field = next(f for f in smtp_manifest.auth.required_fields if f.name == "imap_enabled")
    assert field.required is False
    assert field.default == "true"
    assert field.choices == ["true", "false"]
