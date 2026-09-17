"""The cPanel manifest declares four interfaces and the credentials UAPI needs."""

from bapp_connectors.core.capabilities import MailboxCapability, PanelLinkCapability
from bapp_connectors.core.ports import DnsPort, HostingPort
from bapp_connectors.core.types import AuthStrategy, ProviderFamily
from bapp_connectors.providers.hosting.cpanel.manifest import manifest


def test_identity():
    assert manifest.name == "cpanel"
    assert manifest.family is ProviderFamily.HOSTING
    assert manifest.display_name == "cPanel"
    assert manifest.allow_multiple is True
    assert manifest.validate() == []


def test_declares_both_ports_and_both_capabilities():
    assert set(manifest.capabilities) == {HostingPort, DnsPort, MailboxCapability, PanelLinkCapability}


def test_auth_is_custom_because_uapi_needs_a_prefixed_pair():
    # The framework's TOKEN strategy emits `Authorization: <token>`; UAPI wants
    # `Authorization: cpanel user:token`, so the adapter builds auth itself.
    assert manifest.auth.strategy is AuthStrategy.CUSTOM
    fields = {f.name: f for f in manifest.auth.required_fields}
    assert set(fields) == {"hostname", "username", "token"}
    assert fields["token"].sensitive is True
    assert fields["hostname"].role == "endpoint"
    assert fields["username"].sensitive is False


def test_settings_defaults():
    defaults = {f.name: f.default for f in manifest.settings.fields}
    assert defaults == {"port": 2083, "webmail_port": 2096, "verify_ssl": True, "timeout": 30}


def test_no_webhooks():
    assert manifest.webhooks.supported is False
