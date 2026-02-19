# signal-bot-orx

<p align="center">
  <img src="assets/logo.png" alt="signal-bot-orx" width="600">
</p>

`signal-bot-orx` is a webhook-driven Signal bot powered by
`signal-cli-rest-api` and OpenRouter. 
It is designed for group chats and direct messages.

> **Development Status:** This project is in active development. Some features may be broken or behave unexpectedly between updates.

Primary behavior:
- Mention-triggered group chat replies.
- Direct-message chat replies without mention syntax.
- DDGS-powered search via slash commands (default privacy mode).
- Optional `/imagine <prompt>` image generation via OpenRouter.

## Features

- Handles incoming Signal webhooks (`POST /webhook/signal`).
- Optional WhatsApp bridge webhooks (`POST /webhook/whatsapp`) when enabled.
- Optional Telegram webhooks (`POST /webhook/telegram`) when enabled.
- Enforces number/group allowlists unless auth bypass is explicitly enabled.
- Supports metadata mention detection with alias fallback.
- Maintains and supports customizable in-memory conversation history per group.
- Deduplicates repeated webhook deliveries.
- Supports image generation  via OpenRouter when configured.
- Provides current weather and 5-day forecasts via OpenWeatherMap.

## Requirements

- [`uv`](https://docs.astral.sh/uv/)
- Running [`signal-cli-rest-api`](https://github.com/bbernhard/signal-cli-rest-api/)
- OpenRouter API key for chat
- OpenWeatherMap API key (optional) for weather commands

## Installation

From source:

```bash
uv sync --dev
```

From package index (after publish):

```bash
uv tool install signal-bot-orx
```

or

```bash
pip install signal-bot-orx
```

## Configuration

Create `.env` from `.env.example` and set required values.

```bash
cp .env.example .env
```

Required:
- `OPENROUTER_CHAT_API_KEY`

Enable at least one transport:
- Signal: `SIGNAL_ENABLED=true` (default)
- WhatsApp: `WHATSAPP_ENABLED=true`
- Telegram: `TELEGRAM_ENABLED=true`

Signal required values (when `SIGNAL_ENABLED=true`):
- `SIGNAL_API_BASE_URL`
- `SIGNAL_SENDER_NUMBER`

Auth/allowlist (set at least one unless `SIGNAL_DISABLE_AUTH=true`):
- `SIGNAL_ALLOWED_NUMBER`
- `SIGNAL_ALLOWED_NUMBERS`
- `SIGNAL_ALLOWED_GROUP_IDS`

Optional WhatsApp bridge:
- `WHATSAPP_ENABLED` (default: `false`)
- `WHATSAPP_BRIDGE_BASE_URL` (required when enabled)
- `WHATSAPP_BRIDGE_TOKEN` (optional bearer token)
- `WHATSAPP_ALLOWED_NUMBERS` (required unless `WHATSAPP_DISABLE_AUTH=true`)
- `WHATSAPP_DISABLE_AUTH` (default: `false`)

Optional Telegram transport:
- `TELEGRAM_ENABLED` (default: `false`)
- `TELEGRAM_BOT_TOKEN` (required when enabled)
- `TELEGRAM_WEBHOOK_SECRET` (optional, validates `X-Telegram-Bot-Api-Secret-Token`)
- `TELEGRAM_ALLOWED_USER_IDS` (required unless `TELEGRAM_DISABLE_AUTH=true`)
- `TELEGRAM_ALLOWED_CHAT_IDS` (optional group allowlist)
- `TELEGRAM_DISABLE_AUTH` (default: `false`)
- `TELEGRAM_BOT_USERNAME` (optional, used for group mention/reply detection)

Chat options:
- `OPENROUTER_MODEL` (default: `openai/gpt-4o-mini`)
- `OPENROUTER_TIMEOUT_SECONDS` (default: `45`)
- `OPENROUTER_MAX_OUTPUT_TOKENS` (default: `300`)
- `BOT_CHAT_TEMPERATURE` (default: `0.6`)
- `BOT_CHAT_CONTEXT_TURNS` (default: `6`)
- `BOT_CHAT_CONTEXT_TTL_SECONDS` (default: `1800`)
- `BOT_CHAT_SYSTEM_PROMPT` (optional)
  This env var overrides file-based prompts when set.
- Prompt files:
  local-only override: `src/signal_bot_orx/chat_system_prompt.md` (git-ignored)
  distribution default: `src/signal_bot_orx/default_chat_system_prompt.md` (tracked)
- `BOT_CHAT_FORCE_PLAIN_TEXT` (default: `true`)
- `BOT_MENTION_ALIASES` (default: `@signalbot,@bot`)
- `BOT_MAX_PROMPT_CHARS` (default: `700`)

Search options:
- `BOT_SEARCH_ENABLED` (default: `true`)
- `BOT_SEARCH_CONTEXT_MODE` (`no_context|context`, default: `no_context`)
- `BOT_SEARCH_MODE_SEARCH_ENABLED` (default: `true`, controls `/search`)
- `BOT_SEARCH_MODE_NEWS_ENABLED` (default: `true`, controls `/news`)
- `BOT_SEARCH_MODE_WIKI_ENABLED` (default: `true`, controls `/wiki`)
- `BOT_SEARCH_MODE_IMAGES_ENABLED` (default: `true`, controls `/images`)
- `BOT_SEARCH_MODE_VIDEOS_ENABLED` (default: `true`, controls `/videos`)
- `BOT_SEARCH_DEBUG_LOGGING` (default: `false`, logs routing/summarization decisions without raw message/result payloads)
- `BOT_SEARCH_PERSONA_ENABLED` (default: `false`, reuse core personality for search summaries)
- `BOT_SEARCH_USE_HISTORY_FOR_SUMMARY` (default: `false`, include last 2 turns in search summary prompt)
- `BOT_SEARCH_REGION` (default: `us-en`)
- `BOT_SEARCH_SAFESEARCH` (`on|moderate|off`, default: `moderate`)
- `BOT_SEARCH_BACKEND_STRATEGY` (`first_non_empty|aggregate`, default: `first_non_empty`)
- `BOT_SEARCH_BACKEND_SEARCH_ORDER` (default: `duckduckgo,bing,google,yandex,grokipedia`)
- `BOT_SEARCH_BACKEND_NEWS_ORDER` (default: `duckduckgo,bing,yahoo`)
- `BOT_SEARCH_BACKEND_SEARCH` (default: `auto`, backend for `/search` + auto mode `search`)
- `BOT_SEARCH_BACKEND_NEWS` (default: `auto`, backend for `/news` + auto mode `news`)
- `BOT_SEARCH_BACKEND_WIKI` (default: `wikipedia`, backend for `/wiki` + auto mode `wiki`)
- `BOT_SEARCH_BACKEND_IMAGES` (default: `duckduckgo`, backend for `/images`)
- `BOT_SEARCH_BACKEND_VIDEOS` (default: `youtube`, backend for `/videos`)
- `BOT_SEARCH_TEXT_MAX_RESULTS` (default: `5`)
- `BOT_SEARCH_NEWS_MAX_RESULTS` (default: `5`)
- `BOT_SEARCH_WIKI_MAX_RESULTS` (default: `3`)
- `BOT_SEARCH_IMAGES_MAX_RESULTS` (default: `3`, top image sent)
- `BOT_SEARCH_VIDEOS_MAX_RESULTS` (default: `5`, numbered list size for `/videos`)
- `BOT_SEARCH_JMAIL_MAX_RESULTS` (default: `10`)
- `BOT_SEARCH_LOLCOW_CYRAXX_MAX_RESULTS` (default: `3`)
- `BOT_SEARCH_LOLCOW_LARSON_MAX_RESULTS` (default: `3`)
- `BOT_SEARCH_TIMEOUT_SECONDS` (default: `8`)
- `BOT_SEARCH_SOURCE_TTL_SECONDS` (default: `1800`)

Default search privacy behavior:
- `BOT_SEARCH_CONTEXT_MODE=no_context` means DDGS requests only run for explicit slash commands.
- Set `BOT_SEARCH_CONTEXT_MODE=context` to allow model-routed auto-search from normal chat messages.
- `/videos` is always explicit command mode and never selected by auto-routing.
- In `context` mode, ambiguous follow-ups (for example, pronoun-only references) may trigger `Who are you referring to?`; a short next reply can be applied to continue the pending query.
- You can disable any explicit DDGS command with its corresponding `BOT_SEARCH_MODE_*_ENABLED=false` flag.
- Set `BOT_SEARCH_DEBUG_LOGGING=true` to inspect auto-search decisions (`should_search`, `mode`, query length, path) during debugging.
- `BOT_SEARCH_BACKEND_STRATEGY=first_non_empty` stops at first backend with results.
- `BOT_SEARCH_BACKEND_STRATEGY=aggregate` queries all backends in order, merges/de-dupes by URL, then caps final output to `BOT_SEARCH_TEXT_MAX_RESULTS` / `BOT_SEARCH_NEWS_MAX_RESULTS`.
- `BOT_SEARCH_BACKEND_*_ORDER` defines fallback chains for general `search` and `news`.
- If an order var is set, it takes precedence over legacy single-backend vars.
- `/wiki` remains explicit encyclopedia mode and uses `BOT_SEARCH_BACKEND_WIKI`.
- News backend order rejects encyclopedia backends (`wikipedia`, `grokipedia`).
- With `BOT_SEARCH_PERSONA_ENABLED=true`, search summaries reuse `BOT_CHAT_SYSTEM_PROMPT` but keep factual constraints.

Image mode (`/imagine`) options:
- `OPENROUTER_IMAGE_API_KEY`
- `OPENROUTER_IMAGE_MODEL`
- `OPENROUTER_IMAGE_TIMEOUT_SECONDS` (default: `90`)

Weather options (OpenWeatherMap):
- `WEATHER_API_KEY` (required for weather commands)
- `WEATHER_UNITS` (`metric|imperial`, default: `metric`)
- `WEATHER_DEFAULT_LOCATION` (optional default for empty location args)

Webhook/runtime options:
- `BOT_GROUP_REPLY_MODE` (`group` or `dm_fallback`, default: `group`)
- `BOT_WEBHOOK_HOST` (default: `127.0.0.1`)
- `BOT_WEBHOOK_PORT` (default: `8001`)
  `.env.example` uses `BOT_WEBHOOK_HOST=0.0.0.0` as a deployment-friendly bind example.

**NOTE:** You can use the same key for both `OPENROUTER_CHAT_API_KEY` and
`OPENROUTER_IMAGE_API_KEY` if you are okay sharing limits/settings across chat
and image calls.

## Run

Load environment variables before starting the bot:

```bash
set -a
source .env
set +a
```

Then start the service:

```bash
uv run signal-bot-orx
```

Endpoints:
- `GET /healthz`
- `POST /webhook/signal`
- `POST /webhook/whatsapp` (only active when `WHATSAPP_ENABLED=true`)
- `POST /webhook/telegram` (only active when `TELEGRAM_ENABLED=true`)

If you skip exporting `.env`, startup will fail with missing required
environment variable errors.

Configure `signal-cli-rest-api` callback target:

`http://<BOT_WEBHOOK_HOST>:<BOT_WEBHOOK_PORT>/webhook/signal`

Configure Telegram webhook manually:

```bash
curl -sS "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \
  -d "url=https://<YOUR_PUBLIC_HOST>/webhook/telegram" \
  -d 'allowed_updates=["message","edited_message"]' \
  -d "secret_token=${TELEGRAM_WEBHOOK_SECRET}"
```

Group behavior on Telegram: the bot responds only when mentioned (`@<bot_username>`) or when users reply to the bot.

## Usage

Group chat:

```text
@bot summarize the key decisions from this thread
```

Direct message chat:

```text
summarize the key decisions from this thread
```

Explicit search commands:

```text
/search latest OpenRouter announcements
/news major AI regulation updates
/wiki Ada Lovelace
/images red fox watercolor
/videos nick land interview
```

Video follow-up selection:

```text
1
```

Source follow-ups:

```text
/source Ada claim
source for the second claim
```

Optional image mode:

```text
/imagine a watercolor fox reading a map
```

Weather commands:

```text
/weather London
/forecast Tokyo
```

## Development

```bash
uv run ruff check .
uv run ruff format . && ./scripts/format.sh
uv run ty check .
uv run pytest
uv build
```

## Detailed Setup

See `docs/README.md`.

## License

This project is licensed under the MIT License. See `LICENSE`.
Third-party dependency notices are documented in `THIRD_PARTY_NOTICES.md`.
