from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("BOT_TOKEN", "TEST_TOKEN")
os.environ.setdefault("BOT_CHANNEL", "@test")


class _Bot:
    def __init__(self):
        self._members = {}
        self.messages = []

    def set_member(self, chat_id: int, user_id: int, status: str):
        self._members[(chat_id, user_id)] = SimpleNamespace(status=status)

    async def get_chat_member(self, chat_id: int | str, user_id: int):
        return self._members.get((chat_id, user_id), SimpleNamespace(status="member"))

    async def create_chat_invite_link(self, chat_id: int, creates_join_request: bool = False):
        return SimpleNamespace(invite_link=f"https://t.me/+INV{chat_id}")

    async def get_chat(self, chat_id: int | str):
        return SimpleNamespace(title=f"Chat {chat_id}")

    async def send_message(self, chat_id: int, text: str, **kwargs):
        self.messages.append(text)


@pytest.mark.asyncio
async def test_gate_pick_list_and_apply(monkeypatch):
    from app.routers.roulette import gate_pick as gate_pick_handler
    from app.routers.roulette import gate_pick_apply as gate_pick_apply_handler
    from app.services import context as _ctx

    _ctx.runtime.bot_id = 999

    # Seed BotChat rows
    from app.db import get_async_session
    from app.db.engine import close_engine, init_engine
    from app.db.models import BotChat

    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_gate_pick.sqlite3"
    await init_engine(os.environ["DATABASE_URL"])  # sqlite auto schema

    async for session in get_async_session():
        session.add_all(
            [
                BotChat(chat_id=1001, chat_type="channel", title="A"),
                BotChat(chat_id=1002, chat_type="supergroup", title="B"),
            ]
        )
        await session.commit()

    bot = _Bot()
    # User admin only in 1001; bot admin فقط في 1002 -> لا عنصر مشترك
    bot.set_member(1001, 1111, "administrator")
    bot.set_member(1002, 999, "administrator")

    cb = SimpleNamespace(bot=bot, from_user=SimpleNamespace(id=1111))

    async def _ans(*args, **kwargs):
        return None

    cb.message = SimpleNamespace(answer=_ans)
    cb.answer = _ans

    # Expect no eligible destinations
    state_for_list = SimpleNamespace()

    async def _upd_menu(**kwargs):
        return None

    state_for_list.update_data = _upd_menu
    await gate_pick_handler(cb, state_for_list)
    # Make both admins for 1001
    bot.set_member(1001, 999, "administrator")
    await gate_pick_handler(cb, state_for_list)

    # Apply selection should add to FSM gate list
    state_data = {"gate_channels": []}

    async def _get_data():
        return state_data

    async def _update_data(**kwargs):
        state_data.update(kwargs)

    state = SimpleNamespace(get_data=_get_data, update_data=_update_data)

    cb_apply = SimpleNamespace(
        bot=bot, from_user=SimpleNamespace(id=1111), data="gate_pick_apply:1001"
    )
    cb_apply.message = SimpleNamespace(answer=_ans)
    cb_apply.answer = _ans

    await gate_pick_apply_handler(cb_apply, state)
    assert state_data["gate_channels"], "Expected a gate to be added"

    await close_engine()
