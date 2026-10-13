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
