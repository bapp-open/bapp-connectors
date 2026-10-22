"""Fulfillment capability -- ship a marketplace order with your own courier or with a label
bought through the marketplace (Temu "buy-shipping")."""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Literal

from bapp_connectors.core.dto.base import BaseDTO


class Carrier(BaseDTO):
    """A courier the marketplace accepts for self-fulfilled shipments."""

    carrier_id: str
    name: str
    extra: dict = {}


class ShippingService(BaseDTO):
    """A shipping service the marketplace can buy a label from, for one order."""

    service_id: str
    name: str
    carrier_id: str = ""
    cost: Decimal | None = None
    currency: str = ""
    extra: dict = {}


class ShipmentResult(BaseDTO):
    """Outcome of an asynchronous label purchase."""

    package_sn: str
    status: Literal["pending", "success", "failed"]
    tracking_number: str = ""
    carrier: str = ""
    label_url: str = ""
    error: str = ""
    extra: dict = {}


class FulfillmentCapability(ABC):
    """Adapter can confirm a self-fulfilled shipment and/or buy a shipping label."""

    @abstractmethod
    def list_carriers(self) -> list[Carrier]:
        """Couriers accepted for self-fulfilled shipments."""
        ...

    @abstractmethod
    def confirm_shipment(self, order_id: str, tracking_number: str, carrier_id: str,
                         items: list[str] | None = None) -> None:
        """Tell the marketplace the order (or the given line ids) left with this tracking number."""
        ...

    @abstractmethod
    def list_shipping_services(self, order_id: str, warehouse_id: str) -> list[ShippingService]:
        """Services the marketplace offers to ship this order from this warehouse."""
        ...

    @abstractmethod
    def create_shipment(self, order_id: str, shipping_service_id: str, warehouse_id: str,
                        items: list[str] | None = None, ship_later: bool = False) -> str:
        """Buy a label; returns the package sn to poll with `get_shipment_result`."""
        ...

    @abstractmethod
    def get_shipment_result(self, package_sn: str) -> ShipmentResult:
        """Current state of a label purchase."""
        ...

    @abstractmethod
    def confirm_package_shipped(self, package_sn: str) -> None:
        """Mark a bought-label package as shipped (when the purchase used `ship_later`)."""
        ...
