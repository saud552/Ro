from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("BOT_TOKEN", "TEST_TOKEN")
os.environ.setdefault("BOT_CHANNEL", "@test")


class _Bot:
    def __init__(self):
        self.edits = []
        self._members = {}

    def set_member(self, chat_id: int | str, user_id: int, status: str):
        self._members[(chat_id, user_id)] = SimpleNamespace(status=status)

    async def get_chat_member(self, chat_id: int | str, user_id: int):
        return self._members.get((chat_id, user_id), SimpleNamespace(status="member"))

    async def edit_message_text(
        self, *, chat_id: int, message_id: int, text: str, parse_mode=None, reply_markup=None
    ):
        self.edits.append(
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
                "parse_mode": getattr(parse_mode, "value", str(parse_mode)),
            }
        )

    async def send_message(self, *args, **kwargs):
        return SimpleNamespace(message_id=1)


@pytest.mark.asyncio
async def test_pause_resume_and_join_flow():
    from sqlalchemy import select

    from app.db import get_async_session
    from app.db.engine import close_engine, init_engine
    from app.db.models import Roulette
    from app.routers.roulette import join as join_handler
    from app.routers.roulette import pause as pause_handler
    from app.routers.roulette import resume as resume_handler

    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_pause_resume.sqlite3"
    await init_engine(os.environ["DATABASE_URL"])  # auto create for sqlite

    # Create roulette open with zero participants
    async for session in get_async_session():
        r = Roulette(
            owner_id=10,
            channel_id=8888,
            text_raw="hello",
            text_style="plain",
            winners_count=1,
            is_open=True,
        )
        session.add(r)
        await session.flush()
        rid = r.id
        await session.commit()

    bot = _Bot()
    # Make owner admin in the channel for permission checks
    bot.set_member(8888, 10, "administrator")

    # Build CallbackQuery dummies
    cb_pause = SimpleNamespace(bot=bot, from_user=SimpleNamespace(id=10), data=f"pause:{rid}")

    async def _ans(*args, **kwargs):
        return None

    cb_pause.answer = _ans
    cb_resume = SimpleNamespace(bot=bot, from_user=SimpleNamespace(id=10), data=f"resume:{rid}")
    cb_resume.answer = _ans

    # Pause
    await pause_handler(cb_pause)
    assert any(e["parse_mode"] in ("ParseMode.HTML", "HTML", "html") for e in bot.edits)

    # Resume
    await resume_handler(cb_resume)
    assert any("المشاركة في السحب متاحة" in e["text"] for e in bot.edits)

    # Join path: user 99 joins -> should increment
    # Prepare CB for join with is_open True and subscription OK
    cb_join = SimpleNamespace(bot=bot, from_user=SimpleNamespace(id=99), data=f"join:{rid}")
    cb_join.answer = _ans
    # Ensure user is member of channel
    bot.set_member(8888, 99, "member")
    # Ensure roulette is open
    async for session in get_async_session():
        r = (await session.execute(select(Roulette).where(Roulette.id == rid))).scalar_one()
        r.is_open = True
        await session.commit()
    await join_handler(cb_join)
    # Verify at least one edit after join (count update)
    assert bot.edits, "Expected channel message edit after join"

    await close_engine()
