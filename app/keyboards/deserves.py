from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


# ملخص: أزرار قسم "يستحق".
def deserves_section_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ إنشاء مسابقة جديدة", callback_data="deserves_create")],
            [InlineKeyboardButton(text="📋 مسابقاتي", callback_data="deserves_my_contests")],
            [InlineKeyboardButton(text="❓ كيف يعمل؟", callback_data="deserves_help")],
            [InlineKeyboardButton(text="رجوع", callback_data="back")],
        ]
    )


# ملخص: تأكيد إنشاء المسابقة.
def deserves_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ تأكيد", callback_data="deserves_confirm")],
            [InlineKeyboardButton(text="❌ إلغاء", callback_data="deserves_cancel")],
            [InlineKeyboardButton(text="رجوع", callback_data="back")],
        ]
    )


# ملخص: أزرار المشاركة في "يستحق".
def deserves_join_kb(vote_code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="👏 أنا مستحق!", callback_data=f"deserves_join:{vote_code}"
                )
            ],
        ]
    )


# ملخص: أزرار التحكم (للأدمن).
def deserves_controls_kb(contest_id: int, is_active: bool) -> InlineKeyboardMarkup:
    rows = []
    if is_active:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🔴 إنهاء المسابقة", callback_data=f"deserves_end:{contest_id}"
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="📊 عرض النتائج", callback_data=f"deserves_results:{contest_id}"
            )
        ]
    )
    rows.append([InlineKeyboardButton(text="🗑️ حذف", callback_data=f"deserves_delete:{contest_id}")])
    rows.append([InlineKeyboardButton(text="رجوع", callback_data="back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ملخص: أزرار الانضمام للمسابقة.
def deserves_candidate_kb(contest_id: int, candidate_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="👏 صوّت لهذا المتسابق",
                    callback_data=f"deserves_vote:{contest_id}:{candidate_id}",
                )
            ],
            [InlineKeyboardButton(text="رجوع", callback_data="back")],
        ]
    )
