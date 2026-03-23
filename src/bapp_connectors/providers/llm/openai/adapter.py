"""
OpenAI LLM adapter — implements LLMPort + EmbeddingCapability + TranscriptionCapability.
"""

from __future__ import annotations

from bapp_connectors.core.capabilities import EmbeddingCapability, TranscriptionCapability
from bapp_connectors.core.dto import (
    ChatMessage,
    ConnectionTestResult,
    EmbeddingResult,
    LLMResponse,
    ModelInfo,
    TranscriptionResult,
)
from bapp_connectors.core.http import BearerAuth, ResilientHttpClient
from bapp_connectors.core.ports import LLMPort
from bapp_connectors.providers.llm.openai.client import OpenAIApiClient
from bapp_connectors.providers.llm.openai.manifest import manifest
from bapp_connectors.providers.llm.openai.mappers import (
    embedding_result_from_openai,
    llm_response_from_openai,
    model_info_from_openai,
    openai_messages_from_chat,
    openai_tools_from_definitions,
    transcription_result_from_openai,
)


class OpenAILLMAdapter(LLMPort, EmbeddingCapability, TranscriptionCapability):
    """
    OpenAI adapter.

    Implements:
    - LLMPort: complete, list_models
    - EmbeddingCapability: embed
    - TranscriptionCapability: transcribe (Whisper)
    """

    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs):
        self.credentials = credentials
        self.config = config or {}

        # Platform-level key fallback
        api_key = credentials.get("api_key") or self.config.get("platform_api_key", "")

        if http_client is None:
            http_client = ResilientHttpClient(
                base_url=self.manifest.base_url,
                auth=BearerAuth(token=api_key),
                provider_name="openai",
            )
        else:
            http_client.auth = BearerAuth(token=api_key)

        self.client = OpenAIApiClient(http_client=http_client)

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
        model = model or self.config.get("default_model", "gpt-4o-mini")
        temperature = kwargs.pop("temperature", float(self.config.get("temperature", 0.7)))
        tools_defs = kwargs.pop("tools", None)

        payload: dict = {
            "model": model,
            "messages": openai_messages_from_chat(messages),
            "temperature": temperature,
        }
        if tools_defs:
            payload["tools"] = openai_tools_from_definitions(tools_defs)
        payload.update(kwargs)

        raw = self.client.chat_completion(payload)
        return llm_response_from_openai(raw)

    def list_models(self) -> list[ModelInfo]:
        raw = self.client.list_models()
        return [model_info_from_openai(m) for m in raw.get("data", [])]

    # ── EmbeddingCapability ──

    def embed(self, texts: list[str], model: str | None = None) -> EmbeddingResult:
        model = model or "text-embedding-3-small"
        payload = {"input": texts, "model": model}
        raw = self.client.create_embedding(payload)
        return embedding_result_from_openai(raw)

    # ── TranscriptionCapability ──

    def transcribe(self, audio: bytes, model: str | None = None, language: str | None = None, **kwargs) -> TranscriptionResult:
        model = model or "whisper-1"
        raw = self.client.create_transcription(audio, model=model, language=language, **kwargs)
        return transcription_result_from_openai(raw)
