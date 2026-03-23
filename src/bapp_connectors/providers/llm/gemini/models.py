"""Pydantic models for Gemini API payloads."""

from __future__ import annotations

from pydantic import BaseModel


class GeminiPart(BaseModel):
    text: str = ""
    functionCall: dict | None = None
    functionResponse: dict | None = None


class GeminiContent(BaseModel):
    role: str = ""
    parts: list[GeminiPart] = []


class GeminiUsageMetadata(BaseModel):
    promptTokenCount: int = 0
    candidatesTokenCount: int = 0
    totalTokenCount: int = 0


class GeminiCandidate(BaseModel):
    content: GeminiContent = GeminiContent()
    finishReason: str = ""


class GeminiGenerateResponse(BaseModel):
    candidates: list[GeminiCandidate] = []
    usageMetadata: GeminiUsageMetadata = GeminiUsageMetadata()
    modelVersion: str = ""


class GeminiModel(BaseModel):
    name: str = ""
    displayName: str = ""
    inputTokenLimit: int = 0
    outputTokenLimit: int = 0
    supportedGenerationMethods: list[str] = []
