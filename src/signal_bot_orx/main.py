from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import httpx
import uvicorn
from fastapi import FastAPI

from signal_bot_orx.chat_context import ChatContextStore
from signal_bot_orx.config import Settings
from signal_bot_orx.dedupe import DedupeCache
from signal_bot_orx.openrouter_client import OpenRouterClient, OpenRouterImageClient
from signal_bot_orx.search_client import SearchClient
from signal_bot_orx.search_context import SearchContextStore
from signal_bot_orx.search_service import SearchService
from signal_bot_orx.signal_client import SignalClient
from signal_bot_orx.webhook import WebhookHandler, build_router


def create_app(settings: Settings) -> FastAPI:
    http_client = httpx.AsyncClient()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        await http_client.aclose()

    app = FastAPI(title="signal-bot-orx", version="2.0", lifespan=lifespan)

    signal_client = SignalClient(
        base_url=settings.signal_api_base_url,
        sender_number=settings.signal_sender_number,
        http_client=http_client,
    )
    openrouter_client = OpenRouterClient(
        api_key=settings.openrouter_chat_api_key,
        model=settings.openrouter_model,
        http_client=http_client,
        base_url=settings.openrouter_base_url,
        timeout_seconds=settings.openrouter_timeout_seconds,
        max_output_tokens=settings.openrouter_max_output_tokens,
        temperature=settings.bot_chat_temperature,
        http_referer=settings.openrouter_http_referer,
        app_title=settings.openrouter_app_title,
    )

    openrouter_image_client: OpenRouterImageClient | None = None
    if settings.openrouter_image_api_key:
        openrouter_image_client = OpenRouterImageClient(
            api_key=settings.openrouter_image_api_key,
            http_client=http_client,
            base_url=settings.openrouter_base_url,
            timeout_seconds=settings.openrouter_image_timeout_seconds,
            http_referer=settings.openrouter_http_referer,
            app_title=settings.openrouter_app_title,
        )

    chat_context = ChatContextStore(
        max_turns=settings.bot_chat_context_turns,
        ttl_seconds=settings.bot_chat_context_ttl_seconds,
    )
    search_context = SearchContextStore(
        ttl_seconds=settings.bot_search_source_ttl_seconds
    )
    search_service = SearchService(
        settings=settings,
        search_client=SearchClient(),
        search_context=search_context,
        openrouter_client=openrouter_client,
        http_client=http_client,
    )
    dedupe = DedupeCache(ttl_seconds=300)
    handler = WebhookHandler(
        settings=settings,
        signal_client=signal_client,
        openrouter_client=openrouter_client,
        openrouter_image_client=openrouter_image_client,
        chat_context=chat_context,
        search_service=search_service,
        dedupe=dedupe,
    )

    app.include_router(build_router(handler))

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = Settings.from_env()
    app = create_app(settings)

    uvicorn.run(
        app,
        host=settings.bot_webhook_host,
        port=settings.bot_webhook_port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
