from __future__ import annotations

from typing import Iterable, Optional, Tuple

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def link_instruction_kb(bot_username: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="اختر قناة",
                    url=f"https://t.me/{bot_username}?startchannel=true&startgroup=true",
                )
            ],
            [InlineKeyboardButton(text="رجوع", callback_data="back")],
        ]
    )


def roulette_controls_kb(
    roulette_id: int,
    is_open: bool,
    bot_username: str,
    gate_links: Optional[Iterable[Tuple[str, str]]] = None,
    show_owner_controls: bool = False,
) -> InlineKeyboardMarkup:
    row1 = [InlineKeyboardButton(text="المشاركة في السحب", callback_data=f"join:{roulette_id}")]
    deep_link = f"https://t.me/{bot_username}?start=notify-{roulette_id}"
    row2 = [InlineKeyboardButton(text="ذكّرني إذا فزت", url=deep_link)]
    rows = [row1, row2]
    # Gate links as buttons (text, url)
    if gate_links:
        gate_row = [InlineKeyboardButton(text=text, url=url) for text, url in gate_links]
        if gate_row:
            rows.append(gate_row)
    if show_owner_controls:
        owner_controls = [
            InlineKeyboardButton(text="ابدأ السحب", callback_data=f"draw:{roulette_id}"),
            InlineKeyboardButton(
                text="أوقف المشاركة" if is_open else "استئناف المشاركة",
                callback_data=(f"pause:{roulette_id}" if is_open else f"resume:{roulette_id}"),
            ),
        ]
        rows.append(owner_controls)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def select_channel_kb(channels: Iterable[Tuple[int, str]]) -> InlineKeyboardMarkup:
    rows = []
    for chat_id, title in channels:
        rows.append(
            [
                InlineKeyboardButton(
                    text=title or str(chat_id), callback_data=f"select_channel:{chat_id}"
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="رجوع", callback_data="back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
