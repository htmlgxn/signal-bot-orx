# signal-bot-orx Setup Guide

This guide is for running `signal-bot-orx` as a webhook service.

## 1. Prerequisites

- `signal-cli-rest-api` is running and registered with your bot number.
- `uv` is installed.
- You have an OpenRouter API key for chat.
- (Optional) You have an OpenWeatherMap API key.

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
OPENROUTER_CHAT_API_KEY=sk-or-...
```

Enable at least one transport (`SIGNAL_ENABLED`, `WHATSAPP_ENABLED`, or `TELEGRAM_ENABLED`).

If Signal is enabled (default):

```bash
SIGNAL_API_BASE_URL=http://127.0.0.1:8080
SIGNAL_SENDER_NUMBER=+15550001111
SIGNAL_ALLOWED_GROUP_IDS=group-id-1
```

Optional image mode:

```bash
OPENROUTER_IMAGE_API_KEY=sk-or-...
OPENROUTER_IMAGE_API_KEY=sk-or-...
OPENROUTER_IMAGE_MODEL=openai/gpt-image-1
```

Optional weather:

```bash
WEATHER_API_KEY=your-owm-key
WEATHER_UNITS=metric
WEATHER_DEFAULT_LOCATION=London
```

Optional search tuning:

```bash
BOT_SEARCH_ENABLED=true
BOT_SEARCH_CONTEXT_MODE=no_context
BOT_SEARCH_MODE_SEARCH_ENABLED=true
BOT_SEARCH_MODE_NEWS_ENABLED=true
BOT_SEARCH_MODE_WIKI_ENABLED=true
BOT_SEARCH_MODE_IMAGES_ENABLED=true
BOT_SEARCH_MODE_VIDEOS_ENABLED=true
BOT_SEARCH_DEBUG_LOGGING=false
BOT_SEARCH_PERSONA_ENABLED=false
BOT_SEARCH_USE_HISTORY_FOR_SUMMARY=false
BOT_SEARCH_REGION=us-en
BOT_SEARCH_SAFESEARCH=moderate
BOT_SEARCH_BACKEND_STRATEGY=first_non_empty
BOT_SEARCH_BACKEND_SEARCH_ORDER=duckduckgo,bing,google,yandex,grokipedia
BOT_SEARCH_BACKEND_NEWS_ORDER=duckduckgo,bing,yahoo
BOT_SEARCH_BACKEND_SEARCH=auto
BOT_SEARCH_BACKEND_NEWS=auto
BOT_SEARCH_BACKEND_WIKI=wikipedia
BOT_SEARCH_BACKEND_IMAGES=duckduckgo
BOT_SEARCH_BACKEND_VIDEOS=youtube
BOT_SEARCH_TEXT_MAX_RESULTS=5
BOT_SEARCH_NEWS_MAX_RESULTS=5
BOT_SEARCH_WIKI_MAX_RESULTS=3
BOT_SEARCH_IMAGES_MAX_RESULTS=3
BOT_SEARCH_VIDEOS_MAX_RESULTS=5
BOT_SEARCH_TIMEOUT_SECONDS=8
BOT_SEARCH_SOURCE_TTL_SECONDS=1800

# Optional WhatsApp bridge (whatsapp-web.js)
WHATSAPP_ENABLED=false
WHATSAPP_BRIDGE_BASE_URL=http://127.0.0.1:3001
WHATSAPP_BRIDGE_TOKEN=
WHATSAPP_ALLOWED_NUMBERS=
WHATSAPP_DISABLE_AUTH=false

# Optional Telegram webhook
TELEGRAM_ENABLED=false
TELEGRAM_BOT_TOKEN=
TELEGRAM_WEBHOOK_SECRET=
TELEGRAM_ALLOWED_USER_IDS=
TELEGRAM_ALLOWED_CHAT_IDS=
TELEGRAM_DISABLE_AUTH=false
TELEGRAM_BOT_USERNAME=
```

Notes:
- `BOT_SEARCH_CONTEXT_MODE=no_context` (default) means DDGS is command-only.
- Set `BOT_SEARCH_CONTEXT_MODE=context` to enable auto-search routing from normal chat.
- `/videos` stays command-only and is not selected by auto-search routing.
- In `context` mode, ambiguous follow-ups can trigger `Who are you referring to?`; a short next reply can be used to continue the pending search intent.
- Toggle any explicit DDGS command with `BOT_SEARCH_MODE_*_ENABLED`.
- `BOT_SEARCH_DEBUG_LOGGING=true` logs router/summarizer decision metadata (without raw message text/results) for diagnostics.
- `BOT_SEARCH_BACKEND_STRATEGY=first_non_empty` stops at first backend with results.
- `BOT_SEARCH_BACKEND_STRATEGY=aggregate` queries all configured backends, merges/de-dupes by URL, and caps final output to `BOT_SEARCH_TEXT_MAX_RESULTS` / `BOT_SEARCH_NEWS_MAX_RESULTS`.
- `BOT_SEARCH_BACKEND_*_ORDER` defines fallback chains for general `search` and `news`.
- If an order var is set, it overrides the legacy single-backend var for that mode.
- `/wiki` stays explicit encyclopedia mode via `BOT_SEARCH_BACKEND_WIKI`.
- News backend order blocks encyclopedia backends (`wikipedia`, `grokipedia`).
- `BOT_SEARCH_PERSONA_ENABLED=true` reuses the core chat personality for search summaries.
- `BOT_SEARCH_USE_HISTORY_FOR_SUMMARY=true` includes up to the last 2 turns in the summary prompt.
- File-based prompt behavior:
  local override file `src/signal_bot_orx/chat_system_prompt.md` is git-ignored.
  tracked distribution default is `src/signal_bot_orx/default_chat_system_prompt.md`.

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

Code default bind host is `127.0.0.1`. `.env.example` uses `BOT_WEBHOOK_HOST=0.0.0.0` for container/LAN deployments.

Examples:
- `http://127.0.0.1:8001/webhook/signal`
- `http://192.168.1.20:8001/webhook/signal`

If WhatsApp is enabled, configure your bridge webhook to:
- `http://<BOT_HOST>:8001/webhook/whatsapp`

If Telegram is enabled, configure webhook manually:

```bash
curl -sS "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \
  -d "url=https://<YOUR_PUBLIC_HOST>/webhook/telegram" \
  -d 'allowed_updates=["message","edited_message"]' \
  -d "secret_token=${TELEGRAM_WEBHOOK_SECRET}"
```

Telegram group behavior: replies are mention/reply-only.

## 6. Validate behavior

Mention-triggered group reply:

```text
@bot summarize the last messages
```

Direct-message chat (no mention required):

```text
summarize the last messages
```

Explicit search commands:

```text
/search latest OpenRouter updates
/news latest AI policy headlines
/wiki Alan Turing
/images moonlit forest
/videos nick land interview
```

Video selection follow-up:

```text
2
```

Source lookup:

```text
/source first claim
source for that claim
```

Optional image generation:

```text
/imagine a neon skyline over snowy mountains
```

Weather commands:

```text
/weather New York
/forecast Paris
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
