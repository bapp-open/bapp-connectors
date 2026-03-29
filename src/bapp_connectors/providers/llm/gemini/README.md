# Google Gemini

Google Gemini models for chat completion, embeddings, and multimodal content.

- **Base URL:** `https://generativelanguage.googleapis.com/v1beta/`
- **Auth:** Custom header (`x-goog-api-key`)
- **Rate limit:** 15 req/s, burst 30
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
| `default_model` | select | `gemini-2.0-flash` | Model when none specified. Choices: `gemini-2.5-flash-preview-05-20`, `gemini-2.5-pro-preview-05-06`, `gemini-2.0-flash` |
| `temperature` | str | `1.0` | Default sampling temperature |
| `platform_api_key` | str | | Platform-level API key fallback |

## Capabilities

| Capability | Supported |
|------------|-----------|
| Chat completion (`LLMPort.complete`) | Yes |
| List models (`LLMPort.list_models`) | Yes (live API call) |
| Embedding (`EmbeddingCapability`) | Yes |
| Transcription (`TranscriptionCapability`) | No |
| Streaming (`StreamingCapability`) | No |
| Image generation (`ImageGenerationCapability`) | No |

## API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `models/{model}:generateContent` | Chat completion |
| GET | `models` | List available models |
| POST | `models/{model}:embedContent` | Generate embeddings |

## Embedding

Default embedding model is `text-embedding-004`. The adapter sends all input
texts as parts in a single `embedContent` request and returns the embedding
vector wrapped in an `EmbeddingResult` DTO.

## API Quirks

- **Role naming:** Gemini uses `model` instead of `assistant` for the AI role.
  The mapper translates `ChatRole.ASSISTANT` to `"model"` and all other roles
  to `"user"`.
- **Content format:** Messages use `contents` with `parts: [{"text": "..."}]`
  instead of a plain `content` string.
- **System instruction:** System messages are extracted and sent as a top-level
  `systemInstruction` field (with `parts` array), not as a message.
- **Tool calling:** Uses `functionDeclarations` (in a `tools` array) for tool
  definitions, `functionCall` parts for tool invocations, and
  `functionResponse` parts for tool results.
- **Tool call IDs:** Gemini does not return IDs for function calls. The mapper
  sets `ToolCall.id` to an empty string.
- **Usage fields:** Token counts use `promptTokenCount`,
  `candidatesTokenCount`, `totalTokenCount` inside `usageMetadata`.
- **Finish reasons:** Uses uppercase strings: `STOP`, `MAX_TOKENS`, `SAFETY`,
  `RECITATION` (last two map to `CONTENT_FILTER`).
- **Model name prefix:** The models endpoint returns names like
  `"models/gemini-2.0-flash"`. The mapper strips the `models/` prefix for the
  `ModelInfo.id` field.
- **Connection test:** Verifies the API key by calling `GET /models`.
