from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


# ملخص: أنواع مسابقات التصويتب.
def voting_type_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🗳️ تصويتب عادي", callback_data="voting_normal")],
            [InlineKeyboardButton(text="⭐ تصويتب نجوم", callback_data="voting_stars")],
            [InlineKeyboardButton(text="🗳️⭐ تصويتب عادي + نجوم", callback_data="voting_mixed")],
            [InlineKeyboardButton(text="رجوع", callback_data="back")],
        ]
    )


# ملخص: اختيار إعدادات التصويتب.
def voting_settings_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ تفعيل", callback_data="voting_setting_yes")],
            [InlineKeyboardButton(text="❌ تعطيل", callback_data="voting_setting_no")],
            [InlineKeyboardButton(text="رجوع", callback_data="back")],
        ]
    )


# ملخص: تأكيد إنشاء المسابقة.
def voting_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ تأكيد الإنشاء", callback_data="voting_confirm")],
            [InlineKeyboardButton(text="❌ إلغاء", callback_data="voting_cancel")],
            [InlineKeyboardButton(text="رجوع", callback_data="back")],
        ]
    )


# ملخص: أزرار المشاركة في المسابقة.
def voting_join_kb(vote_code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🗳️ شارك الآن", callback_data=f"voting_join:{vote_code}")],
        ]
    )


# ملخص: أزرار التصويت.
def voting_vote_kb(contest_id: int, candidate_id: int, stars_amount: int = 0) -> InlineKeyboardMarkup:
    rows = []
    rows.append([
        InlineKeyboardButton(text="✅ تصويتب", callback_data=f"vote_normal:{contest_id}:{candidate_id}"),
    ])
    if stars_amount > 0:
        rows.append([
            InlineKeyboardButton(
                text=f"⭐ تصويتب بنجمة ({stars_amount} ⭐)",
                callback_data=f"vote_stars:{contest_id}:{candidate_id}:{stars_amount}"
            ),
        ])
    rows.append([InlineKeyboardButton(text="رجوع", callback_data="back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ملخص: أزرار التحكم في المسابقة (للأدمن).
def voting_controls_kb(contest_id: int, is_active: bool) -> InlineKeyboardMarkup:
    rows = []
    if is_active:
        rows.append([InlineKeyboardButton(text="🔴 إنهاء المسابقة", callback_data=f"voting_end:{contest_id}")])
    rows.append([InlineKeyboardButton(text="📊 عرض النتائج", callback_data=f"voting_results:{contest_id}")])
    rows.append([InlineKeyboardButton(text="🗑️ حذف المسابقة", callback_data=f"voting_delete:{contest_id}")])
    rows.append([InlineKeyboardButton(text="رجوع", callback_data="back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ملخص: أزرار تصويت النجوم.
def voting_stars_payment_kb(contest_id: int, candidate_id: int, stars_amount: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text=f"⭐ صوّت بـ {stars_amount} نجمة",
                callback_data=f"voting_pay_stars:{contest_id}:{candidate_id}:{stars_amount}"
            )],
            [InlineKeyboardButton(text="تصويتب مجاني", callback_data=f"vote_normal:{contest_id}:{candidate_id}")],
            [InlineKeyboardButton(text="رجوع", callback_data="back")],
        ]
    )


# ملخص: عرض قائمة المتسابقين.
def voting_candidates_kb(contest_id: int, candidates: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    rows = []
    for candidate_id, display_name in candidates:
        rows.append([
            InlineKeyboardButton(
                text=display_name,
                callback_data=f"voting_candidate:{contest_id}:{candidate_id}"
            )
        ])
    rows.append([InlineKeyboardButton(text="رجوع", callback_data="back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)