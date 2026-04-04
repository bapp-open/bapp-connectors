"""Image generation capability — optional interface for AI image generation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bapp_connectors.core.dto import ImageResult


class ImageGenerationCapability(ABC):
    """Adapter supports generating and editing images."""

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

    def edit_image(
        self,
        prompt: str,
        image: bytes,
        *,
        model: str | None = None,
        size: str = "1024x1024",
        **kwargs,
    ) -> ImageResult:
        """Edit/transform an image using a text prompt (image-to-image).

        Args:
            prompt: Text prompt describing the desired transformation.
            image: Source image as raw bytes.
            model: Model to use. If None, uses provider default.
            size: Output image size (e.g. "1024x1024").
            **kwargs: Provider-specific parameters (e.g. aspect_ratio, mime_type).

        Raises:
            NotImplementedError: If the provider does not support image editing.
        """
        raise NotImplementedError(f"{type(self).__name__} does not support edit_image")
