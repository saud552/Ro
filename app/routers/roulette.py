from __future__ import annotations

import asyncio
import unicodedata
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from typing import Optional
from urllib.parse import urlparse

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)
from loguru import logger
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from ..db import get_async_session
from ..db.models import (
    BotChat,
    ChannelLink,
    Contest,
    ContestEntry,
    ContestType,
    Notification,
    RouletteGate,
)
from ..keyboards.channel import link_instruction_kb, roulette_controls_kb
from ..keyboards.common import (
    back_kb,
    confirm_cancel_kb,
    gate_add_menu_kb,
    gate_choice_kb,
    gate_pick_list_kb,
    gates_manage_kb,
)
from ..keyboards.my import manage_draw_kb
from ..services.context import runtime
from ..services.formatting import StyledText, parse_style_from_text
from ..services.payments import grant_monthly, grant_one_time, has_gate_access, log_purchase
from ..services.ratelimit import get_rate_limiter
from ..services.security import draw_unique

# ملخص: أقفال داخلية بسيطة لمنع تنفيذ متزامن لنفس العملية (داخل العملية فقط).
_inproc_locks: dict[str, bool] = {}

roulette_router = Router(name="roulette")


class CreateRoulette(StatesGroup):
    await_channel = State()
    await_text = State()
    await_gate_choice = State()
    await_winners = State()
    await_confirm = State()


@dataclass
class PendingRoulette:
    text_raw: str
    style: str
    winners: int
    channel_id: int


async def _allow(user_id: int, action: str, max_calls: int = 3, period_seconds: int = 5) -> bool:
    limiter = get_rate_limiter(runtime.redis)
    return await limiter.allow(f"{user_id}:{action}", max_calls, period_seconds)


async def _get_user_channel_id(user_id: int) -> Optional[int]:
    async for session in get_async_session():
        row = (
            (
                await session.execute(
                    select(ChannelLink)
                    .where(ChannelLink.owner_id == user_id)
                    .order_by(ChannelLink.id.desc())
                )
            )
            .scalars()
            .first()
        )
        return row.channel_id if row else None


# ===== Helpers =====


def _build_channel_post_text(c: Contest, participants_count: int) -> str:
    """Compose channel post text with styling, status line, and participants count."""
    styled = StyledText(c.text_raw, c.text_style).render()
    status_line = (
        "المشاركة في السحب متاحة حالياً" if c.is_open else "المشاركة في السحب متوقفة حالياً"
    )
    return f"{styled}\n\n{status_line}\nعدد المشاركين: {participants_count}"


async def _get_channel_title_and_link(bot, chat_id: int) -> tuple[str, Optional[str]]:
    """Resolve channel/group title and a usable link."""
    title = f"Channel {chat_id}"
    link: Optional[str] = None
    try:
        chat = await bot.get_chat(chat_id)
        title = getattr(chat, "title", None) or title
        uname = getattr(chat, "username", None)
        if uname:
            link = f"https://t.me/{uname}"
            return title, link
        try:
            link = await bot.export_chat_invite_link(chat_id)
        except Exception:
            link = None
        if link:
            return title, link
        try:
            inv = await bot.create_chat_invite_link(chat_id=chat_id, creates_join_request=False)
            link = getattr(inv, "invite_link", None)
        except Exception:
            link = None
        return title, link
    except Exception:
        return title, None


def _username_from_link(link: str) -> Optional[str]:
    """Extract @username from a public t.me link if available."""
    text = (link or "").strip()
    if not text:
        return None
    if text.startswith("t.me/"):
        text = "https://" + text
    try:
        u = urlparse(text)
    except Exception:
        return None
    if u.netloc not in {"t.me", "telegram.me", "telegram.dog"}:
        return None
    path = u.path.strip("/")
    if not path:
        return None
    if path.startswith("+") or path.startswith("joinchat/") or path.startswith("c/"):
        return None
    username = path.split("/", 1)[0]
    if username:
        return f"@{username.lstrip('@')}"
    return None


def _parse_int_strict(text: str) -> Optional[int]:
    """Parse integer from text with support for Unicode digits."""
    s = (text or "").strip()
    if not s:
        return None
    digits: list[str] = []
    for ch in s:
        if ch.isspace():
            continue
        if ch.isdigit():
            try:
                digits.append(str(unicodedata.digit(ch)))
            except Exception:
                return None
        else:
            return None
    return int("".join(digits)) if digits else None


async def _is_admin_in_channel(bot, chat_id: int, user_id: int) -> bool:
    """Return True if user is creator/administrator in channel, else False."""
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return getattr(member, "status", None) in {"creator", "administrator"}
    except Exception:
        return False


@roulette_router.callback_query(F.data == "link_channel")
async def link_channel(cb: CallbackQuery) -> None:
    bot_username = runtime.bot_username or "your_bot"
    text = (
        "للاستفادة من ميزات البوت، يرجى اتباع الخطوات التالية:\n\n"
        f"1️⃣ أضف البوت @{bot_username} كمشرف في قناتك.\n"
        "2️⃣ قم بإعادة توجيه أي رسالة من قناتك إلى البوت.\n\n"
        "📌 ملاحظة:\n"
        "جميع المشرفين الآخرين في القناة سيتمكنون أيضًا من استخدام البوت بعد إضافته."
    )
    await cb.message.answer(
        text,
        reply_markup=link_instruction_kb(bot_username),
    )
    await cb.answer()


@roulette_router.callback_query(F.data == "unlink_channel")
async def unlink_channel(cb: CallbackQuery) -> None:
    if not await _allow(cb.from_user.id, "unlink"):
        await cb.answer("رجاءً أعد المحاولة لاحقاً", show_alert=True)
        return
    async for session in get_async_session():
        links = (
            (
                await session.execute(
                    select(ChannelLink)
                    .where(ChannelLink.owner_id == cb.from_user.id)
                    .order_by(ChannelLink.id.desc())
                )
            )
            .scalars()
            .all()
        )
        if not links:
            await cb.message.answer("لا توجد قنوات أو مجموعات مرتبطة حالياً.")
            await cb.answer()
            return
        rows = []
        for link in links:
            label = link.channel_title or str(link.channel_id)
            rows.append(
                [InlineKeyboardButton(text=label, callback_data=f"unlinkch:{link.channel_id}")]
            )
        rows.append([InlineKeyboardButton(text="رجوع", callback_data="back")])
        kb = InlineKeyboardMarkup(inline_keyboard=rows)
        await cb.message.answer("اختر ما تريد فصله:", reply_markup=kb)
        await cb.answer()


@roulette_router.callback_query(F.data.startswith("unlinkch:"))
async def unlink_channel_apply(cb: CallbackQuery) -> None:
    try:
        chat_id = int(cb.data.split(":", 1)[1])
    except Exception:
        await cb.answer()
        return
    async for session in get_async_session():
        await session.execute(
            delete(ChannelLink).where(
                (ChannelLink.owner_id == cb.from_user.id) & (ChannelLink.channel_id == chat_id)
            )
        )
        await session.commit()
    await cb.message.answer("تم فصل القناة/المجموعة المحددة.")
    await cb.answer()


@roulette_router.message(StateFilter(None), F.forward_from_chat | F.forward_origin)
async def handle_forwarded_channel(message: Message) -> None:
    chat = message.forward_from_chat or (
        getattr(message, "forward_origin", None) and getattr(message.forward_origin, "chat", None)
    )
    if not chat or getattr(chat, "type", None) not in {"channel", "group", "supergroup"}:
        return
    target = chat
    try:
        member = await message.bot.get_chat_member(target.id, message.from_user.id)
        if getattr(member, "status", None) not in {"creator", "administrator"}:
            await message.answer("يجب أن تكون مشرفاً في الوجهة لربطها")
            return
        if runtime.bot_id is not None:
            bot_member = await message.bot.get_chat_member(target.id, runtime.bot_id)
            if getattr(bot_member, "status", None) not in {"creator", "administrator"}:
                await message.answer("يرجى رفع البوت كمشرف أولاً")
                return
    except TelegramRetryAfter as e:
        await asyncio.sleep(getattr(e, "retry_after", 1))
        await message.answer("يرجى المحاولة مرة أخرى")
        return
    except (TelegramForbiddenError, TelegramBadRequest):
        await message.answer("تعذر التحقق من الصلاحيات")
        return
    async for session in get_async_session():
        existing = (
            await session.execute(
                select(ChannelLink).where(
                    (ChannelLink.owner_id == message.from_user.id)
                    & (ChannelLink.channel_id == target.id)
                )
            )
        ).scalar_one_or_none()
        if existing:
            existing.channel_title = getattr(target, "title", None) or "Chat"
        else:
            session.add(
                ChannelLink(
                    owner_id=message.from_user.id,
                    channel_id=target.id,
                    channel_title=(getattr(target, "title", None) or "Chat"),
                )
            )
        await session.commit()
    await message.answer("تم الربط بنجاح ✅")


@roulette_router.message(StateFilter(None), F.text.contains("t.me/") | F.text.startswith("@"))
async def handle_link_text(message: Message) -> None:
    text = (message.text or "").strip()
    candidate = text
    if candidate.startswith("t.me/"):
        candidate = "https://" + candidate
    if candidate.startswith("http://") or candidate.startswith("https://"):
        with suppress(Exception):
            u = urlparse(candidate)
            if u.netloc in {"t.me", "telegram.me", "telegram.dog"}:
                path = u.path.strip("/")
                if path and not path.startswith(("+", "joinchat/", "c/")):
                    candidate = "@" + path.split("/", 1)[0]
                else:
                    candidate = ""
    if not candidate.startswith("@"):
        return
    username = candidate
    try:
        c = await message.bot.get_chat(username)
        ctype = str(getattr(c, "type", ""))
        if ctype not in {"channel", "group", "supergroup"}:
            await message.answer("هذا المعرف ليس قناة عامة أو مجموعة صالحة")
            return
        member = await message.bot.get_chat_member(c.id, message.from_user.id)
        if getattr(member, "status", None) not in {"creator", "administrator"}:
            await message.answer("يجب أن تكون مشرفاً في الوجهة لربطها")
            return
        if runtime.bot_id is not None:
            bot_member = await message.bot.get_chat_member(c.id, runtime.bot_id)
            if getattr(bot_member, "status", None) not in {"creator", "administrator"}:
                await message.answer("يرجى رفع البوت كمشرف أولاً")
                return
    except (TelegramForbiddenError, TelegramBadRequest):
        await message.answer("تعذر الوصول إلى المعرف")
        return
    async for session in get_async_session():
        existing = (
            await session.execute(
                select(ChannelLink).where(
                    (ChannelLink.owner_id == message.from_user.id)
                    & (ChannelLink.channel_id == c.id)
                )
            )
        ).scalar_one_or_none()
        if existing:
            existing.channel_title = getattr(c, "title", None) or "Chat"
        else:
            session.add(
                ChannelLink(
                    owner_id=message.from_user.id,
                    channel_id=c.id,
                    channel_title=(getattr(c, "title", None) or "Chat"),
                )
            )
        await session.commit()
    await message.answer("تم الربط بنجاح ✅")


@roulette_router.callback_query(F.data == "create_roulette")
async def start_create(cb: CallbackQuery, state: FSMContext) -> None:
    if not await _allow(cb.from_user.id, "create"):
        await cb.answer("رجاءً أعد المحاولة لاحقاً", show_alert=True)
        return
    async for session in get_async_session():
        links = (
            (
                await session.execute(
                    select(ChannelLink)
                    .where(ChannelLink.owner_id == cb.from_user.id)
                    .order_by(ChannelLink.id.desc())
                )
            )
            .scalars()
            .all()
        )
        if not links:
            await cb.message.answer("يرجى أولاً ربط قناة.")
            await cb.answer()
            return
        if len(links) > 1:
            from ..keyboards.channel import select_channel_kb

            items = []
            for link in links:
                items.append((link.channel_id, link.channel_title or f"Chat {link.channel_id}"))
            await state.clear()
            await state.set_state(CreateRoulette.await_channel)
            await cb.message.answer(
                "اختر القناة التي تريد نشر السحب فيها:", reply_markup=select_channel_kb(items)
            )
            await cb.answer()
            return
        channel_id = links[0].channel_id
        await state.clear()
        await state.update_data(channel_id=channel_id)
        await state.set_state(CreateRoulette.await_text)
        await cb.message.answer(
            "أرسل نص كليشة السحب.\nمثال الأنماط: #تشويش ... #تشويش أو #عريض ... #عريض",
            reply_markup=back_kb(),
        )
        await cb.answer()


@roulette_router.callback_query(F.data.startswith("select_channel:"))
async def select_channel(cb: CallbackQuery, state: FSMContext) -> None:
    try:
        chat_id = int(cb.data.split(":", 1)[1])
    except Exception:
        await cb.answer()
        return
    await state.update_data(channel_id=chat_id)
    await state.set_state(CreateRoulette.await_text)
    await cb.message.answer(
        "أرسل نص كليشة السحب.",
        reply_markup=back_kb(),
    )
    await cb.answer()


@roulette_router.callback_query(F.data == "back")
async def go_back(cb: CallbackQuery, state: FSMContext) -> None:
    cur = await state.get_state()
    data = await state.get_data()
    if data.get("sub_view") in {"gate_add", "gate_add_public", "gate_add_menu", "gate_pick"}:
        gates = list(data.get("gate_channels", []))
        await state.update_data(sub_view=None)
        await state.set_state(CreateRoulette.await_gate_choice)
        await cb.message.answer(
            "أعد اختيار ما إذا كنت ترغب بإضافة قنوات شرط أو المتابعة:",
            reply_markup=gates_manage_kb(len(gates)) if gates else gate_choice_kb(),
        )
        await cb.answer()
        return
    if cur == CreateRoulette.await_confirm:
        await state.set_state(CreateRoulette.await_winners)
        await cb.message.answer("أدخل عدد الفائزين:", reply_markup=back_kb())
        await cb.answer()
        return
    if cur == CreateRoulette.await_winners:
        await state.set_state(CreateRoulette.await_gate_choice)
        await cb.message.answer("هل تريد إضافة قناة شرط؟", reply_markup=gate_choice_kb())
        await cb.answer()
        return
    if cur == CreateRoulette.await_gate_choice:
        await state.set_state(CreateRoulette.await_text)
        await cb.message.answer("أرسل نص كليشة السحب مرة أخرى:", reply_markup=back_kb())
        await cb.answer()
        return
    if cur == CreateRoulette.await_text or cur == CreateRoulette.await_channel:
        await state.clear()
        from ..keyboards.common import start_menu_kb

        await cb.message.answer("تم الإلغاء. اختر من القائمة:", reply_markup=start_menu_kb())
        await cb.answer()
        return
    await cb.answer()


@roulette_router.message(CreateRoulette.await_text)
async def collect_text(message: Message, state: FSMContext) -> None:
    text, style = parse_style_from_text(message.text or "")
    await state.update_data(text_raw=text, style=style)
    await state.set_state(CreateRoulette.await_gate_choice)
    await message.answer(
        "هل تريد إضافة قناة شرط؟",
        reply_markup=gate_choice_kb(),
    )


@roulette_router.callback_query(F.data == "gate_skip")
async def gate_skip(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(CreateRoulette.await_winners)
    await cb.message.answer("أدخل عدد الفائزين:", reply_markup=back_kb())
    await cb.answer()


@roulette_router.callback_query(F.data == "gate_add")
async def gate_add(cb: CallbackQuery, state: FSMContext) -> None:
    if not await has_gate_access(cb.from_user.id):
        from ..services.payments import get_monthly_price_stars, get_one_time_price_stars

        m_price = await get_monthly_price_stars()
        o_price = await get_one_time_price_stars()
        text = "🔰 ميزة إضافة قناة الشرط متاحة فقط للمشتركين."
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"اشتراك شهري ({m_price})", callback_data="pay_monthly"
                    )
                ],
                [InlineKeyboardButton(text=f"مرة واحدة ({o_price})", callback_data="pay_onetime")],
                [InlineKeyboardButton(text="رجوع", callback_data="back")],
            ]
        )
        await cb.message.answer(text, reply_markup=kb)
        await cb.answer()
        return
    await state.update_data(sub_view="gate_add_menu")
    await cb.message.answer("اختر طريقة إضافة الشرط:", reply_markup=gate_add_menu_kb())
    await cb.answer()


@roulette_router.callback_query(F.data == "gate_done")
async def gate_done(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(CreateRoulette.await_winners)
    await cb.message.answer("أدخل عدد الفائزين:", reply_markup=back_kb())
    await cb.answer()


@roulette_router.message(CreateRoulette.await_winners)
async def collect_winners(message: Message, state: FSMContext) -> None:
    val = _parse_int_strict(message.text or "")
    if not val:
        await message.answer("الرجاء إرسال رقم صحيح")
        return
    count = max(1, min(100, val))
    await state.update_data(winners=count)
    await state.set_state(CreateRoulette.await_confirm)
    data = await state.get_data()
    styled = StyledText(data["text_raw"], data["style"]).render()
    await message.answer(
        f"تأكيد إنشاء السحب:\nالنص:\n{styled}\nعدد الفائزين: {count}",
        reply_markup=confirm_cancel_kb(),
    )


@roulette_router.callback_query(F.data == "confirm_create")
async def confirm_create_cb(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    channel_id = int(data.get("channel_id") or 0)
    import secrets

    unique_code = secrets.token_hex(4)

    async for session in get_async_session():
        contest = Contest(
            owner_id=cb.from_user.id,
            channel_id=channel_id,
            unique_code=unique_code,
            type=ContestType.ROULETTE,
            text_raw=data["text_raw"],
            text_style=data["style"],
            winners_count=data["winners"],
            is_open=True,
        )
        session.add(contest)
        await session.flush()

        gate_channels = list(data.get("gate_channels", []))
        for g in gate_channels:
            session.add(
                RouletteGate(
                    contest_id=contest.id,
                    channel_id=g.get("channel_id"),
                    channel_title=g.get("channel_title") or "Gate",
                    invite_link=g.get("invite_link"),
                )
            )

        gate_links = [
            (g.get("channel_title") or "Gate", g.get("invite_link")) for g in gate_channels
        ]
        post_text = _build_channel_post_text(contest, 0)
        post = await cb.bot.send_message(
            channel_id,
            post_text,
            reply_markup=roulette_controls_kb(
                contest.id, True, runtime.bot_username, gate_links, False
            ),
            parse_mode=ParseMode.HTML,
        )
        contest.message_id = post.message_id
        await session.commit()

        if gate_channels:
            await has_gate_access(cb.from_user.id, consume_one_time=True)

    await cb.bot.send_message(
        cb.from_user.id, "تم إنشاء السحب بنجاح.", reply_markup=manage_draw_kb(contest.id)
    )
    await state.clear()
    await cb.answer()


@roulette_router.callback_query(F.data.startswith("join:"))
async def join(cb: CallbackQuery) -> None:
    if not await _allow(cb.from_user.id, "join"):
        await cb.answer("رجاءً أعد المحاولة لاحقاً", show_alert=True)
        return
    contest_id = int(cb.data.split(":", 1)[1])
    async for session in get_async_session():
        c = (
            await session.execute(select(Contest).where(Contest.id == contest_id))
        ).scalar_one_or_none()
        if not c or not c.is_open:
            await cb.answer("المشاركة مغلقة", show_alert=True)
            return

        existing = (
            await session.execute(
                select(ContestEntry).where(
                    ContestEntry.contest_id == contest_id, ContestEntry.user_id == cb.from_user.id
                )
            )
        ).scalar_one_or_none()

        if existing is None:
            try:
                session.add(ContestEntry(contest_id=contest_id, user_id=cb.from_user.id))
                await session.commit()
            except IntegrityError:
                await session.rollback()

        count = (
            await session.execute(
                select(func.count())
                .select_from(ContestEntry)
                .where(ContestEntry.contest_id == contest_id)
            )
        ).scalar_one()

        with suppress(Exception):
            await cb.bot.edit_message_text(
                chat_id=c.channel_id,
                message_id=c.message_id,
                text=_build_channel_post_text(c, count),
                reply_markup=roulette_controls_kb(c.id, c.is_open, runtime.bot_username, [], False),
                parse_mode=ParseMode.HTML,
            )
    await cb.answer("تم الانضمام ✅")


@roulette_router.callback_query(F.data.startswith("draw:"))
async def draw(cb: CallbackQuery) -> None:
    contest_id = int(cb.data.split(":", 1)[1])
    async for session in get_async_session():
        c = (
            await session.execute(select(Contest).where(Contest.id == contest_id))
        ).scalar_one_or_none()
        if not c or c.closed_at:
            await cb.answer("تم السحب مسبقاً", show_alert=True)
            return

        participants = (
            (
                await session.execute(
                    select(ContestEntry.user_id).where(ContestEntry.contest_id == c.id)
                )
            )
            .scalars()
            .all()
        )
        if not participants:
            await cb.answer("لا يوجد مشاركون", show_alert=True)
            return

        winners_ids = draw_unique(participants, c.winners_count)
        winners_lines = []
        for uid in winners_ids:
            winners_lines.append(f"• <a href='tg://user?id={uid}'>فائز</a>")

        announce_text = f"🎉 فائزو السحب:\n\n" + "\n".join(winners_lines)
        await cb.bot.send_message(c.channel_id, announce_text, parse_mode=ParseMode.HTML)

        c.is_open = False
        c.closed_at = datetime.now(timezone.utc)
        await session.commit()

    await cb.answer("تم إعلان النتائج 🎉")
