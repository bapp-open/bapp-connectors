"""
Shared fixtures for feed tests.
"""

from decimal import Decimal

import pytest

from bapp_connectors.core.dto.product import (
    Product,
    ProductAttribute,
    ProductPhoto,
    ProductVariant,
)


@pytest.fixture
def sample_products() -> list[Product]:
    """A set of sample products covering various scenarios."""
    return [
        # Complete product with all fields
        Product(
            product_id="PROD-001",
            sku="SKU-001",
            barcode="5901234123457",
            name="Premium Wireless Headphones",
            description="<p>High-quality <strong>wireless</strong> headphones with noise cancellation.</p>",
            price=Decimal("299.99"),
            currency="RON",
            stock=50,
            active=True,
            categories=["Electronics", "Audio", "Headphones"],
            photos=[
                ProductPhoto(url="https://myshop.ro/img/headphones-main.jpg", position=0, alt_text="Headphones front"),
                ProductPhoto(url="https://myshop.ro/img/headphones-side.jpg", position=1, alt_text="Headphones side"),
                ProductPhoto(url="https://myshop.ro/img/headphones-box.jpg", position=2, alt_text="Headphones box"),
            ],
            attributes=[
                ProductAttribute(attribute_id="1", attribute_name="Brand", values=["SoundMax"]),
                ProductAttribute(attribute_id="2", attribute_name="Color", values=["Black", "White"]),
            ],
        ),
        # Product with variants
        Product(
            product_id="PROD-002",
            sku="SKU-002",
            name="Cotton T-Shirt",
            description="Comfortable cotton t-shirt, available in multiple sizes.",
            price=Decimal("49.99"),
            currency="RON",
            stock=100,
            active=True,
            categories=["Clothing", "T-Shirts"],
            photos=[
                ProductPhoto(url="https://myshop.ro/img/tshirt.jpg", position=0),
            ],
            attributes=[
                ProductAttribute(attribute_id="3", attribute_name="Brand", values=["BasicWear"]),
                ProductAttribute(attribute_id="4", attribute_name="Gender", values=["Unisex"]),
            ],
            variants=[
                ProductVariant(
                    variant_id="V-002-S",
                    sku="SKU-002-S",
                    name="Cotton T-Shirt - Small",
                    price=Decimal("49.99"),
                    stock=30,
                    attributes={"Size": "S", "Color": "Red"},
                ),
                ProductVariant(
                    variant_id="V-002-M",
                    sku="SKU-002-M",
                    name="Cotton T-Shirt - Medium",
                    price=Decimal("49.99"),
                    stock=40,
                    attributes={"Size": "M", "Color": "Red"},
                ),
                ProductVariant(
                    variant_id="V-002-L",
                    sku="SKU-002-L",
                    name="Cotton T-Shirt - Large",
                    price=Decimal("54.99"),
                    stock=30,
                    attributes={"Size": "L", "Color": "Blue"},
                ),
            ],
        ),
        # Product missing optional fields (no brand, no barcode)
        Product(
            product_id="PROD-003",
            name="Simple Notebook",
            description="A5 ruled notebook, 100 pages.",
            price=Decimal("12.50"),
            currency="RON",
            stock=200,
            active=True,
            categories=["Office", "Notebooks"],
            photos=[
                ProductPhoto(url="https://myshop.ro/img/notebook.jpg", position=0),
            ],
        ),
        # Out of stock product
        Product(
            product_id="PROD-004",
            sku="SKU-004",
            barcode="5901234123464",
            name="Vintage Camera",
            description="Retro-style digital camera.",
            price=Decimal("899.00"),
            currency="RON",
            stock=0,
            active=True,
            categories=["Electronics", "Cameras"],
            photos=[
                ProductPhoto(url="https://myshop.ro/img/camera.jpg", position=0),
            ],
            attributes=[
                ProductAttribute(attribute_id="5", attribute_name="Manufacturer", values=["RetroTech"]),
            ],
        ),
        # Inactive product
        Product(
            product_id="PROD-005",
            name="Discontinued Widget",
            price=Decimal("9.99"),
            stock=5,
            active=False,
        ),
    ]


@pytest.fixture
def minimal_product() -> Product:
    """A product missing required feed fields (no name, no image)."""
    return Product(
        product_id="BAD-001",
        name="",
        price=None,
    )


@pytest.fixture
def feed_config() -> dict:
    """Standard feed configuration for tests."""
    return {
        "base_url": "https://myshop.ro",
        "product_url_template": "{base_url}/product/{product_id}",
        "currency": "RON",
        "default_condition": "new",
        "default_availability": "in stock",
        "brand_fallback": "",
        "include_variants": "true",
    }
