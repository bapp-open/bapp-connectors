"""
OpenAI <-> DTO mappers.

Converts between raw OpenAI API payloads and normalized framework DTOs.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime

from bapp_connectors.core.dto import (
    EmbeddingResult,
    FinishReason,
    ImageResult,
    LLMResponse,
    ModelInfo,
    ProviderMeta,
    TokenUsage,
    ToolCall,
    ToolDefinition,
    TranscriptionResult,
)

# ── Finish reason mapping ──

_FINISH_MAP: dict[str, FinishReason] = {
    "stop": FinishReason.STOP,
    "length": FinishReason.LENGTH,
    "tool_calls": FinishReason.TOOL_CALLS,
    "content_filter": FinishReason.CONTENT_FILTER,
}


# ── Request mappers ──


def _content_block_to_openai(block: dict) -> dict:
    """Convert a multimodal content block to OpenAI's content part format."""
    block_type = block.get("type", "")
    if block_type == "text":
        return {"type": "text", "text": block.get("text", "")}
    if block_type == "image":
        data = block.get("data", b"")
        mime = block.get("mime_type", "image/jpeg")
        if isinstance(data, bytes):
            data = base64.b64encode(data).decode("ascii")
        return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}}
    if block_type == "image_url":
        return {"type": "image_url", "image_url": {"url": block.get("url", "")}}
    return block


def openai_messages_from_chat(messages) -> list[dict]:
    """Convert ChatMessage DTOs to OpenAI message format."""
    result = []
    for msg in messages:
        if isinstance(msg.content, list):
            content = [_content_block_to_openai(block) for block in msg.content]
        else:
            content = msg.content
        entry: dict = {"role": msg.role.value, "content": content}
        if msg.name:
            entry["name"] = msg.name
        if msg.tool_call_id:
            entry["tool_call_id"] = msg.tool_call_id
        if msg.tool_calls:
            entry["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": tc.arguments},
                }
                for tc in msg.tool_calls
            ]
        result.append(entry)
    return result


def openai_tools_from_definitions(tools: list[ToolDefinition]) -> list[dict]:
    """Convert ToolDefinition DTOs to OpenAI tools format."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        }
        for tool in tools
    ]


# ── Response mappers ──


def llm_response_from_openai(raw: dict) -> LLMResponse:
    """Map an OpenAI chat completion response to an LLMResponse DTO."""
    choices = raw.get("choices", [])
    message = choices[0].get("message", {}) if choices else {}
    raw_finish = choices[0].get("finish_reason", "") if choices else ""

    # Extract tool calls
    tool_calls = []
    for tc in message.get("tool_calls", []) or []:
        func = tc.get("function", {})
        tool_calls.append(ToolCall(
            id=tc.get("id", ""),
            name=func.get("name", ""),
            arguments=func.get("arguments", ""),
        ))

    # Map usage
    raw_usage = raw.get("usage", {})
    usage = TokenUsage(
        prompt_tokens=raw_usage.get("prompt_tokens", 0),
        completion_tokens=raw_usage.get("completion_tokens", 0),
        total_tokens=raw_usage.get("total_tokens", 0),
    )

    return LLMResponse(
        content=message.get("content", "") or "",
        model=raw.get("model", ""),
        usage=usage,
        finish_reason=_FINISH_MAP.get(raw_finish),
        tool_calls=tool_calls,
        provider_meta=ProviderMeta(
            provider="openai",
            raw_id=raw.get("id", ""),
            raw_payload=raw,
            fetched_at=datetime.now(UTC),
        ),
    )


def model_info_from_openai(raw: dict) -> ModelInfo:
    """Map an OpenAI model object to a ModelInfo DTO."""
    return ModelInfo(
        id=raw.get("id", ""),
        name=raw.get("id", ""),
    )


def embedding_result_from_openai(raw: dict) -> EmbeddingResult:
    """Map an OpenAI embeddings response to an EmbeddingResult DTO."""
    embeddings = [item.get("embedding", []) for item in raw.get("data", [])]
    raw_usage = raw.get("usage", {})
    usage = TokenUsage(
        prompt_tokens=raw_usage.get("prompt_tokens", 0),
        total_tokens=raw_usage.get("total_tokens", 0),
    )
    return EmbeddingResult(
        embeddings=embeddings,
        model=raw.get("model", ""),
        usage=usage,
    )


def transcription_result_from_openai(raw: dict | str) -> TranscriptionResult:
    """Map an OpenAI transcription response to a TranscriptionResult DTO.

    Handles both verbose_json (dict) and plain text (str) response formats.
    """
    if isinstance(raw, str):
        return TranscriptionResult(text=raw)

    segments = []
    for seg in raw.get("segments", []):
        segments.append({
            "start": seg.get("start", 0),
            "end": seg.get("end", 0),
            "text": seg.get("text", ""),
        })

    return TranscriptionResult(
        text=raw.get("text", ""),
        language=raw.get("language", ""),
        duration=raw.get("duration", 0.0),
        segments=segments,
        provider_meta=ProviderMeta(
            provider="openai",
            raw_id="",
            raw_payload=raw if isinstance(raw, dict) else {"text": raw},
            fetched_at=datetime.now(UTC),
        ),
    )


def image_result_from_openai(raw: dict) -> ImageResult:
    """Map an OpenAI image generation response to an ImageResult DTO."""
    data = raw.get("data", [])
    if not data:
        return ImageResult()
    item = data[0]
    return ImageResult(
        url=item.get("url", ""),
        b64_data=item.get("b64_json", ""),
        revised_prompt=item.get("revised_prompt", ""),
        provider_meta=ProviderMeta(provider="openai", raw_payload=raw, fetched_at=datetime.now(UTC)),
    )
