from __future__ import annotations

from typing import Iterable, Tuple

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from ..db.models import ContestType


def my_channels_kb(channels: Iterable[Tuple[int, str]]) -> InlineKeyboardMarkup:
    rows = []
    for chat_id, title in channels:
        rows.append(
            [InlineKeyboardButton(text=title or str(chat_id), callback_data=f"mych:{chat_id}")]
        )
    rows.append([InlineKeyboardButton(text="رجوع", callback_data="back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def my_roulettes_kb(channel_id: int, contests: Iterable[Tuple[int, str]]) -> InlineKeyboardMarkup:
    rows = []
    for rid, preview in contests:
        rows.append([InlineKeyboardButton(text=preview, callback_data=f"myr:{rid}")])
    rows.append([InlineKeyboardButton(text="رجوع", callback_data="my_draws")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def my_manage_kb(
    contest_id: int, is_open: bool, channel_id: int, participants_count: int, ctype: ContestType = ContestType.ROULETTE
) -> InlineKeyboardMarkup:
    rows = []
    # Static info button (no action)
    rows.append(
        [
            InlineKeyboardButton(text=f"المشاركون: {participants_count}", callback_data="noop"),
        ]
    )

    draw_callback = f"draw:{contest_id}"
    draw_text = "بدء السحب"
    if ctype == ContestType.VOTE:
        draw_callback = f"draw_vote:{contest_id}"
        draw_text = "إعلان الفائزين"

    rows.append(
        [
            InlineKeyboardButton(
                text=("أوقف المشاركة" if is_open else "استئناف المشاركة"),
                callback_data=(f"pause:{contest_id}" if is_open else f"resume:{contest_id}"),
            ),
            InlineKeyboardButton(text=draw_text, callback_data=draw_callback),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(text="تحديث", callback_data=f"myr:{contest_id}"),
            InlineKeyboardButton(text="سحوبات القناة", callback_data=f"mychlist:{channel_id}"),
        ]
    )
    rows.append([InlineKeyboardButton(text="سحوباتي", callback_data="my_draws")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def manage_draw_kb(contest_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="إدارة هذا السحب", callback_data=f"myr:{contest_id}")],
            [InlineKeyboardButton(text="سحوباتي", callback_data="my_draws")],
        ]
    )
