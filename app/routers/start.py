from __future__ import annotations

import logging
from contextlib import suppress

from aiogram import F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select

from ..db import get_async_session
from ..db.repositories import AppSettingRepository, UserRepository
from ..keyboards.common import forced_sub_kb, main_menu_kb
from ..services.subscription import SubscriptionService
from ..db.models import User, Contest, Notification

start_router = Router(name="start")


async def _get_services(bot, session):
    user_repo = UserRepository(session)
    setting_repo = AppSettingRepository(session)
    sub_service = SubscriptionService(bot, setting_repo)
    return user_repo, sub_service


@start_router.message(CommandStart())
async def handle_start(message: Message, state: FSMContext) -> None:
    await state.clear()

    # Check for deep links
    args = (message.text or "").split(maxsplit=1)
    deep_link = args[1] if len(args) == 2 else None

    async for session in get_async_session():
        user_repo, sub_service = await _get_services(message.bot, session)

        # 1. Register or update user & Referral logic
        referred_by_id = None
        if deep_link and deep_link.isdigit():
            referred_by_id = int(deep_link)

        # Check if user already exists
        existing_user = await user_repo.get_by_id(message.from_user.id)
        is_new = existing_user is None

        user = await user_repo.get_or_create(message.from_user.id, message.from_user.username)

        if is_new and referred_by_id and referred_by_id != user.id:
            # Award points to the inviter
            inviter = await user_repo.get_by_id(referred_by_id)
            if inviter:
                user.referred_by_id = referred_by_id
                setting_repo = AppSettingRepository(session)
                ref_enabled = await setting_repo.get_value("referral_enabled", "yes")
                if ref_enabled == "yes":
                    points_to_award = int(await setting_repo.get_value("referral_points", "10"))
                    inviter.points += points_to_award
                    with suppress(Exception):
                        await message.bot.send_message(
                            referred_by_id,
                            f"🎊 مستخدم جديد انضم عبر رابطك! حصلت على {points_to_award} نقطة."
                        )

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

        # 3. Handle specific deep links
        if deep_link:
            from aiogram.types import CallbackQuery as FakeCB
            if deep_link.startswith("reg-"):
                # reg-contest_id
                parts = deep_link.split("-")
                if len(parts) == 2:
                    from .voting import start_registration
                    cb = FakeCB(
                        id="0",
                        from_user=message.from_user,
                        chat_instance="0",
                        message=message,
                        data=f"reg_contest:{parts[1]}"
                    )
                    cb._bot = message.bot
                    await start_registration(cb, state)
                    return

            elif deep_link.startswith("vote-"):
                # vote-contest_id-entry_id
                parts = deep_link.split("-")
                if len(parts) == 3:
                    from .voting import handle_entry_view
                    cb = FakeCB(
                        id="0",
                        from_user=message.from_user,
                        chat_instance="0",
                        message=message,
                        data=f"vote_sel:{parts[1]}:{parts[2]}"
                    )
                    cb._bot = message.bot
                    await handle_entry_view(cb, state)
                    return

            elif deep_link.startswith("join-"):
                # join-contest_id (for Roulette)
                parts = deep_link.split("-")
                if len(parts) == 2:
                    from .roulette import handle_join_request
                    cb = FakeCB(
                        id="0",
                        from_user=message.from_user,
                        chat_instance="0",
                        message=message,
                        data=f"join:{parts[1]}"
                    )
                    cb._bot = message.bot
                    await handle_join_request(cb, state)
                    return

            elif deep_link.startswith("notify-"):
                 # notify-contest_id
                 parts = deep_link.split("-")
                 if len(parts) == 2:
                     contest_id = int(parts[1])
                     stmt = select(Notification).where(
                         (Notification.contest_id == contest_id) & (Notification.user_id == message.from_user.id)
                     )
                     existing = (await session.execute(stmt)).scalar_one_or_none()
                     if not existing:
                         session.add(Notification(contest_id=contest_id, user_id=message.from_user.id))
                         await session.commit()
                         await message.answer("✅ سيتم إخطارك إذا فزت في هذا السحب!")
                     else:
                         await message.answer("🔔 أنت مشترك بالفعل في إشعارات هذا السحب.")
                     return

        # 4. Show Main Menu
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


async def open_my_draws(message: Message):
    """Legacy helper for tests."""
    from .my import my_entry
    await my_entry(message)
