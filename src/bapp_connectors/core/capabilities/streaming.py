"""Streaming capability — optional interface for streaming LLM responses."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:
    from bapp_connectors.core.dto import ChatMessage, LLMChunk


class StreamingCapability(ABC):
    """Adapter supports streaming chat completion responses."""

    @abstractmethod
    def stream(
        self,
        messages: list[ChatMessage],
        model: str | None = None,
        **kwargs,
    ) -> Iterator[LLMChunk]:
        """Stream a chat completion response chunk by chunk."""
        ...
