from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


# ملخص: أزرار قسم كسب النقاط.
def points_section_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📤 مشاركة رابط الإحالة", callback_data="points_share")],
            [InlineKeyboardButton(text="👥 عدد المحالين", callback_data="points_referrals")],
            [InlineKeyboardButton(text="💰 رصيدي من النقاط", callback_data="points_balance")],
            [InlineKeyboardButton(text="🎁 استبدال النقاط", callback_data="points_redeem")],
            [InlineKeyboardButton(text="❓ كيف أكسب نقاط؟", callback_data="points_help")],
            [InlineKeyboardButton(text="رجوع", callback_data="back")],
        ]
    )


# ملخص: أزرار مشاركة الرابط.
def points_share_kb(referral_link: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📤 نسخ الرابط", callback_data="points_copy_link")],
            [InlineKeyboardButton(text="✈️ مشاركة عبر تيليجرام", url=f"https://t.me/shareurl?url={referral_link}")],
            [InlineKeyboardButton(text="رجوع", callback_data="back")],
        ]
    )


# ملخص: أزرار استبدال النقاط.
def points_redeem_kb(contest_type: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🗳️ استبدال للتصويتب", callback_data=f"points_redeem_voting:{contest_type}")],
            [InlineKeyboardButton(text="❓ استبدال للأسئلة", callback_data=f"points_redeem_quiz:{contest_type}")],
            [InlineKeyboardButton(text="🎰 استبدال للروليت", callback_data=f"points_redeem_roulette:{contest_type}")],
            [InlineKeyboardButton(text="رجوع", callback_data="back")],
        ]
    )


# ملخص: أزرار تأكيد الاستبدال.
def points_confirm_redeem_kb(item_type: str, amount: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ تأكيد", callback_data=f"points_confirm_redeem:{item_type}:{amount}")],
            [InlineKeyboardButton(text="❌ إلغاء", callback_data="points_cancel_redeem")],
            [InlineKeyboardButton(text="رجوع", callback_data="back")],
        ]
    )