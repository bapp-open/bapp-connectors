# Design: `hosting` + `dns` families, cPanel provider

Date: 2026-09-17
Status: Draft — pending review

## Summary

Two new provider families and one provider that implements both.

1. **`hosting` family** — a shared-hosting control-panel account: identity, metered
   resources, domains, mailboxes, deep links into the panel.
2. **`dns` family** — authoritative DNS zone management, designed so that the same
   BAPP UI drives cPanel today and Cloudflare later.
3. **cPanel provider** (`providers/hosting/cpanel/`) — implements `HostingPort`,
   `MailboxCapability`, `PanelLinkCapability` **and** `DnsPort`.

The load-bearing decision: **family says what a provider *is*, ports say what it
*can do*, and an adapter may implement more than one port.** cPanel is a hosting
provider that also speaks DNS; Cloudflare will be a DNS provider that does no
hosting. Both satisfy `DnsPort`, so a single DNS manager in BAPP drives both.

This is already how the framework models things — `PROVIDER_GUIDE.md:129` says the
manifest lists "ALL port + capability interfaces", WooCommerce declares `ShopPort`
inside `capabilities=[...]`, and `registry.register` (`registry.py:56`) only checks
`issubclass` per declared interface. Nothing anywhere requires exactly one port.

## Scope / non-goals

- **In scope (v1):** both families, both ports, the three capabilities, the cPanel
  provider implementing all of them including DNS writes, and capability-based
  provider discovery in the registry.
- **Not in scope:** the Cloudflare provider. This spec fixes the contract it will
  implement and the rules for its extra features, nothing more.
- **Not in scope:** WHM (port 2087). Creating cPanel accounts, suspending them, and
  minting a single-sign-on session into the panel all require WHM and would be a
  separate provider. See "Known constraints".
- **Not in scope:** anything in the Django package. `Connection`, `SyncState` and the
  services are family-agnostic and need no change.
- **No new dependencies.** `requests` + `pydantic`, both already present.

## Verified API surface

Every endpoint below was called against a live cPanel account on 2026-09-17,
over the standard secure port 2083. Shapes in this spec are the
observed ones, not the documented ones — the published docs for `mass_edit_zone`
are 404 at the time of writing.

| Need | UAPI call | Observed result |
|---|---|---|
| Account identity | `Variables/get_user_information` | user, plan, limits |
| Domains | `DomainInfo/domains_data?format=hash` | `main_domain` object + `addon_domains`, `parked_domains`, `sub_domains` arrays |
| Metered resources | `ResourceUsage/get_usages` | 17 entries: `{id, usage, maximum, formatter, description}` |
| Disk quota | `Quota/get_quota_info` | megabytes used/remaining, inodes |
| SSL | `SSL/installed_hosts` | cert per vhost, `not_after` as unix int, `is_autossl` |
| Mailboxes | `Email/list_pops_with_disk` | per mailbox usage, see gotcha below |
| Mailbox writes | `Email/add_pop`, `delete_pop`, `edit_pop_quota`, `passwd_pop` | all present |
| Webmail SSO | `Session/create_webmail_session_for_self`, `..._for_mail_user` | returns a session token |
| DNS read | `DNS/parse_zone` | line-oriented, base64 |
| DNS write | `DNS/mass_edit_zone` | signature below |

### Envelope

Every response is `{status, data, errors, warnings, messages, metadata}` and
**arrives as HTTP 200 even when the call fails** — a failed `Email/add_pop` returns
HTTP 200 with `status: 0`. Error detection is on `status`, never on the HTTP code.
`raise_for_status()` alone silently maps failures to successes.

### `DNS/parse_zone` shape

Lines are typed. `comment` and `control` lines carry `text_b64`; `record` lines
carry structured fields and **no** `text_b64`:

```json
{"type": "record", "line_index": 13, "ttl": 14400, "record_type": "MX",
 "dname_raw": "example.test.", "dname_b64": "…",
 "data_b64": ["MA==", "ZXhhbXBsZS50ZXN0Lg=="]}
```

`data_b64` is a **positional** array whose meaning depends on `record_type`
(MX: priority, exchange — SRV: priority, weight, port, target — SOA: seven fields).

### `DNS/mass_edit_zone` signature

Recovered from the server's own validation errors:

```
zone    required
serial  required, enforced:
        "The given serial number (1) does not match the DNS zone's serial
         number (2026010101). Refresh your view of the DNS zone, then resubmit."
add     {dname, ttl, record_type, data}   — data MUST be an array
edit    {line_index, dname, ttl, record_type, data}
remove  line_index (scalar)
```

Writable record types are **A, AAAA, ALIAS, CAA, CNAME, HTTPS, MX, SRV, SVCB, TXT**.
`SOA` and `NS` are readable through `parse_zone` but this interface refuses to
write them.

### Mailbox quota gotcha

`list_pops_with_disk` reports each quota twice:

| Field | Unit | Example |
|---|---|---|
| `diskused` / `diskquota` | **megabytes**, as strings | `"862.11"` / `"1024.00"` |
| `_diskused` / `_diskquota` | **bytes**, as strings | `"903985792"` / `"1073741824"` |

The underscore-prefixed pair is canonical. Confusing the two is a factor-1048576
error that looks plausible in a UI, so the mappers use `_diskused`/`_diskquota`
and a test pins it.

## Known constraints

**1. No single sign-on into the cPanel UI.** `Session/create_session` does not
exist — a cPanel account token cannot mint a panel session for itself, by design.
`Session/create_webmail_session_for_self` and `..._for_mail_user` *do* work, so
webmail gets a real one-click link. The panel link is a plain URL to
`https://{host}:{port}/` with `single_sign_on=False`, and the UI must not promise
otherwise. True SSO would need WHM's `create_user_session`, i.e. reseller access.

**2. DNS writes are positional with an optimistic lock.** cPanel identifies records
by `line_index`, which shifts whenever the zone changes, and guards writes with the
SOA serial. Cloudflare identifies records by a stable `id` and has no serial. The
port must accommodate both without leaking either — see Part 2.

---

## Part 1 — Core: the `hosting` family

### Enum

`src/bapp_connectors/core/types.py`:

```python
HOSTING = "hosting"
```

### Port

`src/bapp_connectors/core/ports/hosting.py`:

```python
class HostingPort(BasePort):
    """Contract for a shared-hosting control-panel account."""

    @abstractmethod
    def get_account(self) -> HostingAccount:
        """Identity of the account: user, primary domain, plan, server."""

    @abstractmethod
    def get_usage(self) -> list[HostingResource]:
        """Every metered resource the panel reports, normalized."""

    @abstractmethod
    def list_domains(self) -> list[HostingDomain]:
        """Main, addon, parked and sub domains, with SSL state."""
```

### DTOs

`src/bapp_connectors/core/dto/hosting.py`:

```python
class HostingAccount(BaseDTO):
    username: str
    primary_domain: str
    plan: str = ""
    server_hostname: str = ""
    panel_version: str = ""
    extra: dict = {}


class HostingResource(BaseDTO):
    """One metered resource: disk, bandwidth, mailbox count, ..."""

    key: str                       # disk_usage | bandwidth | email_accounts | ...
    label: str = ""
    used: Decimal | None = None
    limit: Decimal | None = None   # None means unlimited, never 0
    unit: str = ""                 # bytes | count
    percent: float | None = None


class HostingDomain(BaseDTO):
    domain: str
    kind: str                      # main | addon | parked | sub
    document_root: str = ""
    parent_domain: str = ""
    ssl_expires_at: datetime | None = None
    ssl_issuer: str = ""
    ssl_auto: bool = False
    extra: dict = {}


class Mailbox(BaseDTO):
    email: str
    login: str
    domain: str
    disk_used: Decimal | None = None    # bytes
    disk_quota: Decimal | None = None   # bytes; None means unlimited
    percent_used: float | None = None
    suspended_login: bool = False
    suspended_incoming: bool = False
    extra: dict = {}


class PanelLink(BaseDTO):
    url: str
    kind: str                      # panel | webmail
    single_sign_on: bool           # False: the user still has to log in
    expires_at: datetime | None = None
```

**SSL lives on the domain, not behind its own port method.** `list_domains()` merges
`domains_data` with `installed_hosts`, which costs one extra HTTP call, in exchange
for one call site in BAPP when rendering a domains table.

---

## Part 2 — Core: the `dns` family

### Enum

```python
DNS = "dns"
```

### DTOs

`src/bapp_connectors/core/dto/dns.py`:

```python
class DnsZone(BaseDTO):
    zone: str
    editable: bool = True
    extra: dict = {}


class DnsRecord(BaseDTO):
    ref: str = ""                  # OPAQUE. cPanel: line_index. Cloudflare: record id.
                                   # Empty when creating: `add` ignores it.
    name: str
    record_type: str
    ttl: int
    value: str                     # rendered, human-editable
    priority: int | None = None
    extra: dict = {}               # provider-only data, e.g. Cloudflare `proxied`


class DnsZoneSnapshot(BaseDTO):
    zone: str
    version: str                   # OPAQUE. cPanel: SOA serial. Cloudflare: "".
    records: list[DnsRecord] = []
```

### Port

`src/bapp_connectors/core/ports/dns.py`:

```python
class DnsPort(BasePort):
    """Contract for authoritative DNS zone management."""

    supported_record_types: tuple[str, ...] = ()
    """Record types this provider can WRITE. The UI offers only these."""

    @abstractmethod
    def list_zones(self) -> list[DnsZone]: ...

    @abstractmethod
    def get_zone(self, zone: str) -> DnsZoneSnapshot:
        """Full snapshot. `version` and each `ref` are opaque round-trip tokens."""

    @abstractmethod
    def apply_changes(
        self,
        zone: str,
        version: str,
        *,
        add: Sequence[DnsRecord] = (),
        edit: Sequence[DnsRecord] = (),
        remove: Sequence[str] = (),
    ) -> DnsZoneSnapshot:
        """Apply changes and return the re-read zone.

        `version` is the value from the snapshot the edits were based on. Providers
        with optimistic concurrency MUST reject a stale version; providers without
        it ignore the argument.

        `add` entries carry no `ref`; `edit` entries carry the `ref` they were read
        with; `remove` is a list of `ref`s.
        """
```

**Why `ref` and `version` are opaque.** Callers never parse them: they come out of
`get_zone` and go back into `apply_changes`. cPanel decodes `ref` as a line index and
enforces `version` as the SOA serial; Cloudflare uses `ref` as a record id and ignores
`version`. Neither leaks into BAPP.

**Why `version` exists at all even though only cPanel uses it.** Without it cPanel
cannot be implemented correctly — concurrent edits clobber each other silently.
Adding it later is a breaking interface change.

`supported_record_types` for cPanel is the ten types `mass_edit_zone` accepts.
Without it the UI offers `NS`, the user edits it, and the save fails.

### Capability-based discovery (the only core change beyond additions)

`registry.list_providers()` filters by family only (`registry.py:149`). BAPP needs
"every provider that can do DNS" across families:

```python
def list_providers(
    self,
    family: str | None = None,
    capability: type | None = None,
) -> list[ProviderManifest]:
    """`capability` matches any port or capability interface in the manifest."""
```

This is the mechanism the whole cross-provider DNS UI rests on. Backwards
compatible — `capability` defaults to `None`.

---

## Part 3 — Core: capabilities

`src/bapp_connectors/core/capabilities/mailbox.py`:

```python
class MailboxCapability(ABC):
    @abstractmethod
    def list_mailboxes(self, domain: str | None = None) -> list[Mailbox]: ...
    @abstractmethod
    def create_mailbox(self, email: str, password: str, quota_mb: int | None = None) -> Mailbox: ...
    @abstractmethod
    def delete_mailbox(self, email: str) -> bool: ...
    @abstractmethod
    def set_mailbox_quota(self, email: str, quota_mb: int | None) -> Mailbox: ...
    @abstractmethod
    def set_mailbox_password(self, email: str, password: str) -> bool: ...
```

`src/bapp_connectors/core/capabilities/panel_link.py`:

```python
class PanelLinkCapability(ABC):
    @abstractmethod
    def get_panel_link(self) -> PanelLink: ...
    @abstractmethod
    def get_webmail_link(self, email: str | None = None) -> PanelLink: ...
```

### Rule for provider-specific features

When a provider has something the port does not, triage in this order:

1. **Optional field on the DTO** — only if at least two providers expose it and the
   generic UI renders it.
2. **A separate capability** — if it is a *verb* only some providers can do. Cloudflare's
   orange cloud becomes `DnsProxyCapability.set_proxied(zone, ref, enabled)`, and the UI
   shows the toggle only when `adapter.supports(DnsProxyCapability)`.
3. **`extra: dict`** — data that is displayed but not generically edited.

Page rules, WAF and analytics are Cloudflare capabilities, never `DnsPort` methods.
**Only what the poorest provider can do belongs on a port.**

---

## Part 4 — The cPanel provider

`src/bapp_connectors/providers/hosting/cpanel/`, the standard seven files.

### `manifest.py`

```python
name="cpanel", family=ProviderFamily.HOSTING, display_name="cPanel",
allow_multiple=True,
base_url="https://cpanel.example:2083/",      # placeholder, as pfSense and Woo do
auth=AuthConfig(strategy=AuthStrategy.CUSTOM, required_fields=[
    CredentialField(name="hostname", label="Server", role="endpoint",
                    help_text="e.g. cpanel.example.net"),
    CredentialField(name="username", label="cPanel user"),
    CredentialField(name="token", label="API token", sensitive=True),
]),
settings=SettingsConfig(fields=[
    SettingsField("port", FieldType.INT, default=2083),
    SettingsField("webmail_port", FieldType.INT, default=2096),
    SettingsField("verify_ssl", FieldType.BOOL, default=True),
    SettingsField("timeout", FieldType.INT, default=30),
]),
capabilities=[HostingPort, MailboxCapability, PanelLinkCapability, DnsPort],
rate_limit=RateLimitConfig(requests_per_second=5, burst=10),
retry=RetryConfig(max_retries=3, backoff=EXPONENTIAL,
                  retryable_status_codes=[429, 500, 502, 503, 504],
                  non_retryable_status_codes=[400, 401, 403, 404]),
webhooks=WebhookConfig(supported=False),
```

`AuthStrategy.CUSTOM` because the framework's `TOKEN` strategy emits
`Authorization: <token>`, while UAPI wants `Authorization: cpanel user:token`.
`role="endpoint"` on `hostname` lets the UI label the connection
"cPanel · cpanel.example.net", as WooCommerce does with `domain`.

### `adapter.py`

Rebuilds the HTTP client against the real host, the way WooCommerce does
(`shop/woocommerce/adapter.py:147`):

```python
http_client = ResilientHttpClient(
    base_url=f"https://{hostname}:{port}/",
    auth=TokenAuth(token=f"{username}:{token}", prefix="cpanel"),
    retry_policy=..., rate_limiter=...,      # carried over from the manifest
    provider_name="cpanel",
)
```

No custom auth class is needed: `TokenAuth(prefix="cpanel")` already produces the
exact header. Unlike WooCommerce, which drops the registry's retry policy and rate
limiter when it rebuilds, this adapter passes both through. WooCommerce itself is
left alone — out of scope here.

`supported_record_types = ("A", "AAAA", "ALIAS", "CAA", "CNAME", "HTTPS", "MX", "SRV", "SVCB", "TXT")`

### `client.py`

Transport only, no business logic:

```python
def call(self, module: str, function: str, method: str = "GET", **params) -> Any:
    """GET/POST {base}/execute/{Module}/{function}; unwraps the envelope.

    Raises on `status != 1` regardless of HTTP status.
    """
```

Writes go over POST so passwords never reach a query string, and therefore never
reach the server's access log.

### `errors.py`

| UAPI signal | Framework error |
|---|---|
| HTTP 401/403, `Access denied` | `AuthenticationError` |
| `could not find the function "X" in the module "Y"` | `CpanelFunctionUnavailable(PermanentProviderError)` |
| `You do not have an email account named "…"` | `CpanelNotFoundError(PermanentProviderError)` |
| `strength rating of "0" … too weak` | `CpanelWeakPasswordError(PermanentProviderError)` |
| `The given serial number (…) does not match` | `DnsZoneChangedError(PermanentProviderError)` |
| HTTP 429/5xx, timeouts | retryable, via `RetryConfig` |

`CpanelWeakPasswordError` and `DnsZoneChangedError` are separate because both are
recoverable *by the user* — one means "pick a stronger password", the other means
"your view is stale, reload and redo". A generic failure cannot convey either.

### `mappers.py`

- `get_usages` → `HostingResource`: `formatter == "format_bytes"` gives `unit="bytes"`,
  otherwise `"count"`; `maximum is None` gives `limit=None` (unlimited — `forwarders`
  and `autoresponders` really do come back that way).
- `domains_data` → `HostingDomain`, `kind` taken from the key the entry came from.
- `installed_hosts` → merged onto domains by `fqdns`; `certificate.not_after` is a unix
  int, converted to an aware `datetime`.
- `list_pops_with_disk` → `Mailbox` from `_diskused` / `_diskquota` (bytes).
- `parse_zone` → `DnsRecord`: skip `comment` and `control` lines, base64-decode
  `dname_b64` and each element of `data_b64`, then render `value` per record type
  (MX and SRV lift their leading numeric fields into `priority` / `extra`). The SOA
  line supplies `DnsZoneSnapshot.version`. `ref = str(line_index)`.
- `DnsRecord` → `mass_edit_zone` payload: `data` is always an array, rebuilt
  positionally from `value` + `priority` per record type.
- `create_webmail_session_*` → `PanelLink(kind="webmail", single_sign_on=True)`,
  URL `https://{host}:{webmail_port}/login/?session={session}`.

The exact webmail session URL format is **unverified** — the session token was
obtained but never opened in a browser. Confirm it during implementation before
relying on it.

---

## Part 5 — Tests

```
tests/hosting/
├── test_family.py          # enum, DTO defaults + frozen, port/capability shapes
├── contract.py             # HostingContractTests, reusable by future providers
└── cpanel/
    ├── test_manifest.py
    ├── test_client.py
    ├── test_mappers.py
    ├── test_adapter.py     # HostingContractTests + DnsContractTests + FakeHttpClient
    └── test_integration.py # pytest.mark.integration, skip_unless_cpanel
tests/dns/
├── test_family.py
└── contract.py             # DnsContractTests, what Cloudflare will have to pass
```

Fixtures are **anonymized captures of the real responses** taken on 2026-09-17, not
hand-written payloads: domain replaced with `example.test`, mailbox local parts
replaced, addresses moved to `192.0.2.0/24`, `certificate_text` and `modulus`
dropped. They therefore carry the real shapes — positional `data_b64`,
`maximum: null`, `_diskquota` as a byte string.

Cases that get a dedicated test because each one fails silently:

- `status: 0` under HTTP 200 raises instead of returning `None`
- `maximum: null` maps to `limit=None`, not `limit=0`
- mailbox quota read from `_diskquota` (bytes), not `diskquota` (MB)
- `not_after` unix int to aware `datetime`
- weak password raises `CpanelWeakPasswordError`
- stale serial raises `DnsZoneChangedError`
- `data` is always sent as an array
- MX/SRV positional round-trip: `parse_zone` to `DnsRecord` to `mass_edit_zone` payload
- a record type outside `supported_record_types` is rejected before the HTTP call

### Live-write policy

The account available for testing is a **live production account** with real
mailboxes and a real DNS zone serving a real site. No test writes to it.

Integration tests are read-only by default, gated on `CPANEL_HOSTNAME`,
`CPANEL_USERNAME`, `CPANEL_TOKEN`. Write coverage is unit-level via `FakeHttpClient`.
Live write tests are written but additionally gated on `CPANEL_ALLOW_WRITES=1` and
are meant for a disposable account.

### Verification

```bash
uv run --extra dev pytest tests/hosting tests/dns -v
uv run ruff check
```

---

## Versioning & release

New families and a new provider, no breaking change: **0.36.1 → 0.37.0**.
`registry.list_providers(capability=...)` is additive.

## Affected files

**New — core**

```
src/bapp_connectors/core/ports/hosting.py
src/bapp_connectors/core/ports/dns.py
src/bapp_connectors/core/dto/hosting.py
src/bapp_connectors/core/dto/dns.py
src/bapp_connectors/core/capabilities/mailbox.py
src/bapp_connectors/core/capabilities/panel_link.py
```

**New — provider**

```
src/bapp_connectors/providers/hosting/__init__.py
src/bapp_connectors/providers/hosting/cpanel/{__init__,manifest,client,adapter,mappers,models,errors}.py
```

**New — tests**

```
tests/hosting/{__init__,test_family,contract}.py
tests/hosting/cpanel/{__init__,test_manifest,test_client,test_mappers,test_adapter,test_integration}.py
tests/hosting/cpanel/fixtures/*.json
tests/dns/{__init__,test_family,contract}.py
```

**Modified**

```
src/bapp_connectors/core/types.py                  # HOSTING, DNS
src/bapp_connectors/core/ports/__init__.py         # exports
src/bapp_connectors/core/dto/__init__.py           # exports
src/bapp_connectors/core/capabilities/__init__.py  # exports
src/bapp_connectors/core/registry.py               # list_providers(capability=)
src/bapp_connectors/providers/__init__.py          # import the hosting package
pyproject.toml                                     # 0.37.0
README.md                                          # regenerated by the pre-commit hook
CLAUDE.md                                          # families table: 11 -> 13
docs/PROVIDER_GUIDE.md                             # note that an adapter may implement several ports
```
