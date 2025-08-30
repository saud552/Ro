from __future__ import annotations

from datetime import datetime

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, select

from ..config import settings
from ..db import get_async_session
from ..db.models import AppSetting, BotChat, ChannelLink, FeatureAccess, Purchase, User

# NOTE: Constants are named DEFAULT_MONTHLY_STARS and DEFAULT_ONE_TIME_STARS in services.payments
# Importing them here is unnecessary; dynamic prices are fetched via helpers.

admin_router = Router(name="admin")


class AdminStates(StatesGroup):
    await_price_value = State()
    await_bot_channel = State()


def _is_admin(user_id: int) -> bool:
    return user_id in set(settings.admin_ids)


# ---- Keyboards ----


def admin_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="الاحصائيات", callback_data="admin_stats")],
            [InlineKeyboardButton(text="الاذاعة (قريباً)", callback_data="admin_broadcast")],
            [InlineKeyboardButton(text="تعيين قيمة الاشتراك", callback_data="admin_set_prices")],
            [
                InlineKeyboardButton(
                    text="تعيين قناة البوت الأساسية", callback_data="admin_set_bot_channel"
                )
            ],
        ]
    )


def prices_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="تعيين سعر المرة الواحدة", callback_data="price_once")],
            [InlineKeyboardButton(text="تعيين سعر الاشتراك الشهري", callback_data="price_month")],
            [InlineKeyboardButton(text="رجوع", callback_data="admin_back")],
        ]
    )


# ---- Entry ----


@admin_router.message(Command("admin"))
async def admin_entry(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    await state.clear()
    await message.answer("لوحة التحكم:", reply_markup=admin_menu_kb())


# ---- Back ----


@admin_router.callback_query(F.data == "admin_back")
async def admin_back(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        await cb.answer()
        return
    # Clear FSM and pending keys to prevent leaking states
    await state.clear()
    async for session in get_async_session():
        await session.execute(select(AppSetting))  # noop touch
        # Delete ephemeral pending key if exists
        pending_key = f"pending:{cb.from_user.id}"
        rec = (
            await session.execute(select(AppSetting).where(AppSetting.key == pending_key))
        ).scalar_one_or_none()
        if rec:
            # SQLAlchemy doesn't have simple delete by instance in async version without session.delete
            from sqlalchemy import delete as sqldelete

            await session.execute(sqldelete(AppSetting).where(AppSetting.key == pending_key))
            await session.commit()
    await cb.message.answer("لوحة التحكم:", reply_markup=admin_menu_kb())
    await cb.answer()


# ---- Stats ----


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
                    & (FeatureAccess.expires_at > datetime.utcnow())
                )
            )
        ).scalar_one()
        stars_total = (
            await session.execute(select(func.coalesce(func.sum(Purchase.stars_amount), 0)))
        ).scalar_one()
    text = (
        f"عدد المستخدمين: {total_users}\n"
        f"عدد القنوات المفعّلة: {total_channels}\n"
        f"عدد المجموعات المفعّلة: {total_groups}\n"
        f"عدد من دفعوا: {paid_users}\n"
        f"الاشتراكات النشطة: {active_paid}\n"
        f"إجمالي النجوم المدفوعة: {stars_total}"
    )
    await cb.message.answer(text)
    await cb.answer()


# ---- Broadcast placeholder ----


@admin_router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id):
        await cb.answer()
        return
    await cb.message.answer("الميزة قادمة قريباً")
    await cb.answer()


# ---- Prices ----


@admin_router.callback_query(F.data == "admin_set_prices")
async def admin_set_prices(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        await cb.answer()
        return
    await state.clear()
    # Fetch dynamic prices
    from ..services.payments import get_monthly_price_stars, get_one_time_price_stars

    once = await get_one_time_price_stars()
    month = await get_monthly_price_stars()
    await cb.message.answer(
        f"القيم الحالية:\nمرة واحدة: {once} نجمة\nشهري: {month} نجمة\nاختر ما تريد تعديله:",
        reply_markup=prices_kb(),
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
    await cb.message.answer("أرسل الآن عدد النجوم المطلوب")
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
    # Acknowledge free-tier if price is 0
    if value == 0:
        await message.answer(
            "تم ضبط السعر على 0 — سيتم اعتبار هذه الفئة مجانية.", reply_markup=admin_menu_kb()
        )
    else:
        await message.answer("تم ضبط القيم الجديدة بنجاح", reply_markup=admin_menu_kb())


# ---- Set bot base channel ----


@admin_router.callback_query(F.data == "admin_set_bot_channel")
async def admin_set_bot_channel(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        await cb.answer()
        return
    await state.set_state(AdminStates.await_bot_channel)
    await cb.message.answer("أرسل رابط أو يوزر القناة الأساسية الجديدة (@username أو t.me/...) ")
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
    # Validate via get_chat
    try:
        c = await message.bot.get_chat(value)
        ctype = getattr(c, "type", "")
        if str(ctype) != "channel":
            await message.answer("هذا المعرف ليس قناة عامة صالحة")
            return
    except Exception:
        await message.answer("تعذر التحقق من القناة. تأكد من صحة اليوزر وعلنيتها")
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
    await message.answer(f"تم تعيين قناة البوت إلى: {value}", reply_markup=admin_menu_kb())
