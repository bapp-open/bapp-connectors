"""Modele Pydantic pentru raspunsurile Steamworks (IPartnerFinancialsService).

Schema reala difera de cea documentata: line_item_type e text, sumele sunt siruri,
preturile (base_price/sale_price) sunt in centi ai monedei locale, `currency` e moneda locala,
iar randurile de activari de chei (Retail) nu au campuri monetare.
"""

from __future__ import annotations

from pydantic import BaseModel


class DetailedSalesRow(BaseModel):
    date: str = ""
    appid: int = 0
    primary_appid: int = 0
    packageid: int = 0
    bundleid: int = 0
    country_code: str = ""
    platform: str = ""
    line_item_type: int | str = 0
    package_sale_type: str = ""
    base_price: str = "0"
    sale_price: str = "0"
    currency: str = ""
    gross_units_activated: int = 0
    gross_units_sold: int = 0
    gross_units_returned: int = 0
    gross_sales_usd: str = "0"
    gross_returns_usd: str = "0"
    net_tax_usd: str = "0"
    net_units_sold: int = 0
    net_sales_usd: str = "0"
    additional_revenue_share_tier: int = 0


class DetailedSalesResponse(BaseModel):
    results: list[dict] = []
    max_id: int = 0
    app_info: list[dict] = []
    package_info: list[dict] = []
    bundle_info: list[dict] = []
    country_info: list[dict] = []
