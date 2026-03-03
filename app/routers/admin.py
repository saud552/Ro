from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, select

from ..config import settings
from ..db import get_async_session
from ..db.models import AppSetting, BotChat, ChannelLink, FeatureAccess, Purchase, User
from ..db.repositories import AppSettingRepository

admin_router = Router(name="admin")


class AdminStates(StatesGroup):
    await_broadcast_message = State()
    await_price_value = State()
    await_bot_channel = State()


def _is_admin(user_id: int) -> bool:
    return user_id in settings.admin_ids


def admin_menu_kb() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="📊 إحصائيات البوت", callback_data="admin_stats")],
        [InlineKeyboardButton(text="🚀 إذاعة للمستخدمين", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="💰 إعدادات الأسعار", callback_data="admin_set_prices")],
        [InlineKeyboardButton(text="📢 تعيين قناة البوت", callback_data="admin_set_bot_channel")],
        [InlineKeyboardButton(text="🧠 إدارة الأسئلة", callback_data="admin_quiz_manage")],
        [InlineKeyboardButton(text="👥 إعدادات الإحالة", callback_data="admin_referral_settings")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def prices_kb() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="تعديل سعر المرة الواحدة", callback_data="price_once")],
        [InlineKeyboardButton(text="تعديل سعر الشهر", callback_data="price_month")],
        [InlineKeyboardButton(text="🔙 رجوع", callback_data="admin_back")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@admin_router.message(Command("admin"))
async def admin_menu(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    await message.answer(
        "🛠 <b>لوحة تحكم المسؤول</b>\n\nاختر من الخيارات أدناه:",
        reply_markup=admin_menu_kb(),
        parse_mode=ParseMode.HTML,
    )


@admin_router.callback_query(F.data == "admin_back")
async def admin_back(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        await cb.answer()
        return
    await state.clear()
    await cb.message.edit_text(
        "🛠 <b>لوحة تحكم المسؤول</b>\n\nاختر من الخيارات أدناه:",
        reply_markup=admin_menu_kb(),
        parse_mode=ParseMode.HTML,
    )
    await cb.answer()


@admin_router.callback_query(F.data == "admin_stats")
async def admin_stats(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id):
        await cb.answer()
        return
    async for session in get_async_session():
        total_users = (await session.execute(select(func.count()).select_from(User))).scalar_one()
        total_channels = (
            await session.execute(select(func.count()).select_from(ChannelLink))
        ).scalar_one()
        total_groups = (
            await session.execute(
                select(func.count())
                .select_from(BotChat)
                .where(BotChat.chat_type.in_(["group", "supergroup"]))
            )
        ).scalar_one()
        paid_users = (
            await session.execute(
                select(func.count())
                .select_from(FeatureAccess)
                .where(FeatureAccess.feature_key == "gate_channel")
            )
        ).scalar_one()
        active_paid = (
            await session.execute(
                select(func.count())
                .select_from(FeatureAccess)
                .where(
                    (FeatureAccess.feature_key == "gate_channel")
                    & (FeatureAccess.expires_at.is_not(None))
                    & (FeatureAccess.expires_at > datetime.now(timezone.utc))
                )
            )
        ).scalar_one()
        stars_total = (
            await session.execute(select(func.coalesce(func.sum(Purchase.stars_amount), 0)))
        ).scalar_one()
    text = (
        f"📊 <b>إحصائيات النظام:</b>\n\n"
        f"👤 عدد المستخدمين: <b>{total_users}</b>\n"
        f"📢 عدد القنوات المفعّلة: <b>{total_channels}</b>\n"
        f"👥 عدد المجموعات المفعّلة: <b>{total_groups}</b>\n"
        f"💳 عدد عمليات الشراء: <b>{paid_users}</b>\n"
        f"💎 الاشتراكات النشطة: <b>{active_paid}</b>\n"
        f"⭐️ إجمالي النجوم المحصلة: <b>{stars_total}</b>"
    )
    await cb.message.answer(
        text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="رجوع", callback_data="admin_back")]]
        ),
        parse_mode=ParseMode.HTML,
    )
    await cb.answer()


@admin_router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_start(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        await cb.answer()
        return
    await state.set_state(AdminStates.await_broadcast_message)
    await cb.message.answer("أرسل الرسالة التي تريد إذاعتها لجميع المستخدمين (نص، صورة، إلخ):")
    await cb.answer()


@admin_router.message(AdminStates.await_broadcast_message)
async def admin_broadcast_execute(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return

    async for session in get_async_session():
        user_ids = (await session.execute(select(User.id))).scalars().all()

    await message.answer(f"🚀 بدأت عملية الإذاعة لـ {len(user_ids)} مستخدم...")

    success = 0
    failed = 0
    for uid in user_ids:
        try:
            await message.copy_to(chat_id=uid)
            success += 1
            await asyncio.sleep(0.05)
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
            await message.copy_to(chat_id=uid)
            success += 1
        except (TelegramForbiddenError, Exception):
            failed += 1

    await message.answer(
        f"✅ اكتملت الإذاعة!\n\nنجاح: {success}\nفشل/حظر: {failed}", reply_markup=admin_menu_kb()
    )
    await state.clear()


@admin_router.callback_query(F.data == "admin_set_prices")
async def admin_set_prices(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        await cb.answer()
        return
    await state.clear()
    from ..services.payments import get_monthly_price_stars, get_one_time_price_stars

    once = await get_one_time_price_stars()
    month = await get_monthly_price_stars()
    await cb.message.answer(
        f"💰 <b>إعدادات الأسعار:</b>\n\n"
        f"المرة الواحدة: <b>{once}</b> نجمة\n"
        f"الاشتراك الشهري: <b>{month}</b> نجمة\n\n"
        f"اختر ما تريد تعديله:",
        reply_markup=prices_kb(),
        parse_mode=ParseMode.HTML,
    )
    await cb.answer()


@admin_router.callback_query(F.data.in_({"price_once", "price_month"}))
async def admin_price_choose(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        await cb.answer()
        return
    key = "price_once" if cb.data == "price_once" else "price_month"
    await state.set_state(AdminStates.await_price_value)
    await state.update_data(price_mode=key)
    await cb.message.answer("⌨️ أرسل الآن القيمة الجديدة (عدد النجوم):")
    await cb.answer()


@admin_router.message(AdminStates.await_price_value, F.text.regexp(r"^\d+$"))
async def admin_price_set_value(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    value = int(message.text)
    data = await state.get_data()
    mode = data.get("price_mode", "price_once")
    async for session in get_async_session():
        actual_key = "price_once_value" if mode == "price_once" else "price_month_value"
        row = (
            await session.execute(select(AppSetting).where(AppSetting.key == actual_key))
        ).scalar_one_or_none()
        if row:
            row.value = str(value)
        else:
            session.add(AppSetting(key=actual_key, value=str(value)))
        await session.commit()
    await state.clear()
    await message.answer(f"✅ تم تحديث السعر إلى {value} نجمة.", reply_markup=admin_menu_kb())


@admin_router.callback_query(F.data == "admin_set_bot_channel")
async def admin_set_bot_channel(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        await cb.answer()
        return
    await state.set_state(AdminStates.await_bot_channel)
    await cb.message.answer("🔗 أرسل رابط أو يوزر القناة الأساسية الجديدة (@username):")
    await cb.answer()


@admin_router.message(
    AdminStates.await_bot_channel, F.text.contains("t.me/") | F.text.startswith("@")
)
async def admin_apply_bot_channel(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    text = (message.text or "").strip()
    username = text.split("/")[-1].lstrip("@")
    value = f"@{username}"
    try:
        c = await message.bot.get_chat(value)
        if str(getattr(c, "type", "")) != "channel":
            await message.answer("❌ هذا المعرف ليس قناة عامة صالحة.")
            return
    except Exception:
        await message.answer("❌ تعذر التحقق من القناة. تأكد من صحة المعرف.")
        return
    async for session in get_async_session():
        row = (
            await session.execute(select(AppSetting).where(AppSetting.key == "bot_base_channel"))
        ).scalar_one_or_none()
        if row:
            row.value = value
        else:
            session.add(AppSetting(key="bot_base_channel", value=value))
        await session.commit()
    await state.clear()
    await message.answer(
        f"✅ تم تعيين قناة البوت الأساسية إلى: {value}", reply_markup=admin_menu_kb()
    )


@admin_router.callback_query(F.data == "admin_quiz_manage")
async def admin_quiz_manage(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id):
        await cb.answer()
        return
    text = (
        "🧠 <b>إدارة بنك الأسئلة</b>\n\n"
        "يمكنك رفع الأسئلة بشكل جماعي عبر إرسال نص بالتنسيق التالي:\n"
        "<code>السؤال | الإجابة1, الإجابة2 | النقاط</code>\n\n"
        "مثال:\n"
        "<code>ما هي عاصمة السعودية | الرياض | 2</code>"
    )
    await cb.message.answer(text, parse_mode=ParseMode.HTML)
    await cb.answer()


@admin_router.message(F.text.contains("|") & F.from_user.id.in_(settings.admin_ids))
async def admin_bulk_add_questions(message: Message) -> None:
    async for session in get_async_session():
        from ..services.quiz import QuizService

        service = QuizService(session)
        count = await service.bulk_add_questions(0, message.text)
        await message.answer(f"✅ تم إضافة {count} سؤال لبنك الأسئلة بنجاح.")


@admin_router.callback_query(F.data == "admin_referral_settings")
async def admin_referral_settings(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id):
        await cb.answer()
        return

    async for session in get_async_session():
        repo = AppSettingRepository(session)
        enabled = await repo.get_value("referral_enabled", "yes")
        points = await repo.get_value("referral_points", "10")

    text = (
        "👥 <b>إعدادات نظام الإحالة</b>\n\n"
        f"الحالة الحالية: <b>{'مفعل' if enabled == 'yes' else 'معطل'}</b>\n"
        f"النقاط لكل إحالة: <b>{points}</b>\n\n"
        "اختر الإجراء المطلوب:"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="تغيير الحالة", callback_data="admin_toggle_ref")],
            [InlineKeyboardButton(text="تعديل النقاط", callback_data="admin_edit_ref_points")],
            [InlineKeyboardButton(text="رجوع", callback_data="admin_back")],
        ]
    )
    await cb.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    await cb.answer()


@admin_router.callback_query(F.data == "admin_toggle_ref")
async def admin_toggle_ref(cb: CallbackQuery) -> None:
    async for session in get_async_session():
        repo = AppSettingRepository(session)
        current = await repo.get_value("referral_enabled", "yes")
        new_val = "no" if current == "yes" else "yes"
        await repo.set_value("referral_enabled", new_val)
    await admin_referral_settings(cb)


@admin_router.callback_query(F.data == "admin_share_contest")
async def admin_share_contest(cb: CallbackQuery) -> None:
    await cb.answer("يمكنك استخدام البحث المباشر لمشاركة مسابقاتك!", show_alert=True)
