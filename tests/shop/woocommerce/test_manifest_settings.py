from bapp_connectors.providers.shop.woocommerce.manifest import manifest


def test_sync_settings_have_safe_defaults():
    defaults = manifest.settings.apply_defaults({})
    assert defaults["batch_size"] == 20
    assert defaults["pause_seconds"] == 2
    assert defaults["publish_status"] == "publish"
    assert defaults["sync_images"] is True
    assert defaults["prices_include_vat"] is True


def test_vat_rate_is_not_a_form_setting_but_config_still_wins():
    """The caller prices with each product's own VAT; a stored rate (or the detected one) still converts."""
    from decimal import Decimal

    from bapp_connectors.providers.shop.woocommerce.adapter import WooCommerceShopAdapter

    for provider in ("woocommerce", "magento", "shopify", "prestashop", "bapp_store"):
        module = __import__(f"bapp_connectors.providers.shop.{provider}.manifest", fromlist=["manifest"])
        assert "vat_rate" not in [f.name for f in module.manifest.settings.fields], provider
    adapter = WooCommerceShopAdapter(credentials={"consumer_key": "k", "consumer_secret": "s"},
                                     config={"vat_rate": "0.21"}, http_client=object())
    assert adapter._vat_rate == Decimal("0.21")


def test_publish_status_choices_are_validated():
    assert manifest.settings.validate_settings({"publish_status": "pending"}) != []
    assert manifest.settings.validate_settings({"publish_status": "draft"}) == []
