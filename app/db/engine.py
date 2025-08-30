from __future__ import annotations

from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

_async_engine: AsyncEngine | None = None
_async_sessionmaker: async_sessionmaker[AsyncSession] | None = None


# ملخص: قاعدة ORM لجميع النماذج.
class Base(DeclarativeBase):
    pass


async def init_engine(database_url: str) -> None:
    global _async_engine, _async_sessionmaker
    _async_engine = create_async_engine(database_url, future=True, pool_pre_ping=True)
    _async_sessionmaker = async_sessionmaker(bind=_async_engine, expire_on_commit=False)

    # Auto-create schema only for SQLite to avoid missing-table errors in local/dev
    # For PostgreSQL (prod), Alembic migrations manage the schema.
    if database_url.lower().startswith("sqlite"):
        from .models import Base as ModelsBase  # ensure models are imported

        async with _async_engine.begin() as conn:
            await conn.run_sync(ModelsBase.metadata.create_all)


async def close_engine() -> None:
    global _async_engine
    if _async_engine is not None:
        await _async_engine.dispose()
        _async_engine = None


async def get_async_session() -> AsyncIterator[AsyncSession]:
    if _async_sessionmaker is None:
        raise RuntimeError("Engine not initialized")
    async with _async_sessionmaker() as session:
        yield session
