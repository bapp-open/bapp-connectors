"""Accounting port — push documents into and read reports from an accounting program."""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING

from bapp_connectors.core.ports.base import BasePort

if TYPE_CHECKING:
    from datetime import date
    from decimal import Decimal

    from bapp_connectors.core.dto import Article, ImportResult, StockLine, TrialBalanceLine


class AccountingPort(BasePort):
    """Contract for an accounting program (SAGA Web endpoints in brackets).

    - import_file: push one file to be imported (POST ``Import``).
    - get_article_stock: stock of one article (GET ``Situatii/GetStocArticol``).
    - get_stock_report: stock situation over a period (GET ``Situatii/GetSituatieStocuri``).
    - get_account_balance: balance of one account on a day (GET ``Situatii/GetSoldCont``).
    - get_trial_balance: trial balance over a period (GET ``Situatii/GetBalanta``).
    - get_article: one article from the nomenclature (GET ``Situatii/GetArticol``).
    """

    @abstractmethod
    def import_file(self, filename: str, content: bytes, auto_import: bool = True) -> ImportResult:
        """Push ``content`` (named ``filename``) for import; ``auto_import`` imports it right away."""
        ...

    @abstractmethod
    def get_article_stock(self, article_code: str, warehouse: str = "", day: date | None = None) -> Decimal:
        """Stock of ``article_code`` in ``warehouse`` (all when empty) on ``day`` (today when None)."""
        ...

    @abstractmethod
    def get_stock_report(self, start: date, end: date) -> list[StockLine]:
        """Stock situation per warehouse and article between ``start`` and ``end``."""
        ...

    @abstractmethod
    def get_account_balance(self, account: str, side: str, day: date | None = None) -> Decimal:
        """Balance of ``account`` on ``day``; ``side`` is ``"C"`` (credit) or ``"D"`` (debit)."""
        ...

    @abstractmethod
    def get_trial_balance(self, start: date, end: date, analytic: bool = False) -> list[TrialBalanceLine]:
        """Trial balance between ``start`` and ``end``; ``analytic`` includes analytic accounts."""
        ...

    @abstractmethod
    def get_article(self, article_code: str) -> Article | None:
        """The article with ``article_code``, or None when it does not exist."""
        ...
