"""
Normalized DTOs for LLM operations (chat completion, embeddings, image generation).
"""

from __future__ import annotations

from enum import StrEnum

from .base import BaseDTO


class ChatRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class FinishReason(StrEnum):
    STOP = "stop"
    LENGTH = "length"
    TOOL_CALLS = "tool_calls"
    CONTENT_FILTER = "content_filter"
    ERROR = "error"


class ToolDefinition(BaseDTO):
    """A tool/function definition that the LLM can call."""

    name: str
    description: str = ""
    parameters: dict = {}  # JSON Schema


class ToolCall(BaseDTO):
    """A tool/function call made by the LLM."""

    id: str = ""
    name: str = ""
    arguments: str = ""  # JSON-encoded string


class ChatMessage(BaseDTO):
    """Normalized chat message for LLM conversations."""

    role: ChatRole
    content: str | list = ""  # str for text, list for content blocks (images, etc.)
    name: str = ""
    tool_call_id: str = ""
    tool_calls: list[ToolCall] = []


class TokenUsage(BaseDTO):
    """Token usage from an LLM call."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ModelPricing(BaseDTO):
    """Pricing per million tokens."""

    input_price_per_million: float = 0.0
    output_price_per_million: float = 0.0


class ModelInfo(BaseDTO):
    """Information about an available LLM model."""

    id: str
    name: str = ""
    context_window: int = 0
    capabilities: list[str] = []
    pricing: ModelPricing | None = None


class LLMResponse(BaseDTO):
    """Response from an LLM chat completion."""

    content: str = ""
    model: str = ""
    usage: TokenUsage | None = None
    finish_reason: FinishReason | None = None
    tool_calls: list[ToolCall] = []


class EmbeddingResult(BaseDTO):
    """Response from an embedding request."""

    embeddings: list[list[float]] = []
    model: str = ""
    usage: TokenUsage | None = None


class LLMChunk(BaseDTO):
    """A single chunk from a streaming LLM response."""

    delta: str = ""
    finish_reason: FinishReason | None = None
    usage: TokenUsage | None = None  # only populated on the final chunk


class TranscriptionResult(BaseDTO):
    """Response from an audio transcription request."""

    text: str = ""
    language: str = ""
    duration: float = 0.0  # audio duration in seconds
    segments: list[dict] = []  # timestamped segments (verbose mode)


class ImageResult(BaseDTO):
    """Response from an image generation request."""

    url: str = ""
    b64_data: str = ""
    revised_prompt: str = ""
    mime_type: str = ""
