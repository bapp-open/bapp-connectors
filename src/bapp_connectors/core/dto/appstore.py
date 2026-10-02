"""
DTO-uri normalizate pentru magazinele de aplicatii (Apple App Store, Google Play, Steam).

Vanzarile vin din rapoarte agregate (pe zi sau pe luna), nu din comenzi: un rand
AppStoreSale = (perioada, aplicatie, SKU, tara, tip de produs), cu unitati si sume.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from .base import BaseDTO


class AppStorePlatform(StrEnum):
    APPLE = "apple"
    GOOGLE_PLAY = "google_play"
    STEAM = "steam"


class AppStoreProductType(StrEnum):
    APP = "app"
    IAP = "iap"
    SUBSCRIPTION = "subscription"  # providerul nu distinge nou / reinnoire
    SUBSCRIPTION_NEW = "subscription_new"
    SUBSCRIPTION_RENEWAL = "subscription_renewal"
    DLC = "dlc"
    OTHER = "other"


class AppStoreApp(BaseDTO):
    app_id: str
    platform: AppStorePlatform
    name: str = ""
    bundle_id: str = ""  # bundle id (Apple) / package name (Google) / appid (Steam)
    status: str = ""
    extra: dict = {}


class AppStoreSale(BaseDTO):
    """Un rand agregat dintr-un raport de vanzari."""

    external_key: str  # identitatea randului, stabila intre rulari (vezi core.reports.stable_key)
    period_start: date
    period_end: date
    app_id: str = ""
    sku: str = ""
    product_name: str = ""
    product_type: AppStoreProductType = AppStoreProductType.OTHER
    units: Decimal = Decimal("0")
    country: str = ""
    customer_currency: str = ""
    customer_price: Decimal = Decimal("0")
    proceeds_currency: str = ""
    proceeds_unit: Decimal = Decimal("0")
    proceeds_total: Decimal = Decimal("0")
    is_refund: bool = False
    extra: dict = {}


class AppStoreRefund(BaseDTO):
    refund_id: str
    app_id: str = ""
    sku: str = ""
    transaction_ref: str = ""
    amount: Decimal = Decimal("0")  # valoare absoluta, in `currency`
    currency: str = ""
    reason: str = ""
    refunded_at: datetime | None = None
    extra: dict = {}


class AppStoreReview(BaseDTO):
    review_id: str
    app_id: str = ""
    rating: int | None = None  # 1-5; None la Steam
    recommended: bool | None = None  # Steam: voted_up
    title: str = ""
    body: str = ""
    author: str = ""
    country: str = ""
    language: str = ""
    app_version: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None
    developer_response: str = ""
    developer_response_at: datetime | None = None
    extra: dict = {}


class AppStoreStatMetric(StrEnum):
    # Descarcari / instalari
    DOWNLOADS = "downloads"
    UPDATES = "updates"
    REDOWNLOADS = "redownloads"
    INSTALLS = "installs"
    UNINSTALLS = "uninstalls"
    ACTIVE_DEVICES = "active_devices"
    USER_INSTALLS = "user_installs"
    # Calitate
    RATING_DAILY = "rating_daily"
    RATING_TOTAL = "rating_total"
    CRASHES = "crashes"
    ANRS = "anrs"
    # Vizibilitate in magazin
    STORE_ACQUISITIONS = "store_acquisitions"
    # Wishlist (Steam)
    WISHLIST_ADDS = "wishlist_adds"
    WISHLIST_DELETES = "wishlist_deletes"
    WISHLIST_PURCHASES = "wishlist_purchases"
    WISHLIST_GIFTS = "wishlist_gifts"
    # Jucatori (Steam)
    CURRENT_PLAYERS = "current_players"


class AppStoreStat(BaseDTO):
    """O valoare zilnica a unei metrici, pe aplicatie si optional pe tara ("" = total)."""

    external_key: str
    date: date
    metric: AppStoreStatMetric
    value: Decimal = Decimal("0")
    app_id: str = ""
    country: str = ""
    extra: dict = {}
