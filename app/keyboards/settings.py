from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def roulette_settings_kb(
    is_premium_only: bool,
    sub_check_disabled: bool,
    anti_bot_enabled: bool,
    exclude_leavers_enabled: bool,
) -> InlineKeyboardMarkup:
    """Keyboard for customizing roulette settings during creation."""
    buttons = [
        [
            InlineKeyboardButton(
                text=f"👥 نوع المستخدمين: {'المميزين فقط' if is_premium_only else 'الجميع'}",
                callback_data="toggle_premium",
            )
        ],
        [
            InlineKeyboardButton(
                text=f"📢 اشتراك قناة المسابقة: {'تعطيل' if sub_check_disabled else 'تفعيل'}",
                callback_data="toggle_sub_check",
            )
        ],
        [
            InlineKeyboardButton(
                text=f"🤖 منع الوهمي: {'مفعل' if anti_bot_enabled else 'معطل'}",
                callback_data="toggle_anti_bot",
            )
        ],
        [
            InlineKeyboardButton(
                text=f"🏃 استبعاد المغادرين: {'مفعل' if exclude_leavers_enabled else 'معطل'}",
                callback_data="toggle_leavers",
            )
        ],
        [
            InlineKeyboardButton(text="✅ تأكيد وبدء السحب", callback_data="confirm_settings"),
        ],
        [InlineKeyboardButton(text="🔙 رجوع", callback_data="back")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)
