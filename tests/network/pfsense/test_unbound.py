"""Pure-text tests for the Unbound custom_options view block handling."""

from bapp_connectors.providers.network.pfsense.unbound import (
    BEGIN_MARK,
    END_MARK,
    list_views,
    parse_view,
    render_view,
    replace_view,
)

LEGACY = (
    "server:\n"
    "access-control-view: 172.16.196.0/22 elevi\n"
    "view:\n"
    'name: "elevi"\n'
    "view-first: yes\n"
    'local-zone: "." always_nxdomain\n'
    'local-zone: "scoala198.ro." transparent\n'
    'local-zone: "google.com." transparent\n'
    'local-zone: "youtube.com." transparent\n'
)

OTHER_STUFF = 'server:\nprivate-domain: "intern.local"\nlog-queries: no\n'


def test_render_is_canonical_and_sorted():
    block = render_view("elevi", "172.16.196.0/22", ["youtube.com", "google.com", "google.com"])
    assert block == (
        "# bapp:begin elevi\n"
        "server:\n"
        "access-control-view: 172.16.196.0/22 elevi\n"
        "view:\n"
        'name: "elevi"\n'
        "view-first: yes\n"
        'local-zone: "." always_nxdomain\n'
        'local-zone: "google.com." transparent\n'
        'local-zone: "youtube.com." transparent\n'
        "# bapp:end elevi\n"
    )
    assert BEGIN_MARK.format(view="elevi") == "# bapp:begin elevi"
    assert END_MARK.format(view="elevi") == "# bapp:end elevi"


def test_parse_legacy_block_without_markers():
    parsed = parse_view(OTHER_STUFF + LEGACY, "elevi")
    assert parsed is not None
    assert parsed.managed is False
    assert parsed.cidr == "172.16.196.0/22"
    assert parsed.domains == ["scoala198.ro", "google.com", "youtube.com"]
    assert parsed.block.startswith("view:\n")


def test_parse_managed_block():
    block = render_view("elevi", "172.16.196.0/22", ["a.ro", "b.ro"])
    parsed = parse_view(OTHER_STUFF + "\n" + block, "elevi")
    assert parsed is not None
    assert parsed.managed is True
    assert parsed.domains == ["a.ro", "b.ro"]
    assert parsed.cidr == "172.16.196.0/22"
    assert parsed.block == block


def test_parse_missing_view_returns_none():
    assert parse_view(OTHER_STUFF, "elevi") is None
    assert parse_view("", "elevi") is None


def test_parse_ignores_other_views():
    text = LEGACY + "view:\n" + 'name: "profesori"\n' + 'local-zone: "x.ro." transparent\n'
    parsed = parse_view(text, "elevi")
    assert parsed.domains == ["scoala198.ro", "google.com", "youtube.com"]
    other = parse_view(text, "profesori")
    assert other.domains == ["x.ro"] and other.cidr == ""


def test_replace_managed_block_keeps_rest_byte_identical():
    old_block = render_view("elevi", "172.16.196.0/22", ["a.ro"])
    text = OTHER_STUFF + "\n" + old_block + "\n# trailing comment\n"
    new_block = render_view("elevi", "172.16.196.0/22", ["a.ro", "b.ro"])
    out = replace_view(text, "elevi", new_block)
    assert out == OTHER_STUFF + "\n" + new_block + "\n# trailing comment\n"


def test_replace_legacy_block_adopts_it_and_removes_access_line():
    text = OTHER_STUFF + LEGACY
    new_block = render_view("elevi", "172.16.196.0/22", ["google.com"])
    out = replace_view(text, "elevi", new_block)
    assert out == OTHER_STUFF + "server:\n" + new_block
    assert parse_view(out, "elevi").managed is True
    assert out.count("access-control-view:") == 1


def test_replace_appends_when_missing():
    out = replace_view(OTHER_STUFF, "elevi", render_view("elevi", "10.0.0.0/24", ["a.ro"]))
    assert out.startswith(OTHER_STUFF)
    assert out.endswith(render_view("elevi", "10.0.0.0/24", ["a.ro"]))
    assert replace_view("", "elevi", "X\n") == "X\n"


def test_roundtrip_parse_render():
    domains = ["z.ro", "a.ro", "m.ro"]
    block = render_view("elevi", "10.0.0.0/24", domains)
    assert parse_view(block, "elevi").domains == sorted(domains)


def test_list_views_returns_view_and_cidr_pairs_once():
    text = LEGACY + "access-control-view: 10.0.0.0/24 profesori\naccess-control-view: 172.16.196.0/22 elevi\n"
    assert list_views(text) == [("elevi", "172.16.196.0/22"), ("profesori", "10.0.0.0/24")]
    assert list_views("") == []
