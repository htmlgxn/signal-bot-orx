# Changelog

## 2026.2.14

- Added first-class DDGS search support with `/search`, `/news`, `/wiki`, `/images`, and `/source`.
- Added search configuration surface in `BOT_SEARCH_*`, including per-mode enable flags and per-mode backend selection.
- Added context-mode auto-search routing with follow-up entity resolution across recent chat and recent source memory.
- Added pending follow-up clarification handling so short next-turn replies can continue ambiguous search questions.
- Added search summary controls for persona reuse (`BOT_SEARCH_PERSONA_ENABLED`) and optional recent-history inclusion (`BOT_SEARCH_USE_HISTORY_FOR_SUMMARY`).
- Added prompt file split: local override via `src/signal_bot_orx/chat_system_prompt.md` (git-ignored) and tracked default via `src/signal_bot_orx/default_chat_system_prompt.md`.
- Fixed Python 3 exception tuple syntax in `group_resolver.py`.
- Added `THIRD_PARTY_NOTICES.md` and included it in package license files for DDGS notice coverage.

## 2026.2.13

- Renamed distribution and CLI to `signal-bot-orx`.
- Migrated Python package namespace to `signal_bot_orx`.
- Switched project licensing metadata and documentation to MIT.
- Rewrote user and setup documentation for current OpenRouter-based behavior.
- Added baseline CI workflow for lint/type/test/build checks.
