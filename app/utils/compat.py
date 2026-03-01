from __future__ import annotations
from typing import Any
from aiogram.types import CallbackQuery, Message
from contextlib import suppress

async def safe_answer(cb: CallbackQuery, *args: Any, **kwargs: Any) -> None:
    with suppress(Exception):
        await cb.answer(*args, **kwargs)

async def safe_edit_text(message: Message, *args: Any, **kwargs: Any) -> None:
    with suppress(Exception):
        await message.edit_text(*args, **kwargs)
