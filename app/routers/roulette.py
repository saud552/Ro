from __future__ import annotations

import asyncio
import unicodedata
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
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
from ..db.models import BotChat, ChannelLink, Notification, Participant, Roulette, RouletteGate
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

# Markdown (legacy) escape for link text
_DEF_MD_ESC = set("_*[]()")


def _escape_md(text: str) -> str:
    res = []
    for ch in text:
        if ch in _DEF_MD_ESC:
            res.append("\\" + ch)
        else:
            res.append(ch)
    return "".join(res)


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


def _build_channel_post_text(r: Roulette, participants_count: int) -> str:
    """Compose channel post text with styling, status line, and participants count."""
    styled = StyledText(r.text_raw, r.text_style).render()
    status_line = "المشاركة في السحب متاحة حالياً" if r.is_open else "المشاركة في السحب متوقفة حالياً"
    return f"{styled}\n\n{status_line}\nعدد المشاركين: {participants_count}"


async def _get_channel_title_and_link(bot, chat_id: int) -> tuple[str, Optional[str]]:
    """Resolve channel/group title and a usable link.

    - Prefer public username link if available
    - Else try export_chat_invite_link (primary)
    - Else create a new invite link
    """
    title = f"Channel {chat_id}"
    link: Optional[str] = None
    try:
        c = await bot.get_chat(chat_id)
        title = getattr(c, "title", None) or title
        uname = getattr(c, "username", None)
        if uname:
            link = f"https://t.me/{uname}"
            return title, link
        # no public username -> try export primary invite link
        try:
            link = await bot.export_chat_invite_link(chat_id)
        except Exception:
            link = None
        if link:
            return title, link
        # fallback: create one
        try:
            inv = await bot.create_chat_invite_link(chat_id=chat_id, creates_join_request=False)
            link = getattr(inv, "invite_link", None)
        except Exception:
            link = None
        return title, link
    except Exception:
        return title, None


def _username_from_link(link: str) -> Optional[str]:
    """Extract @username from a public t.me link if available.

    Returns value like "@channelusername" or None if not a public username link.
    """
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
    # Skip joinchat/+hash/private forms
    if path.startswith("+") or path.startswith("joinchat/") or path.startswith("c/"):
        return None
    username = path.split("/", 1)[0]
    if username:
        return f"@{username.lstrip('@')}"
    return None


def _parse_int_strict(text: str) -> Optional[int]:
    """Parse integer from text with support for Unicode digits (e.g., Arabic-Indic).
    Ignores whitespace; fails if any non-digit present.
    """
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
    # List user-linked chats to choose which to unlink
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

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


# Linking via forwarded message: accept channels and groups
@roulette_router.message(StateFilter(None), F.forward_from_chat | F.forward_origin)
async def handle_forwarded_channel(message: Message) -> None:
    chat = message.forward_from_chat or (
        getattr(message, "forward_origin", None) and getattr(message.forward_origin, "chat", None)
    )
    if not chat or getattr(chat, "type", None) not in {"channel", "group", "supergroup"}:
        return
    target = chat
    # Verify the sender is admin/owner in target and the bot is admin
    try:
        member = await message.bot.get_chat_member(target.id, message.from_user.id)
        if getattr(member, "status", None) not in {"creator", "administrator"}:
            await message.answer("يجب أن تكون مشرفاً في الوجهة لربطها")
            return
        # ensure bot is admin
        if runtime.bot_id is not None:
            bot_member = await message.bot.get_chat_member(target.id, runtime.bot_id)
            if getattr(bot_member, "status", None) not in {"creator", "administrator"}:
                await message.answer("يرجى رفع البوت كمشرف أولاً")
                return
    except TelegramRetryAfter as e:
        await asyncio.sleep(getattr(e, "retry_after", 1))
        await message.answer("يرجى المحاولة مرة أخرى")
        return
    except TelegramForbiddenError:
        await message.answer("لا يمكن التحقق من الصلاحيات. تأكد من وجود البوت كمشرف")
        return
    except TelegramBadRequest:
        await message.answer("بيانات الوجهة غير صالحة")
        return
    async for session in get_async_session():
        # Upsert per (owner_id, chat_id)
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


# Linking via text: accept @username or t.me/ for channels and groups
@roulette_router.message(StateFilter(None), F.text.contains("t.me/") | F.text.startswith("@"))
async def handle_link_text(message: Message) -> None:
    text = (message.text or "").strip()
    # Normalize to @username
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
    # Resolve chat and verify admin roles
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
    except TelegramRetryAfter as e:
        await asyncio.sleep(getattr(e, "retry_after", 1))
        await message.answer("يرجى المحاولة مرة أخرى")
        return
    except (TelegramForbiddenError, TelegramBadRequest):
        await message.answer("تعذر الوصول إلى المعرف. تأكد من علنية الوجهة وصحتها")
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
    # If user has multiple linked channels, prompt selection
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
                resolved_title = link.channel_title or f"Channel {link.channel_id}"
                with suppress(Exception):
                    c = await cb.bot.get_chat(link.channel_id)
                    resolved_title = getattr(c, "title", None) or resolved_title
                items.append((link.channel_id, resolved_title))
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
            "أرسل نص كليشة السحب.\nمثال الأنماط: #تشويش ... #تشويش أو #عريض ... #عريض أو #مائل ... #مائل أو #اقتباس ... #اقتباس",
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
        "أرسل نص كليشة السحب.\nمثال الأنماط: #تشويش ... #تشويش أو #عريض ... #عريض أو #مائل ... #مائل أو #اقتباس ... #اقتباس",
        reply_markup=back_kb(),
    )
    await cb.answer()


@roulette_router.callback_query(F.data == "back")
async def go_back(cb: CallbackQuery, state: FSMContext) -> None:
    cur = await state.get_state()
    data = await state.get_data()
    # Back from sub-view in gate add -> return to gate choice managing current gates
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
    # Default: just acknowledge
    await cb.answer()


@roulette_router.message(CreateRoulette.await_text)
async def collect_text(message: Message, state: FSMContext) -> None:
    text, style = parse_style_from_text(message.text or "")
    await state.update_data(text_raw=text, style=style)
    await state.set_state(CreateRoulette.await_gate_choice)
    await message.answer(
        "هل تريد إضافة قناة شرط؟\nعند إضافة قناة شرط لن يتمكن أحد من المشاركة قبل الانضمام للقناة المحددة.",
        reply_markup=gate_choice_kb(),
    )


@roulette_router.callback_query(F.data == "gate_skip")
async def gate_skip(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(CreateRoulette.await_winners)
    await cb.message.answer("أدخل عدد الفائزين:", reply_markup=back_kb())
    await cb.answer()


@roulette_router.callback_query(F.data == "gate_add")
async def gate_add(cb: CallbackQuery, state: FSMContext) -> None:
    # Check access entitlement first
    if not await has_gate_access(cb.from_user.id):
        from ..services import payments as _p

        m_price = await _p.get_monthly_price_stars()
        o_price = await _p.get_one_time_price_stars()
        # Free-tier logic: if any tier price is 0, treat as free and grant accordingly
        if m_price == 0 or o_price == 0:
            if m_price == 0:
                await grant_monthly(cb.from_user.id)
                await cb.message.answer("تم تفعيل ميزة قنوات الشرط مجاناً لمدة شهر ✅")
            elif o_price == 0:
                await grant_one_time(cb.from_user.id, credits=1)
                await cb.message.answer("تم منح رصيد مجاني لاستخدام واحد لميزة قنوات الشرط ✅")
            # proceed to gate add menu
            await state.update_data(sub_view="gate_add_menu")
            await cb.message.answer("اختر طريقة إضافة الشرط:", reply_markup=gate_add_menu_kb())
            await cb.answer()
            return
        text = (
            "♻️ ميزة إضافة قناة الشرط\n"
            "مع هذه الميزة، يمكنك تعيين قناة أو قنوات كشرط لدخول السحب، مما يضمن أن المشاركين لن يتمكنوا من الانضمام إلى الروليت إلا بعد الاشتراك في القناة المحددة.\n\n"
            "🔰 متاح فقط لمستخدمي النسخة المدفوعة\n"
            "💳 الدفع يتم باستخدام نجوم تيليجرام، وبعد الترقية، سيتم تفعيل الميزة تلقائيًا."
        )
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"ترقية اشتراكك لمدة شهر ({m_price} نجمة)", callback_data="pay_monthly"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=f"ترقية الآن لمرة واحدة ({o_price} نجوم)", callback_data="pay_onetime"
                    )
                ],
                [InlineKeyboardButton(text="رجوع", callback_data="back")],
            ]
        )
        await cb.message.answer(text, reply_markup=kb)
        await cb.answer()
        return
    # Show add options menu (قناة أو مجموعة)
    await state.update_data(sub_view="gate_add_menu")
    await cb.message.answer(
        "اختر إضافة قناة أم مجموعة كشرط:",
        reply_markup=gate_add_menu_kb(),
    )
    await cb.answer()


@roulette_router.callback_query(F.data == "gate_add_channel")
async def gate_add_channel(cb: CallbackQuery, state: FSMContext) -> None:
    # After entitlement, prompt for channel input
    await state.update_data(sub_view="gate_add_channel")
    await cb.message.answer(
        "لإضافة قناة كشرط: ارفع البوت مشرفاً في القناة ثم أرسل @username للقناة أو حوّل رسالة منها إذا كانت خاصة.",
        reply_markup=back_kb(),
    )
    await cb.answer()


@roulette_router.callback_query(F.data == "gate_add_group")
async def gate_add_group(cb: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(sub_view="gate_add_group")
    await cb.message.answer(
        "لإضافة مجموعة كشرط: ارفع البوت مشرفاً في المجموعة ثم أرسل رابط المجموعة أو حوّل رسالة منها.",
        reply_markup=back_kb(),
    )
    await cb.answer()


@roulette_router.message(CreateRoulette.await_gate_choice, F.forward_from_chat | F.forward_origin)
async def add_gate_forwarded(message: Message, state: FSMContext) -> None:
    chat = message.forward_from_chat or (
        getattr(message, "forward_origin", None) and getattr(message.forward_origin, "chat", None)
    )
    if not chat or getattr(chat, "type", None) not in {"channel", "group", "supergroup"}:
        return
    # Determine expected type based on sub_view selection
    data = await state.get_data()
    expected = data.get("sub_view")
    if expected == "gate_add_channel" and str(getattr(chat, "type", "")) != "channel":
        return
    if expected == "gate_add_group" and str(getattr(chat, "type", "")) not in {"group", "supergroup"}:
        return
    channel = chat
    # Verify sender and bot are admins in gate channel
    try:
        member = await message.bot.get_chat_member(channel.id, message.from_user.id)
        if getattr(member, "status", None) not in {"creator", "administrator"}:
            await message.answer("يجب أن تكون مشرفاً في الوجهة المضافة كشرط")
            return
        if runtime.bot_id is not None:
            bot_member = await message.bot.get_chat_member(channel.id, runtime.bot_id)
            if getattr(bot_member, "status", None) not in {"creator", "administrator"}:
                await message.answer("يرجى رفع البوت مشرفاً ومنحه الصلاحيات اللازمة")
                return
        # try to create an invite link for convenience (if bot is admin)
        invite_link = None
        with suppress(Exception):
            inv = await message.bot.create_chat_invite_link(
                chat_id=channel.id, creates_join_request=False
            )
            invite_link = getattr(inv, "invite_link", None)
    except TelegramRetryAfter as e:
        await asyncio.sleep(getattr(e, "retry_after", 1))
        await message.answer("يرجى المحاولة مرة أخرى")
        return
    except TelegramForbiddenError:
        await message.answer("لا يمكن التحقق من الصلاحيات لقناة الشرط")
        return
    except TelegramBadRequest:
        await message.answer("بيانات قناة الشرط غير صالحة")
        return
    gates = list(data.get("gate_channels", []))
    gates.append(
        {
            "channel_id": channel.id,
            "channel_title": channel.title or "Channel",
            "invite_link": invite_link,
        }
    )
    await state.update_data(gate_channels=gates)
    await message.answer(
        ("تمت إضافة قناة الشرط ✅" if str(getattr(channel, "type", "")) == "channel" else "تمت إضافة مجموعة الشرط ✅"),
        reply_markup=gates_manage_kb(len(gates)),
    )


@roulette_router.message(CreateRoulette.await_gate_choice, F.text)
async def add_gate_link(message: Message, state: FSMContext) -> None:
    # Handle according to selection: channel vs group
    data = await state.get_data()
    sub_view = data.get("sub_view")
    if sub_view not in {"gate_add_public", "gate_add_channel", "gate_add_group"}:
        return
    text = (message.text or "").strip()
    if not (
        text.startswith("http://")
        or text.startswith("https://")
        or text.startswith("t.me/")
        or text.startswith("@")
    ):
        # ignore unrelated text here
        return
    # Normalize and validate telegram domain
    candidate = text
    if candidate.startswith("t.me/"):
        candidate = "https://" + candidate
    ok = False
    with suppress(Exception):
        from urllib.parse import urlparse as _p

        u = (
            _p(candidate)
            if (candidate.startswith("http://") or candidate.startswith("https://"))
            else None
        )
        ok = (u is None) or (u.netloc in {"t.me", "telegram.me", "telegram.dog"})
    if not ok:
        await message.answer("يُقبل فقط روابط تيليجرام كقناة شرط (t.me/…)")
        return
    # Extract identifier depending on target type
    identifier = None
    if text.startswith("@"):
        identifier = text
    elif candidate.startswith("http://") or candidate.startswith("https://"):
        with suppress(Exception):
            from urllib.parse import urlparse as _p2

            u2 = _p2(candidate)
            path = u2.path.strip("/")
            if path and not path.startswith(("+", "joinchat/")):
                identifier = "@" + path.split("/", 1)[0]
            else:
                # allow private group/channel invite links by resolving via get_chat on the full URL
                identifier = candidate
    if not identifier:
        await message.answer("الرجاء إرسال رابط تيليجرام صحيح أو @username.")
        return
    # Resolve and enforce admin checks per selection
    try:
        c = await message.bot.get_chat(identifier)
        ctype = str(getattr(c, "type", ""))
        if sub_view == "gate_add_channel" and ctype != "channel":
            await message.answer("الرجاء إرسال قناة عامة صحيحة (@username) أو تحويل رسالة من القناة الخاصة.")
            return
        if sub_view == "gate_add_group" and ctype not in {"group", "supergroup"}:
            await message.answer("الرجاء إرسال رابط مجموعة صحيح أو تحويل رسالة من المجموعة.")
            return
        m_user = await message.bot.get_chat_member(c.id, message.from_user.id)
        if getattr(m_user, "status", None) not in {"creator", "administrator"}:
            await message.answer("يجب أن تكون مشرفاً ومنحت الصلاحيات اللازمة لإضافة هذا الوجهة كشرط")
            return
        if runtime.bot_id is not None:
            m_bot = await message.bot.get_chat_member(c.id, runtime.bot_id)
            if getattr(m_bot, "status", None) not in {"creator", "administrator"}:
                await message.answer("يرجى رفع البوت كمشرف ومنحه الصلاحيات ثم أعد المحاولة")
                return
    except TelegramRetryAfter as e:
        await asyncio.sleep(getattr(e, "retry_after", 1))
        await message.answer("يرجى المحاولة مرة أخرى")
        return
    except (TelegramForbiddenError, TelegramBadRequest):
        await message.answer("تعذر الوصول. تأكد من صحة الرابط/المعرف ورفع البوت كمشرف")
        return
    # Optional invite link
    invite_link = None
    with suppress(Exception):
        inv = await message.bot.create_chat_invite_link(chat_id=c.id, creates_join_request=False)
        invite_link = getattr(inv, "invite_link", None)
    gates = list(data.get("gate_channels", []))
    title = getattr(c, "title", None) or (f"Channel {c.id}" if ctype == "channel" else f"Group {c.id}")
    gates.append({"channel_id": c.id, "channel_title": title, "invite_link": invite_link})
    await state.update_data(gate_channels=gates)
    await message.answer(
        ("تمت إضافة قناة الشرط ✅" if ctype == "channel" else "تمت إضافة مجموعة الشرط ✅"),
        reply_markup=gates_manage_kb(len(gates)),
    )


@roulette_router.callback_query(F.data == "gate_done")
async def gate_done(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(CreateRoulette.await_winners)
    await cb.message.answer("أدخل عدد الفائزين:", reply_markup=back_kb())
    await cb.answer()


@roulette_router.callback_query(F.data == "gate_pick")
async def gate_pick(cb: CallbackQuery, state: FSMContext) -> None:
    # Build list from BotChat where bot is present and both user/bot are admins (اختياري)
    items: list[tuple[int, str]] = []
    rows: list[BotChat] = []
    async for session in get_async_session():
        rows = (
            (await session.execute(select(BotChat).where(BotChat.removed_at.is_(None))))
            .scalars()
            .all()
        )
    for rec in rows:
        chat_id = rec.chat_id
        title = rec.title or f"Chat {chat_id}"
        try:
            m_user = await cb.bot.get_chat_member(chat_id, cb.from_user.id)
            if getattr(m_user, "status", None) not in {"creator", "administrator"}:
                continue
            if runtime.bot_id is not None:
                m_bot = await cb.bot.get_chat_member(chat_id, runtime.bot_id)
                if getattr(m_bot, "status", None) not in {"creator", "administrator"}:
                    continue
            items.append((chat_id, title))
        except Exception:
            continue
    # Always open the add menu; if we have items, نعرضها كاختصار
    await state.update_data(sub_view="gate_add_menu")
    if items:
        await cb.message.answer(
            "اختر قناة/مجموعة لإضافتها كشرط أو أرسل/حوّل القناة الآن:",
            reply_markup=gate_pick_list_kb(items),
        )
    else:
        await cb.message.answer(
            "لم نجد وجهات معروفة. يمكنك الآن إرسال/تحويل القناة أو إدخال @username.",
            reply_markup=gate_add_menu_kb(),
        )
    await cb.answer()


@roulette_router.callback_query(F.data.startswith("gate_pick_apply:"))
async def gate_pick_apply(cb: CallbackQuery, state: FSMContext) -> None:
    try:
        chat_id = int(cb.data.split(":", 1)[1])
    except Exception:
        await cb.answer()
        return
    try:
        m_user = await cb.bot.get_chat_member(chat_id, cb.from_user.id)
        if getattr(m_user, "status", None) not in {"creator", "administrator"}:
            await cb.answer("غير مصرح")
            return
        if runtime.bot_id is not None:
            m_bot = await cb.bot.get_chat_member(chat_id, runtime.bot_id)
            if getattr(m_bot, "status", None) not in {"creator", "administrator"}:
                await cb.message.answer("يرجى رفع البوت كمشرف في الوجهة المختارة")
                await cb.answer()
                return
    except TelegramRetryAfter as e:
        await asyncio.sleep(getattr(e, "retry_after", 1))
        await cb.message.answer("يرجى المحاولة مرة أخرى")
        await cb.answer()
        return
    except (TelegramForbiddenError, TelegramBadRequest):
        await cb.message.answer("تعذر التحقق من الصلاحيات للوجهة المحددة")
        await cb.answer()
        return
    invite_link = None
    with suppress(Exception):
        inv = await cb.bot.create_chat_invite_link(chat_id=chat_id, creates_join_request=False)
        invite_link = getattr(inv, "invite_link", None)
    title = None
    async for session in get_async_session():
        rec = (
            await session.execute(select(BotChat).where(BotChat.chat_id == chat_id))
        ).scalar_one_or_none()
        if rec:
            title = rec.title
    if not title:
        with suppress(Exception):
            c = await cb.bot.get_chat(chat_id)
            title = getattr(c, "title", None)
    title = title or f"Chat {chat_id}"
    data = await state.get_data()
    gates = list(data.get("gate_channels", []))
    gates.append({"channel_id": chat_id, "channel_title": title, "invite_link": invite_link})
    await state.update_data(gate_channels=gates)
    await cb.message.answer("تمت إضافة الشرط ✅", reply_markup=gates_manage_kb(len(gates)))
    await cb.answer()


@roulette_router.callback_query(F.data.startswith("gate_remove:"))
async def gate_remove(cb: CallbackQuery, state: FSMContext) -> None:
    # remove gate by index
    try:
        idx = int(cb.data.split(":", 1)[1])
    except Exception:
        await cb.answer()
        return
    data = await state.get_data()
    gates = list(data.get("gate_channels", []))
    if 0 <= idx < len(gates):
        gates.pop(idx)
        await state.update_data(gate_channels=gates)
        await cb.message.edit_text("تم حذف القناة المحددة. يمكنك المتابعة أو إضافة قناة أخرى.")
        await cb.message.edit_reply_markup(reply_markup=gates_manage_kb(len(gates)))
        await cb.answer("تم الحذف")
    else:
        await cb.answer("مؤشر غير صالح")
    return


@roulette_router.callback_query(F.data == "pay_monthly")
async def pay_monthly(cb: CallbackQuery) -> None:
    from ..services import payments as _p

    price = await _p.get_monthly_price_stars()
    prices = [LabeledPrice(label="Premium Gate Access - Monthly", amount=price)]
    await cb.bot.send_invoice(
        chat_id=cb.from_user.id,
        title="ترقية ميزة قناة الشرط (شهري)",
        description="اشتراك لمدة 30 يوماً لميزة قنوات الشرط",
        payload="gate_monthly",
        currency="XTR",
        prices=prices,
    )
    await cb.answer()


@roulette_router.callback_query(F.data == "pay_onetime")
async def pay_onetime(cb: CallbackQuery) -> None:
    from ..services import payments as _p

    price = await _p.get_one_time_price_stars()
    prices = [LabeledPrice(label="Premium Gate Access - One Time", amount=price)]
    await cb.bot.send_invoice(
        chat_id=cb.from_user.id,
        title="ترقية ميزة قناة الشرط (مرة واحدة)",
        description="رصيد استخدام واحد لميزة قنوات الشرط",
        payload="gate_onetime",
        currency="XTR",
        prices=prices,
    )
    await cb.answer()


@roulette_router.pre_checkout_query()
async def pre_checkout(pcq: PreCheckoutQuery) -> None:
    # Approve checkout
    await pcq.bot.answer_pre_checkout_query(pcq.id, ok=True)


@roulette_router.message(F.successful_payment)
async def on_successful_payment(message: Message) -> None:
    sp = message.successful_payment
    if not sp:
        return
    payload = sp.invoice_payload
    amount = sp.total_amount
    currency = getattr(sp, "currency", "")
    if currency and currency.upper() != "XTR":
        await message.answer("تم الدفع بعملة غير مدعومة")
        return
    with suppress(Exception):
        await log_purchase(message.from_user.id, payload=payload, stars_amount=amount)
    from ..services import payments as _p

    m_price = await _p.get_monthly_price_stars()
    o_price = await _p.get_one_time_price_stars()
    # Free-tier safety: if configured 0, grant regardless of paid amount
    if payload == "gate_monthly" and m_price == 0:
        await message.answer("تم تفعيل اشتراك شهر لميزة قنوات الشرط ✅")
        with suppress(Exception):
            await grant_monthly(message.from_user.id)
        return
    if payload == "gate_onetime" and o_price == 0:
        await message.answer("تم إضافة رصيد استخدام واحد لميزة قنوات الشرط ✅")
        with suppress(Exception):
            await grant_one_time(message.from_user.id, credits=1)
        return
    if payload == "gate_monthly" and amount >= m_price:
        await grant_monthly(message.from_user.id)
        await message.answer("تم تفعيل اشتراك شهر لميزة قنوات الشرط ✅")
    elif payload == "gate_onetime" and amount >= o_price:
        await grant_one_time(message.from_user.id, credits=1)
        await message.answer("تم إضافة رصيد استخدام واحد لميزة قنوات الشرط ✅")
    else:
        await message.answer("تم الدفع لكن لم يمكن تحديد الحزمة، سيتم المراجعة يدوياً.")


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
        f"تأكيد إنشاء السحب بهذه البيانات:\nالنص:\n{styled}\nعدد الفائزين: {count}",
        reply_markup=confirm_cancel_kb(),
    )


@roulette_router.callback_query(F.data == "cancel_create")
async def cancel_create(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cb.message.answer("تم الإلغاء والعودة إلى البداية. استخدم /start للبدء من جديد.")
    await cb.answer()


@roulette_router.callback_query(F.data == "confirm_create")
async def confirm_create_cb(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    # Use channel chosen earlier in FSM; fallback to last linked if missing
    channel_id = int(data.get("channel_id") or 0)
    async for session in get_async_session():
        if not channel_id:
            # fallback to latest linked channel
            link = (
                (
                    await session.execute(
                        select(ChannelLink)
                        .where(ChannelLink.owner_id == cb.from_user.id)
                        .order_by(ChannelLink.id.desc())
                    )
                )
                .scalars()
                .first()
            )
            channel_id = link.channel_id if link else 0
        # Validate the selected channel/group belongs to the user
        valid = (
            await session.execute(
                select(ChannelLink).where(
                    (ChannelLink.owner_id == cb.from_user.id)
                    & (ChannelLink.channel_id == channel_id)
                )
            )
        ).scalar_one_or_none()
        if not valid or not channel_id:
            await cb.message.answer("تعذّر تحديد القناة المستهدفة. يرجى المحاولة من جديد.")
            await cb.answer()
            return
        gate_channels = list(data.get("gate_channels", []))
        # If gates are added, ensure entitlement but لا نخصم رصيد الاستخدام مرة واحدة الآن
        if gate_channels:
            allowed = await has_gate_access(cb.from_user.id, consume_one_time=False)
            if not allowed:
                await cb.message.answer(
                    "هذه الميزة تتطلب ترقية. يرجى شراء اشتراك شهري أو رصيد مرة واحدة ثم أعد المحاولة."
                )
                await cb.answer()
                return
        r = Roulette(
            owner_id=cb.from_user.id,
            channel_id=channel_id,
            text_raw=data["text_raw"],
            text_style=data["style"],
            winners_count=data["winners"],
            is_open=True,
        )
        session.add(r)
        await session.flush()
        # persist gates if any
        for g in gate_channels:
            session.add(
                RouletteGate(
                    roulette_id=r.id,
                    channel_id=g.get("channel_id"),
                    channel_title=g.get("channel_title") or "Gate",
                    invite_link=g.get("invite_link"),
                )
            )
        await session.flush()
        # prepare gate link buttons
        gate_rows = (
            (await session.execute(select(RouletteGate).where(RouletteGate.roulette_id == r.id)))
            .scalars()
            .all()
        )
        gate_links = []
        for g in gate_rows:
            if g.invite_link:
                gate_links.append((g.channel_title or "قناة الشرط", g.invite_link))
        post_text = _build_channel_post_text(r, participants_count=0)
        post = await cb.bot.send_message(
            r.channel_id,
            post_text,
            reply_markup=roulette_controls_kb(
                r.id, True, runtime.bot_username, gate_links, False
            ),
            parse_mode=ParseMode.HTML,
        )
        r.channel_message_id = post.message_id
        await session.commit()
        # بعد نشر السحب بنجاح: إن كان لدى المستخدم رصيد استخدام واحد، نخصمه الآن فقط
        if gate_channels:
            with suppress(Exception):
                await has_gate_access(cb.from_user.id, consume_one_time=True)
    # Send DM to owner with manage actions
    try:
        await cb.bot.send_message(
            cb.from_user.id,
            "تم إنشاء السحب. يمكنك إدارته من هنا:",
            reply_markup=manage_draw_kb(r.id),
        )
    except Exception:
        pass
    await state.clear()
    await cb.message.answer("تم نشر السحب في القناة.")
    await cb.answer()


@roulette_router.message(CreateRoulette.await_confirm)
async def confirm_help(message: Message) -> None:
    # تحسين: معالجة النص "تأكيد" كتأكيد فعلي
    if message.text and message.text.strip().lower() in ["تأكيد", "confirm", "ok", "نعم", "yes"]:
        # إرسال رسالة تأكيد واضحة
        await message.answer("✅ تم التأكيد! جاري إنشاء السحب...")
        # إرسال زر تأكيد للمستخدم
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        confirm_kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="تأكيد", callback_data="confirm_create")]]
        )
        await message.answer("يرجى الضغط على زر التأكيد أدناه:", reply_markup=confirm_kb)
    else:
        await message.answer("يرجى الضغط على زر 'تأكيد' أو كتابة 'تأكيد' للمتابعة.")


@roulette_router.callback_query(F.data.startswith("join:"))
async def join(cb: CallbackQuery) -> None:
    if not await _allow(cb.from_user.id, "join"):
        await cb.answer("رجاءً أعد المحاولة لاحقاً", show_alert=True)
        return
    roulette_id = int(cb.data.split(":", 1)[1])
    async for session in get_async_session():
        logger.info(f"join request uid={cb.from_user.id} rid={roulette_id}")
        r = (
            await session.execute(select(Roulette).where(Roulette.id == roulette_id))
        ).scalar_one_or_none()
        if not r or not r.is_open:
            await cb.answer("المشاركة مغلقة", show_alert=True)
            return
        # Ensure channel membership in main channel
        try:
            member = await cb.bot.get_chat_member(r.channel_id, cb.from_user.id)
            if getattr(member, "status", None) not in {"member", "creator", "administrator"}:
                raise TelegramForbiddenError(method="getChatMember", message="not subscribed")
        except TelegramRetryAfter as e:
            await asyncio.sleep(getattr(e, "retry_after", 1))
            await cb.answer("يرجى المحاولة مرة أخرى", show_alert=True)
            return
        except (TelegramForbiddenError, TelegramBadRequest):
            await cb.answer("يرجى الاشتراك في القناة للمشاركة", show_alert=True)
            return
        # Ensure gate channels membership
        gate_rows = (
            (await session.execute(select(RouletteGate).where(RouletteGate.roulette_id == r.id)))
            .scalars()
            .all()
        )
        for gate in gate_rows:
            # Prefer channel_id check; if absent, try username from invite link
            chat_id_for_check: Optional[str | int] = None
            if gate.channel_id:
                chat_id_for_check = gate.channel_id
            elif gate.invite_link:
                uname = _username_from_link(gate.invite_link)
                if uname:
                    chat_id_for_check = uname
            if chat_id_for_check is not None:
                try:
                    m2 = await cb.bot.get_chat_member(chat_id_for_check, cb.from_user.id)
                    if getattr(m2, "status", None) not in {"member", "creator", "administrator"}:
                        raise TelegramForbiddenError(
                            method="getChatMember", message="not subscribed gate"
                        )
                except TelegramRetryAfter as e:
                    await asyncio.sleep(getattr(e, "retry_after", 1))
                    await cb.answer("يرجى الاشتراك في قنوات الشرط ثم المحاولة", show_alert=True)
                    return
                except (TelegramForbiddenError, TelegramBadRequest):
                    await cb.answer("يرجى الاشتراك في قنوات الشرط للمشاركة", show_alert=True)
                    return
        # Idempotent join
        existing = (
            await session.execute(
                select(Participant).where(
                    Participant.roulette_id == r.id, Participant.user_id == cb.from_user.id
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            try:
                session.add(Participant(roulette_id=r.id, user_id=cb.from_user.id))
                await session.commit()
            except IntegrityError:
                await session.rollback()
        # Always recalc count
        count = (
            await session.execute(
                select(func.count()).select_from(Participant).where(Participant.roulette_id == r.id)
            )
        ).scalar_one()
        logger.info(f"join success uid={cb.from_user.id} rid={r.id} participants={count}")
        # include gate links, if any, and try to update channel message
        with suppress(TelegramBadRequest, TelegramForbiddenError):
            gate_rows2 = (
                (
                    await session.execute(
                        select(RouletteGate).where(RouletteGate.roulette_id == r.id)
                    )
                )
                .scalars()
                .all()
            )
            gate_links2 = [
                (g.channel_title or "قناة الشرط", g.invite_link)
                for g in gate_rows2
                if g.invite_link
            ]
            text_rendered = _build_channel_post_text(r, participants_count=count)
            await cb.bot.edit_message_text(
                chat_id=r.channel_id,
                message_id=r.channel_message_id,
                text=text_rendered,
                reply_markup=roulette_controls_kb(
                    r.id, r.is_open, runtime.bot_username, gate_links2, False
                ),
                parse_mode=ParseMode.HTML,
            )
    await cb.answer("تم الانضمام")


@roulette_router.callback_query(F.data.startswith("pause:"))
async def pause(cb: CallbackQuery) -> None:
    if not await _allow(cb.from_user.id, "pause"):
        await cb.answer("رجاءً أعد المحاولة لاحقاً", show_alert=True)
        return
    roulette_id = int(cb.data.split(":", 1)[1])
    async for session in get_async_session():
        r = (
            await session.execute(select(Roulette).where(Roulette.id == roulette_id))
        ).scalar_one_or_none()
        if not r or not (
            r.owner_id == cb.from_user.id
            or (await _is_admin_in_channel(cb.bot, r.channel_id, cb.from_user.id))
        ):
            await cb.answer("غير مصرح", show_alert=True)
            return
        logger.info(f"pause requested by uid={cb.from_user.id} rid={r.id}")
        r.is_open = False
        await session.commit()
        with suppress(TelegramBadRequest, TelegramForbiddenError):
            from ..db.models import RouletteGate as RG1  # local import to avoid cycle in type hints

            rows = (
                (await session.execute(select(RG1).where(RG1.roulette_id == r.id))).scalars().all()
            )
            links = [
                (g.channel_title or "قناة الشرط", g.invite_link) for g in rows if g.invite_link
            ]
            # recalc count for display
            count = (
                await session.execute(
                    select(func.count())
                    .select_from(Participant)
                    .where(Participant.roulette_id == r.id)
                )
            ).scalar_one()
            text_rendered = _build_channel_post_text(r, participants_count=count)
            logger.info(f"pause updated rid={r.id} participants={count}")
            await cb.bot.edit_message_text(
                chat_id=r.channel_id,
                message_id=r.channel_message_id,
                text=text_rendered,
                reply_markup=roulette_controls_kb(
                    r.id, r.is_open, runtime.bot_username, links, False
                ),
                parse_mode=ParseMode.HTML,
            )
    await cb.answer("تم الإيقاف")


@roulette_router.callback_query(F.data.startswith("resume:"))
async def resume(cb: CallbackQuery) -> None:
    if not await _allow(cb.from_user.id, "resume"):
        await cb.answer("رجاءً أعد المحاولة لاحقاً", show_alert=True)
        return
    roulette_id = int(cb.data.split(":", 1)[1])
    async for session in get_async_session():
        r = (
            await session.execute(select(Roulette).where(Roulette.id == roulette_id))
        ).scalar_one_or_none()
        if not r or not (
            r.owner_id == cb.from_user.id
            or (await _is_admin_in_channel(cb.bot, r.channel_id, cb.from_user.id))
        ):
            await cb.answer("غير مصرح", show_alert=True)
            return
        logger.info(f"resume requested by uid={cb.from_user.id} rid={r.id}")
        r.is_open = True
        await session.commit()
        with suppress(TelegramBadRequest, TelegramForbiddenError):
            from ..db.models import RouletteGate as RG2

            rows = (
                (await session.execute(select(RG2).where(RG2.roulette_id == r.id))).scalars().all()
            )
            links = [
                (g.channel_title or "قناة الشرط", g.invite_link) for g in rows if g.invite_link
            ]
            # recalc count for display
            count = (
                await session.execute(
                    select(func.count())
                    .select_from(Participant)
                    .where(Participant.roulette_id == r.id)
                )
            ).scalar_one()
            text_rendered = _build_channel_post_text(r, participants_count=count)
            logger.info(f"resume updated rid={r.id} participants={count}")
            await cb.bot.edit_message_text(
                chat_id=r.channel_id,
                message_id=r.channel_message_id,
                text=text_rendered,
                reply_markup=roulette_controls_kb(
                    r.id, r.is_open, runtime.bot_username, links, False
                ),
                parse_mode=ParseMode.HTML,
            )
    await cb.answer("تم الاستئناف")


@roulette_router.callback_query(F.data.startswith("draw:"))
async def draw(cb: CallbackQuery) -> None:
    if not await _allow(cb.from_user.id, "draw"):
        await cb.answer("رجاءً أعد المحاولة لاحقاً", show_alert=True)
        return
    roulette_id = int(cb.data.split(":", 1)[1])
    async for session in get_async_session():
        # ملخص: يمنع البدء المتعدد المتزامن عبر قفل بسيط داخل العملية.
        lock_key = f"draw_lock:{roulette_id}"
        if _inproc_locks.get(lock_key):
            await cb.answer("⏳ السحب قيد التنفيذ حالياً، يرجى الانتظار حتى يكتمل إعلان الفائزين.", show_alert=True)
            return
        _inproc_locks[lock_key] = True
        try:
            r = (
                await session.execute(select(Roulette).where(Roulette.id == roulette_id))
            ).scalar_one_or_none()
            if not r:
                await cb.answer("السحب غير موجود", show_alert=True)
                return
            # قفل على مستوى قاعدة البيانات لمنع البدء المتكرر عبر عمليات متعددة
            from sqlalchemy.exc import IntegrityError as _SAIntegrityError
            from ..db.models import AppSetting as _AppSetting
            db_lock_key = f"draw:in_progress:{r.id}"
            try:
                session.add(_AppSetting(key=db_lock_key, value="1"))
                await session.commit()
            except _SAIntegrityError:
                # قفل موجود بالفعل => يوجد سحب جارٍ
                await session.rollback()
                await cb.answer("⏳ السحب قيد التنفيذ حالياً، يرجى الانتظار حتى يكتمل إعلان الفائزين.", show_alert=True)
                return
            # authorize: owner or channel admin
            authorized = (r.owner_id == cb.from_user.id) or (
                await _is_admin_in_channel(cb.bot, r.channel_id, cb.from_user.id)
            )
            if not authorized:
                await cb.answer("غير مصرح", show_alert=True)
                return
            # require participation to be stopped first
            if r.is_open:
                await cb.answer("⏸️ يرجى إيقاف المشاركة أولاً ثم ابدأ السحب.", show_alert=True)
                return
            # تحسين: فحص إضافي في قاعدة البيانات لمنع السحب المتعدد
            if r.closed_at is not None:
                await cb.answer("✅ تم إجراء السحب مسبقاً لهذا الروليت.", show_alert=True)
                return
            
            # تحسين: فحص إضافي للتأكد من أن السحب لم يتم إجراؤه في عملية أخرى
            if hasattr(r, '_draw_in_progress') and r._draw_in_progress:
                await cb.answer("🔄 السحب قيد التنفيذ حالياً، يرجى الانتظار.", show_alert=True)
                return
            
            # تحسين: فحص إضافي في قاعدة البيانات للتأكد من عدم وجود سحب متزامن
            existing_draw = await session.execute(
                select(Roulette).where(
                    Roulette.id == r.id,
                    Roulette.closed_at.is_not(None)
                )
            )
            if existing_draw.scalar_one_or_none():
                await cb.answer("✅ تم إجراء السحب مسبقاً لهذا الروليت.", show_alert=True)
                return
            # Ensure there are participants
            rows = (
                await session.execute(
                    select(Participant.user_id).where(Participant.roulette_id == r.id)
                )
            ).scalars().all()
            if len(rows) == 0:
                await cb.answer("👥 لا يوجد أي مشاركين بعد", show_alert=True)
                return
            # Countdown message as a reply to the original post
            prep = None
            prep_text = "سنعلن الفائزين خلال 30 ثانية — استعدوا!"
            with suppress(TelegramBadRequest, TelegramForbiddenError):
                prep = await cb.bot.send_message(
                    r.channel_id, prep_text, reply_to_message_id=r.channel_message_id
                )
                # countdown updates every 5 seconds
                for remaining in [25, 20, 15, 10, 5, 0]:
                    try:
                        await asyncio.sleep(5)
                        if prep is None:
                            break
                        await cb.bot.edit_message_text(
                            chat_id=r.channel_id,
                            message_id=prep.message_id,
                            text=f"سنعلن الفائزين خلال {remaining} ثانية — ترقّبوا!",
                        )
                    except TelegramRetryAfter as e:
                        await asyncio.sleep(getattr(e, "retry_after", 1))
                    except (TelegramBadRequest, TelegramForbiddenError):
                        break
            # Compute winners
            winners_ids = draw_unique(rows, r.winners_count)
            logger.info(f"draw computed winners rid={r.id} winners_count={len(winners_ids)}")
            winners_lines = []
            for idx, uid in enumerate(winners_ids, start=1):
                # Prefer full name for display, fallback to @username, else generic
                display_name = "الفائز"
                link = f"tg://user?id={uid}"
                with suppress(Exception):
                    u = await cb.bot.get_chat(uid)
                    uname = getattr(u, "username", None)
                    first = getattr(u, "first_name", None) or ""
                    last = getattr(u, "last_name", None) or ""
                    fullname = (first + " " + last).strip()
                    if fullname:
                        display_name = fullname
                    elif uname:
                        display_name = f"@{uname}"
                    if uname:
                        link = f"https://t.me/{uname}"
                # HTML anchor with escaped display name
                winners_lines.append(f'{idx}. <a href="{link}">{escape(display_name)}</a>')
            announce_text = (
                "تم إعلان نتائج السحب\n\n"
                + "\n".join(winners_lines)
                + "\n\nلبقية المشاركين الذين لم يحالفهم الحظ: حظاً أوفر ونتمنى لكم التوفيق في السحوبات القادمة — ترقّبوا!"
            )
            # Notify winners (best-effort) with channel details
            channel_title, channel_link = await _get_channel_title_and_link(cb.bot, r.channel_id)
            logger.info(
                f"notify winners for roulette {r.id}: title={channel_title}, link={channel_link}"
            )
            # تحسين: إرسال الإشعارات للفائزين مع فحص إضافي
            for uid in winners_ids:
                try:
                    # ملاحظة: لا حاجة لجلب معلومات المستخدم هنا؛ سنرسل مباشرة
                    # بناء رسالة الإشعار
                    if channel_link:
                        msg = (
                            f"🎉 تهانينا! لقد فزت في السحب رقم {r.id}\n\n"
                            f"📺 اسم قناة السحب: {escape(channel_title)}\n"
                            f"🔗 رابط القناة: <a href='{channel_link}'>{escape(channel_title)}</a>\n\n"
                            f"💫 نتمنى لك التوفيق! 🎊"
                        )
                    else:
                        msg = (
                            f"🎉 تهانينا! لقد فزت في السحب رقم {r.id}\n\n"
                            f"📺 اسم قناة السحب: {escape(channel_title)}\n"
                            f"🔗 رابط القناة: غير متاح\n\n"
                            f"💫 نتمنى لك التوفيق! 🎊"
                        )
                    
                    # محاولة إرسال الإشعار مع معالجة أفضل للأخطاء
                    try:
                        await cb.bot.send_message(
                            uid, msg, parse_mode=ParseMode.HTML, disable_web_page_preview=True
                        )
                        logger.info(f"winner notified successfully uid={uid} for roulette {r.id}")
                    except TelegramForbiddenError:
                        logger.warning(f"user blocked bot uid={uid} rid={r.id}")
                    except TelegramBadRequest as e:
                        if "user not found" in str(e).lower():
                            logger.warning(f"user not found uid={uid} rid={r.id}")
                        else:
                            logger.warning(f"telegram error for uid={uid} rid={r.id}: {e}")
                    except Exception as e:
                        logger.warning(f"unexpected error notifying uid={uid} rid={r.id}: {e}")
                        
                except Exception as e:
                    logger.warning(f"notify winner failed uid={uid} rid={r.id}: {e}")
            # Post announcement: edit countdown message if exists; otherwise update original post
            with suppress(TelegramBadRequest, TelegramForbiddenError):
                if prep is not None:
                    try:
                        await cb.bot.edit_message_text(
                            chat_id=r.channel_id,
                            message_id=prep.message_id,
                            text=announce_text,
                            parse_mode=ParseMode.HTML,
                        )
                    except Exception:
                        # fallback to editing original post
                        await cb.bot.edit_message_text(
                            chat_id=r.channel_id,
                            message_id=r.channel_message_id,
                            text=announce_text,
                            reply_markup=roulette_controls_kb(
                                r.id, r.is_open, runtime.bot_username, [], False
                            ),
                            parse_mode=ParseMode.HTML,
                        )
                else:
                    await cb.bot.edit_message_text(
                        chat_id=r.channel_id,
                        message_id=r.channel_message_id,
                        text=announce_text,
                        reply_markup=roulette_controls_kb(
                            r.id, r.is_open, runtime.bot_username, [], False
                        ),
                        parse_mode=ParseMode.HTML,
                    )
                # Notify owner about successful start
                with suppress(Exception):
                    await cb.bot.send_message(r.owner_id, f"تم بدء السحب رقم {r.id} بنجاح.")
                            # Mark closed time and update status
            r.closed_at = r.closed_at or datetime.utcnow()
            # تحسين: تحديث حالة السحب لمنع السحب المتعدد
            r.is_open = False  # إغلاق السحب نهائياً بعد إعلان الفائزين
            await session.commit()
        finally:
            # إزالة الأقفال
            _inproc_locks.pop(lock_key, None)
            with suppress(Exception):
                from sqlalchemy import delete as _sqldelete
                from ..db.models import AppSetting as _AppSetting2
                await session.execute(
                    _sqldelete(_AppSetting2).where(_AppSetting2.key == f"draw:in_progress:{roulette_id}")
                )
                await session.commit()
        await cb.answer("🎉 تم السحب وإعلان الفائزين بنجاح!")


@roulette_router.callback_query(F.data == "notify_me")
async def notify_me(cb: CallbackQuery) -> None:
    await cb.message.answer(f"لفتح الخاص والاشتراك، راسلني هنا: @{runtime.bot_username}")
    await cb.answer()


@roulette_router.message(StateFilter(None), Command("notify"))
async def enable_notify(message: Message) -> None:
    # user enables notification for the last created roulette in the channel context — simplified
    async for session in get_async_session():
        last = (
            (
                await session.execute(
                    select(Roulette)
                    .where(Roulette.owner_id == message.from_user.id)
                    .order_by(Roulette.id.desc())
                )
            )
            .scalars()
            .first()
        )
        if last:
            exists = (
                await session.execute(
                    select(Notification).where(
                        Notification.user_id == message.from_user.id,
                        Notification.roulette_id == last.id,
                    )
                )
            ).scalar_one_or_none()
            if not exists:
                session.add(Notification(user_id=message.from_user.id, roulette_id=last.id))
                await session.commit()
            await message.answer("سيتم تنبيهك إن فزت")
        else:
            await message.answer("لا يوجد سحب متعلق")
