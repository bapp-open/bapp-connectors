"""Embedding capability — optional interface for text embedding."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bapp_connectors.core.dto import EmbeddingResult


class EmbeddingCapability(ABC):
    """Adapter supports generating text embeddings."""

    @abstractmethod
    def embed(self, texts: list[str], model: str | None = None) -> EmbeddingResult:
        """Generate embeddings for a list of text inputs."""
        ...
