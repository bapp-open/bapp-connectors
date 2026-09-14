# pfSense (network)

Talks to pfSense / pfSense Plus through the built-in XML-RPC endpoint (`/xmlrpc.php`,
method `pfsense.exec_php`) using an admin account over HTTP basic auth.

- Credentials: `username`, `password` (equivalent to root on the firewall — treat accordingly).
- Settings: `endpoints` (base URLs separated by commas or newlines, tried in order; one per WAN when multi-homed),
  `verify_ssl` (default off, self-signed certificate), `timeout`.
- Capabilities: `NetworkPort` (device info, segments, connected clients) and
  `DnsAllowlistCapability` (per-view Unbound allowlist kept between `# bapp:begin <view>` /
  `# bapp:end <view>` markers inside DNS Resolver → Custom options).

Reading uses `config_get_path`, `system_get_dhcpleases()` and `arp -an`. Writing rewrites only the
owned block of `unbound/custom_options`, calls `write_config()` + `services_unbound_configure()`,
then hot-applies the diff with `unbound-control view_local_zone[_remove]`.
