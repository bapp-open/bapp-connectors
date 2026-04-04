"""Tests for LLM mappers — OpenAI, Anthropic, Gemini."""

import base64
import json

from bapp_connectors.core.dto import (
    ChatMessage,
    ChatRole,
    FinishReason,
    ToolCall,
    ToolDefinition,
)
from bapp_connectors.providers.llm.anthropic.mappers import (
    anthropic_messages_from_chat,
    anthropic_tools_from_definitions,
    hardcoded_models,
    llm_response_from_anthropic,
)
from bapp_connectors.providers.llm.gemini.mappers import (
    _content_block_to_gemini_part,
    gemini_contents_from_chat,
    image_result_from_gemini,
)
from bapp_connectors.providers.llm.openai.mappers import (
    _content_block_to_openai,
    embedding_result_from_openai,
    image_result_from_openai,
    llm_response_from_openai,
    openai_messages_from_chat,
    openai_tools_from_definitions,
)

# ── OpenAI Mappers ──


class TestOpenAIMessages:
    def test_basic_messages(self):
        msgs = [
            ChatMessage(role=ChatRole.USER, content="Hello"),
            ChatMessage(role=ChatRole.ASSISTANT, content="Hi there"),
        ]
        result = openai_messages_from_chat(msgs)
        assert len(result) == 2
        assert result[0] == {"role": "user", "content": "Hello"}
        assert result[1] == {"role": "assistant", "content": "Hi there"}

    def test_system_message(self):
        msgs = [ChatMessage(role=ChatRole.SYSTEM, content="Be helpful")]
        result = openai_messages_from_chat(msgs)
        assert result[0]["role"] == "system"

    def test_tool_calls_in_message(self):
        msgs = [ChatMessage(
            role=ChatRole.ASSISTANT,
            content="",
            tool_calls=[ToolCall(id="call_1", name="get_weather", arguments='{"city": "London"}')],
        )]
        result = openai_messages_from_chat(msgs)
        assert result[0]["tool_calls"][0]["function"]["name"] == "get_weather"

    def test_tool_result_message(self):
        msgs = [ChatMessage(role=ChatRole.TOOL, content="22C sunny", tool_call_id="call_1")]
        result = openai_messages_from_chat(msgs)
        assert result[0]["role"] == "tool"
        assert result[0]["tool_call_id"] == "call_1"


class TestOpenAITools:
    def test_tool_definitions(self):
        tools = [ToolDefinition(name="search", description="Search the web", parameters={"type": "object", "properties": {"q": {"type": "string"}}})]
        result = openai_tools_from_definitions(tools)
        assert result[0]["type"] == "function"
        assert result[0]["function"]["name"] == "search"
        assert result[0]["function"]["parameters"]["properties"]["q"]["type"] == "string"


class TestOpenAIResponse:
    def test_basic_response(self):
        raw = {
            "id": "chatcmpl-123",
            "model": "gpt-4o-mini",
            "choices": [{"message": {"role": "assistant", "content": "Hello!"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        resp = llm_response_from_openai(raw)
        assert resp.content == "Hello!"
        assert resp.model == "gpt-4o-mini"
        assert resp.finish_reason == FinishReason.STOP
        assert resp.usage.prompt_tokens == 10
        assert resp.usage.completion_tokens == 5
        assert resp.usage.total_tokens == 15

    def test_tool_call_response(self):
        raw = {
            "id": "chatcmpl-456",
            "model": "gpt-4o",
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "get_weather", "arguments": '{"city":"Paris"}'}}],
                },
                "finish_reason": "tool_calls",
            }],
            "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
        }
        resp = llm_response_from_openai(raw)
        assert resp.finish_reason == FinishReason.TOOL_CALLS
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].name == "get_weather"
        assert json.loads(resp.tool_calls[0].arguments) == {"city": "Paris"}

    def test_empty_choices(self):
        raw = {"id": "", "model": "", "choices": [], "usage": {}}
        resp = llm_response_from_openai(raw)
        assert resp.content == ""


class TestOpenAIEmbedding:
    def test_embedding_response(self):
        raw = {
            "data": [{"embedding": [0.1, 0.2, 0.3], "index": 0}],
            "model": "text-embedding-3-small",
            "usage": {"prompt_tokens": 5, "total_tokens": 5},
        }
        result = embedding_result_from_openai(raw)
        assert len(result.embeddings) == 1
        assert result.embeddings[0] == [0.1, 0.2, 0.3]
        assert result.model == "text-embedding-3-small"
        assert result.usage.prompt_tokens == 5


# ── Anthropic Mappers ──


class TestAnthropicMessages:
    def test_system_extraction(self):
        msgs = [
            ChatMessage(role=ChatRole.SYSTEM, content="Be concise"),
            ChatMessage(role=ChatRole.USER, content="Hi"),
        ]
        system, messages = anthropic_messages_from_chat(msgs)
        assert system == "Be concise"
        assert len(messages) == 1
        assert messages[0]["role"] == "user"

    def test_content_as_array(self):
        msgs = [ChatMessage(role=ChatRole.USER, content="Hello")]
        _, messages = anthropic_messages_from_chat(msgs)
        assert messages[0]["content"] == [{"type": "text", "text": "Hello"}]

    def test_tool_result_as_user_message(self):
        msgs = [ChatMessage(role=ChatRole.TOOL, content="result data", tool_call_id="toolu_1")]
        _, messages = anthropic_messages_from_chat(msgs)
        assert messages[0]["role"] == "user"
        assert messages[0]["content"][0]["type"] == "tool_result"
        assert messages[0]["content"][0]["tool_use_id"] == "toolu_1"

    def test_assistant_with_tool_calls(self):
        msgs = [ChatMessage(
            role=ChatRole.ASSISTANT,
            content="Let me check",
            tool_calls=[ToolCall(id="toolu_1", name="search", arguments='{"q":"test"}')],
        )]
        _, messages = anthropic_messages_from_chat(msgs)
        content = messages[0]["content"]
        assert content[0]["type"] == "text"
        assert content[1]["type"] == "tool_use"
        assert content[1]["name"] == "search"

    def test_multiple_system_messages(self):
        msgs = [
            ChatMessage(role=ChatRole.SYSTEM, content="Rule 1"),
            ChatMessage(role=ChatRole.SYSTEM, content="Rule 2"),
            ChatMessage(role=ChatRole.USER, content="Hi"),
        ]
        system, messages = anthropic_messages_from_chat(msgs)
        assert system == "Rule 1\n\nRule 2"
        assert len(messages) == 1


class TestAnthropicTools:
    def test_tool_definitions(self):
        tools = [ToolDefinition(name="calc", description="Calculator", parameters={"type": "object"})]
        result = anthropic_tools_from_definitions(tools)
        assert result[0]["name"] == "calc"
        assert result[0]["input_schema"] == {"type": "object"}


class TestAnthropicResponse:
    def test_basic_response(self):
        raw = {
            "id": "msg_123",
            "model": "claude-sonnet-4-20250514",
            "content": [{"type": "text", "text": "Hello!"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        resp = llm_response_from_anthropic(raw)
        assert resp.content == "Hello!"
        assert resp.model == "claude-sonnet-4-20250514"
        assert resp.finish_reason == FinishReason.STOP
        assert resp.usage.prompt_tokens == 10
        assert resp.usage.completion_tokens == 5
        assert resp.usage.total_tokens == 15

    def test_tool_use_response(self):
        raw = {
            "id": "msg_456",
            "model": "claude-sonnet-4-20250514",
            "content": [
                {"type": "text", "text": "I'll search for that."},
                {"type": "tool_use", "id": "toolu_1", "name": "search", "input": {"q": "test"}},
            ],
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 20, "output_tokens": 15},
        }
        resp = llm_response_from_anthropic(raw)
        assert resp.finish_reason == FinishReason.TOOL_CALLS
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].name == "search"
        assert json.loads(resp.tool_calls[0].arguments) == {"q": "test"}


class TestAnthropicModels:
    def test_hardcoded_models(self):
        models = hardcoded_models()
        assert len(models) == 3
        ids = [m.id for m in models]
        assert "claude-sonnet-4-20250514" in ids
        assert "claude-opus-4-20250514" in ids
        assert all(m.pricing is not None for m in models)
        assert all(m.context_window == 200000 for m in models)


# ── OpenAI Image + Multimodal Mappers ──


class TestOpenAIImageResult:
    def test_b64_json_response(self):
        raw = {"data": [{"b64_json": "abc123", "revised_prompt": "a cat"}]}
        result = image_result_from_openai(raw)
        assert result.b64_data == "abc123"
        assert result.revised_prompt == "a cat"

    def test_url_response(self):
        raw = {"data": [{"url": "https://example.com/img.png"}]}
        result = image_result_from_openai(raw)
        assert result.url == "https://example.com/img.png"

    def test_empty_data(self):
        raw = {"data": []}
        result = image_result_from_openai(raw)
        assert result.url == ""
        assert result.b64_data == ""


class TestOpenAIMultimodalMessages:
    def test_image_bytes_content(self):
        msg = ChatMessage(
            role=ChatRole.USER,
            content=[
                {"type": "text", "text": "What is this?"},
                {"type": "image", "data": b"\x89PNG", "mime_type": "image/png"},
            ],
        )
        result = openai_messages_from_chat([msg])
        content = result[0]["content"]
        assert content[0] == {"type": "text", "text": "What is this?"}
        assert content[1]["type"] == "image_url"
        b64 = base64.b64encode(b"\x89PNG").decode()
        assert content[1]["image_url"]["url"] == f"data:image/png;base64,{b64}"

    def test_image_url_content(self):
        msg = ChatMessage(
            role=ChatRole.USER,
            content=[{"type": "image_url", "url": "https://example.com/img.jpg"}],
        )
        result = openai_messages_from_chat([msg])
        assert result[0]["content"][0]["image_url"]["url"] == "https://example.com/img.jpg"

    def test_text_only_passthrough(self):
        msg = ChatMessage(role=ChatRole.USER, content="Hello")
        result = openai_messages_from_chat([msg])
        assert result[0]["content"] == "Hello"


class TestContentBlockToOpenAI:
    def test_text_block(self):
        assert _content_block_to_openai({"type": "text", "text": "hi"}) == {"type": "text", "text": "hi"}

    def test_image_block(self):
        result = _content_block_to_openai({"type": "image", "data": b"x", "mime_type": "image/jpeg"})
        assert result["type"] == "image_url"
        assert result["image_url"]["url"].startswith("data:image/jpeg;base64,")

    def test_image_url_block(self):
        result = _content_block_to_openai({"type": "image_url", "url": "https://test.com/a.png"})
        assert result["image_url"]["url"] == "https://test.com/a.png"

    def test_unknown_passthrough(self):
        block = {"type": "custom", "value": 42}
        assert _content_block_to_openai(block) == block


# ── Gemini Image + Multimodal Mappers ──


class TestGeminiImageResult:
    def test_inline_data_response(self):
        raw = {
            "candidates": [{
                "content": {
                    "parts": [{"inlineData": {"mimeType": "image/png", "data": "iVBOR"}}]
                }
            }]
        }
        result = image_result_from_gemini(raw)
        assert result.b64_data == "iVBOR"
        assert result.mime_type == "image/png"

    def test_text_and_image_response(self):
        raw = {
            "candidates": [{
                "content": {
                    "parts": [
                        {"text": "Here is the image:"},
                        {"inlineData": {"mimeType": "image/jpeg", "data": "abc"}},
                    ]
                }
            }]
        }
        result = image_result_from_gemini(raw)
        assert result.b64_data == "abc"
        assert result.revised_prompt == "Here is the image:"

    def test_empty_candidates(self):
        raw = {"candidates": []}
        result = image_result_from_gemini(raw)
        assert result.b64_data == ""


class TestGeminiMultimodalMessages:
    def test_image_bytes_in_content(self):
        msg = ChatMessage(
            role=ChatRole.USER,
            content=[
                {"type": "text", "text": "Describe this"},
                {"type": "image", "data": b"\xff\xd8", "mime_type": "image/jpeg"},
            ],
        )
        _, contents = gemini_contents_from_chat([msg])
        parts = contents[0]["parts"]
        assert parts[0] == {"text": "Describe this"}
        assert parts[1]["inlineData"]["mimeType"] == "image/jpeg"
        assert parts[1]["inlineData"]["data"] == base64.b64encode(b"\xff\xd8").decode()

    def test_image_url_remote(self):
        msg = ChatMessage(
            role=ChatRole.USER,
            content=[{"type": "image_url", "url": "https://example.com/img.jpg"}],
        )
        _, contents = gemini_contents_from_chat([msg])
        parts = contents[0]["parts"]
        assert parts[0]["fileData"]["mimeUri"] == "https://example.com/img.jpg"

    def test_image_url_data_uri(self):
        msg = ChatMessage(
            role=ChatRole.USER,
            content=[{"type": "image_url", "url": "data:image/png;base64,iVBOR"}],
        )
        _, contents = gemini_contents_from_chat([msg])
        parts = contents[0]["parts"]
        assert parts[0]["inlineData"]["mimeType"] == "image/png"
        assert parts[0]["inlineData"]["data"] == "iVBOR"


class TestContentBlockToGemini:
    def test_text_block(self):
        assert _content_block_to_gemini_part({"type": "text", "text": "hello"}) == {"text": "hello"}

    def test_image_block(self):
        result = _content_block_to_gemini_part({"type": "image", "data": b"x", "mime_type": "image/png"})
        assert result["inlineData"]["mimeType"] == "image/png"
        assert result["inlineData"]["data"] == base64.b64encode(b"x").decode()

    def test_unknown_passthrough(self):
        block = {"functionCall": {"name": "f"}}
        assert _content_block_to_gemini_part(block) == block
