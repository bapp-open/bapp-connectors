# Ollama

Ollama local LLM server for running open-source models (Llama, Mistral, Gemma, etc.).

- **Default Base URL:** `http://localhost:11434/`
- **Auth:** None (local server)
- **Rate limit:** 10 req/s, burst 20
- **Retry:** 2 retries, exponential backoff on 429, 500, 502, 503, 504

## Credentials

No credentials are required. Ollama runs locally and does not need an API key.
`validate_credentials()` always returns `True`.

## Settings

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `base_url` | str | `http://localhost:11434` | URL of the Ollama server |
| `default_model` | str | `llama3.2` | Model to use when none specified (e.g., `llama3.2`, `mistral`, `gemma2`) |
| `temperature` | str | `0.7` | Default sampling temperature |

## Capabilities

| Capability | Supported |
|------------|-----------|
| Chat completion (`LLMPort.complete`) | Yes |
| List models (`LLMPort.list_models`) | Yes (lists locally installed models) |
| Embedding (`EmbeddingCapability`) | Yes |
| Transcription (`TranscriptionCapability`) | No |
| Streaming (`StreamingCapability`) | No |
| Image generation (`ImageGenerationCapability`) | No |

## API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `api/chat` | Chat completion (non-streaming) |
| GET | `api/tags` | List installed models |
| POST | `api/embed` | Generate embeddings |

## Embedding

The embedding model defaults to the same model as chat (`default_model`).
Ollama's `embed` endpoint accepts a list of strings in the `input` field and
returns one embedding vector per input.

## API Quirks

- **No authentication:** Uses `NoAuth`. The adapter only requires a reachable
  Ollama server.
- **Configurable base URL:** The server URL comes from the `base_url` setting,
  not from the manifest's `base_url` (which is just a default). The adapter
  updates the HTTP client's base URL at init time.
- **Streaming disabled:** Chat requests always set `stream: false` to get a
  single JSON response. The client also calls `setdefault("stream", False)` as
  a safeguard.
- **Message format:** Similar to OpenAI -- uses `role`/`content` fields with
  tool calls in `tool_calls[].function.{name, arguments}`.
- **Usage fields:** Token counts use `prompt_eval_count` and `eval_count`
  (not `prompt_tokens`/`completion_tokens`).
- **Finish reasons:** Uses `done_reason` field with values `stop`, `length`,
  `tool_calls`.
- **Model info:** `list_models()` returns locally installed models from
  `api/tags`. Model entries contain `name` and `size` but no context window or
  pricing information.
- **Embedding fallback:** Older Ollama versions return embeddings in an
  `"embedding"` field (singular). The mapper handles both `"embeddings"` (list)
  and `"embedding"` (single vector) formats.
- **Connection test:** Verifies the Ollama server is reachable by calling
  `GET /api/tags`.
- **Extra options:** Additional model parameters can be passed via an `options`
  dict in `kwargs`, which gets merged into the payload's `options` field.
