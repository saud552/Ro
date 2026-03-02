from __future__ import annotations

from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


# ملخص: القاعدة الأساسية لجميع نماذج قاعدة البيانات.
class Base(DeclarativeBase):
    pass


_async_engine: AsyncEngine | None = None
_async_sessionmaker: async_sessionmaker[AsyncSession] | None = None


async def init_engine(database_url: str) -> None:
    """Initialize the SQLAlchemy engine and sessionmaker."""
    global _async_engine, _async_sessionmaker

    # Use asyncpg for PostgreSQL by default
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    # SQLite doesn't support pool_size and max_overflow
    kwargs = {
        "future": True,
    }
    if "sqlite" not in database_url.lower():
        kwargs.update(
            {
                "pool_pre_ping": True,
                "pool_size": 20,
                "max_overflow": 10,
            }
        )

    _async_engine = create_async_engine(database_url, **kwargs)
    _async_sessionmaker = async_sessionmaker(
        bind=_async_engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )

    # For local dev/SQLite, auto-create tables
    if "sqlite" in database_url.lower():
        from . import models  # noqa: F401

        async with _async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)


async def close_engine() -> None:
    """Dispose of the database engine."""
    global _async_engine
    if _async_engine is not None:
        await _async_engine.dispose()
        _async_engine = None


async def get_async_session() -> AsyncIterator[AsyncSession]:
    """Yield an asynchronous database session."""
    if _async_sessionmaker is None:
        raise RuntimeError("Engine not initialized. Call init_engine() first.")

    async with _async_sessionmaker() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
