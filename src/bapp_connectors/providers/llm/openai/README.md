# OpenAI

OpenAI GPT models for chat completion, embeddings, and function calling.

- **Base URL:** `https://api.openai.com/v1/`
- **Auth:** Bearer token (`Authorization: Bearer <api_key>`)
- **Rate limit:** 50 req/s, burst 100
- **Retry:** 3 retries, exponential backoff on 429, 500, 502, 503, 504

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
| `default_model` | select | `gpt-4o-mini` | Model when none specified. Choices: `gpt-4o`, `gpt-4o-mini`, `gpt-4-turbo`, `gpt-3.5-turbo` |
| `temperature` | str | `0.7` | Default sampling temperature (0.0-2.0) |
| `platform_api_key` | str | | Platform-level API key fallback |

## Capabilities

| Capability | Supported |
|------------|-----------|
| Chat completion (`LLMPort.complete`) | Yes |
| List models (`LLMPort.list_models`) | Yes (live API call) |
| Embedding (`EmbeddingCapability`) | Yes |
| Transcription (`TranscriptionCapability`) | Yes (Whisper) |
| Streaming (`StreamingCapability`) | No |
| Image generation (`ImageGenerationCapability`) | No |

## API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `chat/completions` | Chat completion |
| GET | `models` | List available models |
| POST | `embeddings` | Generate embeddings |
| POST | `audio/transcriptions` | Transcribe audio (Whisper) |

## Embedding

Default embedding model is `text-embedding-3-small`. The adapter sends the
input texts as a list in the `input` field and returns one embedding vector per
input, wrapped in an `EmbeddingResult` DTO with token usage.

## Transcription (Whisper)

Default transcription model is `whisper-1`. The adapter uploads raw audio bytes
via `multipart/form-data`. Response format defaults to `verbose_json`, which
includes word-level timestamps, language detection, and duration.

The mapper handles both `verbose_json` (dict with segments) and plain text
(str) response formats.

## API Quirks

- **Standard message format:** OpenAI uses the canonical `role`/`content`
  message format. System messages are passed as `role: system` messages
  directly (no extraction needed).
- **Tool calling format:** Uses `tools[].function.{name, description,
  parameters}` for definitions and `tool_calls[].function.{name, arguments}`
  in responses. Tool results use `role: tool` with `tool_call_id`.
- **Usage fields:** Standard `prompt_tokens`, `completion_tokens`,
  `total_tokens` in the `usage` object.
- **Finish reasons:** Uses `stop`, `length`, `tool_calls`, `content_filter`
  (all lowercase).
- **Transcription multipart:** The `audio/transcriptions` endpoint requires
  `multipart/form-data` with the audio file. The HTTP client handles this via
  `files` + `data` params.
- **Model listing:** Returns all models the API key has access to, including
  fine-tuned models. No filtering is applied.
- **Connection test:** Verifies the API key by calling `GET /models`.
