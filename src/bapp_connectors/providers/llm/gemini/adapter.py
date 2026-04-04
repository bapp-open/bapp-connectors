"""
Google Gemini LLM adapter — implements LLMPort + EmbeddingCapability + ImageGenerationCapability.

Auth via x-goog-api-key header using MultiHeaderAuth.
"""

from __future__ import annotations

import base64

from bapp_connectors.core.capabilities import EmbeddingCapability, ImageGenerationCapability
from bapp_connectors.core.dto import (
    ChatMessage,
    ConnectionTestResult,
    EmbeddingResult,
    ImageResult,
    LLMResponse,
    ModelInfo,
)
from bapp_connectors.core.http import MultiHeaderAuth, ResilientHttpClient
from bapp_connectors.core.ports import LLMPort
from bapp_connectors.providers.llm.gemini.client import GeminiApiClient
from bapp_connectors.providers.llm.gemini.manifest import manifest
from bapp_connectors.providers.llm.gemini.mappers import (
    embedding_result_from_gemini,
    gemini_contents_from_chat,
    gemini_tools_from_definitions,
    image_result_from_gemini,
    llm_response_from_gemini,
    model_info_from_gemini,
)


class GeminiLLMAdapter(LLMPort, EmbeddingCapability, ImageGenerationCapability):
    """
    Google Gemini adapter.

    Implements:
    - LLMPort: complete, list_models
    - EmbeddingCapability: embed
    - ImageGenerationCapability: generate_image, edit_image
    """

    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs):
        self.credentials = credentials
        self.config = config or {}

        api_key = credentials.get("api_key") or self.config.get("platform_api_key", "")

        auth = MultiHeaderAuth({"x-goog-api-key": api_key})

        if http_client is None:
            http_client = ResilientHttpClient(
                base_url=self.manifest.base_url,
                auth=auth,
                provider_name="gemini",
            )
        else:
            http_client.auth = auth

        self.client = GeminiApiClient(http_client=http_client)

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
        model = model or self.config.get("default_model", "gemini-2.5-flash")
        temperature = kwargs.pop("temperature", float(self.config.get("temperature", 1.0)))
        max_tokens = kwargs.pop("max_tokens", kwargs.pop("maxOutputTokens", None))
        tools_defs = kwargs.pop("tools", None)

        system_instruction, contents = gemini_contents_from_chat(messages)

        payload: dict = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
            },
        }
        if max_tokens:
            payload["generationConfig"]["maxOutputTokens"] = max_tokens
        if system_instruction:
            payload["systemInstruction"] = system_instruction
        if tools_defs:
            payload["tools"] = gemini_tools_from_definitions(tools_defs)

        raw = self.client.generate_content(model, payload)
        return llm_response_from_gemini(raw)

    def list_models(self) -> list[ModelInfo]:
        raw = self.client.list_models()
        return [model_info_from_gemini(m) for m in raw.get("models", [])]

    # ── EmbeddingCapability ──

    def embed(self, texts: list[str], model: str | None = None) -> EmbeddingResult:
        model = model or "gemini-embedding-001"
        # Gemini embedContent takes a single content, batch by calling multiple times
        # For simplicity, embed the first text (batch support can be added later)
        payload = {"content": {"parts": [{"text": t} for t in texts]}}
        raw = self.client.embed_content(model, payload)
        return embedding_result_from_gemini(raw)

    # ── ImageGenerationCapability ──

    def generate_image(
        self,
        prompt: str,
        model: str | None = None,
        size: str = "1024x1024",
        **kwargs,
    ) -> ImageResult:
        model = model or "gemini-2.5-flash"
        payload: dict = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["IMAGE"]},
        }
        aspect_ratio = kwargs.pop("aspect_ratio", None)
        if aspect_ratio:
            payload["generationConfig"]["imageConfig"] = {"aspectRatio": aspect_ratio}
        raw = self.client.generate_content(model, payload, timeout=60)
        return image_result_from_gemini(raw)

    def edit_image(
        self,
        prompt: str,
        image: bytes,
        *,
        model: str | None = None,
        size: str = "1024x1024",
        **kwargs,
    ) -> ImageResult:
        model = model or "gemini-2.5-flash"
        b64_image = base64.b64encode(image).decode("ascii")
        mime_type = kwargs.pop("mime_type", "image/jpeg")
        payload: dict = {
            "contents": [{"role": "user", "parts": [
                {"text": prompt},
                {"inlineData": {"mimeType": mime_type, "data": b64_image}},
            ]}],
            "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
        }
        aspect_ratio = kwargs.pop("aspect_ratio", None)
        if aspect_ratio:
            payload["generationConfig"]["imageConfig"] = {"aspectRatio": aspect_ratio}
        raw = self.client.generate_content(model, payload, timeout=60)
        return image_result_from_gemini(raw)
