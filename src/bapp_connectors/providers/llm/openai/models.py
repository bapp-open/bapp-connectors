"""
Pydantic models for OpenAI API payloads.

These model the raw OpenAI API — they are NOT normalized DTOs.
"""

from __future__ import annotations

from pydantic import BaseModel


class OpenAIChatMessage(BaseModel):
    role: str = ""
    content: str | list | None = None
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[dict] | None = None


class OpenAIUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class OpenAIChatChoice(BaseModel):
    index: int = 0
    message: OpenAIChatMessage = OpenAIChatMessage()
    finish_reason: str | None = None


class OpenAIChatResponse(BaseModel):
    id: str = ""
    model: str = ""
    choices: list[OpenAIChatChoice] = []
    usage: OpenAIUsage = OpenAIUsage()


class OpenAIModel(BaseModel):
    id: str = ""
    owned_by: str = ""


class OpenAIEmbeddingData(BaseModel):
    embedding: list[float] = []
    index: int = 0


class OpenAIEmbeddingResponse(BaseModel):
    data: list[OpenAIEmbeddingData] = []
    model: str = ""
    usage: OpenAIUsage = OpenAIUsage()
