"""
LLM port — the common contract for all LLM provider adapters.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING

from bapp_connectors.core.ports.base import BasePort

if TYPE_CHECKING:
    from bapp_connectors.core.dto import ChatMessage, LLMResponse, ModelInfo


class LLMPort(BasePort):
    """
    Common contract for all LLM adapters (OpenAI, Anthropic, etc.).

    Covers: chat completion, model listing.
    Optional capabilities (embedding, streaming, image generation)
    are separate ABC interfaces in core/capabilities/.
    """

    @abstractmethod
    def complete(
        self,
        messages: list[ChatMessage],
        model: str | None = None,
        **kwargs,
    ) -> LLMResponse:
        """
        Send a chat completion request.

        Args:
            messages: Conversation history as normalized ChatMessage DTOs.
            model: Model identifier. If None, uses default from config.
            **kwargs: Provider-specific params (temperature, max_tokens, tools, etc.).
                      tools: list[ToolDefinition] for function calling.
        """
        ...

    @abstractmethod
    def list_models(self) -> list[ModelInfo]:
        """List available models from this provider."""
        ...
