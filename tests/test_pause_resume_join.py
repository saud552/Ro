from __future__ import annotations

import os
import secrets
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
            }
        )

    async def send_message(self, *args, **kwargs):
        return SimpleNamespace(message_id=1)


@pytest.mark.asyncio
async def test_join_flow():
    from sqlalchemy import select

    from app.db import get_async_session
    from app.db.engine import close_engine, init_engine
    from app.db.models import Contest, ContestType
    from app.routers.roulette import handle_join_request as join_handler

    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_join.sqlite3"
    await init_engine(os.environ["DATABASE_URL"])

    async for session in get_async_session():
        r = Contest(
            owner_id=10,
            channel_id=8888,
            unique_code=f"join_test_{secrets.token_hex(4)}",
            type=ContestType.ROULETTE,
            text_raw="hello",
            text_style="plain",
            winners_count=1,
            is_open=True,
            anti_bot_enabled=False,
        )
        session.add(r)
        await session.flush()
        rid = r.id
        await session.commit()

    bot = _Bot()

    async def _ans(*args, **kwargs):
        return None

    cb_join = SimpleNamespace(
        bot=bot,
        from_user=SimpleNamespace(id=99, full_name="Tester"),
        data=f"join:{rid}",
        id="123",
        message=SimpleNamespace(answer=_ans, edit_text=_ans),
    )
    cb_join.answer = _ans
    bot.set_member(8888, 99, "member")

    async def _async_none(*args, **kwargs):
        return None

    state = SimpleNamespace(set_state=_async_none, update_data=_async_none, get_data=lambda: {})

    await join_handler(cb_join, state)

    async for session in get_async_session():
        from app.db.models import ContestEntry

        stmt = select(ContestEntry).where(
            ContestEntry.contest_id == rid, ContestEntry.user_id == 99
        )
        entry = (await session.execute(stmt)).scalar_one_or_none()
        assert entry is not None

    await close_engine()
