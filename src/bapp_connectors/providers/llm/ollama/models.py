"""Pydantic models for Ollama API payloads."""

from __future__ import annotations

from pydantic import BaseModel


class OllamaMessage(BaseModel):
    role: str = ""
    content: str = ""
    tool_calls: list[dict] | None = None


class OllamaChatResponse(BaseModel):
    model: str = ""
    message: OllamaMessage = OllamaMessage()
    done: bool = False
    done_reason: str = ""
    prompt_eval_count: int = 0
    eval_count: int = 0
    total_duration: int = 0


class OllamaModelTag(BaseModel):
    name: str = ""
    modified_at: str = ""
    size: int = 0


class OllamaEmbedResponse(BaseModel):
    model: str = ""
    embeddings: list[list[float]] = []
    prompt_eval_count: int = 0
