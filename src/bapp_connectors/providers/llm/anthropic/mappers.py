"""
Anthropic <-> DTO mappers.

Handles key differences from OpenAI:
- System message is a top-level param, not a message with role: system
- Content is always an array of content blocks
- Tool use is represented as content blocks, not a separate field
- Usage fields are input_tokens/output_tokens (not prompt_tokens/completion_tokens)
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from bapp_connectors.core.dto import (
    ChatMessage,
    ChatRole,
    FinishReason,
    LLMResponse,
    ModelInfo,
    ModelPricing,
    ProviderMeta,
    TokenUsage,
    ToolCall,
    ToolDefinition,
)

# ── Finish reason mapping ──

_STOP_MAP: dict[str, FinishReason] = {
    "end_turn": FinishReason.STOP,
    "stop_sequence": FinishReason.STOP,
    "max_tokens": FinishReason.LENGTH,
    "tool_use": FinishReason.TOOL_CALLS,
}


# ── Request mappers ──


def anthropic_messages_from_chat(messages: list[ChatMessage]) -> tuple[str, list[dict]]:
    """
    Convert ChatMessage DTOs to Anthropic format.

    Returns (system_prompt, messages_list).
    System messages are extracted and concatenated into a single string.
    """
    system_parts = []
    result = []

    for msg in messages:
        if msg.role == ChatRole.SYSTEM:
            system_parts.append(msg.content if isinstance(msg.content, str) else str(msg.content))
            continue

        if msg.role == ChatRole.TOOL:
            # Anthropic expects tool results as user messages with tool_result content blocks
            result.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": msg.tool_call_id,
                    "content": msg.content if isinstance(msg.content, str) else str(msg.content),
                }],
            })
            continue

        # Build content blocks
        if isinstance(msg.content, str):
            content = [{"type": "text", "text": msg.content}] if msg.content else []
        elif isinstance(msg.content, list):
            content = msg.content
        else:
            content = [{"type": "text", "text": str(msg.content)}]

        # Add tool_use blocks for assistant messages with tool calls
        if msg.role == ChatRole.ASSISTANT and msg.tool_calls:
            for tc in msg.tool_calls:
                try:
                    input_data = json.loads(tc.arguments) if tc.arguments else {}
                except json.JSONDecodeError:
                    input_data = {}
                content.append({
                    "type": "tool_use",
                    "id": tc.id,
                    "name": tc.name,
                    "input": input_data,
                })

        result.append({
            "role": msg.role.value,
            "content": content,
        })

    system_prompt = "\n\n".join(system_parts)
    return system_prompt, result


def anthropic_tools_from_definitions(tools: list[ToolDefinition]) -> list[dict]:
    """Convert ToolDefinition DTOs to Anthropic tools format."""
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.parameters,
        }
        for tool in tools
    ]


# ── Response mappers ──


def llm_response_from_anthropic(raw: dict) -> LLMResponse:
    """Map an Anthropic messages response to an LLMResponse DTO."""
    content_blocks = raw.get("content", [])

    # Extract text content
    text_parts = []
    tool_calls = []
    for block in content_blocks:
        if block.get("type") == "text":
            text_parts.append(block.get("text", ""))
        elif block.get("type") == "tool_use":
            tool_calls.append(ToolCall(
                id=block.get("id", ""),
                name=block.get("name", ""),
                arguments=json.dumps(block.get("input", {})),
            ))

    # Map usage (Anthropic uses input_tokens/output_tokens)
    raw_usage = raw.get("usage", {})
    input_tokens = raw_usage.get("input_tokens", 0)
    output_tokens = raw_usage.get("output_tokens", 0)
    usage = TokenUsage(
        prompt_tokens=input_tokens,
        completion_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
    )

    return LLMResponse(
        content="\n".join(text_parts),
        model=raw.get("model", ""),
        usage=usage,
        finish_reason=_STOP_MAP.get(raw.get("stop_reason", "")),
        tool_calls=tool_calls,
        provider_meta=ProviderMeta(
            provider="anthropic",
            raw_id=raw.get("id", ""),
            raw_payload=raw,
            fetched_at=datetime.now(UTC),
        ),
    )


# ── Model listing (hardcoded — Anthropic has no models endpoint) ──


def hardcoded_models() -> list[ModelInfo]:
    """Return known Anthropic models with pricing and context windows."""
    return [
        ModelInfo(
            id="claude-opus-4-20250514",
            name="Claude Opus 4",
            context_window=200000,
            capabilities=["chat", "tool_use", "vision"],
            pricing=ModelPricing(input_price_per_million=15.0, output_price_per_million=75.0),
        ),
        ModelInfo(
            id="claude-sonnet-4-20250514",
            name="Claude Sonnet 4",
            context_window=200000,
            capabilities=["chat", "tool_use", "vision"],
            pricing=ModelPricing(input_price_per_million=3.0, output_price_per_million=15.0),
        ),
        ModelInfo(
            id="claude-haiku-4-5-20251001",
            name="Claude Haiku 4.5",
            context_window=200000,
            capabilities=["chat", "tool_use", "vision"],
            pricing=ModelPricing(input_price_per_million=0.80, output_price_per_million=4.0),
        ),
    ]
