import os
from types import SimpleNamespace

import pytest

# Minimal env for Settings import side effects
os.environ.setdefault("BOT_TOKEN", "TEST_TOKEN")
os.environ.setdefault("BOT_CHANNEL", "@test")


class _DummyMessage:
    def __init__(self, chat_type: str, from_user_id: int) -> None:
        self.chat = SimpleNamespace(type=chat_type)
        self.from_user = SimpleNamespace(id=from_user_id)


class _DummyBot:
    def __init__(self) -> None:
        self._sent = []

    async def send_message(self, chat_id: int, text: str) -> None:
        # Simulate failure to ensure suppress works (e.g., user has no open chat)
        raise RuntimeError("cannot DM user in test stub")


class _DummyCallback:
    def __init__(self, chat_type: str, user_id: int) -> None:
        self.message = _DummyMessage(chat_type, user_id)
        self.from_user = SimpleNamespace(id=user_id)
        self.bot = _DummyBot()
        self._answered = False

    async def answer(self, *args, **kwargs):
        self._answered = True


@pytest.mark.asyncio
async def test_open_my_draws_from_channel_suppressed() -> None:
    # Import handler
    from app.routers.start import open_my_draws

    cb = _DummyCallback(chat_type="channel", user_id=12345)
    # Should not raise due to suppress around send_message
    await open_my_draws(cb)
    assert cb._answered is True
