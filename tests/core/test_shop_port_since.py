from bapp_connectors.core.ports import ShopPort


def test_shop_port_does_not_support_modified_since_by_default():
    assert ShopPort.supports_modified_since is False


def test_woocommerce_supports_modified_since():
    from bapp_connectors.providers.shop.woocommerce.adapter import WooCommerceShopAdapter

    assert WooCommerceShopAdapter.supports_modified_since is True


def test_shop_port_sideloads_images_by_default():
    assert ShopPort.sideloads_images is True
