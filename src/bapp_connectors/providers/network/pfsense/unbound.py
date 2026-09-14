"""Pure-text handling of the Unbound `custom_options` view block managed by bapp.

No I/O here. The block owned by bapp is delimited by marker comments; a legacy block
(written by hand, without markers) is recognised by its `view:` / `name:` pair so it can
be adopted on the first write. Everything outside the owned block is preserved verbatim.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

BEGIN_MARK = "# bapp:begin {view}"
END_MARK = "# bapp:end {view}"

_CLAUSES = (
    "server:",
    "view:",
    "forward-zone:",
    "stub-zone:",
    "auth-zone:",
    "remote-control:",
    "rpz:",
    "dnstap:",
    "cachedb:",
    "python:",
    "dynlib:",
)
_LOCAL_ZONE_RE = re.compile(r'^\s*local-zone:\s*"([^"]*)"\s+(\S+)\s*$')
_NAME_RE = re.compile(r'^\s*name:\s*"([^"]*)"\s*$')
_ACCESS_RE = re.compile(r"^\s*access-control-view:\s*(\S+)\s+(\S+)\s*$")


@dataclass
class ParsedView:
    view: str
    cidr: str = ""
    domains: list[str] = field(default_factory=list)
    managed: bool = False
    block: str = ""


def _is_clause(line: str) -> bool:
    stripped = line.strip()
    return stripped in _CLAUSES or stripped.startswith("# bapp:begin ")


def _find_access_line(lines: list[str], view: str) -> int | None:
    for idx, line in enumerate(lines):
        m = _ACCESS_RE.match(line)
        if m and m.group(2) == view:
            return idx
    return None


def _find_managed_span(lines: list[str], view: str) -> tuple[int, int] | None:
    begin = BEGIN_MARK.format(view=view)
    end = END_MARK.format(view=view)
    start = next((i for i, line in enumerate(lines) if line.strip() == begin), None)
    if start is None:
        return None
    stop = next((i for i in range(start + 1, len(lines)) if lines[i].strip() == end), None)
    if stop is None:
        return None
    return start, stop + 1  # slice bounds


def _find_legacy_span(lines: list[str], view: str) -> tuple[int, int] | None:
    for i, line in enumerate(lines):
        if line.strip() != "view:":
            continue
        j = i + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        m = _NAME_RE.match(lines[j]) if j < len(lines) else None
        if not m or m.group(1) != view:
            continue
        stop = j + 1
        while stop < len(lines) and not _is_clause(lines[stop]):
            stop += 1
        return i, stop
    return None


def _domains_in(lines: list[str]) -> list[str]:
    out: list[str] = []
    for line in lines:
        m = _LOCAL_ZONE_RE.match(line)
        if not m:
            continue
        zone, kind = m.group(1), m.group(2)
        if zone == "." or kind != "transparent":
            continue
        out.append(zone.rstrip("."))
    return out


def parse_view(text: str, view: str) -> ParsedView | None:
    """Locate the view block (managed or legacy) and extract its domains and CIDR."""
    lines = text.split("\n")
    span = _find_managed_span(lines, view)
    managed = span is not None
    if span is None:
        span = _find_legacy_span(lines, view)
    if span is None:
        return None
    block_lines = lines[span[0] : span[1]]
    access_idx = _find_access_line(lines, view)
    cidr = _ACCESS_RE.match(lines[access_idx]).group(1) if access_idx is not None else ""
    block = "\n".join(block_lines)
    if managed:
        block += "\n"
    return ParsedView(view=view, cidr=cidr, domains=_domains_in(block_lines), managed=managed, block=block)


def render_view(view: str, cidr: str, domains: list[str]) -> str:
    """Canonical managed block: sorted, deduplicated, wrapped in markers, newline-terminated."""
    unique = sorted({d.strip().strip(".").lower() for d in domains if d.strip()})
    lines = [
        BEGIN_MARK.format(view=view),
        "server:",
        f"access-control-view: {cidr} {view}",
        "view:",
        f'name: "{view}"',
        "view-first: yes",
        'local-zone: "." always_nxdomain',
        *[f'local-zone: "{d}." transparent' for d in unique],
        END_MARK.format(view=view),
    ]
    return "\n".join(lines) + "\n"


def replace_view(text: str, view: str, block: str) -> str:
    """Replace the managed block, adopt a legacy block, or append; leave everything else intact."""
    lines = text.split("\n")
    span = _find_managed_span(lines, view)
    if span is not None:
        new_lines = lines[: span[0]] + block.rstrip("\n").split("\n") + lines[span[1] :]
        return "\n".join(new_lines)
    span = _find_legacy_span(lines, view)
    if span is not None:
        access_idx = _find_access_line(lines, view)
        drop = set(range(span[0], span[1]))
        if access_idx is not None:
            drop.add(access_idx)
        kept = [line for i, line in enumerate(lines) if i not in drop]
        base = "\n".join(kept)
    else:
        base = text
    if base and not base.endswith("\n"):
        base += "\n"
    return base + block


def list_views(text: str) -> list[tuple[str, str]]:
    """All `(view, cidr)` pairs declared by `access-control-view` lines, in order, without duplicates."""
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for line in text.split("\n"):
        m = _ACCESS_RE.match(line)
        if m and m.group(2) not in seen:
            seen.add(m.group(2))
            out.append((m.group(2), m.group(1)))
    return out
