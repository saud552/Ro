from __future__ import annotations

from typing import Iterable, Tuple

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="رجوع", callback_data="back")]]
    )


def start_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="إنشاء الروليت", callback_data="create_roulette")],
            [InlineKeyboardButton(text="ربط القناة", callback_data="link_channel")],
            [InlineKeyboardButton(text="فصل القناة", callback_data="unlink_channel")],
            [InlineKeyboardButton(text="سحوباتي", callback_data="my_draws")],
            [InlineKeyboardButton(text="ذكّرني إذا فزت", callback_data="notify_me")],
            [InlineKeyboardButton(text="الدعم الفني", url="https://t.me/support")],
        ]
    )


def gate_kb(channel_username: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="قناة البوت", url=f"https://t.me/{channel_username.lstrip('@')}"
                )
            ],
            [InlineKeyboardButton(text="تحقق من الاشتراك", callback_data="check_subscription")],
        ]
    )


def gate_choice_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="تخطي", callback_data="gate_skip")],
            [InlineKeyboardButton(text="إضافة قناة شرط", callback_data="gate_add")],
            [InlineKeyboardButton(text="رجوع", callback_data="back")],
        ]
    )


def gate_more_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="إضافة قناة أخرى", callback_data="gate_add")],
            [InlineKeyboardButton(text="متابعة", callback_data="gate_done")],
            [InlineKeyboardButton(text="رجوع", callback_data="back")],
        ]
    )


def gates_manage_kb(num_gates: int) -> InlineKeyboardMarkup:
    rows = []
    for i in range(num_gates):
        rows.append(
            [InlineKeyboardButton(text=f"حذف القناة #{i+1}", callback_data=f"gate_remove:{i}")]
        )
    rows.append([InlineKeyboardButton(text="إضافة قناة أخرى", callback_data="gate_add")])
    rows.append([InlineKeyboardButton(text="متابعة", callback_data="gate_done")])
    rows.append([InlineKeyboardButton(text="رجوع", callback_data="back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="تأكيد", callback_data="confirm_create"),
                InlineKeyboardButton(text="إلغاء", callback_data="cancel_create"),
            ]
        ]
    )


def gate_add_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="إضافة قناة كشرط", callback_data="gate_add_channel")],
            [InlineKeyboardButton(text="إضافة مجموعة كشرط", callback_data="gate_add_group")],
            [
                InlineKeyboardButton(
                    text="اختيار من قائمة القنوات/المجموعات", callback_data="gate_pick"
                )
            ],
            [InlineKeyboardButton(text="رجوع", callback_data="back")],
        ]
    )


def gate_pick_list_kb(items: Iterable[Tuple[int, str]]) -> InlineKeyboardMarkup:
    rows = []
    for chat_id, title in items:
        rows.append(
            [
                InlineKeyboardButton(
                    text=title or str(chat_id), callback_data=f"gate_pick_apply:{chat_id}"
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="رجوع", callback_data="back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
