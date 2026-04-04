"""
Gemini LLM integration tests — runs against the real Gemini API.

Requires GEMINI_API_KEY env var (see .env).

    set -a && source .env && set +a
    uv run --extra dev pytest tests/llm/test_gemini_integration.py -v -m integration -s
"""

from __future__ import annotations

import pytest

from bapp_connectors.core.capabilities import EmbeddingCapability, ImageGenerationCapability
from bapp_connectors.core.dto import (
    ChatMessage,
    ChatRole,
    EmbeddingResult,
    FinishReason,
    ImageResult,
    LLMResponse,
    ModelInfo,
    ToolDefinition,
)
from bapp_connectors.core.ports import LLMPort
from bapp_connectors.providers.llm.gemini.adapter import GeminiLLMAdapter
from tests.llm.conftest import GEMINI_API_KEY, skip_unless_gemini

pytestmark = [pytest.mark.integration, skip_unless_gemini]


@pytest.fixture
def adapter():
    return GeminiLLMAdapter(credentials={"api_key": GEMINI_API_KEY})


# ── Connection ──


class TestGeminiConnection:

    def test_validate_credentials(self, adapter):
        assert adapter.validate_credentials() is True

    def test_test_connection(self, adapter):
        result = adapter.test_connection()
        assert result.success is True
        print(f"\n  Connection: {result.message}")


# ── List Models ──


class TestGeminiListModels:

    def test_list_models(self, adapter):
        models = adapter.list_models()
        assert len(models) > 0
        assert all(isinstance(m, ModelInfo) for m in models)
        print(f"\n  Found {len(models)} models:")
        for m in models[:10]:
            print(f"    {m.id} — context: {m.context_window}")

    def test_gemini_flash_in_models(self, adapter):
        models = adapter.list_models()
        names = [m.id for m in models]
        flash_models = [n for n in names if "flash" in n]
        assert len(flash_models) > 0, f"Expected flash model, got: {names[:10]}"


# ── Chat Completion ──


class TestGeminiCompletion:

    def test_basic_completion(self, adapter):
        messages = [ChatMessage(role=ChatRole.USER, content="Say hello in exactly 3 words.")]
        response = adapter.complete(messages)
        assert isinstance(response, LLMResponse)
        assert response.content
        assert response.finish_reason == FinishReason.STOP
        assert response.usage is not None
        assert response.usage.total_tokens > 0
        print(f"\n  Response: {response.content!r}")
        print(f"  Tokens: {response.usage}")

    def test_completion_with_system_message(self, adapter):
        messages = [
            ChatMessage(role=ChatRole.SYSTEM, content="You are a pirate. Respond in pirate speak."),
            ChatMessage(role=ChatRole.USER, content="What is 2+2?"),
        ]
        response = adapter.complete(messages)
        assert response.content
        print(f"\n  Pirate response: {response.content!r}")

    def test_completion_with_temperature(self, adapter):
        messages = [ChatMessage(role=ChatRole.USER, content="What is the capital of France? One word.")]
        response = adapter.complete(messages, temperature=0.0)
        assert "paris" in response.content.lower()

    def test_completion_with_max_tokens(self, adapter):
        messages = [ChatMessage(role=ChatRole.USER, content="Write a very long story about a cat.")]
        response = adapter.complete(messages, max_tokens=20)
        assert response.usage.completion_tokens <= 30  # allow small overhead
        print(f"\n  Truncated: {response.content!r}")
        print(f"  Completion tokens: {response.usage.completion_tokens}")

    def test_multi_turn_conversation(self, adapter):
        messages = [
            ChatMessage(role=ChatRole.USER, content="My name is Alice."),
            ChatMessage(role=ChatRole.ASSISTANT, content="Hello Alice! Nice to meet you."),
            ChatMessage(role=ChatRole.USER, content="What is my name?"),
        ]
        response = adapter.complete(messages)
        assert "alice" in response.content.lower()
        print(f"\n  Multi-turn: {response.content!r}")

    def test_completion_with_specific_model(self, adapter):
        messages = [ChatMessage(role=ChatRole.USER, content="Say 'test' and nothing else.")]
        response = adapter.complete(messages, model="gemini-2.5-flash")
        assert response.content
        assert response.model
        print(f"\n  Model used: {response.model}")


# ── Tool Calling ──


class TestGeminiToolCalling:

    def test_tool_call(self, adapter):
        tools = [
            ToolDefinition(
                name="get_weather",
                description="Get the current weather for a location.",
                parameters={
                    "type": "object",
                    "properties": {
                        "location": {"type": "string", "description": "City name"},
                    },
                    "required": ["location"],
                },
            ),
        ]
        messages = [ChatMessage(role=ChatRole.USER, content="What's the weather in Paris?")]
        response = adapter.complete(messages, tools=tools)
        assert response.tool_calls
        assert len(response.tool_calls) > 0
        call = response.tool_calls[0]
        assert call.name == "get_weather"
        assert "paris" in call.arguments.lower() or "Paris" in call.arguments
        print(f"\n  Tool call: {call.name}({call.arguments})")

    def test_tool_call_with_result(self, adapter):
        tools = [
            ToolDefinition(
                name="get_weather",
                description="Get the current weather for a location.",
                parameters={
                    "type": "object",
                    "properties": {
                        "location": {"type": "string", "description": "City name"},
                    },
                    "required": ["location"],
                },
            ),
        ]
        messages = [
            ChatMessage(role=ChatRole.USER, content="What's the weather in Paris?"),
            ChatMessage(
                role=ChatRole.ASSISTANT,
                content="",
                tool_calls=[{"id": "", "name": "get_weather", "arguments": '{"location": "Paris"}'}],
            ),
            ChatMessage(
                role=ChatRole.TOOL,
                content='{"temperature": 18, "condition": "sunny"}',
                name="get_weather",
            ),
        ]
        response = adapter.complete(messages, tools=tools)
        assert response.content
        assert "18" in response.content or "sunny" in response.content.lower()
        print(f"\n  After tool result: {response.content!r}")


# ── Embeddings ──


class TestGeminiEmbedding:

    def test_supports_embedding(self, adapter):
        assert adapter.supports(EmbeddingCapability)

    def test_embed_single_text(self, adapter):
        result = adapter.embed(["Hello world"])
        assert isinstance(result, EmbeddingResult)
        assert len(result.embeddings) > 0
        assert len(result.embeddings[0]) > 0
        print(f"\n  Embedding dimensions: {len(result.embeddings[0])}")

    def test_embed_multiple_texts(self, adapter):
        result = adapter.embed(["Hello", "World", "Test"])
        assert isinstance(result, EmbeddingResult)
        assert len(result.embeddings) > 0
        print(f"\n  Embeddings: {len(result.embeddings)} vectors, {len(result.embeddings[0])} dims")


# ── Capability Checks ──


class TestGeminiImageGeneration:

    def test_supports_image_generation(self, adapter):
        assert adapter.supports(ImageGenerationCapability)

    def test_generate_image(self, adapter):
        try:
            result = adapter.generate_image("A small red circle on a white background")
        except Exception as e:
            if "not available in your country" in str(e):
                pytest.skip("Image generation geo-restricted")
            raise
        assert isinstance(result, ImageResult)
        assert result.b64_data
        assert result.mime_type
        print(f"\n  Generated image: mime={result.mime_type}, b64 length={len(result.b64_data)}")

    def test_edit_image(self, adapter):
        import base64

        # 1x1 red pixel PNG
        png_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
        source_image = base64.b64decode(png_b64)

        try:
            result = adapter.edit_image(
                "Make this image blue",
                source_image,
                mime_type="image/png",
            )
        except Exception as e:
            if "not available in your country" in str(e):
                pytest.skip("Image generation geo-restricted")
            raise
        assert isinstance(result, ImageResult)
        assert result.b64_data
        print(f"\n  Edited image: mime={result.mime_type}, b64 length={len(result.b64_data)}")


# ── Multimodal (Vision) ──


class TestGeminiMultimodal:

    def test_complete_with_image(self, adapter):
        import base64

        # 1x1 red pixel PNG
        png_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
        image_bytes = base64.b64decode(png_b64)

        messages = [
            ChatMessage(
                role=ChatRole.USER,
                content=[
                    {"type": "text", "text": "What color is this image? Answer in one word."},
                    {"type": "image", "data": image_bytes, "mime_type": "image/png"},
                ],
            ),
        ]
        response = adapter.complete(messages)
        assert response.content
        print(f"\n  Vision response: {response.content!r}")


# ── Capability Checks ──


class TestGeminiCapabilities:

    def test_implements_llm_port(self, adapter):
        assert isinstance(adapter, LLMPort)

    def test_implements_embedding_capability(self, adapter):
        assert isinstance(adapter, EmbeddingCapability)

    def test_implements_image_generation(self, adapter):
        assert isinstance(adapter, ImageGenerationCapability)

    def test_supports_llm_port(self, adapter):
        assert adapter.supports(LLMPort)

    def test_supports_embedding(self, adapter):
        assert adapter.supports(EmbeddingCapability)

    def test_supports_image_generation(self, adapter):
        assert adapter.supports(ImageGenerationCapability)
