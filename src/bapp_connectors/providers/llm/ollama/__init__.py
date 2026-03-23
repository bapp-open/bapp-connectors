"""Ollama local LLM provider."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.llm.ollama.adapter import OllamaLLMAdapter
from bapp_connectors.providers.llm.ollama.manifest import manifest

__all__ = ["OllamaLLMAdapter", "manifest"]

registry.register(OllamaLLMAdapter)
