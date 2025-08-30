from __future__ import annotations

import importlib.util as _il
import os
from typing import Set

import pytest

# Minimal env to satisfy app.config.Settings at import time
os.environ.setdefault("BOT_TOKEN", "TEST_TOKEN")
os.environ.setdefault("BOT_CHANNEL", "@test")

# Skip DB async tests if greenlet is unavailable (e.g., Python 3.13 env)
if _il.find_spec("greenlet") is None:  # pragma: no cover
    pytest.skip("greenlet is not installed; skipping DB async tests", allow_module_level=True)

from app.db import get_async_session
from app.db.engine import close_engine, init_engine
from app.db.models import Roulette
from app.routers.my import _list_manageable_channels, _list_open_roulettes


class _DummyMember:
    def __init__(self, status: str) -> None:
        self.status = status


class _DummyChat:
    def __init__(self, title: str) -> None:
        self.title = title
        self.type = "channel"


class _DummyBot:
    def __init__(self, admin_chats: Set[int]) -> None:
        self._admin_chats = set(admin_chats)

    async def get_chat_member(self, chat_id: int | str, user_id: int) -> _DummyMember:
        # Treat username strings as non-admin in this stub
        if isinstance(chat_id, int) and chat_id in self._admin_chats:
            return _DummyMember("administrator")
        return _DummyMember("member")

    async def get_chat(self, chat_id: int | str) -> _DummyChat:
        return _DummyChat(f"Channel {chat_id}")


@pytest.mark.asyncio
async def test_manageable_channels_owner_and_admin(tmp_path) -> None:
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{tmp_path}/test.sqlite3"
    await init_engine(os.environ["DATABASE_URL"])  # auto-creates schema for sqlite
    user_owner = 100
    user_other = 200
    ch1 = 1111
    ch2 = 2222
    # Seed: open roulette in ch1 by owner; open roulette in ch2 by other user
    async for session in get_async_session():
        session.add(
            Roulette(
                owner_id=user_owner,
                channel_id=ch1,
                text_raw="hello",
                text_style="plain",
                winners_count=1,
                is_open=True,
            )
        )
        session.add(
            Roulette(
                owner_id=user_other,
                channel_id=ch2,
                text_raw="world",
                text_style="plain",
                winners_count=1,
                is_open=True,
            )
        )
        await session.commit()
    bot = _DummyBot(admin_chats={ch2})
    chs = await _list_manageable_channels(bot, user_owner)
    # Should include ch1 (owner) and ch2 (admin)
    ids = {c for c, _ in chs}
    assert ch1 in ids and ch2 in ids
    await close_engine()


@pytest.mark.asyncio
async def test_open_roulettes_order_and_filter(tmp_path) -> None:
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{tmp_path}/test2.sqlite3"
    await init_engine(os.environ["DATABASE_URL"])  # auto-creates schema for sqlite
    user_owner = 300
    ch1 = 3333
    # Seed multiple roulettes (2 open, 1 closed)
    async for session in get_async_session():
        r1 = Roulette(
            owner_id=user_owner,
            channel_id=ch1,
            text_raw="a" * 40,
            text_style="plain",
            winners_count=1,
            is_open=True,
        )
        r2 = Roulette(
            owner_id=user_owner,
            channel_id=ch1,
            text_raw="b" * 10,
            text_style="plain",
            winners_count=1,
            is_open=True,
        )
        r3 = Roulette(
            owner_id=user_owner,
            channel_id=ch1,
            text_raw="c" * 10,
            text_style="plain",
            winners_count=1,
            is_open=False,
        )
        session.add_all([r1, r2, r3])
        await session.commit()
    # Fetch list
    lst = await _list_open_roulettes(ch1)
    # Expect only 2, ordered by id desc (r2 newer than r1)
    assert len(lst) == 2
    ids = [rid for rid, _ in lst]
    assert ids == sorted(ids, reverse=True)
    # Preview for long text should be trimmed with ellipsis
    _, preview = lst[-1]
    assert len(preview) <= 32
    await close_engine()
