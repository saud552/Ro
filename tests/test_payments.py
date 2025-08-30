from __future__ import annotations

import importlib.util as _il
import os

import pytest

# Skip these DB integration tests if greenlet is unavailable (e.g., Python 3.13 env)
if _il.find_spec("greenlet") is None:  # pragma: no cover
    pytest.skip("greenlet is not installed; skipping DB async tests", allow_module_level=True)

from app.db import get_async_session
from app.db.engine import close_engine, init_engine
from app.db.models import Base
from app.services.payments import (
    get_monthly_price_stars,
    get_one_time_price_stars,
    grant_monthly,
    grant_one_time,
    has_gate_access,
)


@pytest.mark.asyncio
async def test_prices_defaults_sqlite(tmp_path) -> None:
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{tmp_path}/test.sqlite3"
    await init_engine(os.environ["DATABASE_URL"])
    # No settings rows -> defaults (ensure tables exist for settings queries)
    async for session in get_async_session():
        await session.run_sync(
            lambda sync_sess: Base.metadata.create_all(bind=sync_sess.get_bind())
        )
    monthly = await get_monthly_price_stars()
    one = await get_one_time_price_stars()
    assert monthly >= 1
    assert one >= 1
    await close_engine()


@pytest.mark.asyncio
async def test_entitlements_flow(tmp_path) -> None:
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{tmp_path}/test2.sqlite3"
    await init_engine(os.environ["DATABASE_URL"])
    # Ensure schema exists
    async for session in get_async_session():
        await session.run_sync(
            lambda sync_sess: Base.metadata.create_all(bind=sync_sess.get_bind())
        )
    user_id = 123

    # Initially no access
    ok = await has_gate_access(user_id)
    assert ok is False

    # Grant one-time and consume
    await grant_one_time(user_id, 1)
    ok = await has_gate_access(user_id)
    assert ok is True
    ok2 = await has_gate_access(user_id, consume_one_time=True)
    assert ok2 is True
    # Consumed -> should still be true if monthly set later
    # Grant monthly and verify
    await grant_monthly(user_id)
    ok3 = await has_gate_access(user_id)
    assert ok3 is True

    await close_engine()
