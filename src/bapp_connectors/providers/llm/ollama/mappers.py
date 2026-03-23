"""
Ollama <-> DTO mappers.

Ollama's API is similar to OpenAI but with some differences:
- Chat uses /api/chat with messages in the same format
- Token counts: prompt_eval_count, eval_count (not prompt_tokens/completion_tokens)
- Models listed via /api/tags with name, size, modified_at
- Embeddings return embeddings[] array
- Tool calls in message.tool_calls
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from bapp_connectors.core.dto import (
    EmbeddingResult,
    FinishReason,
    LLMResponse,
    ModelInfo,
    ProviderMeta,
    TokenUsage,
    ToolCall,
    ToolDefinition,
)

_DONE_REASON_MAP: dict[str, FinishReason] = {
    "stop": FinishReason.STOP,
    "length": FinishReason.LENGTH,
    "tool_calls": FinishReason.TOOL_CALLS,
}


def ollama_messages_from_chat(messages) -> list[dict]:
    """Convert ChatMessage DTOs to Ollama message format."""
    result = []
    for msg in messages:
        entry: dict = {"role": msg.role.value, "content": msg.content if isinstance(msg.content, str) else str(msg.content)}
        if msg.tool_calls:
            entry["tool_calls"] = [
                {"function": {"name": tc.name, "arguments": json.loads(tc.arguments) if tc.arguments else {}}}
                for tc in msg.tool_calls
            ]
        result.append(entry)
    return result


def ollama_tools_from_definitions(tools: list[ToolDefinition]) -> list[dict]:
    """Convert ToolDefinition DTOs to Ollama tools format."""
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


def llm_response_from_ollama(raw: dict) -> LLMResponse:
    """Map an Ollama chat response to an LLMResponse DTO."""
    message = raw.get("message", {})

    tool_calls = []
    for tc in message.get("tool_calls", []) or []:
        func = tc.get("function", {})
        tool_calls.append(ToolCall(
            id="",
            name=func.get("name", ""),
            arguments=json.dumps(func.get("arguments", {})),
        ))

    prompt_tokens = raw.get("prompt_eval_count", 0)
    completion_tokens = raw.get("eval_count", 0)
    usage = TokenUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
    )

    done_reason = raw.get("done_reason", "")

    return LLMResponse(
        content=message.get("content", ""),
        model=raw.get("model", ""),
        usage=usage,
        finish_reason=_DONE_REASON_MAP.get(done_reason),
        tool_calls=tool_calls,
        provider_meta=ProviderMeta(
            provider="ollama",
            raw_id="",
            raw_payload=raw,
            fetched_at=datetime.now(UTC),
        ),
    )


def model_info_from_ollama(raw: dict) -> ModelInfo:
    """Map an Ollama model tag to a ModelInfo DTO."""
    return ModelInfo(
        id=raw.get("name", raw.get("model", "")),
        name=raw.get("name", raw.get("model", "")),
    )


def embedding_result_from_ollama(raw: dict) -> EmbeddingResult:
    """Map an Ollama embed response to an EmbeddingResult DTO."""
    embeddings = raw.get("embeddings", [])
    # Single embedding returned as "embedding" (older API)
    if not embeddings and "embedding" in raw:
        embeddings = [raw["embedding"]]
    prompt_tokens = raw.get("prompt_eval_count", 0)
    return EmbeddingResult(
        embeddings=embeddings,
        model=raw.get("model", ""),
        usage=TokenUsage(prompt_tokens=prompt_tokens, total_tokens=prompt_tokens),
    )
