from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("BOT_TOKEN", "TEST_TOKEN")
os.environ.setdefault("BOT_CHANNEL", "@test")


class _Bot:
    def __init__(self):
        self._members = {}

    def set_member(self, chat_id: int, user_id: int, status: str):
        self._members[(chat_id, user_id)] = SimpleNamespace(status=status)

    async def get_chat_member(self, chat_id: int | str, user_id: int):
        return self._members.get((chat_id, user_id), SimpleNamespace(status="member"))

    async def create_chat_invite_link(self, chat_id: int, creates_join_request: bool = False):
        return SimpleNamespace(invite_link=f"https://t.me/+INV{chat_id}")


@pytest.mark.asyncio
async def test_add_gate_by_forward_requires_admins():
    from app.routers.roulette import add_gate_forwarded
    from app.services import context as _ctx

    _ctx.runtime.bot_id = 999

    bot = _Bot()
    # Forwarded chat stub
    fwd_chat = SimpleNamespace(id=5555, type="channel", title="FWD")

    async def _answer(*args, **kwargs):
        return None

    message = SimpleNamespace(
        bot=bot,
        from_user=SimpleNamespace(id=1111),
        forward_from_chat=fwd_chat,
        forward_origin=None,
        answer=_answer,
    )

    # FSM state capture
    state_data = {"gate_channels": []}

    async def _get():
        return state_data

    async def _upd(**kwargs):
        state_data.update(kwargs)

    state = SimpleNamespace(get_data=_get, update_data=_upd)

    # user not admin → should not add
    await add_gate_forwarded(message, state)
    assert not state_data["gate_channels"]
    # user admin but bot not admin → should not add
    bot.set_member(5555, 1111, "administrator")
    await add_gate_forwarded(message, state)
    assert not state_data["gate_channels"]
    # bot admin → success
    bot.set_member(5555, 999, "administrator")
    await add_gate_forwarded(message, state)
    assert state_data["gate_channels"], "Expected gate added after both admins"
