# Anthropic

Anthropic Claude models for chat completion and function calling.

- **API version:** 2023-06-01
- **Base URL:** `https://api.anthropic.com/v1/`
- **Auth:** Custom headers (`x-api-key` + `anthropic-version`)
- **Rate limit:** 10 req/s, burst 20
- **Retry:** 3 retries, exponential backoff on 429, 500, 502, 503, 504, 529

## Credentials

| Field | Label | Required | Sensitive |
|-------|-------|----------|-----------|
| `api_key` | API Key | No | Yes |

**Platform-key fallback:** If the tenant does not provide `api_key`, the adapter
falls back to `config.platform_api_key`. This lets the platform owner provide a
shared key while still allowing tenants to bring their own.

## Settings

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `default_model` | select | `claude-sonnet-4-6` | Model when none specified. Choices: `claude-opus-4-7`, `claude-sonnet-4-6`, `claude-haiku-4-5-20251001`, `claude-opus-4-20250514`, `claude-sonnet-4-20250514` |
| `max_tokens` | int | `4096` | Default maximum tokens in the response |
| `platform_api_key` | str | | Platform-level API key fallback |

## Capabilities

| Capability | Supported |
|------------|-----------|
| Chat completion (`LLMPort.complete`) | Yes |
| List models (`LLMPort.list_models`) | Yes (hardcoded list) |
| Embedding (`EmbeddingCapability`) | No |
| Transcription (`TranscriptionCapability`) | No |
| Streaming (`StreamingCapability`) | No |
| Image generation (`ImageGenerationCapability`) | No |

## API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `messages` | Chat completion |

## Models (hardcoded)

Anthropic does not provide a models listing endpoint; `list_models()` returns a
hardcoded catalog:

| Model ID | Name | Context Window | Capabilities | Input $/M | Output $/M |
|----------|------|----------------|-------------|-----------|------------|
| `claude-opus-4-20250514` | Claude Opus 4 | 200k | chat, tool_use, vision | 15.00 | 75.00 |
| `claude-sonnet-4-20250514` | Claude Sonnet 4 | 200k | chat, tool_use, vision | 3.00 | 15.00 |
| `claude-haiku-4-5-20251001` | Claude Haiku 4.5 | 200k | chat, tool_use, vision | 0.80 | 4.00 |

## API Quirks

- **System message handling:** Anthropic does not accept `role: system` messages.
  System messages are extracted from the ChatMessage list and sent as the
  top-level `system` parameter. Multiple system messages are concatenated.
- **Content blocks:** Content is always an array of content blocks (text,
  tool_use, tool_result), not a plain string.
- **Tool results as user messages:** Tool call results must be sent as
  `role: user` messages containing `tool_result` content blocks, not as a
  separate `role: tool` message.
- **Tool use content blocks:** Tool calls appear as content blocks within the
  assistant message rather than as a separate `tool_calls` field.
- **Usage fields:** Token counts use `input_tokens`/`output_tokens` (not
  `prompt_tokens`/`completion_tokens` like OpenAI).
- **Finish reasons:** Uses `end_turn`, `stop_sequence`, `max_tokens`,
  `tool_use` (mapped to framework `STOP`, `STOP`, `LENGTH`, `TOOL_CALLS`).
- **Overloaded status (529):** Anthropic returns HTTP 529 when the API is
  overloaded. This is included in the retryable status codes.
- **No models endpoint:** Model listing is hardcoded. There is no API endpoint
  to enumerate available models.
- **Connection test:** Sends a minimal one-token message to verify the API key.
