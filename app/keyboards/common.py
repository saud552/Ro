from __future__ import annotations

from typing import Iterable, Tuple

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu_kb() -> InlineKeyboardMarkup:
    """Arabic Main Menu with all requested sections."""
    buttons = [
        [InlineKeyboardButton(text="🎰 قسم الروليت", callback_data="section_roulette")],
        [InlineKeyboardButton(text="🗳️ قسم مسابقات التصويت", callback_data="section_vote")],
        [InlineKeyboardButton(text="🏆 مسابقة 'يستحق'", callback_data="section_yastahiq")],
        [InlineKeyboardButton(text="❓ قسم مسابقة الأسئلة", callback_data="section_quiz")],
        [InlineKeyboardButton(text="⚙️ إدارة مسابقاتي", callback_data="my_draws")],
        [
            InlineKeyboardButton(
                text="📢 إدارة القنوات والمجموعات", callback_data="section_channels"
            )
        ],
        [InlineKeyboardButton(text="💎 متجر النقاط واشتراكاتي", callback_data="section_store")],
        [InlineKeyboardButton(text="📊 حسابي", callback_data="section_account")],
        [InlineKeyboardButton(text="💰 كسب النقاط", callback_data="section_referral")],
        [InlineKeyboardButton(text="👨‍💻 الدعم الفني", url="https://t.me/support")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def forced_sub_kb(channel_url: str) -> InlineKeyboardMarkup:
    """Keyboard for forced subscription gate."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📢 اضغط للاشتراك", url=channel_url)],
            [InlineKeyboardButton(text="✅ لقد اشتركت", callback_data="check_subscription")],
        ]
    )


def back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="رجوع", callback_data="back")]]
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
            [InlineKeyboardButton(text="إضافة شرط", callback_data="gate_add")],
            [InlineKeyboardButton(text="رجوع", callback_data="back")],
        ]
    )


def gate_more_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="إضافة شرط آخر", callback_data="gate_add")],
            [InlineKeyboardButton(text="متابعة", callback_data="gate_done")],
            [InlineKeyboardButton(text="رجوع", callback_data="back")],
        ]
    )


def gates_manage_kb(num_gates: int) -> InlineKeyboardMarkup:
    rows = []
    for i in range(num_gates):
        rows.append(
            [InlineKeyboardButton(text=f"حذف الشرط #{i+1}", callback_data=f"gate_remove:{i}")]
        )
    rows.append([InlineKeyboardButton(text="إضافة شرط آخر", callback_data="gate_add")])
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
            [InlineKeyboardButton(text="📢 قناة شرط", callback_data="gate_type:channel")],
            [InlineKeyboardButton(text="👥 مجموعة شرط", callback_data="gate_type:group")],
            [InlineKeyboardButton(text="🗳 تصويت لمتسابق", callback_data="gate_type:vote")],
            [InlineKeyboardButton(text="🔥 تعليق يستحق", callback_data="gate_type:yastahiq")],
            [
                InlineKeyboardButton(
                    text="🎰 اشتراك في روليت آخر", callback_data="gate_type:contest"
                )
            ],
            [InlineKeyboardButton(text="🔙 رجوع", callback_data="back")],
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
