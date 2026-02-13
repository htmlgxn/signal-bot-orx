# signal-box-orx

`signal-box-orx` is a webhook-driven Signal bot powered by
`signal-cli-rest-api` and OpenRouter.

Primary behavior:
- Mention-triggered group chat replies.
- Optional `/imagine <prompt>` image generation.

## Features

- Handles incoming Signal webhooks (`POST /webhook/signal`).
- Enforces number/group allowlists unless auth bypass is explicitly enabled.
- Supports metadata mention detection with alias fallback.
- Maintains short-lived in-memory conversation history per group.
- Deduplicates repeated webhook deliveries.
- Sends images via OpenRouter image-capable chat completions when configured.

## Requirements

- Python 3.14+
- [`uv`](https://docs.astral.sh/uv/)
- Running [`signal-cli-rest-api`](https://github.com/bbernhard/signal-cli-rest-api/tree/master/doc)
- OpenRouter API key for chat

## Installation

From source:

```bash
uv sync --dev
```

From package index (after publish):

```bash
uv tool install signal-box-orx
```

or

```bash
pip install signal-box-orx
```

## Configuration

Create `.env` from `.env.example` and set required values.

Required:
- `SIGNAL_API_BASE_URL`
- `SIGNAL_SENDER_NUMBER`
- `OPENROUTER_CHAT_API_KEY`

Auth/allowlist (set at least one unless `SIGNAL_DISABLE_AUTH=true`):
- `SIGNAL_ALLOWED_NUMBER`
- `SIGNAL_ALLOWED_NUMBERS`
- `SIGNAL_ALLOWED_GROUP_IDS`

Chat options:
- `OPENROUTER_MODEL` (default: `openai/gpt-4o-mini`)
- `OPENROUTER_TIMEOUT_SECONDS` (default: `45`)
- `OPENROUTER_MAX_OUTPUT_TOKENS` (default: `300`)
- `BOT_CHAT_TEMPERATURE` (default: `0.6`)
- `BOT_CHAT_CONTEXT_TURNS` (default: `6`)
- `BOT_CHAT_CONTEXT_TTL_SECONDS` (default: `1800`)
- `BOT_CHAT_SYSTEM_PROMPT` (optional)
- `BOT_CHAT_FORCE_PLAIN_TEXT` (default: `true`)
- `BOT_MENTION_ALIASES` (default: `@signalbot,@bot`)
- `BOT_MAX_PROMPT_CHARS` (default: `700`)

Image mode (`/imagine`) options:
- `OPENROUTER_IMAGE_API_KEY`
- `OPENROUTER_IMAGE_MODEL`
- `OPENROUTER_IMAGE_TIMEOUT_SECONDS` (default: `90`)

Webhook/runtime options:
- `BOT_GROUP_REPLY_MODE` (`group` or `dm_fallback`, default: `group`)
- `BOT_WEBHOOK_HOST` (default: `127.0.0.1`)
- `BOT_WEBHOOK_PORT` (default: `8001`)

**NOTE: You can pass in the same API key in both CHAT_API_KEY AND IMAGE_API_KEY if you don't mind the same settings / limits for both text and images**

## Run

```bash
uv run signal-box-orx
```

Endpoints:
- `GET /healthz`
- `POST /webhook/signal`

Configure `signal-cli-rest-api` callback target:

`http://<BOT_WEBHOOK_HOST>:<BOT_WEBHOOK_PORT>/webhook/signal`

## Usage

Group chat:

```text
@bot summarize the key decisions from this thread
```

Optional image mode:

```text
/imagine a watercolor fox reading a map
```

## Development

```bash
uv run ruff check .
uv run ruff format .
uv run ty check .
uv run pytest
uv build
```

## Detailed Setup

See `docs/README.md`.

## License

This project is licensed under the MIT License. See `LICENSE`.
