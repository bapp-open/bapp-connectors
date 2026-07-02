"""
Google Ads specific error helpers.

HTTP-level errors (401/403 auth, 429 rate limit, other 4xx/5xx) are already
classified into framework errors by ResilientHttpClient. These helpers cover
Google Ads specifics: resource-name parsing and "no GAQL rows" lookups.
"""

from __future__ import annotations

from typing import NoReturn

from bapp_connectors.core.errors import PermanentProviderError


def extract_resource_id(resource_name: str) -> str:
    """Return the last path segment of a Google Ads resource name.

    "customers/1/campaigns/42" -> "42"
    "customers/1/adGroupAds/123~456" -> "123~456" (composite adGroupAd id)
    """
    return resource_name.rstrip("/").rsplit("/", 1)[-1]


def extract_ad_id(resource_name: str) -> str:
    """Return the ad id from an adGroupAd resource name.

    "customers/1/adGroupAds/123~456" -> "456" (the part after the "~").
    """
    return extract_resource_id(resource_name).split("~")[-1]


def not_found(entity: str, entity_id: str) -> NoReturn:
    """Raise a PermanentProviderError for an entity whose GAQL lookup returned no rows."""
    raise PermanentProviderError(f"Google Ads {entity} '{entity_id}' not found.", status_code=404)
