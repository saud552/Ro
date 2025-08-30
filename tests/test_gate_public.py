from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("BOT_TOKEN", "TEST_TOKEN")
os.environ.setdefault("BOT_CHANNEL", "@test")


class _Bot:
    def __init__(self):
        self._chats = {}
        self._members = {}
        self.messages = []

    def set_channel(self, username: str, chat_id: int, title: str = "Channel"):
        self._chats[username] = SimpleNamespace(id=chat_id, type="channel", title=title)

    def set_member(self, chat_id: int, user_id: int, status: str):
        self._members[(chat_id, user_id)] = SimpleNamespace(status=status)

    async def get_chat(self, username_or_id):
        return self._chats.get(username_or_id, SimpleNamespace(id=-1, type="channel", title="X"))

    async def get_chat_member(self, chat_id, user_id):
        return self._members.get((chat_id, user_id), SimpleNamespace(status="member"))

    async def create_chat_invite_link(self, chat_id: int, creates_join_request: bool = False):
        return SimpleNamespace(invite_link=f"https://t.me/+INV{chat_id}")

    async def send_message(self, chat_id: int, text: str, **kwargs):
        self.messages.append(text)


@pytest.mark.asyncio
async def test_reject_private_link_and_require_admin(monkeypatch):
    from app.routers.roulette import add_gate_link
    from app.services import context as _ctx

    _ctx.runtime.bot_id = 999

    bot = _Bot()

    async def _answer(*args, **kwargs):
        return None

    message = SimpleNamespace(
        bot=bot,
        from_user=SimpleNamespace(id=1111),
        text="https://t.me/c/123/456",
        answer=_answer,
    )

    # FSM with public sub_view
    async def _get_data():
        return {"sub_view": "gate_add_public", "gate_channels": []}

    async def _update_data(**kwargs):
        return None

    state = SimpleNamespace(
        get_data=_get_data,
        update_data=_update_data,
    )
    # Should reject private-style link
    await add_gate_link(message, state)

    # Now test admin checks with @username
    bot.set_channel("@pub", chat_id=7777, title="Pub")
    # user not admin → should prompt admin requirement
    message.text = "@pub"
    await add_gate_link(message, state)
    # make user admin but bot not admin → should prompt raise bot
    bot.set_member(7777, 1111, "administrator")
    await add_gate_link(message, state)
    # make bot admin → should succeed
    bot.set_member(7777, 999, "administrator")

    # Track gate_channels changes by capturing update_data calls
    gates = {"items": []}

    async def upd(**kwargs):
        if "gate_channels" in kwargs:
            gates["items"] = kwargs["gate_channels"]

    state.update_data = upd
    await add_gate_link(message, state)
    assert gates["items"], "Expected gate to be added on success"
