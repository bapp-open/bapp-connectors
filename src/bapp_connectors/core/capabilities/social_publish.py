"""
Social publish capability — optional interface for social providers that can
create posts, not just read them.

Some platforms publish synchronously (a post id comes back immediately), others
asynchronously (the platform transcodes/reviews first). PublishResult.status
tells them apart; poll check_publish_status with PublishResult.publish_id for
async platforms until PUBLISHED or FAILED.

get_publish_profile declares what each format accepts (media types, limits,
mentions, product tags, location); see bapp_connectors.core.social_profile.fit_draft.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from bapp_connectors.core.dto.social import SocialPublishProfile

if TYPE_CHECKING:
    from bapp_connectors.core.dto.social import PublishResult, SocialPostDraft


class SocialPublishCapability(ABC):
    """Adapter can publish posts to the connected account."""

    @abstractmethod
    def publish_post(self, draft: SocialPostDraft) -> PublishResult:
        """Publish a post/video.

        Raises ValidationError when the draft's media source (media_url /
        file_path / content) isn't supported by the platform.
        """
        ...

    @abstractmethod
    def check_publish_status(self, publish_id: str) -> PublishResult:
        """Poll the status of an asynchronous publish.

        Synchronous platforms return PUBLISHED for ids of existing posts.
        """
        ...

    def get_publish_profile(self) -> SocialPublishProfile:
        """What the channel accepts per format. Empty = no profile declared."""
        return SocialPublishProfile()
