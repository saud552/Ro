from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

# Minimal env for Settings imports in app
os.environ.setdefault("BOT_TOKEN", "TEST_TOKEN")
os.environ.setdefault("BOT_CHANNEL", "@test")


class _DummyBot:
    def __init__(self):
        self.edits = []
        self._users = {}

    def set_user(
        self, uid: int, username: str | None, first_name: str = "", last_name: str = ""
    ) -> None:
        self._users[uid] = SimpleNamespace(
            username=username, first_name=first_name, last_name=last_name
        )

    async def get_chat(self, chat_id: int):
        # Return user info for DM lookups during announce
        if isinstance(chat_id, int) and chat_id in self._users:
            return self._users[chat_id]
        return SimpleNamespace(title=f"Channel {chat_id}")

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
        # Ignore in test (DM to winners)
        return None


class _DummyCB:
    def __init__(self):
        self.bot = _DummyBot()
        self.from_user = SimpleNamespace(id=999)
        self.message = SimpleNamespace()

    async def answer(self, *args, **kwargs):
        return None


@pytest.mark.asyncio
async def test_announce_html_parse_mode_and_content(monkeypatch):
    # Prepare a roulette row and participants
    from app.db import get_async_session
    from app.db.engine import close_engine, init_engine
    from app.db.models import Participant, Roulette
    from app.routers.roulette import draw as draw_handler

    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_announce.sqlite3"
    await init_engine(os.environ["DATABASE_URL"])  # auto create for sqlite

    # Seed a roulette and participants
    rid = None
    async for session in get_async_session():
        r = Roulette(
            owner_id=1,
            channel_id=7777,
            text_raw="hello",
            text_style="plain",
            winners_count=1,
            is_open=False,
        )
        session.add(r)
        await session.flush()
        rid = r.id
        session.add(Participant(roulette_id=rid, user_id=123456))
        await session.commit()

    cb = _DummyCB()
    # Make the invoking user the owner to pass authorization
    cb.from_user.id = 1
    # Provide user details for winner to build nicer display (optional)
    cb.bot.set_user(123456, username="winneruser", first_name="First", last_name="Last")

    # Monkeypatch get_async_session to ensure our session is used (already correct), and runtime.bot_username
    from app.services import context as _ctx

    _ctx.runtime.bot_username = "botname"

    # Execute handler
    cb.data = f"draw:{rid}"

    # Inject a minimal prep message namespace into the function scope by monkeypatching send_message to return obj with message_id
    async def _send_message(channel_id, text, reply_to_message_id=None):
        return SimpleNamespace(message_id=42)

    cb.bot.send_message = _send_message

    await draw_handler(cb)

    # Verify an edit occurred with HTML parse mode
    assert cb.bot.edits, "No message edits captured"
    last_edit = cb.bot.edits[-1]
    assert last_edit["parse_mode"] in ("ParseMode.HTML", "HTML", "html")
    assert "<a href=" in last_edit["text"], "Winners list should contain HTML anchor"

    await close_engine()
