"""
Ollama LLM adapter — implements LLMPort + EmbeddingCapability.

Ollama runs open-source models locally. No API key required.
"""

from __future__ import annotations

from bapp_connectors.core.capabilities import EmbeddingCapability
from bapp_connectors.core.dto import (
    ChatMessage,
    ConnectionTestResult,
    EmbeddingResult,
    LLMResponse,
    ModelInfo,
)
from bapp_connectors.core.http import NoAuth, ResilientHttpClient
from bapp_connectors.core.ports import LLMPort
from bapp_connectors.providers.llm.ollama.client import OllamaApiClient
from bapp_connectors.providers.llm.ollama.manifest import manifest
from bapp_connectors.providers.llm.ollama.mappers import (
    embedding_result_from_ollama,
    llm_response_from_ollama,
    model_info_from_ollama,
    ollama_messages_from_chat,
    ollama_tools_from_definitions,
)


class OllamaLLMAdapter(LLMPort, EmbeddingCapability):
    """
    Ollama adapter.

    Implements:
    - LLMPort: complete, list_models
    - EmbeddingCapability: embed
    """

    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs):
        self.credentials = credentials
        self.config = config or {}

        base_url = self.config.get("base_url", "http://localhost:11434")
        if not base_url.endswith("/"):
            base_url += "/"

        if http_client is None:
            http_client = ResilientHttpClient(
                base_url=base_url,
                auth=NoAuth(),
                provider_name="ollama",
            )
        else:
            http_client.base_url = base_url

        self.client = OllamaApiClient(http_client=http_client)

    # ── BasePort ──

    def validate_credentials(self) -> bool:
        return True  # Ollama requires no credentials

    def test_connection(self) -> ConnectionTestResult:
        try:
            success = self.client.test_auth()
            return ConnectionTestResult(
                success=success,
                message="Ollama server reachable" if success else "Ollama server unreachable",
            )
        except Exception as e:
            return ConnectionTestResult(success=False, message=str(e))

    # ── LLMPort ──

    def complete(self, messages: list[ChatMessage], model: str | None = None, **kwargs) -> LLMResponse:
        model = model or self.config.get("default_model", "llama3.2")
        temperature = kwargs.pop("temperature", float(self.config.get("temperature", 0.7)))
        tools_defs = kwargs.pop("tools", None)

        payload: dict = {
            "model": model,
            "messages": ollama_messages_from_chat(messages),
            "stream": False,
            "options": {"temperature": temperature},
        }
        if tools_defs:
            payload["tools"] = ollama_tools_from_definitions(tools_defs)
        # Merge extra options
        if extra_options := kwargs.pop("options", None):
            payload["options"].update(extra_options)
        payload.update(kwargs)

        raw = self.client.chat(payload)
        return llm_response_from_ollama(raw)

    def list_models(self) -> list[ModelInfo]:
        raw = self.client.list_models()
        return [model_info_from_ollama(m) for m in raw.get("models", [])]

    # ── EmbeddingCapability ──

    def embed(self, texts: list[str], model: str | None = None) -> EmbeddingResult:
        model = model or self.config.get("default_model", "llama3.2")
        payload = {"model": model, "input": texts}
        raw = self.client.embed(payload)
        return embedding_result_from_ollama(raw)
