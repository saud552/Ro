from __future__ import annotations

import secrets

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery

from ..db import get_async_session
from ..db.repositories import PointsRepository, SubscriptionRepository
from ..keyboards.points import (
    points_confirm_redeem_kb,
    points_redeem_kb,
    points_section_kb,
    points_share_kb,
)
from ..services.context import runtime

points_router = Router(name="points")


class PointsStates(StatesGroup):
    await_payment = State()


def _generate_referral_code() -> str:
    return secrets.token_hex(8)


@points_router.callback_query(F.data == "earn_points")
async def section_points(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    text = (
        "💰 قسم كسب النقاط\n\n"
        "اكسب النقاط من خلال دعوة أصدقائك!\n"
        "كل صديق ينضم تحصل على نقاط.\n\n"
        "اختر:"
    )
    await cb.message.edit_text(text, reply_markup=points_section_kb())
    await cb.answer()


@points_router.callback_query(F.data == "points_share")
async def share_referral(cb: CallbackQuery) -> None:
    user_id = cb.from_user.id

    async for session in get_async_session():
        sub_repo = SubscriptionRepository(session)
        sub = await sub_repo.get_by_user_id(user_id)

        if not sub:
            # Create new subscription with referral code
            code = _generate_referral_code()
            sub = await sub_repo.create(user_id, "referral", code)

        referral_link = f"https://t.me/{runtime.bot_username}?start=ref_{sub.referral_code}"

    await cb.message.edit_text(
        f"📤 رابط الإحالة الخاص بك:\n\n"
        f"{referral_link}\n\n"
        f"🔖 الكود: {sub.referral_code}\n\n"
        f"📌 شارك الرابط مع أصدقائك للحصول على نقاط!",
        reply_markup=points_share_kb(referral_link),
    )
    await cb.answer()


@points_router.callback_query(F.data == "points_referrals")
async def show_referrals(cb: CallbackQuery) -> None:
    user_id = cb.from_user.id

    async for session in get_async_session():
        repo = PointsRepository(session)
        referrals = await repo.get_user_referrals(user_id)
        count = len(referrals)

    text = (
        f"👥 عدد المحالين: {count}\n\n"
        f"📌 كل صديق يسجل تحصل على نقاط.\n"
        f"💰 رصيدك: {count * 10} نقطة"
    )
    await cb.message.edit_text(text, reply_markup=points_section_kb())
    await cb.answer()


@points_router.callback_query(F.data == "points_balance")
async def show_balance(cb: CallbackQuery) -> None:
    user_id = cb.from_user.id

    async for session in get_async_session():
        sub_repo = SubscriptionRepository(session)
        repo = PointsRepository(session)

        sub = await sub_repo.get_by_user_id(user_id)
        referrals = await repo.get_user_referrals(user_id)

        if sub:
            points = sub.referral_points
            credits = sub.one_time_credits
        else:
            points = 0
            credits = 0

    text = (
        "💰 رصيدك من النقاط\n\n"
        f"⭐ نقاط الإحالة: {points}\n"
        f"🎟️ رصيد الاستخدمات: {credits}\n\n"
        f"👥 عدد المحالين: {len(referrals)}"
    )
    await cb.message.edit_text(text, reply_markup=points_section_kb())
    await cb.answer()


@points_router.callback_query(F.data == "points_redeem")
async def redeem_points(cb: CallbackQuery) -> None:
    user_id = cb.from_user.id

    async for session in get_async_session():
        sub_repo = SubscriptionRepository(session)
        sub = await sub_repo.get_by_user_id(user_id)

        points = sub.referral_points if sub else 0

    if points < 10:
        await cb.answer("❌ تحتاج على الأقل 10 نقاط للاستبدال!", show_alert=True)
        return

    text = f"🎁 استبدال النقاط\n\n" f"💰 رصيدك: {points} نقطة\n\n" f"اختر ما تريد:"
    await cb.message.edit_text(text, reply_markup=points_redeem_kb("roulette"))
    await cb.answer()


@points_router.callback_query(F.data.startswith("points_redeem_"))
async def redeem_option(cb: CallbackQuery) -> None:
    parts = cb.data.split("_")
    item_type = parts[-1]  # voting, quiz, roulette

    text = f"🎁 تأكيد الاستبدال لـ {item_type}\n\n" f"💰 التكلفة: 10 نقاط\n\n" "✅ تأكيد | ❌ إلغاء"
    await cb.message.edit_text(text, reply_markup=points_confirm_redeem_kb(item_type, 10))
    await cb.answer()


@points_router.callback_query(F.data.startswith("points_confirm_redeem:"))
async def confirm_redeem(cb: CallbackQuery, state: FSMContext) -> None:
    parts = cb.data.split(":")
    item_type = parts[1]
    amount = int(parts[2])

    user_id = cb.from_user.id

    async for session in get_async_session():
        sub_repo = SubscriptionRepository(session)
        sub = await sub_repo.get_by_user_id(user_id)

        if not sub or sub.referral_points < amount:
            await cb.answer("❌ نقاط غير كافية!", show_alert=True)
            return

        # Deduct points
        sub.referral_points -= amount

        # Add to one_time_credits or grant feature access
        if item_type == "roulette":
            # Grant one-time roulette access
            from ..db.repositories import FeatureAccessRepository

            fa_repo = FeatureAccessRepository(session)
            await fa_repo.grant_one_time(user_id, "roulette_one_time", credits=1)
        elif item_type == "voting":
            # Grant voting credits
            sub.one_time_credits += 1
        elif item_type == "quiz":
            # Grant quiz access
            sub.one_time_credits += 1

        await session.commit()

    await cb.answer(f"✅ تم استبدال {amount} نقاط بنجاح!", show_alert=True)
    await state.clear()


@points_router.callback_query(F.data == "points_cancel_redeem")
async def cancel_redeem(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cb.message.edit_text("❌ تم إلغاء الاستبدال.")
    await cb.answer()


@points_router.callback_query(F.data == "points_help")
async def points_help(cb: CallbackQuery) -> None:
    text = (
        "❓ كيف تكسب النقاط؟\n\n"
        "1️⃣ شارك رابط الإحالة مع أصدقائك\n"
        "2️⃣ كل صديق يسجل عبر رابطك تحصل على نقاط\n"
        "3️⃣ استخدم النقاط للحصول على رصيد مجاني!\n\n"
        "💰 كل إحالة = 10 نقاط\n"
        "🎟️ 10 نقاط = رصيد سحب/تصويتب/أسئلة"
    )
    await cb.message.edit_text(text, reply_markup=points_section_kb())
    await cb.answer()


@points_router.callback_query(F.data == "points_copy_link")
async def copy_link(cb: CallbackQuery) -> None:
    user_id = cb.from_user.id

    async for session in get_async_session():
        sub_repo = SubscriptionRepository(session)
        sub = await sub_repo.get_by_user_id(user_id)

        if not sub:
            code = _generate_referral_code()
            sub = await sub_repo.create(user_id, "referral", code)

        referral_link = f"https://t.me/{runtime.bot_username}?start=ref_{sub.referral_code}"

    await cb.answer("🔗 تم نسخ الرابط!", show_alert=True)
    await cb.message.edit_text(
        f"📋 رابط الإحالة:\n\n`{referral_link}`\n\n"
        f"🔖 أو استخدم الكود مباشرة: `{sub.referral_code}`",
        parse_mode="Markdown",
    )
    await cb.answer()
