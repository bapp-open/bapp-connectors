# cPanel hosting + DNS connector — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two provider families (`hosting`, `dns`) and a cPanel provider that implements both, so BAPP can administer a cPanel account — domains, resources, mailboxes, DNS — through contracts a future Cloudflare provider will satisfy unchanged.

**Architecture:** Ports-and-adapters, as the rest of the package. `HostingPort` stays minimal (account, usage, domains); mailboxes and panel links are optional capabilities; `DnsPort` is its own port so a DNS-only provider can implement it without hosting. One adapter may implement several ports — `registry.register` only checks `issubclass` per declared interface, and the manifest's `capabilities` list already mixes ports and capabilities. cPanel therefore registers as `hosting:cpanel` while also satisfying `DnsPort`.

**Tech Stack:** Python 3.11+, pydantic v2, requests, pytest, ruff, uv.

**Spec:** `docs/superpowers/specs/2026-09-17-cpanel-hosting-dns-connector-design.md`

## Global Constraints

- **No Django imports** anywhere in `src/bapp_connectors/`.
- **No new dependencies.** `requests` + `pydantic` only.
- **No secrets or customer data** in any committed file. Fixtures are already anonymized; keep them that way.
- **Never write to a live cPanel account** from a test that runs by default. Live write tests are gated on `CPANEL_ALLOW_WRITES=1`.
- `line-length = 120`, `target-version = "py311"` (ruff).
- Tests run with `uv run --extra dev pytest`; integration tests are excluded by `addopts = "-m 'not integration'"`.
- DTOs inherit `BaseDTO`, which is **frozen** (`ConfigDict(frozen=True)`). Never mutate a DTO; construct a new one.
- Every `__init__.py` export list in `core/` is alphabetically sorted. Keep it sorted.
- Fixtures already exist, committed in `b793d5d`: `tests/hosting/cpanel/fixtures/{domains_data,pops_disk,quota,ssl_hosts,usages,zone}.json`. Each is a full UAPI envelope (`{"data": …, "status": 1, "errors": null}`).

---

### Task 1: The `hosting` family core

**Files:**
- Modify: `src/bapp_connectors/core/types.py` — add `HOSTING` to `ProviderFamily`
- Create: `src/bapp_connectors/core/dto/hosting.py`
- Create: `src/bapp_connectors/core/ports/hosting.py`
- Modify: `src/bapp_connectors/core/dto/__init__.py` — exports
- Modify: `src/bapp_connectors/core/ports/__init__.py` — exports
- Test: `tests/hosting/__init__.py`, `tests/hosting/test_family.py`

**Interfaces:**
- Consumes: `BaseDTO` from `bapp_connectors.core.dto.base`, `BasePort` from `bapp_connectors.core.ports.base`.
- Produces: `ProviderFamily.HOSTING`; DTOs `HostingAccount`, `HostingResource`, `HostingDomain`, `Mailbox`, `PanelLink`; port `HostingPort` with abstract `get_account()`, `get_usage()`, `list_domains()`.

- [ ] **Step 1: Write the failing test**

Create `tests/hosting/__init__.py` (empty) and `tests/hosting/test_family.py`:

```python
"""Family-level tests: enum, DTOs, port shapes."""

from abc import ABC
from decimal import Decimal

import pytest
from pydantic import ValidationError

from bapp_connectors.core.dto import HostingAccount, HostingDomain, HostingResource, Mailbox, PanelLink
from bapp_connectors.core.ports import BasePort, HostingPort
from bapp_connectors.core.types import ProviderFamily


def test_hosting_family_enum():
    assert ProviderFamily.HOSTING == "hosting"
    assert ProviderFamily("hosting") is ProviderFamily.HOSTING


def test_dtos_are_frozen_with_defaults():
    acc = HostingAccount(username="u", primary_domain="example.test")
    assert acc.plan == "" and acc.server_hostname == "" and acc.extra == {}
    with pytest.raises(ValidationError):
        acc.plan = "x"  # frozen

    res = HostingResource(key="disk_usage")
    assert res.used is None and res.limit is None and res.unit == "" and res.percent is None

    dom = HostingDomain(domain="example.test", kind="main")
    assert dom.document_root == "" and dom.ssl_expires_at is None and dom.ssl_auto is False

    box = Mailbox(email="a@example.test", login="a@example.test", domain="example.test")
    assert box.disk_used is None and box.disk_quota is None
    assert box.suspended_login is False and box.suspended_incoming is False

    link = PanelLink(url="https://cpanel.example.net:2083/", kind="panel", single_sign_on=False)
    assert link.expires_at is None


def test_resource_accepts_decimal_amounts():
    res = HostingResource(key="disk_usage", used=Decimal("1305116672"), limit=Decimal("128849018880"), unit="bytes")
    assert res.used == Decimal("1305116672")


def test_port_is_abstract():
    assert issubclass(HostingPort, BasePort)
    assert issubclass(HostingPort, ABC)
    with pytest.raises(TypeError):
        HostingPort()  # type: ignore[abstract]
    assert {"get_account", "get_usage", "list_domains", "validate_credentials", "test_connection"} <= HostingPort.__abstractmethods__
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/hosting/test_family.py -v`
Expected: FAIL — `ImportError: cannot import name 'HostingAccount' from 'bapp_connectors.core.dto'`

- [ ] **Step 3: Add the enum value**

In `src/bapp_connectors/core/types.py`, inside `class ProviderFamily(StrEnum)`, after `NETWORK = "network"`:

```python
    HOSTING = "hosting"
```

- [ ] **Step 4: Write the DTOs**

Create `src/bapp_connectors/core/dto/hosting.py`:

```python
"""Hosting family DTOs — control-panel account, resources, domains, mailboxes, links."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from bapp_connectors.core.dto.base import BaseDTO


class HostingAccount(BaseDTO):
    """Identity of a shared-hosting control-panel account."""

    username: str
    primary_domain: str
    plan: str = ""
    server_hostname: str = ""
    panel_version: str = ""
    extra: dict = {}


class HostingResource(BaseDTO):
    """One metered resource reported by the panel: disk, bandwidth, mailbox count, ..."""

    key: str
    label: str = ""
    used: Decimal | None = None
    limit: Decimal | None = None
    """None means unlimited. Never use 0 to mean unlimited."""
    unit: str = ""
    """bytes | count"""
    percent: float | None = None


class HostingDomain(BaseDTO):
    """A domain served by the account, with its SSL state."""

    domain: str
    kind: str
    """main | addon | parked | sub"""
    document_root: str = ""
    parent_domain: str = ""
    ssl_expires_at: datetime | None = None
    ssl_issuer: str = ""
    ssl_auto: bool = False
    extra: dict = {}


class Mailbox(BaseDTO):
    """An email account on the hosting plan. Disk figures are bytes."""

    email: str
    login: str
    domain: str
    disk_used: Decimal | None = None
    disk_quota: Decimal | None = None
    """None means unlimited."""
    percent_used: float | None = None
    suspended_login: bool = False
    suspended_incoming: bool = False
    extra: dict = {}


class PanelLink(BaseDTO):
    """A URL that opens the panel or webmail."""

    url: str
    kind: str
    """panel | webmail"""
    single_sign_on: bool
    """False means the user still has to log in at the far end."""
    expires_at: datetime | None = None
```

- [ ] **Step 5: Write the port**

Create `src/bapp_connectors/core/ports/hosting.py`:

```python
"""Hosting port — a shared-hosting control-panel account."""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING

from bapp_connectors.core.ports.base import BasePort

if TYPE_CHECKING:
    from bapp_connectors.core.dto import HostingAccount, HostingDomain, HostingResource


class HostingPort(BasePort):
    """Base operations every hosting control-panel provider must implement.

    Mailbox management and panel links are optional capabilities, not port
    methods: a provider may run a panel with no mail service at all.
    """

    @abstractmethod
    def get_account(self) -> HostingAccount:
        """Identity of the account: user, primary domain, plan, server."""
        ...

    @abstractmethod
    def get_usage(self) -> list[HostingResource]:
        """Every metered resource the panel reports, normalized."""
        ...

    @abstractmethod
    def list_domains(self) -> list[HostingDomain]:
        """Main, addon, parked and sub domains, with SSL state where known."""
        ...
```

- [ ] **Step 6: Wire the exports**

In `src/bapp_connectors/core/dto/__init__.py`, add the import (keep import block ordering) and add `"HostingAccount"`, `"HostingDomain"`, `"HostingResource"`, `"Mailbox"`, `"PanelLink"` to `__all__` in alphabetical position:

```python
from .hosting import HostingAccount, HostingDomain, HostingResource, Mailbox, PanelLink
```

In `src/bapp_connectors/core/ports/__init__.py`:

```python
from .hosting import HostingPort
```

and add `"HostingPort"` to `__all__` after `"FileInfo"`.

- [ ] **Step 7: Run the tests**

Run: `uv run --extra dev pytest tests/hosting/test_family.py -v`
Expected: PASS, 4 tests.

- [ ] **Step 8: Lint and commit**

```bash
uv run ruff check src/bapp_connectors/core tests/hosting
git add src/bapp_connectors/core/types.py src/bapp_connectors/core/dto/hosting.py \
        src/bapp_connectors/core/dto/__init__.py src/bapp_connectors/core/ports/hosting.py \
        src/bapp_connectors/core/ports/__init__.py tests/hosting
git commit -m "feat(core): familia hosting — HostingPort si DTO-urile ei"
```

---

### Task 2: The `dns` family core

**Files:**
- Modify: `src/bapp_connectors/core/types.py` — add `DNS` to `ProviderFamily`
- Create: `src/bapp_connectors/core/dto/dns.py`
- Create: `src/bapp_connectors/core/ports/dns.py`
- Modify: `src/bapp_connectors/core/dto/__init__.py`, `src/bapp_connectors/core/ports/__init__.py`
- Test: `tests/dns/__init__.py`, `tests/dns/test_family.py`

**Interfaces:**
- Consumes: `BaseDTO`, `BasePort`.
- Produces: `ProviderFamily.DNS`; DTOs `DnsZone`, `DnsRecord`, `DnsZoneSnapshot`; port `DnsPort` with class attribute `supported_record_types: tuple[str, ...]` and abstract `list_zones()`, `get_zone(zone)`, `apply_changes(zone, version, *, add, edit, remove)`.

- [ ] **Step 1: Write the failing test**

Create `tests/dns/__init__.py` (empty) and `tests/dns/test_family.py`:

```python
"""Family-level tests: enum, DTOs, port shape."""

from abc import ABC

import pytest
from pydantic import ValidationError

from bapp_connectors.core.dto import DnsRecord, DnsZone, DnsZoneSnapshot
from bapp_connectors.core.ports import BasePort, DnsPort
from bapp_connectors.core.types import ProviderFamily


def test_dns_family_enum():
    assert ProviderFamily.DNS == "dns"
    assert ProviderFamily("dns") is ProviderFamily.DNS


def test_dtos_are_frozen_with_defaults():
    zone = DnsZone(zone="example.test")
    assert zone.editable is True and zone.extra == {}
    with pytest.raises(ValidationError):
        zone.zone = "x"  # frozen

    rec = DnsRecord(name="example.test.", record_type="A", ttl=14400, value="192.0.2.10")
    assert rec.ref == "", "ref is empty for a record that does not exist yet"
    assert rec.priority is None and rec.extra == {}

    snap = DnsZoneSnapshot(zone="example.test", version="2026010101")
    assert snap.records == []


def test_port_is_abstract_and_declares_supported_types():
    assert issubclass(DnsPort, BasePort)
    assert issubclass(DnsPort, ABC)
    with pytest.raises(TypeError):
        DnsPort()  # type: ignore[abstract]
    assert {"list_zones", "get_zone", "apply_changes", "validate_credentials", "test_connection"} <= DnsPort.__abstractmethods__
    assert DnsPort.supported_record_types == ()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/dns/test_family.py -v`
Expected: FAIL — `ImportError: cannot import name 'DnsRecord'`

- [ ] **Step 3: Add the enum value**

In `src/bapp_connectors/core/types.py`, after `HOSTING = "hosting"`:

```python
    DNS = "dns"
```

- [ ] **Step 4: Write the DTOs**

Create `src/bapp_connectors/core/dto/dns.py`:

```python
"""DNS family DTOs — zones, records, and a snapshot that carries a write token.

`DnsRecord.ref` and `DnsZoneSnapshot.version` are OPAQUE to callers. They come out
of `get_zone` and go back into `apply_changes` untouched. cPanel encodes a line
index and the SOA serial in them; Cloudflare encodes a record id and nothing.
"""

from __future__ import annotations

from bapp_connectors.core.dto.base import BaseDTO


class DnsZone(BaseDTO):
    """A zone the account is authoritative for."""

    zone: str
    editable: bool = True
    extra: dict = {}


class DnsRecord(BaseDTO):
    """One resource record."""

    ref: str = ""
    """Opaque provider handle. Empty when creating — `add` ignores it."""
    name: str
    record_type: str
    ttl: int
    value: str
    """Rendered, human-editable form of the record's data."""
    priority: int | None = None
    extra: dict = {}
    """Provider-only data, e.g. Cloudflare's `proxied`, SRV weight and port."""


class DnsZoneSnapshot(BaseDTO):
    """A zone as read at one instant, with the token needed to write it back."""

    zone: str
    version: str = ""
    """Opaque concurrency token. Empty for providers without optimistic locking."""
    records: list[DnsRecord] = []
```

- [ ] **Step 5: Write the port**

Create `src/bapp_connectors/core/ports/dns.py`:

```python
"""DNS port — authoritative zone management, shared by hosting panels and DNS providers."""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Sequence
from typing import TYPE_CHECKING

from bapp_connectors.core.ports.base import BasePort

if TYPE_CHECKING:
    from bapp_connectors.core.dto import DnsRecord, DnsZone, DnsZoneSnapshot


class DnsPort(BasePort):
    """Contract for authoritative DNS zone management."""

    supported_record_types: tuple[str, ...] = ()
    """Record types this provider can WRITE. A UI offers only these."""

    @abstractmethod
    def list_zones(self) -> list[DnsZone]:
        """Zones this connection is authoritative for."""
        ...

    @abstractmethod
    def get_zone(self, zone: str) -> DnsZoneSnapshot:
        """Full snapshot. `version` and each record's `ref` are opaque round-trip tokens."""
        ...

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
        with optimistic concurrency MUST reject a stale version rather than
        overwrite; providers without it ignore the argument.

        `add` entries carry no `ref`; `edit` entries carry the `ref` they were read
        with; `remove` is a list of `ref`s.
        """
        ...
```

- [ ] **Step 6: Wire the exports**

`src/bapp_connectors/core/dto/__init__.py`:

```python
from .dns import DnsRecord, DnsZone, DnsZoneSnapshot
```

Add `"DnsRecord"`, `"DnsZone"`, `"DnsZoneSnapshot"` to `__all__` alphabetically (they sort next to the existing `DnsAllowlist` entries).

`src/bapp_connectors/core/ports/__init__.py`:

```python
from .dns import DnsPort
```

Add `"DnsPort"` to `__all__` after `"CourierPort"`.

- [ ] **Step 7: Run the tests**

Run: `uv run --extra dev pytest tests/dns/test_family.py -v`
Expected: PASS, 3 tests.

- [ ] **Step 8: Lint and commit**

```bash
uv run ruff check src/bapp_connectors/core tests/dns
git add src/bapp_connectors/core/types.py src/bapp_connectors/core/dto/dns.py \
        src/bapp_connectors/core/dto/__init__.py src/bapp_connectors/core/ports/dns.py \
        src/bapp_connectors/core/ports/__init__.py tests/dns
git commit -m "feat(core): familia dns — DnsPort cu ref si version opace"
```

---

### Task 3: Mailbox and panel-link capabilities

**Files:**
- Create: `src/bapp_connectors/core/capabilities/mailbox.py`
- Create: `src/bapp_connectors/core/capabilities/panel_link.py`
- Modify: `src/bapp_connectors/core/capabilities/__init__.py`
- Test: `tests/hosting/test_family.py` (append)

**Interfaces:**
- Consumes: `Mailbox`, `PanelLink` DTOs from Task 1.
- Produces: `MailboxCapability` with abstract `list_mailboxes`, `create_mailbox`, `delete_mailbox`, `set_mailbox_quota`, `set_mailbox_password`; `PanelLinkCapability` with abstract `get_panel_link`, `get_webmail_link`.

- [ ] **Step 1: Write the failing test**

Append to `tests/hosting/test_family.py`:

```python
def test_capabilities_are_plain_abcs():
    from bapp_connectors.core.capabilities import MailboxCapability, PanelLinkCapability

    assert issubclass(MailboxCapability, ABC)
    assert not issubclass(MailboxCapability, BasePort), "a capability is not a port"
    assert set(MailboxCapability.__abstractmethods__) == {
        "list_mailboxes",
        "create_mailbox",
        "delete_mailbox",
        "set_mailbox_quota",
        "set_mailbox_password",
    }
    assert set(PanelLinkCapability.__abstractmethods__) == {"get_panel_link", "get_webmail_link"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/hosting/test_family.py::test_capabilities_are_plain_abcs -v`
Expected: FAIL — `ImportError: cannot import name 'MailboxCapability'`

- [ ] **Step 3: Write the capabilities**

Create `src/bapp_connectors/core/capabilities/mailbox.py`:

```python
"""Mailbox capability — manage email accounts on a hosting plan."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bapp_connectors.core.dto import Mailbox


class MailboxCapability(ABC):
    """Adapter can list and manage the account's email boxes.

    Quotas are expressed in megabytes because that is what every panel's UI uses;
    the `Mailbox` DTO reports usage in bytes. `None` means unlimited on both sides.
    """

    @abstractmethod
    def list_mailboxes(self, domain: str | None = None) -> list[Mailbox]:
        """Every mailbox, optionally restricted to one domain."""
        ...

    @abstractmethod
    def create_mailbox(self, email: str, password: str, quota_mb: int | None = None) -> Mailbox:
        """Create a mailbox and return it as re-read from the provider."""
        ...

    @abstractmethod
    def delete_mailbox(self, email: str) -> bool:
        """Delete a mailbox. Returns True when the provider confirms."""
        ...

    @abstractmethod
    def set_mailbox_quota(self, email: str, quota_mb: int | None) -> Mailbox:
        """Change a mailbox quota; `None` sets unlimited."""
        ...

    @abstractmethod
    def set_mailbox_password(self, email: str, password: str) -> bool:
        """Change a mailbox password. Providers may reject weak passwords."""
        ...
```

Create `src/bapp_connectors/core/capabilities/panel_link.py`:

```python
"""Panel link capability — URLs that open the provider's own UI."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bapp_connectors.core.dto import PanelLink


class PanelLinkCapability(ABC):
    """Adapter can hand out links into the provider's web UI.

    `PanelLink.single_sign_on` says whether the link logs the user in. A provider
    that can only offer a login page returns False, and the caller must not present
    the link as one-click.
    """

    @abstractmethod
    def get_panel_link(self) -> PanelLink:
        """Link to the control panel itself."""
        ...

    @abstractmethod
    def get_webmail_link(self, email: str | None = None) -> PanelLink:
        """Link to webmail; for a specific mailbox when `email` is given."""
        ...
```

- [ ] **Step 4: Wire the exports**

In `src/bapp_connectors/core/capabilities/__init__.py`, add in alphabetical position among the `from .x import Y` lines:

```python
from .mailbox import MailboxCapability
from .panel_link import PanelLinkCapability
```

and add `"MailboxCapability"` and `"PanelLinkCapability"` to `__all__`.

- [ ] **Step 5: Run the tests**

Run: `uv run --extra dev pytest tests/hosting/test_family.py -v`
Expected: PASS, 5 tests.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check src/bapp_connectors/core tests/hosting
git add src/bapp_connectors/core/capabilities tests/hosting/test_family.py
git commit -m "feat(core): MailboxCapability si PanelLinkCapability"
```

---

### Task 4: Capability-based provider discovery in the registry

This is the mechanism a single cross-provider DNS UI rests on: BAPP must be able to ask "which providers can do DNS?" without knowing that one of them is filed under `hosting`.

**Files:**
- Modify: `src/bapp_connectors/core/registry.py:149` — `list_providers`
- Test: `tests/core/test_registry.py` (append)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `registry.list_providers(family: str | None = None, capability: type | None = None) -> list[ProviderManifest]`.

- [ ] **Step 1: Write the failing test**

Append to `tests/core/test_registry.py`:

```python
def test_list_providers_filters_by_capability():
    from bapp_connectors.core.capabilities import WebhookCapability
    from bapp_connectors.core.ports import ShopPort
    from bapp_connectors.core.registry import registry

    import bapp_connectors.providers.shop.woocommerce  # noqa: F401  (registers the adapter)

    shop_manifests = registry.list_providers(capability=ShopPort)
    assert shop_manifests, "at least one shop provider is registered"
    assert all(ShopPort in m.capabilities for m in shop_manifests)

    # family and capability compose
    both = registry.list_providers(family="shop", capability=WebhookCapability)
    assert all(m.family.value == "shop" and WebhookCapability in m.capabilities for m in both)

    # unfiltered behaviour is unchanged
    assert len(registry.list_providers()) >= len(shop_manifests)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/core/test_registry.py::test_list_providers_filters_by_capability -v`
Expected: FAIL — `TypeError: list_providers() got an unexpected keyword argument 'capability'`

- [ ] **Step 3: Extend `list_providers`**

Replace the body of `list_providers` in `src/bapp_connectors/core/registry.py` (currently at line 149) with:

```python
    def list_providers(
        self,
        family: str | None = None,
        capability: type | None = None,
    ) -> list[ProviderManifest]:
        """List registered provider manifests.

        `family` filters by the family a provider is filed under. `capability`
        filters by any port or capability interface the provider declares, which
        crosses families on purpose: a hosting provider that also speaks DNS is
        found by `capability=DnsPort` even though its family is `hosting`.
        """
        manifests = [cls.manifest for cls in self._adapters.values()]
        if family is not None:
            manifests = [m for m in manifests if m.family.value == family]
        if capability is not None:
            manifests = [m for m in manifests if capability in m.capabilities]
        return manifests
```

Keep whatever sorting or return shape the current implementation has if it differs — read the existing body first and preserve its behaviour for the no-argument case.

- [ ] **Step 4: Run the tests**

Run: `uv run --extra dev pytest tests/core/test_registry.py -v`
Expected: PASS, all tests including the pre-existing ones.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check src/bapp_connectors/core/registry.py tests/core/test_registry.py
git add src/bapp_connectors/core/registry.py tests/core/test_registry.py
git commit -m "feat(core): list_providers filtreaza si dupa capability, peste familii"
```

---

### Task 5: cPanel manifest, errors and raw models

**Files:**
- Create: `src/bapp_connectors/providers/hosting/__init__.py`
- Create: `src/bapp_connectors/providers/hosting/cpanel/errors.py`
- Create: `src/bapp_connectors/providers/hosting/cpanel/models.py`
- Create: `src/bapp_connectors/providers/hosting/cpanel/manifest.py`
- Test: `tests/hosting/cpanel/__init__.py`, `tests/hosting/cpanel/test_manifest.py`

**Interfaces:**
- Consumes: `HostingPort` (Task 1), `DnsPort` (Task 2), `MailboxCapability` + `PanelLinkCapability` (Task 3).
- Produces: `manifest` (a `ProviderManifest` named `cpanel`, family `HOSTING`); errors `CpanelError`, `CpanelFunctionUnavailableError`, `CpanelNotFoundError`, `CpanelWeakPasswordError`, `DnsZoneChangedError`, and the classifier `classify_uapi_error(message: str) -> ConnectorError`; pydantic models `UapiEnvelope`, `CpanelPop`, `CpanelResourceUsage`, `CpanelZoneLine`.

- [ ] **Step 1: Write the failing test**

Create `tests/hosting/cpanel/__init__.py` (empty) and `tests/hosting/cpanel/test_manifest.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/hosting/cpanel/test_manifest.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bapp_connectors.providers.hosting'`

- [ ] **Step 3: Create the package and the errors**

Create `src/bapp_connectors/providers/hosting/__init__.py`:

```python
"""Hosting providers — shared-hosting control panels (cPanel, ...)."""
```

Create `src/bapp_connectors/providers/hosting/cpanel/errors.py`:

```python
"""cPanel error mapping onto the framework hierarchy.

UAPI answers HTTP 200 even when a call fails, so every error arrives as a string
inside the envelope. These classes exist so callers can tell apart the failures a
user can fix from the ones they cannot.
"""

from __future__ import annotations

import re

from bapp_connectors.core.errors import AuthenticationError, ConnectorError, PermanentProviderError, ProviderError


class CpanelError(ProviderError):
    """Generic cPanel failure (transport or unexpected payload)."""


class CpanelFunctionUnavailableError(PermanentProviderError):
    """The server does not expose this UAPI module or function."""


class CpanelNotFoundError(PermanentProviderError):
    """The addressed object (mailbox, domain, zone) does not exist."""


class CpanelWeakPasswordError(PermanentProviderError):
    """The password was rejected by the server's strength policy.

    Recoverable by the user: pick a stronger password.
    """


class DnsZoneChangedError(PermanentProviderError):
    """The zone changed since it was read; the submitted serial is stale.

    Recoverable by the user: reload the zone and redo the edit.
    """


_FUNCTION_MISSING = re.compile(r"could not find the function", re.I)
_NOT_FOUND = re.compile(r"do not have an email account named|does not exist", re.I)
_WEAK_PASSWORD = re.compile(r"strength rating", re.I)
_STALE_SERIAL = re.compile(r"serial number .* does not match", re.I)
_DENIED = re.compile(r"access denied|permission denied|not authorized", re.I)


def classify_uapi_error(message: str) -> ConnectorError:
    """Map a UAPI error string onto the framework's error hierarchy."""
    if _STALE_SERIAL.search(message):
        return DnsZoneChangedError(message)
    if _WEAK_PASSWORD.search(message):
        return CpanelWeakPasswordError(message)
    if _FUNCTION_MISSING.search(message):
        return CpanelFunctionUnavailableError(message)
    if _NOT_FOUND.search(message):
        return CpanelNotFoundError(message)
    if _DENIED.search(message):
        return AuthenticationError(message)
    return CpanelError(message)
```

- [ ] **Step 4: Write the raw payload models**

Create `src/bapp_connectors/providers/hosting/cpanel/models.py`:

```python
"""Pydantic models for raw UAPI payloads. These are NOT DTOs."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class UapiEnvelope(BaseModel):
    """Every UAPI response, success or failure, arrives in this shape."""

    status: int = 0
    data: Any = None
    errors: list[str] | None = None
    warnings: list[str] | None = None
    messages: list[str] | None = None
    metadata: dict = {}

    @property
    def ok(self) -> bool:
        return self.status == 1

    @property
    def first_error(self) -> str:
        return (self.errors or ["cPanel reported a failure with no message"])[0]


class CpanelResourceUsage(BaseModel):
    """One entry of `ResourceUsage/get_usages`."""

    id: str
    usage: float | int | str | None = None
    maximum: float | int | str | None = None
    """None means unlimited."""
    formatter: str | None = None
    description: str | None = None


class CpanelPop(BaseModel):
    """One entry of `Email/list_pops_with_disk`.

    `diskused`/`diskquota` are MEGABYTES as strings; the underscore-prefixed pair
    is BYTES. Always read the underscore pair.
    """

    email: str
    login: str = ""
    domain: str = ""
    diskused: str | None = None
    diskquota: str | None = None
    raw_disk_used: str | None = Field(default=None, alias="_diskused")
    raw_disk_quota: str | None = Field(default=None, alias="_diskquota")
    diskusedpercent_float: float | None = None
    suspended_login: int = 0
    suspended_incoming: int = 0

    model_config = {"populate_by_name": True}


class CpanelZoneLine(BaseModel):
    """One line of `DNS/parse_zone`.

    `comment` and `control` lines carry `text_b64`. `record` lines carry structured
    fields and no `text_b64`.
    """

    type: str
    line_index: int
    text_b64: str | None = None
    record_type: str | None = None
    ttl: int | None = None
    dname_raw: str | None = None
    dname_b64: str | None = None
    data_b64: list[str] | None = None
```

- [ ] **Step 5: Write the manifest**

Create `src/bapp_connectors/providers/hosting/cpanel/manifest.py`:

```python
"""cPanel provider manifest — UAPI over HTTPS with an account API token."""

from bapp_connectors.core.capabilities import MailboxCapability, PanelLinkCapability
from bapp_connectors.core.manifest import (
    AuthConfig,
    CredentialField,
    ProviderManifest,
    RateLimitConfig,
    RetryConfig,
    SettingsConfig,
    SettingsField,
    WebhookConfig,
)
from bapp_connectors.core.ports import DnsPort, HostingPort
from bapp_connectors.core.types import AuthStrategy, BackoffStrategy, FieldType, ProviderFamily

manifest = ProviderManifest(
    name="cpanel",
    family=ProviderFamily.HOSTING,
    display_name="cPanel",
    description="cPanel hosting account managed through UAPI: domains, resources, mailboxes and DNS.",
    # Placeholder: the real host comes from per-connection credentials, as with pfSense and WooCommerce.
    base_url="https://cpanel.example.net:2083/",
    allow_multiple=True,
    auth=AuthConfig(
        strategy=AuthStrategy.CUSTOM,
        required_fields=[
            CredentialField(
                name="hostname",
                label="Server",
                role="endpoint",
                help_text="Hostname of the cPanel server, e.g. cpanel.example.net (no scheme, no port).",
            ),
            CredentialField(name="username", label="cPanel user"),
            CredentialField(
                name="token",
                label="API token",
                sensitive=True,
                help_text="Created in cPanel under Security > Manage API Tokens.",
            ),
        ],
    ),
    settings=SettingsConfig(
        fields=[
            SettingsField(name="port", label="Port", field_type=FieldType.INT, default=2083),
            SettingsField(name="webmail_port", label="Webmail port", field_type=FieldType.INT, default=2096),
            SettingsField(name="verify_ssl", label="Verify TLS certificate", field_type=FieldType.BOOL, default=True),
            SettingsField(name="timeout", label="Timeout (seconds)", field_type=FieldType.INT, default=30),
        ],
    ),
    capabilities=[HostingPort, DnsPort, MailboxCapability, PanelLinkCapability],
    rate_limit=RateLimitConfig(requests_per_second=5, burst=10),
    retry=RetryConfig(
        max_retries=3,
        backoff=BackoffStrategy.EXPONENTIAL,
        base_delay=1.0,
        max_delay=30.0,
        retryable_status_codes=[429, 500, 502, 503, 504],
        non_retryable_status_codes=[400, 401, 403, 404],
    ),
    webhooks=WebhookConfig(supported=False),
)
```

- [ ] **Step 6: Run the tests**

Run: `uv run --extra dev pytest tests/hosting/cpanel/test_manifest.py -v`
Expected: PASS, 5 tests.

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff check src/bapp_connectors/providers/hosting tests/hosting
git add src/bapp_connectors/providers/hosting tests/hosting/cpanel
git commit -m "feat(cpanel): manifest, erori si modele brute UAPI"
```

---

### Task 6: The UAPI transport client

**Files:**
- Create: `src/bapp_connectors/providers/hosting/cpanel/client.py`
- Test: `tests/hosting/cpanel/test_client.py`

**Interfaces:**
- Consumes: `UapiEnvelope`, `classify_uapi_error` (Task 5); `FakeHttpClient` from `tests/fake_http.py`.
- Produces: `CpanelUapiClient(http_client, timeout=30, verify_ssl=True)` with `call(module, function, method="GET", **params) -> Any` returning the unwrapped `data`.

- [ ] **Step 1: Write the failing test**

Create `tests/hosting/cpanel/test_client.py`:

```python
"""The envelope, not the HTTP status, decides success."""

import pytest

from bapp_connectors.providers.hosting.cpanel.client import CpanelUapiClient
from bapp_connectors.providers.hosting.cpanel.errors import (
    CpanelNotFoundError,
    CpanelWeakPasswordError,
    DnsZoneChangedError,
)
from tests.fake_http import FakeHttpClient


def make_client(response):
    http = FakeHttpClient()
    http.add(None, "execute/", response)
    return CpanelUapiClient(http_client=http), http


def test_unwraps_data_on_success():
    client, _ = make_client({"status": 1, "data": {"main_domain": "example.test"}, "errors": None})
    assert client.call("DomainInfo", "list_domains") == {"main_domain": "example.test"}


def test_status_zero_raises_even_though_http_was_200():
    # A failed UAPI call is HTTP 200 with status 0. Trusting the HTTP status turns
    # every failure into a silent success.
    client, _ = make_client(
        {"status": 0, "data": None, "errors": ['You do not have an email account named "ghost@example.test".']}
    )
    with pytest.raises(CpanelNotFoundError):
        client.call("Email", "delete_pop", email="ghost@example.test")


def test_weak_password_is_its_own_error():
    client, _ = make_client(
        {"status": 0, "data": None, "errors": ['The password that you entered has a strength rating of "0".']}
    )
    with pytest.raises(CpanelWeakPasswordError):
        client.call("Email", "passwd_pop", method="POST", email="a@example.test", password="x")


def test_stale_serial_is_its_own_error():
    client, _ = make_client(
        {
            "status": 0,
            "data": None,
            "errors": ["The given serial number (1) does not match the DNS zone's serial number (2026010101)."],
        }
    )
    with pytest.raises(DnsZoneChangedError):
        client.call("DNS", "mass_edit_zone", method="POST", zone="example.test", serial="1")


def test_reads_use_get_with_query_params():
    client, http = make_client({"status": 1, "data": [], "errors": None})
    client.call("Email", "list_pops_with_disk", domain="example.test")
    call = http.calls[-1]
    assert call.method == "GET"
    assert call.path == "execute/Email/list_pops_with_disk"
    assert call.kwargs["params"] == {"domain": "example.test"}


def test_writes_use_post_body_so_passwords_never_reach_the_url():
    client, http = make_client({"status": 1, "data": {}, "errors": None})
    client.call("Email", "add_pop", method="POST", email="a@example.test", password="hunter2")
    call = http.calls[-1]
    assert call.method == "POST"
    assert "params" not in call.kwargs or call.kwargs["params"] is None
    assert call.kwargs["data"] == {"email": "a@example.test", "password": "hunter2"}


def test_none_params_are_dropped():
    client, http = make_client({"status": 1, "data": [], "errors": None})
    client.call("Email", "list_pops_with_disk", domain=None)
    assert http.calls[-1].kwargs["params"] == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/hosting/cpanel/test_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named '...cpanel.client'`

- [ ] **Step 3: Write the client**

Create `src/bapp_connectors/providers/hosting/cpanel/client.py`:

```python
"""Raw UAPI transport. No business logic, no DTOs — only HTTP and the envelope."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from bapp_connectors.providers.hosting.cpanel.errors import CpanelError, classify_uapi_error
from bapp_connectors.providers.hosting.cpanel.models import UapiEnvelope

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient


class CpanelUapiClient:
    """Calls `/execute/{Module}/{function}` and unwraps the UAPI envelope.

    Reads go over GET with a query string; writes go over POST with a form body so
    that passwords never reach a URL, and therefore never reach an access log.
    """

    def __init__(self, http_client: ResilientHttpClient, timeout: int = 30, verify_ssl: bool = True):
        self.http = http_client
        self.timeout = timeout
        self.verify_ssl = verify_ssl

    def call(self, module: str, function: str, method: str = "GET", **params: Any) -> Any:
        """Call a UAPI function and return its `data`.

        Raises a mapped framework error when the envelope reports `status != 1`,
        regardless of the HTTP status — a failed UAPI call is still HTTP 200.
        """
        payload = {k: v for k, v in params.items() if v is not None}
        path = f"execute/{module}/{function}"

        kwargs: dict[str, Any] = {"timeout": self.timeout, "verify": self.verify_ssl}
        if method.upper() == "GET":
            kwargs["params"] = payload
        else:
            kwargs["data"] = payload

        raw = self.http.call(method.upper(), path, **kwargs)
        if not isinstance(raw, dict):
            raise CpanelError(f"Unexpected UAPI response type: {type(raw).__name__}")

        envelope = UapiEnvelope.model_validate(raw)
        if not envelope.ok:
            raise classify_uapi_error(envelope.first_error)
        return envelope.data
```

- [ ] **Step 4: Run the tests**

Run: `uv run --extra dev pytest tests/hosting/cpanel/test_client.py -v`
Expected: PASS, 7 tests.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check src/bapp_connectors/providers/hosting tests/hosting
git add src/bapp_connectors/providers/hosting/cpanel/client.py tests/hosting/cpanel/test_client.py
git commit -m "feat(cpanel): transport UAPI — envelope peste HTTP 200, scrieri pe POST"
```

---

### Task 7: Hosting mappers — account, resources, domains, SSL

**Files:**
- Create: `src/bapp_connectors/providers/hosting/cpanel/mappers.py`
- Test: `tests/hosting/cpanel/conftest.py`, `tests/hosting/cpanel/test_mappers.py`

**Interfaces:**
- Consumes: DTOs from Task 1, models from Task 5, fixtures committed in `b793d5d`.
- Produces: `map_usages(raw) -> list[HostingResource]`, `map_domains(raw, certs) -> list[HostingDomain]`, `map_account(user_info, hostname, primary_domain) -> HostingAccount`.

- [ ] **Step 1: Write the fixture loader**

Create `tests/hosting/cpanel/conftest.py`:

```python
"""Fixture loader for the anonymized UAPI captures."""

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str):
    """Return the `data` payload of a captured UAPI envelope."""
    return json.loads((FIXTURES / f"{name}.json").read_text())["data"]


@pytest.fixture
def usages_raw():
    return load("usages")


@pytest.fixture
def domains_raw():
    return load("domains_data")


@pytest.fixture
def ssl_raw():
    return load("ssl_hosts")


@pytest.fixture
def pops_raw():
    return load("pops_disk")


@pytest.fixture
def zone_raw():
    return load("zone")
```

- [ ] **Step 2: Write the failing test**

Create `tests/hosting/cpanel/test_mappers.py`:

```python
"""Mapper tests. Every case here is one that fails silently if mapped wrong."""

from datetime import UTC
from decimal import Decimal

from bapp_connectors.providers.hosting.cpanel.mappers import map_account, map_domains, map_usages


def test_byte_formatted_resources_carry_the_bytes_unit(usages_raw):
    by_key = {r.key: r for r in map_usages(usages_raw)}
    disk = by_key["disk_usage"]
    assert disk.unit == "bytes"
    assert disk.used == Decimal("1305116672")
    assert disk.limit == Decimal("128849018880")
    assert by_key["email_accounts"].unit == "count"


def test_null_maximum_means_unlimited_not_zero(usages_raw):
    by_key = {r.key: r for r in map_usages(usages_raw)}
    # `forwarders` and `autoresponders` really do come back with maximum: null.
    assert by_key["forwarders"].limit is None
    assert by_key["autoresponders"].limit is None


def test_percent_is_computed_only_when_a_limit_exists(usages_raw):
    by_key = {r.key: r for r in map_usages(usages_raw)}
    assert by_key["forwarders"].percent is None
    assert by_key["disk_usage"].percent is not None
    assert 0 <= by_key["disk_usage"].percent <= 100


def test_main_domain_is_mapped_with_its_kind(domains_raw):
    domains = map_domains(domains_raw, [])
    assert len(domains) == 1
    main = domains[0]
    assert main.domain == "example.test"
    assert main.kind == "main"
    assert main.document_root == "/home/exampleuser/public_html"
    assert main.ssl_expires_at is None, "no certs passed in"


def test_ssl_is_merged_onto_the_matching_domain(domains_raw, ssl_raw):
    main = map_domains(domains_raw, ssl_raw)[0]
    assert main.ssl_expires_at is not None
    assert main.ssl_expires_at.tzinfo is not None, "not_after is a unix int; make it aware"
    assert main.ssl_expires_at.tzinfo is UTC
    assert main.ssl_auto is True
    assert main.ssl_issuer


def test_account_takes_the_hostname_from_the_connection():
    info = {"user": "exampleuser", "maximum_mail_accounts": 1000, "plan": "starter"}
    acc = map_account(info, hostname="cpanel.example.net", primary_domain="example.test")
    assert acc.username == "exampleuser"
    assert acc.primary_domain == "example.test"
    assert acc.server_hostname == "cpanel.example.net"
    assert acc.plan == "starter"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/hosting/cpanel/test_mappers.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named '...cpanel.mappers'`

- [ ] **Step 4: Write the mappers**

Create `src/bapp_connectors/providers/hosting/cpanel/mappers.py`:

```python
"""Conversions between raw UAPI payloads and framework DTOs."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from bapp_connectors.core.dto import HostingAccount, HostingDomain, HostingResource

_DOMAIN_KINDS = {
    "main_domain": "main",
    "addon_domains": "addon",
    "parked_domains": "parked",
    "sub_domains": "sub",
}


def _decimal(value: Any) -> Decimal | None:
    """Parse a UAPI numeric that may be a string, a number, None, or 'unlimited'."""
    if value is None or value == "" or str(value).lower() == "unlimited":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def map_usages(raw: list[dict]) -> list[HostingResource]:
    """`ResourceUsage/get_usages` to normalized resources.

    `maximum: null` means unlimited and must stay None — mapping it to 0 turns an
    unlimited resource into a full one.
    """
    resources = []
    for item in raw or []:
        used = _decimal(item.get("usage"))
        limit = _decimal(item.get("maximum"))
        percent = None
        if used is not None and limit is not None and limit > 0:
            percent = float(used / limit * 100)
        resources.append(
            HostingResource(
                key=str(item.get("id", "")),
                label=str(item.get("description") or ""),
                used=used,
                limit=limit,
                unit="bytes" if item.get("formatter") == "format_bytes" else "count",
                percent=percent,
            )
        )
    return resources


def _cert_index(certs: list[dict]) -> dict[str, dict]:
    """Map every FQDN a certificate covers to that certificate."""
    index: dict[str, dict] = {}
    for host in certs or []:
        certificate = host.get("certificate") or {}
        names = set(host.get("fqdns") or []) | set(host.get("domains") or []) | set(certificate.get("domains") or [])
        for name in names:
            index.setdefault(name, certificate)
    return index


def map_domains(raw: dict, certs: list[dict]) -> list[HostingDomain]:
    """`DomainInfo/domains_data` plus `SSL/installed_hosts` to domains with SSL state."""
    index = _cert_index(certs)
    domains: list[HostingDomain] = []

    for key, kind in _DOMAIN_KINDS.items():
        entries = raw.get(key) or []
        if isinstance(entries, dict):  # main_domain is a single object
            entries = [entries]
        for entry in entries:
            if isinstance(entry, str):  # some panels return bare names
                entry = {"domain": entry}
            name = entry.get("domain") or entry.get("servername") or ""
            certificate = index.get(name) or {}
            not_after = certificate.get("not_after")
            domains.append(
                HostingDomain(
                    domain=name,
                    kind=kind,
                    document_root=entry.get("documentroot") or "",
                    parent_domain=entry.get("parent_domain") or "",
                    ssl_expires_at=datetime.fromtimestamp(int(not_after), tz=UTC) if not_after else None,
                    ssl_issuer=str(certificate.get("issuer.organizationName") or ""),
                    ssl_auto=bool(int(certificate.get("is_autossl") or 0)),
                    extra={"ip": entry.get("ip", ""), "serveralias": entry.get("serveralias", "")},
                )
            )
    return domains


def map_account(user_info: dict, hostname: str, primary_domain: str) -> HostingAccount:
    """`Variables/get_user_information` to the account identity."""
    return HostingAccount(
        username=str(user_info.get("user") or ""),
        primary_domain=primary_domain,
        plan=str(user_info.get("plan") or ""),
        server_hostname=hostname,
        panel_version=str(user_info.get("cpanel_version") or ""),
        extra={"maximum_mail_accounts": user_info.get("maximum_mail_accounts")},
    )
```

- [ ] **Step 5: Run the tests**

Run: `uv run --extra dev pytest tests/hosting/cpanel/test_mappers.py -v`
Expected: PASS, 6 tests.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check src/bapp_connectors/providers/hosting tests/hosting
git add src/bapp_connectors/providers/hosting/cpanel/mappers.py tests/hosting/cpanel/conftest.py \
        tests/hosting/cpanel/test_mappers.py
git commit -m "feat(cpanel): mapari pentru cont, resurse si domenii cu SSL"
```

---

### Task 8: Mailbox and DNS mappers

The DNS half is the part most likely to be got wrong: `parse_zone` returns base64 in a positional array whose meaning depends on the record type, and `mass_edit_zone` wants that array rebuilt.

**Files:**
- Modify: `src/bapp_connectors/providers/hosting/cpanel/mappers.py` (append)
- Test: `tests/hosting/cpanel/test_mappers.py` (append)

**Interfaces:**
- Consumes: `Mailbox`, `DnsRecord`, `DnsZoneSnapshot` DTOs; `CpanelZoneLine`.
- Produces: `map_mailboxes(raw) -> list[Mailbox]`, `map_zone(zone, raw_lines) -> DnsZoneSnapshot`, `record_to_payload(record) -> dict`.

- [ ] **Step 1: Write the failing test**

Append to `tests/hosting/cpanel/test_mappers.py`:

```python
from bapp_connectors.core.dto import DnsRecord
from bapp_connectors.providers.hosting.cpanel.mappers import map_mailboxes, map_zone, record_to_payload


def test_mailbox_quota_comes_from_the_byte_pair_not_the_megabyte_pair(pops_raw):
    # diskquota is "1024.00" MB while _diskquota is "1073741824" bytes. Reading the
    # wrong one is a factor-1048576 error that still looks plausible in a UI.
    boxes = {b.email: b for b in map_mailboxes(pops_raw)}
    admin = boxes["admin@example.test"]
    assert admin.disk_quota == Decimal("1073741824")
    assert admin.disk_used == Decimal("903985792")
    assert admin.percent_used is not None and admin.percent_used > 80


def test_mailbox_suspension_flags_become_booleans(pops_raw):
    box = map_mailboxes(pops_raw)[0]
    assert box.suspended_login is False
    assert box.suspended_incoming is False


def test_zone_skips_comments_and_controls_and_keeps_the_serial(zone_raw):
    snapshot = map_zone("example.test", zone_raw)
    assert snapshot.zone == "example.test"
    assert snapshot.version, "the SOA serial is the write token"
    assert all(r.record_type not in ("", None) for r in snapshot.records)
    assert not any(r.record_type == "SOA" for r in snapshot.records), "SOA is not an editable record"


def test_records_are_decoded_and_carry_their_line_index_as_ref(zone_raw):
    records = map_zone("example.test", zone_raw).records
    a_record = next(r for r in records if r.record_type == "A")
    assert a_record.name == "example.test."
    assert a_record.value == "192.0.2.10"
    assert a_record.ref.isdigit(), "cPanel's ref is the line index"
    assert a_record.ttl == 14400


def test_mx_lifts_its_priority_out_of_the_positional_array(zone_raw):
    mx = next(r for r in map_zone("example.test", zone_raw).records if r.record_type == "MX")
    assert mx.priority == 0
    assert mx.value == "example.test."


def test_srv_keeps_weight_and_port_in_extra(zone_raw):
    srv = next(r for r in map_zone("example.test", zone_raw).records if r.record_type == "SRV")
    assert srv.priority == 0
    assert srv.extra["weight"] == 0
    assert srv.extra["port"] == 2080
    assert srv.value == "example.test."


def test_payload_data_is_always_an_array():
    # The server rejects a scalar: '"data" must be an array.'
    payload = record_to_payload(DnsRecord(name="www", record_type="A", ttl=300, value="192.0.2.11"))
    assert payload == {"dname": "www", "ttl": 300, "record_type": "A", "data": ["192.0.2.11"]}


def test_payload_rebuilds_mx_positionally():
    payload = record_to_payload(
        DnsRecord(name="example.test.", record_type="MX", ttl=300, value="mail.example.test.", priority=10)
    )
    assert payload["data"] == ["10", "mail.example.test."]


def test_payload_for_an_edit_carries_the_line_index():
    payload = record_to_payload(
        DnsRecord(ref="13", name="www", record_type="A", ttl=300, value="192.0.2.11"), include_ref=True
    )
    assert payload["line_index"] == 13
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/hosting/cpanel/test_mappers.py -v`
Expected: FAIL — `ImportError: cannot import name 'map_mailboxes'`

- [ ] **Step 3: Append the mappers**

Add to the imports at the top of `src/bapp_connectors/providers/hosting/cpanel/mappers.py`:

```python
import base64

from bapp_connectors.core.dto import DnsRecord, DnsZoneSnapshot, Mailbox
from bapp_connectors.providers.hosting.cpanel.models import CpanelPop, CpanelZoneLine
```

Then append:

```python
def map_mailboxes(raw: list[dict]) -> list[Mailbox]:
    """`Email/list_pops_with_disk` to mailboxes, in bytes."""
    boxes = []
    for item in raw or []:
        pop = CpanelPop.model_validate(item)
        boxes.append(
            Mailbox(
                email=pop.email,
                login=pop.login or pop.email,
                domain=pop.domain,
                disk_used=_decimal(pop.raw_disk_used),
                disk_quota=_decimal(pop.raw_disk_quota),
                percent_used=pop.diskusedpercent_float,
                suspended_login=bool(pop.suspended_login),
                suspended_incoming=bool(pop.suspended_incoming),
            )
        )
    return boxes


def _b64(value: str | None) -> str:
    if not value:
        return ""
    return base64.b64decode(value).decode("utf-8", errors="replace")


# Record types whose leading positional fields are numbers rather than part of the value.
_LEADING_NUMBERS = {"MX": ("priority",), "SRV": ("priority", "weight", "port"), "CAA": ("flags",)}

# SOA and NS are readable but `mass_edit_zone` refuses to write them, so they are
# not offered as editable records.
_NOT_EDITABLE = {"SOA", "NS"}


def map_zone(zone: str, raw_lines: list[dict]) -> DnsZoneSnapshot:
    """`DNS/parse_zone` to a snapshot. The SOA serial becomes the write token."""
    version = ""
    records: list[DnsRecord] = []

    for item in raw_lines or []:
        line = CpanelZoneLine.model_validate(item)
        if line.type != "record" or not line.record_type:
            continue

        fields = [_b64(chunk) for chunk in (line.data_b64 or [])]

        if line.record_type == "SOA":
            # SOA data is: primary, hostmaster, serial, refresh, retry, expire, minimum
            if len(fields) >= 3:
                version = fields[2]
            continue
        if line.record_type in _NOT_EDITABLE:
            continue

        priority = None
        extra: dict = {}
        leading = _LEADING_NUMBERS.get(line.record_type, ())
        if leading and len(fields) > len(leading):
            for name, raw_value in zip(leading, fields, strict=False):
                try:
                    parsed = int(raw_value)
                except ValueError:
                    parsed = raw_value
                if name == "priority":
                    priority = parsed
                else:
                    extra[name] = parsed
            fields = fields[len(leading) :]

        records.append(
            DnsRecord(
                ref=str(line.line_index),
                name=_b64(line.dname_b64) or (line.dname_raw or ""),
                record_type=line.record_type,
                ttl=line.ttl or 0,
                value=" ".join(fields),
                priority=priority,
                extra=extra,
            )
        )

    return DnsZoneSnapshot(zone=zone, version=version, records=records)


def record_to_payload(record: DnsRecord, include_ref: bool = False) -> dict:
    """A `DnsRecord` to the object `mass_edit_zone` expects.

    `data` is always an array — the server rejects a scalar outright.
    """
    data: list[str] = []
    if record.priority is not None:
        data.append(str(record.priority))
    if record.record_type == "SRV":
        data.append(str(record.extra.get("weight", 0)))
        data.append(str(record.extra.get("port", 0)))
    data.extend(part for part in record.value.split(" ") if part)

    payload: dict = {
        "dname": record.name,
        "ttl": record.ttl,
        "record_type": record.record_type,
        "data": data,
    }
    if include_ref:
        payload["line_index"] = int(record.ref)
    return payload
```

- [ ] **Step 4: Run the tests**

Run: `uv run --extra dev pytest tests/hosting/cpanel/test_mappers.py -v`
Expected: PASS, 15 tests.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check src/bapp_connectors/providers/hosting tests/hosting
git add src/bapp_connectors/providers/hosting/cpanel/mappers.py tests/hosting/cpanel/test_mappers.py
git commit -m "feat(cpanel): mapari pentru casute si zona DNS, cu data pozitional"
```

---

### Task 9: The adapter — hosting, mailboxes and panel links

**Files:**
- Create: `src/bapp_connectors/providers/hosting/cpanel/adapter.py`
- Create: `tests/hosting/contract.py`
- Test: `tests/hosting/cpanel/test_adapter.py`

**Interfaces:**
- Consumes: everything from Tasks 1, 3, 5, 6, 7, 8.
- Produces: `CpanelAdapter(credentials, http_client=None, config=None, **kwargs)` implementing `HostingPort`, `MailboxCapability`, `PanelLinkCapability` (DnsPort lands in Task 10); `HostingContractTests`. The package `__init__.py` and registry registration land in Task 10, once the class satisfies every interface the manifest declares.

- [ ] **Step 1: Write the reusable contract tests**

Create `tests/hosting/contract.py`:

```python
"""Reusable contract tests every hosting provider must pass."""

import pytest

from bapp_connectors.core.dto import ConnectionTestResult, HostingAccount, HostingDomain, HostingResource
from bapp_connectors.core.ports import HostingPort


class HostingContractTests:
    @pytest.fixture
    def adapter(self) -> HostingPort:
        raise NotImplementedError("provider tests must supply an adapter fixture")

    def test_is_hosting_port(self, adapter):
        assert isinstance(adapter, HostingPort)

    def test_validate_credentials(self, adapter):
        assert adapter.validate_credentials() is True

    def test_test_connection(self, adapter):
        result = adapter.test_connection()
        assert isinstance(result, ConnectionTestResult)
        assert result.success is True

    def test_get_account(self, adapter):
        account = adapter.get_account()
        assert isinstance(account, HostingAccount)
        assert account.username

    def test_get_usage(self, adapter):
        usage = adapter.get_usage()
        assert isinstance(usage, list)
        assert all(isinstance(r, HostingResource) and r.key for r in usage)

    def test_list_domains(self, adapter):
        domains = adapter.list_domains()
        assert isinstance(domains, list)
        assert all(isinstance(d, HostingDomain) and d.domain and d.kind for d in domains)
```

- [ ] **Step 2: Write the failing adapter test**

Create `tests/hosting/cpanel/test_adapter.py`:

```python
"""Adapter tests against canned UAPI responses."""

import json
from pathlib import Path

import pytest

from bapp_connectors.core.capabilities import MailboxCapability, PanelLinkCapability
from bapp_connectors.core.ports import HostingPort
from bapp_connectors.providers.hosting.cpanel.adapter import CpanelAdapter
from tests.fake_http import FakeHttpClient
from tests.hosting.contract import HostingContractTests

FIXTURES = Path(__file__).parent / "fixtures"

CREDENTIALS = {"hostname": "cpanel.example.net", "username": "exampleuser", "token": "not-a-real-token"}


def envelope(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def build_http() -> FakeHttpClient:
    http = FakeHttpClient()
    http.add("GET", "DomainInfo/domains_data", envelope("domains_data"))
    http.add("GET", "SSL/installed_hosts", envelope("ssl_hosts"))
    http.add("GET", "ResourceUsage/get_usages", envelope("usages"))
    http.add("GET", "Quota/get_quota_info", envelope("quota"))
    http.add("GET", "Email/list_pops_with_disk", envelope("pops_disk"))
    http.add("GET", "DNS/parse_zone", envelope("zone"))
    http.add(
        "GET",
        "Variables/get_user_information",
        {"status": 1, "errors": None, "data": {"user": "exampleuser", "plan": "starter"}},
    )
    http.add(
        "GET",
        "Session/create_webmail_session_for_self",
        {"status": 1, "errors": None, "data": {"session": "exampleuser:abc:TOKEN,deadbeef", "token": "/cpsess1"}},
    )
    http.add("POST", "Email/add_pop", {"status": 1, "errors": None, "data": {}})
    http.add("POST", "Email/delete_pop", {"status": 1, "errors": None, "data": {}})
    return http


@pytest.fixture
def http():
    return build_http()


@pytest.fixture
def adapter(http):
    return CpanelAdapter(credentials=CREDENTIALS, http_client=http, config={})


class TestCpanelHostingContract(HostingContractTests):
    @pytest.fixture
    def adapter(self, http):
        return CpanelAdapter(credentials=CREDENTIALS, http_client=http, config={})


def test_declares_the_interfaces_its_manifest_claims(adapter):
    for interface in (HostingPort, MailboxCapability, PanelLinkCapability):
        assert isinstance(adapter, interface)
        assert adapter.supports(interface)


def test_list_domains_merges_ssl(adapter):
    main = adapter.list_domains()[0]
    assert main.domain == "example.test"
    assert main.ssl_expires_at is not None


def test_list_mailboxes_returns_bytes(adapter):
    boxes = {b.email: b for b in adapter.list_mailboxes()}
    assert boxes["admin@example.test"].disk_quota == 1073741824


def test_panel_link_is_honest_about_not_being_single_sign_on(adapter):
    link = adapter.get_panel_link()
    assert link.kind == "panel"
    assert link.url == "https://cpanel.example.net:2083/"
    assert link.single_sign_on is False


def test_webmail_link_is_single_sign_on(adapter):
    link = adapter.get_webmail_link()
    assert link.kind == "webmail"
    assert link.single_sign_on is True
    assert link.url.startswith("https://cpanel.example.net:2096/login/?session=")


def test_create_mailbox_posts_and_rereads(adapter, http):
    adapter.create_mailbox("new@example.test", "a-strong-passphrase", quota_mb=512)
    post = next(c for c in http.calls if c.method == "POST")
    assert post.kwargs["data"]["email"] == "new"
    assert post.kwargs["data"]["domain"] == "example.test"
    assert post.kwargs["data"]["quota"] == 512


def test_create_mailbox_with_no_quota_sends_unlimited(adapter, http):
    adapter.create_mailbox("new@example.test", "a-strong-passphrase")
    post = next(c for c in http.calls if c.method == "POST")
    assert post.kwargs["data"]["quota"] == 0, "cPanel spells unlimited as 0"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/hosting/cpanel/test_adapter.py -v`
Expected: FAIL — `ImportError: cannot import name 'CpanelAdapter'`

- [ ] **Step 4: Write the adapter**

Create `src/bapp_connectors/providers/hosting/cpanel/adapter.py`:

```python
"""cPanel adapter — HostingPort, mailboxes and panel links. DNS lives in the same class."""

from __future__ import annotations

from urllib.parse import quote

from bapp_connectors.core.capabilities import MailboxCapability, PanelLinkCapability
from bapp_connectors.core.dto import ConnectionTestResult, HostingAccount, HostingDomain, HostingResource, Mailbox, PanelLink
from bapp_connectors.core.errors import ConnectorError
from bapp_connectors.core.http import ResilientHttpClient
from bapp_connectors.core.http.auth import TokenAuth
from bapp_connectors.core.ports import HostingPort
from bapp_connectors.core.http.rate_limit import RateLimiter
from bapp_connectors.core.http.retry import RetryPolicy
from bapp_connectors.providers.hosting.cpanel.client import CpanelUapiClient
from bapp_connectors.providers.hosting.cpanel.manifest import manifest
from bapp_connectors.providers.hosting.cpanel.mappers import (
    map_account,
    map_domains,
    map_mailboxes,
    map_usages,
)


class CpanelAdapter(HostingPort, MailboxCapability, PanelLinkCapability):
    """A single cPanel account, reached over UAPI with an account API token."""

    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs):
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
```

- [ ] **Step 5: Run the tests**

Run: `uv run --extra dev pytest tests/hosting -v`
Expected: PASS — 6 contract tests plus 7 adapter tests plus everything from earlier tasks.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check src/bapp_connectors/providers/hosting tests/hosting
git add src/bapp_connectors/providers/hosting/cpanel/adapter.py \
        tests/hosting/contract.py tests/hosting/cpanel/test_adapter.py
git commit -m "feat(cpanel): adapter cu HostingPort, casute si link-uri de panou"
```

---

### Task 10: The adapter's DNS half

**Files:**
- Modify: `src/bapp_connectors/providers/hosting/cpanel/adapter.py`
- Create: `src/bapp_connectors/providers/hosting/cpanel/__init__.py`
- Create: `tests/dns/contract.py`
- Test: `tests/hosting/cpanel/test_adapter.py` (append)

**Interfaces:**
- Consumes: `DnsPort` (Task 2), `map_zone` / `record_to_payload` (Task 8).
- Produces: `CpanelAdapter` additionally implementing `DnsPort`; the package `__init__.py` that registers it as `hosting:cpanel`; `DnsContractTests`.

- [ ] **Step 1: Write the reusable DNS contract tests**

Create `tests/dns/contract.py`:

```python
"""Reusable contract tests every DNS provider must pass.

A provider satisfies this whether DNS is its whole purpose (Cloudflare) or one
capability among many (cPanel).
"""

import pytest

from bapp_connectors.core.dto import DnsRecord, DnsZone, DnsZoneSnapshot
from bapp_connectors.core.ports import DnsPort


class DnsContractTests:
    @pytest.fixture
    def dns_adapter(self) -> DnsPort:
        raise NotImplementedError("provider tests must supply a dns_adapter fixture")

    @pytest.fixture
    def zone_name(self) -> str:
        raise NotImplementedError("provider tests must supply a zone_name fixture")

    def test_is_dns_port(self, dns_adapter):
        assert isinstance(dns_adapter, DnsPort)

    def test_declares_writable_record_types(self, dns_adapter):
        types = dns_adapter.supported_record_types
        assert isinstance(types, tuple) and types, "a writable provider names its record types"
        assert "A" in types

    def test_list_zones(self, dns_adapter):
        zones = dns_adapter.list_zones()
        assert isinstance(zones, list)
        assert all(isinstance(z, DnsZone) and z.zone for z in zones)

    def test_get_zone_returns_a_snapshot(self, dns_adapter, zone_name):
        snapshot = dns_adapter.get_zone(zone_name)
        assert isinstance(snapshot, DnsZoneSnapshot)
        assert snapshot.zone == zone_name
        assert all(isinstance(r, DnsRecord) for r in snapshot.records)
        assert all(r.ref for r in snapshot.records), "a read record always has a ref"
```

- [ ] **Step 2: Write the failing test**

Append to `tests/hosting/cpanel/test_adapter.py`:

```python
from bapp_connectors.core.dto import DnsRecord
from bapp_connectors.core.errors import ValidationError
from bapp_connectors.core.ports import DnsPort
from tests.dns.contract import DnsContractTests


class TestCpanelDnsContract(DnsContractTests):
    @pytest.fixture
    def dns_adapter(self, http):
        return CpanelAdapter(credentials=CREDENTIALS, http_client=http, config={})

    @pytest.fixture
    def zone_name(self):
        return "example.test"


def test_supported_record_types_match_what_the_server_accepts(adapter):
    assert adapter.supported_record_types == (
        "A", "AAAA", "ALIAS", "CAA", "CNAME", "HTTPS", "MX", "SRV", "SVCB", "TXT",
    )
    assert "NS" not in adapter.supported_record_types, "mass_edit_zone refuses NS"


def test_apply_changes_sends_the_serial_as_the_guard(adapter, http):
    http.add("POST", "DNS/mass_edit_zone", {"status": 1, "errors": None, "data": {}})
    snapshot = adapter.get_zone("example.test")
    adapter.apply_changes(
        "example.test",
        snapshot.version,
        add=[DnsRecord(name="www", record_type="A", ttl=300, value="192.0.2.11")],
    )
    post = next(c for c in http.calls if c.method == "POST" and "mass_edit_zone" in c.path)
    assert post.kwargs["data"]["serial"] == snapshot.version
    assert post.kwargs["data"]["zone"] == "example.test"


def test_apply_changes_rejects_an_unsupported_record_type_before_calling_out(adapter, http):
    before = len(http.calls)
    with pytest.raises(ValidationError, match="NS"):
        adapter.apply_changes(
            "example.test", "2026010101", add=[DnsRecord(name="@", record_type="NS", ttl=300, value="ns1.example.net.")]
        )
    assert len(http.calls) == before, "no HTTP call for a type the provider cannot write"


def test_apply_changes_refuses_an_empty_changeset(adapter):
    with pytest.raises(ValidationError):
        adapter.apply_changes("example.test", "2026010101")


def test_remove_sends_line_indexes(adapter, http):
    http.add("POST", "DNS/mass_edit_zone", {"status": 1, "errors": None, "data": {}})
    adapter.apply_changes("example.test", "2026010101", remove=["13"])
    post = next(c for c in http.calls if c.method == "POST" and "mass_edit_zone" in c.path)
    assert post.kwargs["data"]["remove"] == ["13"]
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/hosting/cpanel/test_adapter.py -v`
Expected: FAIL — `CpanelAdapter` is not a `DnsPort`.

- [ ] **Step 4: Extend the adapter**

In `src/bapp_connectors/providers/hosting/cpanel/adapter.py`, extend the imports:

```python
import json
from collections.abc import Sequence

from bapp_connectors.core.dto import DnsRecord, DnsZone, DnsZoneSnapshot
from bapp_connectors.core.errors import ValidationError
from bapp_connectors.core.ports import DnsPort
from bapp_connectors.providers.hosting.cpanel.mappers import map_zone, record_to_payload
```

Change the class declaration to:

```python
class CpanelAdapter(HostingPort, DnsPort, MailboxCapability, PanelLinkCapability):
```

Add the class attribute just under `manifest = manifest`:

```python
    # Exactly what `DNS/mass_edit_zone` accepts. SOA and NS are readable but not writable.
    supported_record_types = ("A", "AAAA", "ALIAS", "CAA", "CNAME", "HTTPS", "MX", "SRV", "SVCB", "TXT")
```

Append the DNS methods:

```python
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
```

- [ ] **Step 5: Register the provider**

Create `src/bapp_connectors/providers/hosting/cpanel/__init__.py`:

```python
"""cPanel hosting provider (UAPI)."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.hosting.cpanel.adapter import CpanelAdapter
from bapp_connectors.providers.hosting.cpanel.manifest import manifest

__all__ = ["CpanelAdapter", "manifest"]

# Auto-register with the global registry
registry.register(CpanelAdapter)
```

`registry.register` checks `issubclass` for every interface in `manifest.capabilities`,
so this import fails loudly if the class does not satisfy all four. That is why it
lands here rather than in Task 9.

Append to `tests/hosting/cpanel/test_adapter.py`:

```python
def test_registered_under_hosting_but_discoverable_as_a_dns_provider():
    import bapp_connectors.providers.hosting.cpanel  # noqa: F401  (registers the adapter)
    from bapp_connectors.core.registry import registry

    assert registry.is_registered("hosting", "cpanel")
    names = {m.name for m in registry.list_providers(capability=DnsPort)}
    assert "cpanel" in names, "a hosting provider must be findable by its DNS port"
```

- [ ] **Step 6: Run the tests**

Run: `uv run --extra dev pytest tests/hosting tests/dns -v`
Expected: PASS — including the four `DnsContractTests` and the six new adapter tests.

- [ ] **Step 7: Run the whole suite to catch regressions**

Run: `uv run --extra dev pytest -q`
Expected: no new failures compared to the baseline you recorded before starting.

- [ ] **Step 8: Lint and commit**

```bash
uv run ruff check src tests
git add src/bapp_connectors/providers/hosting/cpanel/adapter.py \
        src/bapp_connectors/providers/hosting/cpanel/__init__.py tests/dns/contract.py \
        tests/hosting/cpanel/test_adapter.py
git commit -m "feat(cpanel): DnsPort — zona citita si scrisa cu garda pe serial"
```

---

### Task 11: Integration test, docs and release

**Files:**
- Create: `tests/hosting/cpanel/test_integration.py`
- Modify: `scripts/update_readme.py` — family label for `dns`
- Modify: `CLAUDE.md` — families table
- Modify: `docs/PROVIDER_GUIDE.md` — multi-port note
- Modify: `pyproject.toml` — version

**Interfaces:**
- Consumes: `CpanelAdapter`.
- Produces: no importable API; this task closes the release.

- [ ] **Step 1: Write the gated integration test**

Create `tests/hosting/cpanel/test_integration.py`:

```python
"""Live cPanel tests. Read-only unless CPANEL_ALLOW_WRITES=1.

The account these run against is a live production account. Writes are gated
separately and are meant for a disposable account, never a real one.
"""

import os

import pytest

from bapp_connectors.core.dto import HostingAccount
from bapp_connectors.providers.hosting.cpanel import CpanelAdapter

CREDENTIALS = {
    "hostname": os.getenv("CPANEL_HOSTNAME", ""),
    "username": os.getenv("CPANEL_USERNAME", ""),
    "token": os.getenv("CPANEL_TOKEN", ""),
}

skip_unless_cpanel = pytest.mark.skipif(
    not all(CREDENTIALS.values()),
    reason="set CPANEL_HOSTNAME, CPANEL_USERNAME and CPANEL_TOKEN to run",
)
skip_unless_writes = pytest.mark.skipif(
    os.getenv("CPANEL_ALLOW_WRITES") != "1",
    reason="set CPANEL_ALLOW_WRITES=1 on a DISPOSABLE account to run write tests",
)

pytestmark = [pytest.mark.integration, skip_unless_cpanel]


@pytest.fixture
def adapter():
    return CpanelAdapter(credentials=CREDENTIALS, config={})


def test_connection(adapter):
    assert adapter.test_connection().success is True


def test_account(adapter):
    account = adapter.get_account()
    assert isinstance(account, HostingAccount)
    assert account.username == CREDENTIALS["username"]


def test_usage_reports_disk(adapter):
    keys = {r.key for r in adapter.get_usage()}
    assert "disk_usage" in keys


def test_domains_and_zone_round_trip(adapter):
    domains = adapter.list_domains()
    assert domains
    snapshot = adapter.get_zone(domains[0].domain)
    assert snapshot.version, "the zone must report a serial"
    assert snapshot.records


def test_mailboxes_are_listed_in_bytes(adapter):
    for box in adapter.list_mailboxes():
        assert box.disk_used is None or box.disk_used >= 0


@skip_unless_writes
def test_create_and_delete_mailbox(adapter):
    email = "bapp-connectors-probe@" + adapter.get_account().primary_domain
    try:
        adapter.create_mailbox(email, "Corect-Cal-Baterie-Capsator-9", quota_mb=10)
        assert any(b.email == email for b in adapter.list_mailboxes())
    finally:
        adapter.delete_mailbox(email)
    assert not any(b.email == email for b in adapter.list_mailboxes())
```

- [ ] **Step 2: Verify it skips cleanly**

Run: `uv run --extra dev pytest tests/hosting/cpanel/test_integration.py -v -m integration`
Expected: all tests SKIPPED with the credential reason (assuming no env vars set).

- [ ] **Step 3: Give the `dns` family a proper README label**

In `scripts/update_readme.py`, in `family_labels`, add after `"network": "Network",`:

```python
        "hosting": "Hosting",
        "dns": "DNS",
```

- [ ] **Step 4: Update the docs**

In `CLAUDE.md`, change the heading `### Provider Families (11)` to `### Provider Families (13)` and add two rows to the table, after the `network` row:

```markdown
| hosting | `HostingPort` | cPanel |
| dns | `DnsPort` | (cPanel, via its hosting connection) |
```

Also add to the "Key Patterns" list:

```markdown
- **An adapter may implement several ports:** the manifest's `capabilities` list holds ports and capabilities alike, and the registry only checks `issubclass`. cPanel is filed under `hosting` but also satisfies `DnsPort`, so `registry.list_providers(capability=DnsPort)` finds it. Family says what a provider *is*; ports say what it *can do*.
```

In `docs/PROVIDER_GUIDE.md`, at the end of the "Creating a New Provider Family" section (after Step 5), add:

```markdown
### A provider may belong to one family and implement several ports

`family` is the registry key and the label; it does not limit what an adapter can
implement. List every port in `capabilities` and implement them all. cPanel is
filed under `hosting` and also implements `DnsPort`, so a DNS UI finds it with
`registry.list_providers(capability=DnsPort)` without knowing about hosting.
```

- [ ] **Step 5: Bump the version**

In `pyproject.toml`, set:

```toml
version = "0.37.0"
```

- [ ] **Step 6: Run everything**

```bash
uv run --extra dev pytest -q
uv run ruff check src tests
```

Expected: no new failures against the baseline; ruff clean.

- [ ] **Step 7: Commit**

The pre-commit hook regenerates the README providers table; let it, and check the diff
only touches that table.

```bash
git add tests/hosting/cpanel/test_integration.py scripts/update_readme.py CLAUDE.md \
        docs/PROVIDER_GUIDE.md pyproject.toml
git commit -m "feat: v0.37.0 — familiile hosting si dns, providerul cPanel"
```

---

## Notes for the executor

- **Record the test baseline first.** Run `uv run --extra dev pytest -q` before Task 1 and write down the failure count. This package has pre-existing failures; "no new failures" is the bar, not "zero failures".
- **The fixtures are already anonymized and committed.** Do not regenerate them, and never replace them with captures from a live account.
- **Do not point any test at a real cPanel account by default.** If you need to check something live, use the gated integration test with your own env vars.
- **`FakeHttpClient.add` matches on a path substring**, checked in order. When a test needs two different responses from the same endpoint, add the more specific rule first.
