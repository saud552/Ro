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
            [InlineKeyboardButton(text="🎰 قسم الروليت", callback_data="create_roulette")],
            [InlineKeyboardButton(text="🗳️ قسم مسابقات التصويتب", callback_data="section_voting")],
            [InlineKeyboardButton(text="👏 قسم مسابقة يستحق", callback_data="section_deserves")],
            [InlineKeyboardButton(text="🎯 قسم مسابقة الأسئلة", callback_data="section_quiz")],
            [InlineKeyboardButton(text="🔗 ربط القناة", callback_data="link_channel")],
            [InlineKeyboardButton(text="🔗 فصل القناة", callback_data="unlink_channel")],
            [InlineKeyboardButton(text="📦 سحوباتي", callback_data="my_draws")],
            [InlineKeyboardButton(text="💰 إدارة الاشتراك", callback_data="manage_subscription")],
            [InlineKeyboardButton(text="⭐ كسب النقاط", callback_data="earn_points")],
            [InlineKeyboardButton(text="❓ الدعم الفني", url="https://t.me/support")],
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


# ملخص: بوابة الاشتراك المحسّنة مع أزرار تفاعلية.
def subscription_gate_kb(channel_username: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ اشتراك في قناة البوت",
                    url=f"https://t.me/{channel_username.lstrip('@')}",
                )
            ],
            [InlineKeyboardButton(text="🔄 تحقق من الاشتراك", callback_data="check_subscription")],
        ]
    )


# ملخص: قائمة إدارة الاشتراك.
def subscription_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💎 اشتراك شهري", callback_data="sub_monthly")],
            [InlineKeyboardButton(text="🎟️ شراء رصيد", callback_data="sub_one_time")],
            [InlineKeyboardButton(text="🎁 استبدال نقاط", callback_data="sub_redeem_points")],
            [InlineKeyboardButton(text="📊 حالة الاشتراك", callback_data="sub_status")],
            [InlineKeyboardButton(text="رجوع", callback_data="back")],
        ]
    )


# ملخص: عرض حالة الاشتراك مع تفاصيل.
def subscription_status_kb(
    has_access: bool, access_type: str, expires_at: str
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 تجديد الاشتراك", callback_data="sub_renew")],
            [InlineKeyboardButton(text="💰 شراء رصيد", callback_data="sub_buy_credits")],
            [InlineKeyboardButton(text="رجوع", callback_data="back")],
        ]
    )
