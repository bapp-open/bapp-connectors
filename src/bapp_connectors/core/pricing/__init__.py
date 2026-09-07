"""
Price/VAT conversion utilities.

Convention: all prices in the framework are NET (without VAT).

Providers that expect or return VAT-inclusive prices declare
`prices_include_vat=True` in their manifest settings. The tenant
configures `vat_rate` (e.g., 0.19 for 19%).

Adapters use these helpers in mappers to convert on the boundary:
- to_gross(): before sending to a VAT-inclusive provider
- to_net(): when reading from a VAT-inclusive provider
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

_TWO_PLACES = Decimal("0.01")


def to_gross(net_price: Decimal, vat_rate: Decimal | float) -> Decimal:
    """Convert a net (without VAT) price to gross (with VAT).

    Args:
        net_price: Price without VAT.
        vat_rate: VAT rate as a decimal (e.g., 0.19 for 19%).

    Returns:
        Price with VAT, rounded to 2 decimal places.
    """
    rate = Decimal(str(vat_rate))
    return (net_price * (1 + rate)).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)


def to_net(gross_price: Decimal, vat_rate: Decimal | float) -> Decimal:
    """Convert a gross (with VAT) price to net (without VAT).

    Args:
        gross_price: Price with VAT.
        vat_rate: VAT rate as a decimal (e.g., 0.19 for 19%).

    Returns:
        Price without VAT, rounded to 2 decimal places.
    """
    rate = Decimal(str(vat_rate))
    return (gross_price / (1 + rate)).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
