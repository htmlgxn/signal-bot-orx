# signal-bot-orx Setup Guide

This guide is for running `signal-bot-orx` as a webhook service.

## 1. Prerequisites

- `signal-cli-rest-api` is running and registered with your bot number.
- `uv` is installed.
- You have an OpenRouter API key for chat.

## 2. Clone and install

```bash
git clone https://github.com/htmlgxn/signal-bot-orx.git
cd signal-bot-orx
uv sync --dev
```

## 3. Configure environment

```bash
cp .env.example .env
```

Minimum required values:

```bash
SIGNAL_API_BASE_URL=http://127.0.0.1:8080
SIGNAL_SENDER_NUMBER=+15550001111
SIGNAL_ALLOWED_GROUP_IDS=group-id-1
OPENROUTER_CHAT_API_KEY=sk-or-...
```

Optional image mode:

```bash
OPENROUTER_IMAGE_API_KEY=sk-or-...
OPENROUTER_IMAGE_MODEL=openai/gpt-image-1
```

## 4. Start the bot

```bash
set -a
source .env
set +a
uv run signal-bot-orx
```

Health check:

```bash
curl -s http://127.0.0.1:8001/healthz
```

## 5. Configure webhook callback

Set `signal-cli-rest-api` callback URL to:

`http://<BOT_HOST>:8001/webhook/signal`

Examples:
- `http://127.0.0.1:8001/webhook/signal`
- `http://192.168.1.20:8001/webhook/signal`

## 6. Validate behavior

Mention-triggered group reply:

```text
@bot summarize the last messages
```

Optional image generation:

```text
/imagine a neon skyline over snowy mountains
```

## 7. Troubleshooting

No replies:
- Confirm webhook reachability from `signal-cli-rest-api`.
- Confirm sender/group is allowlisted.
- Verify `OPENROUTER_CHAT_API_KEY` is valid.

`/imagine` unavailable:
- Set both `OPENROUTER_IMAGE_API_KEY` and `OPENROUTER_IMAGE_MODEL`.

Signal send failures:
- Verify `SIGNAL_API_BASE_URL` and bot number registration.
- Try `BOT_GROUP_REPLY_MODE=dm_fallback` while debugging group recipient issues.

## 8. Dev checks

```bash
uv run ruff check .
uv run ty check .
uv run pytest
```

## License

MIT License. See `LICENSE`.
