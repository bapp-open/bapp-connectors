"""
Gemini <-> DTO mappers.

Key differences from OpenAI/Anthropic:
- Messages use "contents" with role "user"/"model" (not "assistant")
- Content is always parts: [{"text": "..."}]
- System instruction is a top-level field, not a message
- Tool calling uses functionDeclarations / functionCall / functionResponse
- Usage: promptTokenCount, candidatesTokenCount, totalTokenCount
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime

from bapp_connectors.core.dto import (
    ChatMessage,
    ChatRole,
    EmbeddingResult,
    FinishReason,
    ImageResult,
    LLMResponse,
    ModelInfo,
    ProviderMeta,
    TokenUsage,
    ToolCall,
    ToolDefinition,
)

_FINISH_MAP: dict[str, FinishReason] = {
    "STOP": FinishReason.STOP,
    "MAX_TOKENS": FinishReason.LENGTH,
    "SAFETY": FinishReason.CONTENT_FILTER,
    "RECITATION": FinishReason.CONTENT_FILTER,
}


def _content_block_to_gemini_part(block: dict) -> dict:
    """Convert a multimodal content block to a Gemini part dict."""
    block_type = block.get("type")

    if block_type == "text":
        return {"text": block["text"]}

    if block_type == "image":
        b64 = base64.b64encode(block["data"]).decode("ascii")
        return {"inlineData": {"mimeType": block.get("mime_type", "image/jpeg"), "data": b64}}

    if block_type == "image_url":
        url: str = block["url"]
        if url.startswith("data:"):
            # data:image/jpeg;base64,<data>
            header, _, data = url.partition(",")
            mime = header.split(";")[0].removeprefix("data:")
            return {"inlineData": {"mimeType": mime, "data": data}}
        return {"fileData": {"mimeUri": url, "mimeType": block.get("mime_type", "image/jpeg")}}

    # Fallback: return block as-is
    return block


def gemini_contents_from_chat(messages: list[ChatMessage]) -> tuple[dict | None, list[dict]]:
    """
    Convert ChatMessage DTOs to Gemini format.

    Returns (system_instruction, contents).
    Gemini uses role "user" and "model" (not "assistant").
    """
    system_parts = []
    contents = []

    for msg in messages:
        if msg.role == ChatRole.SYSTEM:
            text = msg.content if isinstance(msg.content, str) else str(msg.content)
            system_parts.append({"text": text})
            continue

        # Map role
        role = "model" if msg.role == ChatRole.ASSISTANT else "user"

        parts = []
        # Text content
        if isinstance(msg.content, str) and msg.content:
            parts.append({"text": msg.content})
        elif isinstance(msg.content, list):
            for block in msg.content:
                parts.append(_content_block_to_gemini_part(block))

        # Tool calls (assistant → functionCall parts)
        if msg.role == ChatRole.ASSISTANT and msg.tool_calls:
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.arguments) if tc.arguments else {}
                except json.JSONDecodeError:
                    args = {}
                parts.append({
                    "functionCall": {"name": tc.name, "args": args},
                })

        # Tool results (tool role → functionResponse parts)
        if msg.role == ChatRole.TOOL:
            parts = [{
                "functionResponse": {
                    "name": msg.name or msg.tool_call_id,
                    "response": {"result": msg.content if isinstance(msg.content, str) else str(msg.content)},
                },
            }]

        if parts:
            contents.append({"role": role, "parts": parts})

    system_instruction = {"parts": system_parts} if system_parts else None
    return system_instruction, contents


def gemini_tools_from_definitions(tools: list[ToolDefinition]) -> list[dict]:
    """Convert ToolDefinition DTOs to Gemini tools format."""
    declarations = []
    for tool in tools:
        decl: dict = {"name": tool.name}
        if tool.description:
            decl["description"] = tool.description
        if tool.parameters:
            decl["parameters"] = tool.parameters
        declarations.append(decl)
    return [{"functionDeclarations": declarations}]


def llm_response_from_gemini(raw: dict) -> LLMResponse:
    """Map a Gemini generateContent response to an LLMResponse DTO."""
    candidates = raw.get("candidates", [])
    content = candidates[0].get("content", {}) if candidates else {}
    parts = content.get("parts", [])

    text_parts = []
    tool_calls = []
    for part in parts:
        if "text" in part:
            text_parts.append(part["text"])
        elif "functionCall" in part:
            fc = part["functionCall"]
            tool_calls.append(ToolCall(
                id="",
                name=fc.get("name", ""),
                arguments=json.dumps(fc.get("args", {})),
            ))

    # Finish reason
    finish_reason_str = candidates[0].get("finishReason", "") if candidates else ""

    # Usage
    usage_meta = raw.get("usageMetadata", {})
    usage = TokenUsage(
        prompt_tokens=usage_meta.get("promptTokenCount", 0),
        completion_tokens=usage_meta.get("candidatesTokenCount", 0),
        total_tokens=usage_meta.get("totalTokenCount", 0),
    )

    return LLMResponse(
        content="\n".join(text_parts),
        model=raw.get("modelVersion", ""),
        usage=usage,
        finish_reason=_FINISH_MAP.get(finish_reason_str),
        tool_calls=tool_calls,
        provider_meta=ProviderMeta(
            provider="gemini",
            raw_id="",
            raw_payload=raw,
            fetched_at=datetime.now(UTC),
        ),
    )


def model_info_from_gemini(raw: dict) -> ModelInfo:
    """Map a Gemini model object to a ModelInfo DTO."""
    # Model name comes as "models/gemini-2.0-flash" — strip prefix
    name = raw.get("name", "")
    model_id = name.removeprefix("models/") if name.startswith("models/") else name
    return ModelInfo(
        id=model_id,
        name=raw.get("displayName", model_id),
        context_window=raw.get("inputTokenLimit", 0),
        capabilities=[m for m in raw.get("supportedGenerationMethods", [])],
    )


def embedding_result_from_gemini(raw: dict) -> EmbeddingResult:
    """Map a Gemini embedContent response to an EmbeddingResult DTO."""
    embedding_data = raw.get("embedding", {})
    values = embedding_data.get("values", [])
    return EmbeddingResult(
        embeddings=[values] if values else [],
        model="",
    )


def image_result_from_gemini(raw: dict) -> ImageResult:
    """Map a Gemini generateContent response containing an image to an ImageResult DTO."""
    candidates = raw.get("candidates", [])
    parts = candidates[0].get("content", {}).get("parts", []) if candidates else []

    b64_data = ""
    mime_type = ""
    text_parts: list[str] = []

    for part in parts:
        if "inlineData" in part:
            inline = part["inlineData"]
            b64_data = inline.get("data", "")
            mime_type = inline.get("mimeType", "")
        elif "text" in part:
            text_parts.append(part["text"])

    return ImageResult(
        b64_data=b64_data,
        mime_type=mime_type,
        revised_prompt="\n".join(text_parts),
    )
