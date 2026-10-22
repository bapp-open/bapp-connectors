"""Temu enumerations and raw-payload constants.

Status codes 3/4/5 were verified on Temu's Developer Test Shop (RO); 1/2 follow the order of the
"Order Guide" (Pending → Unshipped → Shipped → Delivered, Cancelled) — re-check against the
official ``bg.order.list.v2.get`` field doc if an order ever shows an unmapped code.
"""

from __future__ import annotations

from enum import IntEnum, StrEnum


class ParentOrderStatus(IntEnum):
    ALL = 0
    PENDING = 1
    UNSHIPPED = 2
    CANCELLED = 3
    SHIPPED = 4
    RECEIVED = 5


class AfterSalesStatus(IntEnum):
    """``parentAfterSalesStatus`` (Return and Refund Guide)."""

    REFUND_REQUESTED = 1          # buyer applied for refund, pending processing
    RETURN_SHIPPED = 2            # buyer's return package has been shipped
    RETURN_RECEIVED = 3           # return package received, pending merchant processing
    REFUND_PROCESSING = 4         # refund initiated, system processing
    REFUNDED = 5                  # refund completed
    BUYER_CANCELLED = 6           # buyer cancelled the after-sales request
    REJECTED = 7                  # refund request denied
    LABEL_PENDING_MERCHANT = 8    # buyer used merchant label, pending merchant review/upload
    REFUND_PROCESSING_2 = 9       # refund initiated, system processing
    RETURN_REQUESTED = 10         # buyer has applied for return
    PLATFORM_REVIEW = 11          # platform review in progress


#: after-sales statuses that imply a parcel coming back (vs. a refund-only request)
RETURN_STATUSES = frozenset({
    AfterSalesStatus.RETURN_SHIPPED, AfterSalesStatus.RETURN_RECEIVED,
    AfterSalesStatus.LABEL_PENDING_MERCHANT, AfterSalesStatus.RETURN_REQUESTED,
})


class WebhookEventCode(StrEnum):
    ORDER_STATUS_CHANGE = "bg_order_status_change_event"
    LOGISTICS_ADDRESS_CHANGED = "bg_trade_logistics_address_changed"
    AFTERSALES_STATUS_CHANGE = "bg_aftersales_status_change"
    CANCEL_ORDER_STATUS_CHANGE = "bg_cancel_order_status_change"


class ShippingLabelStatus(IntEnum):
    """``shippingLabelStatus`` of a buy-shipping package."""

    IN_APPLICATION = 0
    SUCCESS = 1
    FAILED = 2


#: ``siteId`` → settlement currency (Temu "Product Differences in site currency").
SITE_CURRENCY: dict[int, str] = {
    100: "USD", 101: "CAD", 102: "GBP", 103: "AUD", 105: "EUR", 106: "EUR", 107: "EUR", 108: "EUR",
    109: "EUR", 110: "MXN", 111: "EUR", 112: "PLN", 113: "SEK", 114: "CHF", 115: "EUR", 116: "EUR",
    117: "EUR", 118: "JPY", 119: "KRW", 120: "SAR", 122: "AED", 124: "NOK", 132: "BRL", 137: "CZK",
    138: "HUF", 139: "DKK", 140: "RON", 141: "EUR", 142: "EUR", 143: "EUR", 144: "EUR", 145: "EUR",
    146: "EUR", 147: "EUR", 148: "EUR", 149: "EUR", 150: "EUR", 152: "EUR", 174: "TRY",
}

#: ``regionName1`` as Temu spells it → ISO 3166-1 alpha-2
REGION_COUNTRY: dict[str, str] = {
    "romania": "RO", "germany": "DE", "france": "FR", "italy": "IT", "netherlands": "NL", "spain": "ES",
    "portugal": "PT", "poland": "PL", "sweden": "SE", "greece": "GR", "czech republic": "CZ", "czechia": "CZ",
    "hungary": "HU", "denmark": "DK", "bulgaria": "BG", "belgium": "BE", "austria": "AT", "finland": "FI",
    "slovakia": "SK", "slovenia": "SI", "ireland": "IE", "lithuania": "LT", "croatia": "HR", "estonia": "EE",
    "switzerland": "CH", "latvia": "LV", "cyprus": "CY", "norway": "NO", "luxembourg": "LU",
    "united kingdom": "GB", "united states": "US", "canada": "CA", "australia": "AU", "mexico": "MX",
    "japan": "JP", "korea": "KR", "south korea": "KR", "brazil": "BR", "türkiye": "TR", "turkey": "TR",
    "united arab emirates": "AE", "saudi arabia": "SA",
}


#: ``afterSalesReasonCode`` (Return and Refund Guide) → normalised reason; everything else is OTHER
REASON_CODES: dict[int, str] = {
    2: "ordered_by_mistake", 49: "ordered_by_mistake", 53: "ordered_by_mistake",
    4: "changed_mind", 17: "changed_mind", 26: "changed_mind", 27: "changed_mind", 28: "changed_mind",
    34: "changed_mind", 40: "changed_mind", 41: "changed_mind", 42: "changed_mind", 59: "changed_mind",
    8: "not_as_described", 11: "not_as_described", 18: "not_as_described", 44: "not_as_described",
    52: "not_as_described", 58: "not_as_described",
    14: "defective", 51: "defective", 57: "defective",
    15: "wrong_item", 60: "wrong_item",
    19: "not_delivered", 25: "not_delivered", 40007: "not_delivered", 40010: "not_delivered", 40018: "not_delivered",
    22: "missing_parts", 36: "missing_parts", 56: "missing_parts",
    23: "damaged", 24: "damaged",
    54: "size_fit", 55: "size_fit",
}
