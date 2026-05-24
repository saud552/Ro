from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


# ملخص: أزرار قسم المسابقة.
def quiz_section_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📺 إنشاء مسابقة قناة", callback_data="quiz_channel")],
            [InlineKeyboardButton(text="👥 إنشاء مسابقة مجموعة", callback_data="quiz_group")],
            [InlineKeyboardButton(text="📋 مسابقاتي", callback_data="quiz_my_contests")],
            [InlineKeyboardButton(text="❓ كيف يعمل؟", callback_data="quiz_help")],
            [InlineKeyboardButton(text="رجوع", callback_data="back")],
        ]
    )


# ملخص: تأكيد إنشاء المسابقة.
def quiz_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ تأكيد", callback_data="quiz_confirm")],
            [InlineKeyboardButton(text="❌ إلغاء", callback_data="quiz_cancel")],
            [InlineKeyboardButton(text="رجوع", callback_data="back")],
        ]
    )


# ملخص: أزرار التحكم في المسابقة (للأدمن).
def quiz_controls_kb(
    contest_id: int, is_active: bool, is_paused: bool = False
) -> InlineKeyboardMarkup:
    rows = []
    if is_active:
        if is_paused:
            rows.append(
                [InlineKeyboardButton(text="▶️ استئناف", callback_data=f"quiz_resume:{contest_id}")]
            )
        else:
            rows.append(
                [
                    InlineKeyboardButton(
                        text="⏸️ إيقاف مؤقت", callback_data=f"quiz_pause:{contest_id}"
                    )
                ]
            )
        rows.append(
            [InlineKeyboardButton(text="⏭️ سؤال التالي", callback_data=f"quiz_next:{contest_id}")]
        )
        rows.append(
            [InlineKeyboardButton(text="🔴 إنهاء المسابقة", callback_data=f"quiz_end:{contest_id}")]
        )
    rows.append(
        [InlineKeyboardButton(text="📊 عرض النتائج", callback_data=f"quiz_results:{contest_id}")]
    )
    rows.append(
        [InlineKeyboardButton(text="🗑️ حذف المسابقة", callback_data=f"quiz_delete:{contest_id}")]
    )
    rows.append([InlineKeyboardButton(text="رجوع", callback_data="back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ملخص: أزرار المشاركة.
def quiz_join_kb(contest_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎯 اشترك الآن!", callback_data=f"quiz_join:{contest_id}")],
        ]
    )


# ملخص: أزرار الإجابة على السؤال.
def quiz_answer_kb(contest_id: int, question_id: int, options: list[str]) -> InlineKeyboardMarkup:
    rows = []
    for i, option in enumerate(options):
        rows.append(
            [
                InlineKeyboardButton(
                    text=option, callback_data=f"quiz_answer:{contest_id}:{question_id}:{i}"
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="⚠️ لا أعرف", callback_data=f"quiz_skip:{contest_id}:{question_id}"
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ملخص: عرض النتيجة.
def quiz_result_kb(contest_id: int, correct: bool) -> InlineKeyboardMarkup:
    text = "🎉 إجابة صحيحة!" if correct else "❌ إجابة خاطئة"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=text, callback_data=f"quiz_result:{contest_id}:{1 if correct else 0}"
                )
            ],
            [InlineKeyboardButton(text="الترتيب", callback_data=f"quiz_leaderboard:{contest_id}")],
            [InlineKeyboardButton(text="رجوع", callback_data="back")],
        ]
    )


# ملخص: عرض المتصدرين.
def quiz_leaderboard_kb(contest_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📊 عرض المتصدرين", callback_data=f"quiz_leaderboard:{contest_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎯 السؤال التالي", callback_data=f"quiz_next_question:{contest_id}"
                )
            ],
            [InlineKeyboardButton(text="رجوع", callback_data="back")],
        ]
    )
