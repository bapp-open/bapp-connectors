"""Anthropic LLM provider."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.llm.anthropic.adapter import AnthropicLLMAdapter
from bapp_connectors.providers.llm.anthropic.manifest import manifest

__all__ = ["AnthropicLLMAdapter", "manifest"]

registry.register(AnthropicLLMAdapter)
