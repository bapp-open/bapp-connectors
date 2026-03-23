"""
Pydantic models for Anthropic API payloads.

These model the raw Anthropic API — they are NOT normalized DTOs.
"""

from __future__ import annotations

from pydantic import BaseModel


class AnthropicContentBlock(BaseModel):
    type: str = "text"
    text: str = ""
    id: str | None = None
    name: str | None = None
    input: dict | None = None


class AnthropicUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0


class AnthropicMessageResponse(BaseModel):
    id: str = ""
    type: str = "message"
    role: str = "assistant"
    content: list[AnthropicContentBlock] = []
    model: str = ""
    stop_reason: str | None = None
    usage: AnthropicUsage = AnthropicUsage()
