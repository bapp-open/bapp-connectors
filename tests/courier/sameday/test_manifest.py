"""Setarile declarate de conectorul Sameday.

Rambursurile incasate de curier pot fi luate din desfasuratorul XLSX trimis pe
e-mail sau direct din API-ul Sameday. Alegerea apartine firmei si tine de
CONEXIUNE, nu de modulul de incasari, asa ca sta in manifestul providerului si
ajunge in `Connection.config`.
"""

from __future__ import annotations

from bapp_connectors.core.types import FieldType
from bapp_connectors.providers.courier.sameday.manifest import manifest


def _field(name: str):
    return next((f for f in manifest.settings.fields if f.name == name), None)


def test_cod_source_setting_is_declared():
    field = _field("cod_source")
    assert field is not None, "conectorul trebuie sa expuna sursa rambursurilor"
    assert field.field_type == FieldType.SELECT
    assert field.choices == ["email", "api", "both"]


def test_cod_source_defaults_to_the_email_statement():
    """Comportamentul istoric: XLSX-ul de pe mail, singurul cu data virarii."""
    assert _field("cod_source").default == "email"


def test_cod_source_help_text_explains_the_tradeoff():
    help_text = _field("cod_source").help_text.lower()
    assert "payout" in help_text or "wire" in help_text
    assert "delivery" in help_text


def test_defaults_are_applied_for_a_connection_that_never_set_it():
    assert manifest.settings.apply_defaults({})["cod_source"] == "email"


def test_existing_settings_survive_the_new_field():
    config = manifest.settings.apply_defaults({"service_id": 7})
    assert config["service_id"] == 7
    assert config["cod_source"] == "email"


def test_an_unknown_source_is_rejected():
    assert manifest.settings.validate_settings({"cod_source": "carbon-copy"})
    assert manifest.settings.validate_settings({"cod_source": "api"}) == []
