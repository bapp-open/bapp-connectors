from bapp_connectors.providers.shop.woocommerce.manifest import manifest


def test_sync_settings_have_safe_defaults():
    defaults = manifest.settings.apply_defaults({})
    assert defaults["batch_size"] == 20
    assert defaults["pause_seconds"] == 2
    assert defaults["publish_status"] == "publish"
    assert defaults["sync_images"] is True
    assert defaults["prices_include_vat"] is True and defaults["vat_rate"] == "0.19"


def test_publish_status_choices_are_validated():
    assert manifest.settings.validate_settings({"publish_status": "pending"}) != []
    assert manifest.settings.validate_settings({"publish_status": "draft"}) == []
