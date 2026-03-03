from __future__ import annotations

from contextlib import suppress
from typing import Any, Optional

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message


async def safe_answer(cb: CallbackQuery, *args: Any, **kwargs: Any) -> None:
    with suppress(Exception):
        await cb.answer(*args, **kwargs)


async def safe_edit_text(message: Message, *args: Any, **kwargs: Any) -> None:
    try:
        await message.edit_text(*args, **kwargs)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            return
        raise
    except Exception:
        with suppress(Exception):
            await message.answer(*args, **kwargs)


async def safe_edit_markup(
    message: Message, reply_markup: Optional[InlineKeyboardMarkup] = None, **kwargs: Any
) -> None:
    try:
        await message.edit_reply_markup(reply_markup=reply_markup, **kwargs)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            return
        raise
    except Exception:
        pass
