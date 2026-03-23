"""Image generation capability — optional interface for AI image generation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bapp_connectors.core.dto import ImageResult


class ImageGenerationCapability(ABC):
    """Adapter supports generating images from text prompts."""

    @abstractmethod
    def generate_image(
        self,
        prompt: str,
        model: str | None = None,
        size: str = "1024x1024",
        **kwargs,
    ) -> ImageResult:
        """Generate an image from a text prompt."""
        ...
