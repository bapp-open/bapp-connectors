"""pfSense adapter — NetworkPort + DnsAllowlistCapability over XML-RPC exec_php."""

from __future__ import annotations

import base64
import json
import logging
import re
import shlex

from bapp_connectors.core.capabilities import DnsAllowlistCapability
from bapp_connectors.core.dto import (
    ConnectionTestResult,
    DnsAllowlist,
    NetworkClient,
    NetworkDeviceInfo,
    NetworkSegment,
)
from bapp_connectors.core.errors import ConfigurationError
from bapp_connectors.core.http import BasicAuth, ResilientHttpClient
from bapp_connectors.core.ports import NetworkPort
from bapp_connectors.providers.network.pfsense.client import PfSenseClient
from bapp_connectors.providers.network.pfsense.manifest import manifest
from bapp_connectors.providers.network.pfsense.mappers import (
    map_clients,
    map_device_info,
    map_segments,
    segment_ref_for,
)
from bapp_connectors.providers.network.pfsense.unbound import parse_view, render_view, replace_view

logger = logging.getLogger(__name__)

# Each snippet carries a `// bapp:<name>` marker so tests can route on it.
PHP_DEVICE_INFO = """// bapp:device_info
$uptime = null;
if (function_exists('get_uptime_sec')) { $uptime = (int) get_uptime_sec(); }
$platform = '';
if (function_exists('system_identify_specific_platform')) {
    $p = system_identify_specific_platform();
    $platform = is_array($p) ? ($p['descr'] ?? ($p['name'] ?? '')) : (string) $p;
}
return [
    'hostname' => config_get_path('system/hostname'),
    'domain'   => config_get_path('system/domain'),
    'version'  => trim((string) @file_get_contents('/etc/version')),
    'platform' => $platform,
    'uptime'   => $uptime,
];
"""

PHP_SEGMENTS = """// bapp:segments
$out = [];
foreach (get_configured_interface_with_descr() as $if => $descr) {
    $ip = get_interface_ip($if);
    if (!$ip) { continue; }
    $d = config_get_path("dhcpd/{$if}", []);
    $out[] = [
        'ref' => $if,
        'descr' => $descr,
        'ip' => $ip,
        'subnet' => get_interface_subnet($if),
        'dhcp_from' => $d['range']['from'] ?? '',
        'dhcp_to' => $d['range']['to'] ?? '',
        'dhcp_enabled' => is_array($d) && array_key_exists('enable', $d),
    ];
}
return $out;
"""

PHP_CLIENTS = """// bapp:clients
$leases = function_exists('system_get_dhcpleases') ? system_get_dhcpleases() : [];
return [
    'leases' => $leases['lease'] ?? [],
    'arp' => (string) shell_exec('/usr/sbin/arp -an'),
];
"""

PHP_GET_UNBOUND = """// bapp:get_unbound
return [
    'custom_options' => (string) config_get_path('unbound/custom_options', ''),
    'section' => config_get_path('unbound', []),
];
"""

# {b64} and {view} are substituted with str.format; the PHP has no other braces.
PHP_SET_UNBOUND = """// bapp:set_unbound
config_set_path('unbound/custom_options', base64_encode(base64_decode('{b64}')));
write_config('bapp: DNS allowlist for view {view}');
services_unbound_configure();
return true;
"""

PHP_HOT_APPLY = """// bapp:hot_apply
$cmds = json_decode(base64_decode('{b64}'), true);
$out = [];
foreach ($cmds as $cmd) {{
    $out[] = trim((string) shell_exec('/usr/local/sbin/unbound-control -c /var/unbound/unbound.conf ' . $cmd . ' 2>&1'));
}}
return ['ok' => true, 'output' => implode("\\n", $out)];
"""


class PfSenseNetworkAdapter(NetworkPort, DnsAllowlistCapability):
    manifest = manifest

    def __init__(
        self,
        credentials: dict,
        http_client: ResilientHttpClient | None = None,
        config: dict | None = None,
        **kwargs,
    ):
        self.credentials = credentials
        self.config = config or {}
        endpoints = self._endpoints(self.config)
        verify_ssl = bool(self.config.get("verify_ssl", False))
        timeout = int(self.config.get("timeout", 20) or 20)

        if http_client is None:
            http_client = ResilientHttpClient(
                base_url=endpoints[0] if endpoints else self.manifest.base_url,
                auth=BasicAuth(username=credentials.get("username", ""), password=credentials.get("password", "")),
                provider_name="pfsense",
                timeout=timeout,
            )
        session = getattr(http_client, "_session", None)
        if session is not None:
            session.verify = verify_ssl  # per-call `verify=` is also passed; belt and braces for the real client

        self.client = PfSenseClient(http_client, endpoints=endpoints, verify_ssl=verify_ssl, timeout=timeout)
        self._segments_cache: list[NetworkSegment] | None = None

    # -- helpers -------------------------------------------------------------------

    @staticmethod
    def _endpoints(config: dict) -> list[str]:
        """Accept a list, or a string with URLs separated by newlines, commas, semicolons or spaces."""
        raw = config.get("endpoints", "")
        items = raw if isinstance(raw, list) else re.split(r"[\s,;]+", str(raw))
        return [item.strip().rstrip("/") for item in items if item and item.strip()]

    def _segments(self, refresh: bool = False) -> list[NetworkSegment]:
        if self._segments_cache is None or refresh:
            self._segments_cache = map_segments(self.client.run(PHP_SEGMENTS))
        return self._segments_cache

    def _segment(self, segment_ref: str) -> NetworkSegment:
        for seg in self._segments():
            if seg.ref == segment_ref:
                return seg
        raise ConfigurationError(f"pfSense: unknown segment {segment_ref!r}")

    # -- BasePort ------------------------------------------------------------------

    def validate_credentials(self) -> bool:
        return not self.manifest.auth.validate_credentials(self.credentials)

    def test_connection(self) -> ConnectionTestResult:
        try:
            info = self.get_device_info()
        except Exception as exc:
            return ConnectionTestResult(success=False, message=str(exc))
        return ConnectionTestResult(
            success=True,
            message=f"Connected to {info.hostname} ({info.version})",
            details={"hostname": info.hostname, "version": info.version, "endpoint": self.client.active_endpoint or ""},
        )

    # -- NetworkPort ---------------------------------------------------------------

    def get_device_info(self) -> NetworkDeviceInfo:
        return map_device_info(self.client.run(PHP_DEVICE_INFO))

    def list_segments(self) -> list[NetworkSegment]:
        return self._segments(refresh=True)

    def list_clients(self, segment_ref: str | None = None) -> list[NetworkClient]:
        segments = self._segments()
        cidr = self._segment(segment_ref).cidr if segment_ref else None
        payload = self.client.run(PHP_CLIENTS)
        clients = map_clients(payload.get("leases", []), payload.get("arp", ""), cidr)
        return [
            c.model_copy(update={"segment_ref": segment_ref or segment_ref_for(c.ip, segments)})
            for c in clients
        ]

    # -- DnsAllowlistCapability ------------------------------------------------------

    @staticmethod
    def _view(config: dict) -> str:
        view = str(config.get("view", "")).strip()
        if not view:
            raise ConfigurationError("pfSense: segment config needs a `view` name for the DNS allowlist")
        return view

    def _read_unbound(self) -> tuple[str, str]:
        payload = self.client.run(PHP_GET_UNBOUND)
        encoded = payload.get("custom_options") or ""
        text = base64.b64decode(encoded).decode("utf-8", errors="replace") if encoded else ""
        return text, json.dumps(payload.get("section", {}), ensure_ascii=False)

    def get_dns_allowlist(self, segment_ref: str, config: dict) -> DnsAllowlist:
        view = self._view(config)
        text, _section = self._read_unbound()
        parsed = parse_view(text, view)
        if parsed is None:
            return DnsAllowlist(segment_ref=segment_ref, domains=[], present=False, raw="")
        return DnsAllowlist(segment_ref=segment_ref, domains=parsed.domains, present=True, raw=parsed.block)

    def set_dns_allowlist(self, segment_ref: str, config: dict, domains: list[str]) -> DnsAllowlist:
        view = self._view(config)
        cidr = str(config.get("cidr") or "").strip() or self._segment(segment_ref).cidr
        if not cidr:
            raise ConfigurationError(f"pfSense: no CIDR known for segment {segment_ref!r}")

        text, backup = self._read_unbound()
        before = parse_view(text, view)
        block = render_view(view, cidr, domains)
        new_text = replace_view(text, view, block)

        b64 = base64.b64encode(new_text.encode("utf-8")).decode("ascii")
        self.client.run(PHP_SET_UNBOUND.format(b64=b64, view=view))

        wanted = set(parse_view(block, view).domains)
        had = set(before.domains) if before else set()
        commands = [f"view_local_zone {shlex.quote(view)} {shlex.quote(d + '.')} transparent" for d in sorted(wanted - had)]
        commands += [f"view_local_zone_remove {shlex.quote(view)} {shlex.quote(d + '.')}" for d in sorted(had - wanted)]
        if commands:
            cmds_b64 = base64.b64encode(json.dumps(commands).encode("utf-8")).decode("ascii")
            try:
                output = self.client.run(PHP_HOT_APPLY.format(b64=cmds_b64)).get("output", "")
                logger.info("pfSense hot apply for view %s: %s", view, output)
            except Exception:  # best effort: the reconfigure above already applied the list
                logger.warning("pfSense hot apply for view %s failed", view, exc_info=True)

        after = self.get_dns_allowlist(segment_ref, config)
        return after.model_copy(update={"backup": backup})
