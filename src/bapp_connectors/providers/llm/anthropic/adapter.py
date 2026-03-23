"""
Anthropic LLM adapter — implements LLMPort.

Uses x-api-key header + anthropic-version header for auth.
"""

from __future__ import annotations

from bapp_connectors.core.dto import (
    ChatMessage,
    ConnectionTestResult,
    LLMResponse,
    ModelInfo,
)
from bapp_connectors.core.http import MultiHeaderAuth, NoAuth, ResilientHttpClient
from bapp_connectors.core.ports import LLMPort
from bapp_connectors.providers.llm.anthropic.client import AnthropicApiClient
from bapp_connectors.providers.llm.anthropic.manifest import manifest
from bapp_connectors.providers.llm.anthropic.mappers import (
    anthropic_messages_from_chat,
    anthropic_tools_from_definitions,
    hardcoded_models,
    llm_response_from_anthropic,
)


class AnthropicLLMAdapter(LLMPort):
    """
    Anthropic adapter.

    Implements:
    - LLMPort: complete, list_models
    """

    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs):
        self.credentials = credentials
        self.config = config or {}

        api_key = credentials.get("api_key") or self.config.get("platform_api_key", "")

        auth = MultiHeaderAuth({
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        })

        if http_client is None:
            http_client = ResilientHttpClient(
                base_url=self.manifest.base_url,
                auth=auth,
                provider_name="anthropic",
            )
        else:
            http_client.auth = auth

        self.client = AnthropicApiClient(http_client=http_client)

    # ── BasePort ──

    def validate_credentials(self) -> bool:
        api_key = self.credentials.get("api_key") or self.config.get("platform_api_key", "")
        return bool(api_key)

    def test_connection(self) -> ConnectionTestResult:
        try:
            success = self.client.test_auth()
            return ConnectionTestResult(
                success=success,
                message="Connection successful" if success else "Authentication failed",
            )
        except Exception as e:
            return ConnectionTestResult(success=False, message=str(e))

    # ── LLMPort ──

    def complete(self, messages: list[ChatMessage], model: str | None = None, **kwargs) -> LLMResponse:
        model = model or self.config.get("default_model", "claude-sonnet-4-20250514")
        max_tokens = kwargs.pop("max_tokens", int(self.config.get("max_tokens", 4096)))
        tools_defs = kwargs.pop("tools", None)

        system_prompt, anthropic_messages = anthropic_messages_from_chat(messages)

        payload: dict = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": anthropic_messages,
        }
        if system_prompt:
            payload["system"] = system_prompt
        if tools_defs:
            payload["tools"] = anthropic_tools_from_definitions(tools_defs)
        payload.update(kwargs)

        raw = self.client.create_message(payload)
        return llm_response_from_anthropic(raw)

    def list_models(self) -> list[ModelInfo]:
        return hardcoded_models()
