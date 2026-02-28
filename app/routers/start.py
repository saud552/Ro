from __future__ import annotations

from contextlib import suppress

from aiogram import F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ..db import get_async_session
from ..db.repositories import AppSettingRepository, UserRepository
from ..keyboards.common import forced_sub_kb, main_menu_kb
from ..services.subscription import SubscriptionService

start_router = Router(name="start")


async def _get_services(bot, session):
    user_repo = UserRepository(session)
    setting_repo = AppSettingRepository(session)
    sub_service = SubscriptionService(bot, setting_repo)
    return user_repo, sub_service


@start_router.message(CommandStart())
async def handle_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    async for session in get_async_session():
        user_repo, sub_service = await _get_services(message.bot, session)

        # 1. Register or update user & Referral logic
        args = (message.text or "").split(maxsplit=1)
        referred_by = None
        if len(args) == 2 and args[1].isdigit():
            referred_by = int(args[1])

        user = await user_repo.get_or_create(message.from_user.id, message.from_user.username)
        if referred_by and not user.referred_by_id and referred_by != user.id:
            user.referred_by_id = referred_by
        await user_repo.commit()

        # 2. Check Forced Subscription
        if not await sub_service.check_forced_subscription(message.from_user.id):
            channel = await sub_service.get_required_channel()
            url = f"https://t.me/{channel.lstrip('@')}" if channel else "https://t.me/telegram"
            await message.answer(
                "❌ يرجى الاشتراك في قناة البوت أولاً لاستخدام الخدمات.",
                reply_markup=forced_sub_kb(url),
            )
            return

        # 3. Show Main Menu
        await message.answer(
            f"👋 أهلاً بك يا {message.from_user.first_name} في منصة المسابقات المتكاملة.\n\n"
            "يرجى اختيار القسم المطلوب من القائمة أدناه:",
            reply_markup=main_menu_kb(),
        )


@start_router.callback_query(F.data == "check_subscription")
async def check_subscription(cb: CallbackQuery) -> None:
    async for session in get_async_session():
        _, sub_service = await _get_services(cb.bot, session)
        if await sub_service.check_forced_subscription(cb.from_user.id):
            await cb.message.edit_text("✅ تم التحقق بنجاح! يمكنك الآن استخدام البوت.")
            await cb.message.answer(
                "اختر من القائمة الرئيسية:",
                reply_markup=main_menu_kb(),
            )
        else:
            await cb.answer("⚠️ لا زلت غير مشترك في القناة المطلوبة!", show_alert=True)


@start_router.message(Command("cancel"))
async def cancel_flow(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("✅ تم إلغاء العملية والعودة للبداية.", reply_markup=main_menu_kb())
