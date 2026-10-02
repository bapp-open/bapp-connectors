"""App store port — vanzari, rambursari, recenzii si abonamente din magazinele de aplicatii."""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING

from bapp_connectors.core.ports.base import BasePort

if TYPE_CHECKING:
    from datetime import date, datetime

    from bapp_connectors.core.dto import (
        AppStoreApp,
        AppStoreRefund,
        AppStoreReview,
        AppStoreSale,
        PaginatedResult,
        Subscription,
    )


class AppStorePort(BasePort):
    """
    Contractul comun pentru magazinele de aplicatii (Apple App Store, Google Play, Steam).

    Rapoartele sunt fisiere pe zi sau pe luna, de aceea `cursor` codifica
    „urmatoarea perioada neadusa" (vezi core.reports.daily_page / monthly_page).
    Decontarile vin prin FinancialCapability, notificarile prin WebhookCapability.
    """

    @abstractmethod
    def list_apps(self) -> list[AppStoreApp]:
        """Aplicatiile vizibile pentru aceasta conexiune."""
        ...

    @abstractmethod
    def get_sales(self, start: date, end: date, cursor: str | None = None) -> PaginatedResult[AppStoreSale]:
        """Randurile de vanzari (inclusiv rambursari cu unitati negative) din intervalul [start, end]."""
        ...

    @abstractmethod
    def list_refunds(self, start: date, end: date, cursor: str | None = None) -> PaginatedResult[AppStoreRefund]:
        """Rambursarile / cumparaturile anulate din interval."""
        ...

    @abstractmethod
    def list_reviews(
        self,
        app_id: str,
        since: datetime | None = None,
        cursor: str | None = None,
    ) -> PaginatedResult[AppStoreReview]:
        """Recenziile unei aplicatii, cele mai noi primele."""
        ...

    def reply_to_review(self, app_id: str, review_id: str, text: str) -> AppStoreReview:
        raise NotImplementedError(f"{type(self).__name__} nu suporta raspunsul la recenzii")

    def get_subscription(self, reference: str) -> Subscription:
        """Starea unui abonament dupa referinta platformei (original transaction id / purchase token)."""
        raise NotImplementedError(f"{type(self).__name__} nu suporta interogarea abonamentelor")
