from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from loguru import logger

from .config import settings
from .db import get_async_session
from .db.engine import close_engine, init_engine
from .routers import setup_routers
from .services.context import runtime


# ملخص: دالة تُستدعى عند بدء تشغيل البوت لتسجيل الرسالة.
async def on_startup(bot: Bot) -> None:
    logger.info("Bot started")


# ملخص: دالة تُستدعى عند إيقاف البوت لتسجيل الرسالة.
async def on_shutdown(bot: Bot) -> None:
    logger.info("Bot stopped")


# ملخص: ينشئ Dispatcher مع تخزين الحالة المناسب ويثبت الراوترات.
async def create_dispatcher(bot: Bot) -> Dispatcher:
    if settings.redis_url:
        try:
            from aiogram.fsm.storage.redis import RedisStorage
            from redis.asyncio import from_url as redis_from_url

            redis = redis_from_url(settings.redis_url)
            storage: BaseStorage = RedisStorage(redis=redis)
            runtime.redis = redis
        except Exception:
            storage = MemoryStorage()
            runtime.redis = None
    else:
        if getattr(settings, "require_redis", False):
            raise RuntimeError("Redis is required by configuration but REDIS_URL is not set")
        storage = MemoryStorage()
        runtime.redis = None

    dp = Dispatcher(storage=storage)
    setup_routers(dp)
    # cache bot identity
    me = await bot.get_me()
    dp["bot_username"] = me.username or ""
    dp["bot_id"] = me.id
    runtime.bot_username = dp["bot_username"]
    runtime.bot_id = dp["bot_id"]
    return dp


async def _expire_feature_access_loop() -> None:
    # Periodically remove or mark expired monthly entitlements (no-op for one-time credits)
    while True:
        try:
            now = datetime.now(timezone.utc)
            from .db.models import FeatureAccess

            async for session in get_async_session():
                # Example maintenance: log count of expired monthly records
                from sqlalchemy import select as _sel

                expired = (
                    (
                        await session.execute(
                            _sel(FeatureAccess).where(
                                (FeatureAccess.expires_at.is_not(None))
                                & (FeatureAccess.expires_at < now)
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                if expired:
                    logger.info(f"feature access expired count: {len(expired)}")
        except Exception as e:
            logger.exception("feature access maintenance error: {}", e)
        finally:
            await asyncio.sleep(3600)


async def run_polling(bot: Bot, dp: Dispatcher) -> None:
    # run maintenance task in background
    asyncio.create_task(_expire_feature_access_loop())
    await dp.start_polling(bot, on_startup=on_startup, on_shutdown=on_shutdown)


async def run_webhook(bot: Bot, dp: Dispatcher) -> None:
    app = web.Application()
    # Secure the path with token
    webhook_path = settings.webhook_path(settings.bot_token)
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=webhook_path)
    setup_application(app, dp, on_startup=[on_startup], on_shutdown=[on_shutdown])

    webhook_url = settings.webhook_full_url(settings.bot_token)
    await bot.set_webhook(url=webhook_url, secret_token=settings.webhook_secret)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host=settings.webapp_host, port=settings.webapp_port)
    logger.info(f"Webhook listening on {settings.webapp_host}:{settings.webapp_port}{webhook_path}")
    await site.start()
    # Run forever
    asyncio.create_task(_expire_feature_access_loop())
    while True:
        await asyncio.sleep(3600)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    # Ensure Loguru writes to file for runtime diagnostics
    try:
        logger.add("/workspace/bot.log", rotation="10 MB", backtrace=True, diagnose=True)
    except Exception:
        # Fallback to current working dir if workspace path unavailable
        with suppress(Exception):
            logger.add("bot.log", rotation="10 MB", backtrace=True, diagnose=True)
    await init_engine(settings.database_url)
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = await create_dispatcher(bot)

    try:
        if settings.webhook_url:
            await run_webhook(bot, dp)
        else:
            await run_polling(bot, dp)
    finally:
        with suppress(Exception):
            await bot.delete_webhook(drop_pending_updates=False)
        with suppress(Exception):
            await bot.session.close()
        with suppress(Exception):
            await close_engine()


if __name__ == "__main__":
    asyncio.run(main())
