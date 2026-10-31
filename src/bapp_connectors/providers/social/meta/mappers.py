"""
Meta Graph payload -> framework DTO mappers.
"""

from __future__ import annotations

from bapp_connectors.core.dto.social import SocialDestination
from bapp_connectors.providers.social.meta.models import MetaPage


def destinations_from_page(raw: dict) -> list[SocialDestination]:
    """Map one ``me/accounts`` entry to its Facebook Page destination, plus its Instagram account if linked."""
    page = MetaPage.model_validate(raw)
    destinations = [
        SocialDestination(
            id=page.id,
            provider="facebook",
            kind="facebook_page",
            name=page.name,
            username=page.username,
            avatar_url=(page.picture.get("data") or {}).get("url", ""),
            credentials={"token": page.access_token, "page_id": page.id},
        )
    ]
    ig = page.instagram_business_account
    if ig is not None and ig.id:
        destinations.append(
            SocialDestination(
                id=ig.id,
                provider="instagram",
                kind="instagram_account",
                name=ig.name or ig.username,
                username=ig.username,
                avatar_url=ig.profile_picture_url,
                credentials={"token": page.access_token, "ig_user_id": ig.id},
            )
        )
    return destinations
