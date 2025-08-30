from __future__ import annotations

from contextlib import suppress

from aiogram import F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from ..config import settings
from ..db import get_async_session
from ..db.models import Notification, Roulette, User
from ..keyboards.common import gate_kb, start_menu_kb
from ..services.context import runtime
from ..services.payments import grant_monthly, grant_one_time, has_gate_access
from .my import my_draws_command

start_router = Router(name="start")


async def _ensure_user(user_id: int, username: str | None) -> None:
    async for session in get_async_session():
        exists = (
            await session.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        if exists is None:
            try:
                session.add(User(id=user_id, username=username))
                await session.commit()
            except Exception:
                # In case of a race (duplicate insert), roll back quietly
                await session.rollback()
        else:
            # Update username if changed
            if exists.username != username:
                exists.username = username
                await session.commit()


async def _is_subscribed_to_bot_channel(event) -> bool:
    try:
        member = await event.bot.get_chat_member(settings.bot_channel, event.from_user.id)
        return member.status in {"member", "creator", "administrator"}
    except Exception:
        return False


@start_router.message(CommandStart())
async def handle_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _ensure_user(message.from_user.id, message.from_user.username)
    if not await _is_subscribed_to_bot_channel(message):
        await message.answer(
            "يرجى الاشتراك في قناة البوت لاستخدام الخدمات.",
            reply_markup=gate_kb(settings.bot_channel),
        )
        return
    args = (message.text or "").split(maxsplit=1)
    if len(args) == 2 and args[1].startswith("notify-"):
        try:
            rid = int(args[1].split("-", 1)[1])
        except ValueError:
            rid = None
        if rid:
            async for session in get_async_session():
                exists = (
                    await session.execute(
                        select(Notification).where(
                            Notification.user_id == message.from_user.id,
                            Notification.roulette_id == rid,
                        )
                    )
                ).scalar_one_or_none()
                roul = (
                    await session.execute(select(Roulette).where(Roulette.id == rid))
                ).scalar_one_or_none()
                if roul and not exists:
                    session.add(Notification(user_id=message.from_user.id, roulette_id=rid))
                    await session.commit()
            await message.answer("تم تفعيل التنبيه لهذا السحب ✅")
            return
    # Deep-link to open my draws from start parameter
    if len(args) == 2 and args[1].strip().lower() == "my":
        await my_draws_command(message)
        return
    await message.answer(
        "حياك الله في روليت سحوبات\nاختر من القائمة:",
        reply_markup=start_menu_kb(),
    )


@start_router.callback_query(F.data == "check_subscription")
async def check_subscription(cb: CallbackQuery) -> None:
    if await _is_subscribed_to_bot_channel(cb):
        await cb.message.edit_text("تم التحقق، يمكنك البدء الآن.")
        await cb.message.answer("اختر من القائمة:", reply_markup=start_menu_kb())
    else:
        await cb.answer("لا زلت غير مشترك", show_alert=True)


@start_router.message(
    StateFilter(None),
    ~(F.forward_from_chat | F.forward_origin),
    ~F.text.startswith("/"),
    ~F.text.regexp(r"^\d+$"),
    ~(F.text.contains("t.me/") | F.text.startswith("@")),
)
async def fallback(message: Message) -> None:
    await _ensure_user(message.from_user.id, message.from_user.username)
    if not await _is_subscribed_to_bot_channel(message):
        await message.answer("يرجى الاشتراك أولاً", reply_markup=gate_kb(settings.bot_channel))
        return
    await message.answer("استخدم /start لعرض القائمة", reply_markup=start_menu_kb())


@start_router.callback_query(F.data == "my_draws")
async def open_my_draws(cb: CallbackQuery) -> None:
    # Open management in private if possible; if pressed in private chat, run directly
    chat_type = getattr(cb.message.chat, "type", "")
    if str(chat_type) == "private":
        await my_draws_command(cb.message)
    else:
        link = f"https://t.me/{runtime.bot_username}?start=my"
        with suppress(Exception):
            await cb.bot.send_message(cb.from_user.id, f"لفتح سحوباتك اضغط: {link}")
    await cb.answer()


# ===== Admin commands =====


def _is_admin(user_id: int) -> bool:
    return user_id in set(settings.admin_ids)


@start_router.message(Command("gate_status"))
async def admin_gate_status(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    ok = await has_gate_access(message.from_user.id)
    await message.answer("لديك استحقاق" if ok else "لا يوجد استحقاق")


@start_router.message(Command("gate_grant_month"))
async def admin_grant_month(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    await grant_monthly(message.from_user.id)
    await message.answer("تم منح اشتراك شهر")


@start_router.message(Command("gate_grant_one"))
async def admin_grant_one(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    await grant_one_time(message.from_user.id, 1)
    await message.answer("تم منح رصيد مرة واحدة")


@start_router.message(Command("cancel"))
async def cancel_flow(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("تم الإلغاء.")
