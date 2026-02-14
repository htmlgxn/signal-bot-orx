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

Optional search tuning:

```bash
BOT_SEARCH_ENABLED=true
BOT_SEARCH_CONTEXT_MODE=no_context
BOT_SEARCH_MODE_SEARCH_ENABLED=true
BOT_SEARCH_MODE_NEWS_ENABLED=true
BOT_SEARCH_MODE_WIKI_ENABLED=true
BOT_SEARCH_MODE_IMAGES_ENABLED=true
BOT_SEARCH_DEBUG_LOGGING=false
BOT_SEARCH_PERSONA_ENABLED=false
BOT_SEARCH_USE_HISTORY_FOR_SUMMARY=false
BOT_SEARCH_REGION=us-en
BOT_SEARCH_SAFESEARCH=moderate
BOT_SEARCH_BACKEND_SEARCH_ORDER=duckduckgo,bing,google,yandex,grokipedia
BOT_SEARCH_BACKEND_NEWS_ORDER=duckduckgo,bing,yahoo
BOT_SEARCH_BACKEND_SEARCH=auto
BOT_SEARCH_BACKEND_NEWS=auto
BOT_SEARCH_BACKEND_WIKI=wikipedia
BOT_SEARCH_BACKEND_IMAGES=duckduckgo
BOT_SEARCH_TEXT_MAX_RESULTS=5
BOT_SEARCH_NEWS_MAX_RESULTS=5
BOT_SEARCH_WIKI_MAX_RESULTS=3
BOT_SEARCH_IMAGES_MAX_RESULTS=3
BOT_SEARCH_TIMEOUT_SECONDS=8
BOT_SEARCH_SOURCE_TTL_SECONDS=1800
```

Notes:
- `BOT_SEARCH_CONTEXT_MODE=no_context` (default) means DDGS is command-only.
- Set `BOT_SEARCH_CONTEXT_MODE=context` to enable auto-search routing from normal chat.
- In `context` mode, ambiguous follow-ups can trigger `Who are you referring to?`; a short next reply can be used to continue the pending search intent.
- Toggle any explicit DDGS command with `BOT_SEARCH_MODE_*_ENABLED`.
- `BOT_SEARCH_DEBUG_LOGGING=true` logs router/summarizer decision metadata (without raw message text/results) for diagnostics.
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
