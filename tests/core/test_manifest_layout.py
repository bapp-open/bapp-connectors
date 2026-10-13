import pytest

from bapp_connectors.core.manifest import CredentialField, SettingsField


@pytest.mark.parametrize("cls", [CredentialField, SettingsField])
def test_layout_defaults_to_full_row_and_no_section(cls):
    f = cls(name="x")
    assert f.colspan == 0 and f.group == ""


@pytest.mark.parametrize("cls", [CredentialField, SettingsField])
@pytest.mark.parametrize("colspan", [-1, 25])
def test_colspan_outside_the_24_column_grid_is_refused(cls, colspan):
    with pytest.raises(ValueError):
        cls(name="x", colspan=colspan)


def test_smtp_server_fields_share_rows():
    from bapp_connectors.providers.email.smtp.manifest import manifest

    span = {f.name: f.colspan for f in manifest.auth.required_fields}
    assert span["host"] + span["port"] == 24
    assert span["username"] + span["password"] == 24
    assert span["from_email"] + span["from_name"] == 24


def _field_lists():
    import importlib
    from pathlib import Path

    import bapp_connectors.providers as providers

    base = Path(providers.__file__).parent
    for family_dir in sorted(base.iterdir()):
        if not family_dir.is_dir() or family_dir.name.startswith("_"):
            continue
        family = family_dir.name
        for provider_dir in sorted(family_dir.iterdir()):
            if not (provider_dir / "manifest.py").exists():
                continue
            provider = provider_dir.name
            m = importlib.import_module(f"bapp_connectors.providers.{family}.{provider}.manifest").manifest
            yield f"{family}/{provider}/credentials", list(m.auth.required_fields)
            oauth = getattr(m.auth, "oauth", None)
            if oauth and getattr(oauth, "credential_fields", None):
                yield f"{family}/{provider}/oauth", list(oauth.credential_fields)
            if m.settings:
                yield f"{family}/{provider}/settings", list(m.settings.fields)


def test_every_manifest_fills_its_rows():
    """Inside a group, side-by-side fields add up to whole rows of 24: no field left half-empty
    next to a full-row one, a group change or the end of the list."""
    dangling = []
    for where, fields in _field_lists():
        used, group = 0, None
        for f in fields:
            if f.group != group or not f.colspan:
                if used % 24:
                    dangling.append(f"{where}: row before {f.name}")
                used = 0
            group, used = f.group, used + f.colspan
        if used % 24:
            dangling.append(f"{where}: last row")
    assert dangling == []
