"""cPanel adapter — HostingPort, mailboxes and panel links. DNS lives in the same class."""

from __future__ import annotations

import json
from collections.abc import Sequence
from urllib.parse import quote

from bapp_connectors.core.capabilities import MailboxCapability, PanelLinkCapability
from bapp_connectors.core.dto import (
    ConnectionTestResult,
    DnsRecord,
    DnsZone,
    DnsZoneSnapshot,
    HostingAccount,
    HostingDomain,
    HostingResource,
    Mailbox,
    PanelLink,
)
from bapp_connectors.core.errors import ConnectorError, ValidationError
from bapp_connectors.core.http import ResilientHttpClient
from bapp_connectors.core.http.auth import TokenAuth
from bapp_connectors.core.http.rate_limit import RateLimiter
from bapp_connectors.core.http.retry import RetryPolicy
from bapp_connectors.core.ports import DnsPort, HostingPort
from bapp_connectors.providers.hosting.cpanel.client import CpanelUapiClient
from bapp_connectors.providers.hosting.cpanel.manifest import manifest
from bapp_connectors.providers.hosting.cpanel.mappers import (
    map_account,
    map_domains,
    map_mailboxes,
    map_usages,
    map_zone,
    record_to_payload,
)


class CpanelAdapter(HostingPort, DnsPort, MailboxCapability, PanelLinkCapability):
    """A single cPanel account, reached over UAPI with an account API token."""

    manifest = manifest

    # Exactly what `DNS/mass_edit_zone` accepts. SOA and NS are readable but not writable.
    supported_record_types = ("A", "AAAA", "ALIAS", "CAA", "CNAME", "HTTPS", "MX", "SRV", "SVCB", "TXT")

    def __init__(
        self,
        credentials: dict,
        http_client: ResilientHttpClient | None = None,
        config: dict | None = None,
        **kwargs,
    ):
        self.credentials = credentials or {}
        config = config or {}

        self.hostname = str(self.credentials.get("hostname", "")).strip().rstrip("/")
        self.username = str(self.credentials.get("username", ""))
        self.token = str(self.credentials.get("token", ""))
        self.port = int(config.get("port", 2083))
        self.webmail_port = int(config.get("webmail_port", 2096))
        self.verify_ssl = bool(config.get("verify_ssl", True))
        self.timeout = int(config.get("timeout", 30))

        # The manifest carries a placeholder base_url; the real server comes from
        # per-connection credentials. Rebuild the client, carrying the manifest's
        # retry policy and rate limiter over rather than dropping them.
        if http_client is None and self.hostname:
            http_client = ResilientHttpClient(
                base_url=f"https://{self.hostname}:{self.port}/",
                auth=TokenAuth(token=f"{self.username}:{self.token}", prefix="cpanel"),
                retry_policy=RetryPolicy(
                    max_retries=manifest.retry.max_retries,
                    backoff=manifest.retry.backoff,
                    base_delay=manifest.retry.base_delay,
                    max_delay=manifest.retry.max_delay,
                    retryable_status_codes=set(manifest.retry.retryable_status_codes),
                    non_retryable_status_codes=set(manifest.retry.non_retryable_status_codes),
                ),
                rate_limiter=RateLimiter(
                    requests_per_second=manifest.rate_limit.requests_per_second,
                    burst=manifest.rate_limit.burst,
                ),
                timeout=self.timeout,
                provider_name="cpanel",
            )

        self.client = CpanelUapiClient(http_client=http_client, timeout=self.timeout, verify_ssl=self.verify_ssl)

    # -- BasePort ------------------------------------------------------------------

    def validate_credentials(self) -> bool:
        return not manifest.auth.validate_credentials(self.credentials)

    def test_connection(self) -> ConnectionTestResult:
        try:
            data = self.client.call("DomainInfo", "list_domains")
        except ConnectorError as exc:
            return ConnectionTestResult(success=False, message=str(exc))
        return ConnectionTestResult(
            success=True,
            message="Connected.",
            details={"main_domain": (data or {}).get("main_domain", "")},
        )

    # -- HostingPort ---------------------------------------------------------------

    def get_account(self) -> HostingAccount:
        info = self.client.call("Variables", "get_user_information") or {}
        domains = self.client.call("DomainInfo", "list_domains") or {}
        return map_account(info, hostname=self.hostname, primary_domain=domains.get("main_domain", ""))

    def get_usage(self) -> list[HostingResource]:
        return map_usages(self.client.call("ResourceUsage", "get_usages") or [])

    def list_domains(self) -> list[HostingDomain]:
        data = self.client.call("DomainInfo", "domains_data", format="hash") or {}
        certs = self.client.call("SSL", "installed_hosts") or []
        return map_domains(data, certs)

    # -- MailboxCapability ---------------------------------------------------------

    def list_mailboxes(self, domain: str | None = None) -> list[Mailbox]:
        return map_mailboxes(self.client.call("Email", "list_pops_with_disk", domain=domain) or [])

    def _find_mailbox(self, email: str) -> Mailbox:
        _, _, domain = email.partition("@")
        for box in self.list_mailboxes(domain=domain or None):
            if box.email == email:
                return box
        return Mailbox(email=email, login=email, domain=domain)

    def create_mailbox(self, email: str, password: str, quota_mb: int | None = None) -> Mailbox:
        local, _, domain = email.partition("@")
        self.client.call(
            "Email",
            "add_pop",
            method="POST",
            email=local,
            domain=domain,
            password=password,
            quota=quota_mb if quota_mb is not None else 0,  # cPanel spells unlimited as 0
        )
        return self._find_mailbox(email)

    def delete_mailbox(self, email: str) -> bool:
        self.client.call("Email", "delete_pop", method="POST", email=email)
        return True

    def set_mailbox_quota(self, email: str, quota_mb: int | None) -> Mailbox:
        self.client.call(
            "Email",
            "edit_pop_quota",
            method="POST",
            email=email,
            quota=quota_mb if quota_mb is not None else 0,
        )
        return self._find_mailbox(email)

    def set_mailbox_password(self, email: str, password: str) -> bool:
        self.client.call("Email", "passwd_pop", method="POST", email=email, password=password)
        return True

    # -- PanelLinkCapability -------------------------------------------------------

    def get_panel_link(self) -> PanelLink:
        # UAPI has no `Session/create_session`: an account token cannot mint a panel
        # session for itself. Only WHM's create_user_session can, so this is a plain
        # login URL and must not be presented as one-click.
        return PanelLink(url=f"https://{self.hostname}:{self.port}/", kind="panel", single_sign_on=False)

    def get_webmail_link(self, email: str | None = None) -> PanelLink:
        if email:
            local, _, domain = email.partition("@")
            data = self.client.call("Session", "create_webmail_session_for_mail_user", login=local, domain=domain)
        else:
            data = self.client.call("Session", "create_webmail_session_for_self")
        session = (data or {}).get("session", "")
        return PanelLink(
            url=f"https://{self.hostname}:{self.webmail_port}/login/?session={quote(session, safe='')}",
            kind="webmail",
            single_sign_on=True,
        )

    # -- DnsPort -------------------------------------------------------------------

    def list_zones(self) -> list[DnsZone]:
        """cPanel serves one zone per domain it hosts."""
        return [DnsZone(zone=domain.domain) for domain in self.list_domains()]

    def get_zone(self, zone: str) -> DnsZoneSnapshot:
        return map_zone(zone, self.client.call("DNS", "parse_zone", zone=zone) or [])

    def apply_changes(
        self,
        zone: str,
        version: str,
        *,
        add: Sequence[DnsRecord] = (),
        edit: Sequence[DnsRecord] = (),
        remove: Sequence[str] = (),
    ) -> DnsZoneSnapshot:
        if not (add or edit or remove):
            raise ValidationError("At least one change is required.")

        for record in (*add, *edit):
            if record.record_type not in self.supported_record_types:
                raise ValidationError(
                    f"cPanel cannot write {record.record_type} records. "
                    f"Writable types: {', '.join(self.supported_record_types)}."
                )

        payload: dict = {"zone": zone, "serial": version}
        if add:
            payload["add"] = [json.dumps(record_to_payload(r)) for r in add]
        if edit:
            payload["edit"] = [json.dumps(record_to_payload(r, include_ref=True)) for r in edit]
        if remove:
            payload["remove"] = list(remove)

        # A stale serial raises DnsZoneChangedError from the client's error mapping.
        self.client.call("DNS", "mass_edit_zone", method="POST", **payload)
        return self.get_zone(zone)
