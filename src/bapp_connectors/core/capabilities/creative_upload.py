"""
Creative upload capability — optional interface for ads providers that can
upload media assets and create ad creatives.

Closes the gap between "I have a video file" and "I have a running ad":
upload_media stores the asset on the platform, create_creative wraps it in a
platform creative whose id feeds ``Ad.creative.id`` (or, on platforms with
inline creatives like TikTok, returns the creative with the media reference
populated in ``extra`` for ``create_ad`` to consume).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bapp_connectors.core.dto.ads import AdCreative, AdMediaAsset, UploadedAdMedia


class CreativeUploadCapability(ABC):
    """Adapter can upload media to the ad platform and build creatives from it."""

    @abstractmethod
    def upload_media(self, asset: AdMediaAsset) -> UploadedAdMedia:
        """Upload an image/video to the platform's asset library.

        Raises ValidationError when the given source (url / file_path /
        content) isn't supported by the platform, UnsupportedFeatureError when
        the platform cannot host that media type at all.
        """
        ...

    @abstractmethod
    def create_creative(self, creative: AdCreative, media: UploadedAdMedia | None = None) -> AdCreative:
        """Create a platform creative from normalized content plus uploaded media.

        Returns the creative with the platform ``id`` set. Platforms whose
        creatives are inline to the ad (TikTok) return the creative with the
        media reference merged into ``extra`` instead; platforms without a
        creative resource (Google search ads) raise UnsupportedFeatureError.
        """
        ...
