"""
Product management capabilities — optional interfaces for product CRUD, categories,
attributes, variants, and related products.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bapp_connectors.core.dto import (
        AttributeDefinition,
        AttributeValue,
        Product,
        ProductCategory,
        ProductUpdate,
        ProductVariant,
        RelatedProductLink,
    )


class ProductCreationCapability(ABC):
    """Adapter supports creating and deleting products on the provider."""

    @abstractmethod
    def create_product(self, product: Product) -> Product:
        """Create a product on the provider. Returns the created product with provider's ID."""
        ...

    @abstractmethod
    def delete_product(self, product_id: str) -> None:
        """Delete a product from the provider."""
        ...


class ProductFullUpdateCapability(ABC):
    """Adapter supports full product updates (name, description, categories, photos, attributes)."""

    @abstractmethod
    def update_product(self, update: ProductUpdate) -> None:
        """Apply a full update to a product on the provider."""
        ...


class CategoryManagementCapability(ABC):
    """Adapter supports reading and optionally creating categories."""

    @abstractmethod
    def get_categories(self) -> list[ProductCategory]:
        """Fetch all categories from the provider as a flat list with parent_id."""
        ...

    def create_category(self, name: str, parent_id: str | None = None) -> ProductCategory:
        """Create a category on the provider. Returns the created category with provider's ID."""
        raise NotImplementedError("This provider does not support category creation.")


class AttributeManagementCapability(ABC):
    """Adapter supports CRUD for product attribute definitions (Color, Size, etc.)."""

    @abstractmethod
    def get_attributes(self) -> list[AttributeDefinition]:
        """Fetch all attribute definitions from the provider."""
        ...

    @abstractmethod
    def get_attribute(self, attribute_id: str) -> AttributeDefinition:
        """Fetch a single attribute definition by ID."""
        ...

    @abstractmethod
    def create_attribute(self, attribute: AttributeDefinition) -> AttributeDefinition:
        """Create an attribute definition. Returns with provider ID."""
        ...

    def update_attribute(self, attribute: AttributeDefinition) -> AttributeDefinition:
        """Update an attribute definition."""
        raise NotImplementedError("This provider does not support attribute updates.")

    def delete_attribute(self, attribute_id: str) -> None:
        """Delete an attribute definition."""
        raise NotImplementedError("This provider does not support attribute deletion.")

    def add_attribute_value(self, attribute_id: str, value: AttributeValue) -> AttributeValue:
        """Add a value (term/option) to an existing attribute."""
        raise NotImplementedError("This provider does not support adding attribute values.")


class VariantManagementCapability(ABC):
    """Adapter supports CRUD for product variants (variations/combinations/configurable children)."""

    @abstractmethod
    def get_variants(self, product_id: str) -> list[ProductVariant]:
        """Fetch all variants for a product."""
        ...

    @abstractmethod
    def create_variant(self, product_id: str, variant: ProductVariant) -> ProductVariant:
        """Create a variant on a product. Returns with provider ID."""
        ...

    @abstractmethod
    def update_variant(self, product_id: str, variant: ProductVariant) -> ProductVariant:
        """Update a variant. Returns the updated variant."""
        ...

    def delete_variant(self, product_id: str, variant_id: str) -> None:
        """Delete a variant."""
        raise NotImplementedError("This provider does not support variant deletion.")

    def get_variant(self, product_id: str, variant_id: str) -> ProductVariant:
        """Fetch a single variant by ID."""
        raise NotImplementedError("This provider does not support fetching individual variants.")


class RelatedProductCapability(ABC):
    """Adapter supports reading and optionally writing related/upsell/cross-sell product links."""

    @abstractmethod
    def get_related_products(self, product_id: str) -> list[RelatedProductLink]:
        """Fetch related product links for a product."""
        ...

    def set_related_products(self, product_id: str, links: list[RelatedProductLink]) -> None:
        """Set related product links. Override for writable providers."""
        raise NotImplementedError("This provider does not support writing related products.")
