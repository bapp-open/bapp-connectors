"""OpenAI LLM provider."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.llm.openai.adapter import OpenAILLMAdapter
from bapp_connectors.providers.llm.openai.manifest import manifest

__all__ = ["OpenAILLMAdapter", "manifest"]

registry.register(OpenAILLMAdapter)
