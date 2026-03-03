from __future__ import annotations

import asyncio
import logging
import secrets
from contextlib import suppress
from datetime import datetime, timezone
from typing import Optional

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy import delete, select

from ..config import settings
from ..db import get_async_session
from ..db.models import (
    ChannelLink,
    Contest,
    ContestEntry,
    ContestType,
    RouletteGate,
    VoteMode,
)
from ..db.repositories import (
    AppSettingRepository,
    ContestEntryRepository,
    ContestRepository,
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
from ..keyboards.settings import roulette_settings_kb
from ..services.antibot import AntiBotService
from ..services.context import runtime
from ..services.formatting import StyledText, parse_style_from_text
from ..services.ratelimit import get_rate_limiter
from ..services.subscription import SubscriptionService
from ..utils.compat import safe_answer, safe_edit_markup, safe_edit_text

# ملخص: أقفال داخلية بسيطة لمنع تنفيذ متزامن لنفس العملية (داخل العملية فقط).
_inproc_locks: dict[str, bool] = {}

roulette_router = Router(name="roulette")


class CreateRoulette(StatesGroup):
    await_channel = State()
    await_text = State()
    await_gate_choice = State()
    await_winners = State()
    await_vote_mode = State()
    await_star_ratio = State()
    await_settings = State()
    await_confirm = State()
    await_gate_target = State()

    # Quiz Specific
    await_quiz_questions_count = State()
    await_quiz_interval = State()

    # Advanced Gates
    await_gate_contest_selection = State()


class RouletteFlow(StatesGroup):
    await_antibot = State()


async def _allow(user_id: int, action: str, max_calls: int = 3, period_seconds: int = 5) -> bool:
    limiter = get_rate_limiter(runtime.redis)
    return await limiter.allow(f"{user_id}:{action}", max_calls, period_seconds)


# ===== Helpers =====


def _build_channel_post_text(c: Contest, participants_count: int) -> str:
    """Compose channel post text with styling, status line, and participants count."""
    styled = StyledText(c.text_raw, c.text_style).render()
    status_line = (
        "🟢 <b>المشاركة متاحة حالياً</b>" if c.is_open else "🔴 <b>المشاركة متوقفة حالياً</b>"
    )

    if c.type == ContestType.VOTE:
        type_label = "🗳 مسابقة تصويت"
    elif c.type == ContestType.QUIZ:
        type_label = "🧠 مسابقة ثقافية"
    elif c.type == ContestType.YASTAHIQ:
        type_label = "🔥 مسابقة يستحق"
    else:
        type_label = "🎰 سحب عشوائي"

    return f"{type_label}\n\n{styled}\n\n{status_line}\n👥 عدد المشاركين: {participants_count}"


async def _get_channel_title_and_link(bot, chat_id: int) -> tuple[str, Optional[str]]:
    try:
        chat = await bot.get_chat(chat_id)
        title = chat.title or "قناة غير معروفة"
        link = chat.invite_link
        if not link and chat.username:
            link = f"https://t.me/{chat.username}"
        return title, link
    except Exception:
        return "قناة غير معروفة", None


def _parse_int_strict(text: str) -> Optional[int]:
    try:
        return int(text.strip())
    except (ValueError, AttributeError):
        return None


async def start_create_flow(cb: CallbackQuery, state: FSMContext, ctype: ContestType) -> None:
    if not await _allow(cb.from_user.id, "create"):
        await cb.answer("⚠️ رجاءً أعد المحاولة لاحقاً", show_alert=True)
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
            await cb.message.answer("⚠️ يرجى أولاً ربط قناة عبر قسم 'حسابي'.")
            await cb.answer()
            return

        await state.clear()
        await state.update_data(contest_type=ctype.value)

        if len(links) > 1:
            from ..keyboards.channel import select_channel_kb

            items = []
            for link in links:
                items.append((link.channel_id, link.channel_title or f"Chat {link.channel_id}"))
            await state.set_state(CreateRoulette.await_channel)
            await safe_edit_text(cb.message,
                "📋 اختر القناة التي تريد نشر الفعالية فيها:", reply_markup=select_channel_kb(items)
            )
        else:
            channel_id = links[0].channel_id
            await state.update_data(channel_id=channel_id)
            await state.set_state(CreateRoulette.await_text)
            await safe_edit_text(cb.message,
                "📝 أرسل نص كليشة المسابقة.\nمثال الأنماط: #عريض نص #عريض أو #تشويش نص #تشويش",
                reply_markup=back_kb(),
            )
        await cb.answer()


# ===== Handlers =====


@roulette_router.callback_query(F.data == "link_channel")
async def link_channel(cb: CallbackQuery) -> None:
    bot_username = runtime.bot_username or "your_bot"
    text = (
        "🔗 للاستفادة من ميزات البوت، يرجى اتباع الخطوات التالية:\n\n"
        f"1️⃣ أضف البوت @{bot_username} كمشرف في قناتك.\n"
        "2️⃣ قم بإعادة توجيه أي رسالة من قناتك إلى البوت.\n\n"
        "📌 ملاحظة:\n"
        "جميع المشرفين الآخرين في القناة سيتمكنون أيضًا من استخدام البوت بعد إضافته."
    )
    await cb.message.answer(text, reply_markup=link_instruction_kb(bot_username))
    await cb.answer()


@roulette_router.callback_query(F.data == "unlink_channel")
async def unlink_channel(cb: CallbackQuery) -> None:
    if not await _allow(cb.from_user.id, "unlink"):
        await cb.answer("⚠️ رجاءً أعد المحاولة لاحقاً", show_alert=True)
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
            await cb.message.answer("⚠️ لا توجد قنوات أو مجموعات مرتبطة حالياً.")
            await cb.answer()
            return
        rows = []
        for link in links:
            label = link.channel_title or str(link.channel_id)
            rows.append(
                [InlineKeyboardButton(text=label, callback_data=f"unlinkch:{link.channel_id}")]
            )
        rows.append([InlineKeyboardButton(text="🔙 رجوع", callback_data="back")])
        kb = InlineKeyboardMarkup(inline_keyboard=rows)
        await cb.message.answer("🗑️ اختر القناة المراد فك ارتباطها:", reply_markup=kb)
        await cb.answer()


@roulette_router.callback_query(F.data.startswith("unlinkch:"))
async def unlink_channel_apply(cb: CallbackQuery) -> None:
    chat_id = int(cb.data.split(":")[1])
    async for session in get_async_session():
        await session.execute(
            delete(ChannelLink).where(
                (ChannelLink.owner_id == cb.from_user.id) & (ChannelLink.channel_id == chat_id)
            )
        )
        await session.commit()
    await safe_edit_text(cb.message, "✅ تم فك ارتباط القناة بنجاح.")
    await cb.answer()


@roulette_router.message(F.forward_from_chat)
async def handle_forwarded_channel(message: Message) -> None:
    chat = message.forward_from_chat
    if not chat or chat.type != "channel":
        await message.answer("⚠️ يرجى إعادة توجيه رسالة من قناة عامة.")
        return

    # Check if user is admin in that channel
    try:
        member = await message.bot.get_chat_member(chat.id, message.from_user.id)
        if member.status not in ["administrator", "creator"]:
            await message.answer("❌ يجب أن تكون مشرفاً في القناة لربطها.")
            return
    except Exception:
        await message.answer("❌ تعذر التحقق من صلاحياتك في القناة. تأكد من إضافة البوت كمشرف.")
        return

    # Check if bot is admin
    try:
        me = await message.bot.get_chat_member(chat.id, runtime.bot_id)
        if me.status not in ["administrator"]:
            await message.answer("❌ يجب إضافة البوت كمشرف في القناة أولاً.")
            return
    except Exception:
        await message.answer("❌ تعذر التحقق من وجود البوت كمشرف في القناة.")
        return

    async for session in get_async_session():
        # Check if already linked
        stmt = select(ChannelLink).where(
            (ChannelLink.owner_id == message.from_user.id) & (ChannelLink.channel_id == chat.id)
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing:
            await message.answer("✅ هذه القناة مرتبطة بالفعل بحسابك.")
            return

        new_link = ChannelLink(
            owner_id=message.from_user.id, channel_id=chat.id, channel_title=chat.title
        )
        session.add(new_link)
        await session.commit()
        await message.answer(f"✅ تم ربط القناة بنجاح: {chat.title}")


@roulette_router.message(F.text.startswith("https://t.me/"))
async def handle_link_text(message: Message) -> None:
    # Basic support for joining by link if public
    url = message.text.strip()
    username = url.split("/")[-1]
    if not username or username.startswith("+"):
        return  # skip private links here

    try:
        chat = await message.bot.get_chat(f"@{username}")
        if chat.type != "channel":
            return
        # Reuse logic from forward handler
        message.forward_from_chat = chat
        await handle_forwarded_channel(message)
    except Exception:
        pass


@roulette_router.callback_query(F.data == "create_roulette")
async def legacy_start_create(cb: CallbackQuery, state: FSMContext) -> None:
    await start_create_flow(cb, state, ContestType.ROULETTE)


@roulette_router.callback_query(F.data.startswith("select_channel:"))
async def select_channel(cb: CallbackQuery, state: FSMContext) -> None:
    chat_id = int(cb.data.split(":")[1])
    await state.update_data(channel_id=chat_id)
    await state.set_state(CreateRoulette.await_text)
    await safe_edit_text(cb.message,
        "📝 أرسل نص كليشة المسابقة.\nمثال الأنماط: #عريض نص #عريض أو #تشويش نص #تشويش",
        reply_markup=back_kb(),
    )
    await cb.answer()


@roulette_router.callback_query(F.data == "back")
async def go_back(cb: CallbackQuery, state: FSMContext) -> None:
    cur = await state.get_state()
    if cur == CreateRoulette.await_text:
        await state.clear()
        from .sections import section_roulette

        await section_roulette(cb)
    elif cur == CreateRoulette.await_gate_choice:
        await state.set_state(CreateRoulette.await_text)
        await safe_edit_text(cb.message, "📝 أرسل نص كليشة المسابقة:", reply_markup=back_kb())
    elif cur == CreateRoulette.await_winners:
        await state.set_state(CreateRoulette.await_gate_choice)
        await safe_edit_text(cb.message, "🛡️ هل تريد إضافة شروط انضمام؟", reply_markup=gate_choice_kb())
    elif cur == CreateRoulette.await_settings:
        await state.set_state(CreateRoulette.await_winners)
        await safe_edit_text(cb.message, "🏆 كم عدد الفائزين المطلوب؟ (أرسل رقماً بين 1 و 100):")
    else:
        await state.clear()
        from .sections import back_to_main

        await back_to_main(cb)
    await cb.answer()


@roulette_router.message(CreateRoulette.await_text)
async def collect_text(message: Message, state: FSMContext) -> None:
    raw = (message.text or message.caption or "").strip()
    if not raw:
        await message.answer("⚠️ يرجى إرسال نص صالح.")
        return

    text, style = parse_style_from_text(raw)
    await state.update_data(text_raw=text, style=style)
    await state.set_state(CreateRoulette.await_gate_choice)
    await message.answer("🛡️ هل تريد إضافة شروط انضمام؟", reply_markup=gate_choice_kb())


@roulette_router.callback_query(F.data == "gate_skip")
async def gate_skip(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    ctype = data.get("contest_type")

    if ctype == ContestType.VOTE.value:
        await state.set_state(CreateRoulette.await_vote_mode)
        from ..keyboards.voting import vote_mode_kb

        await safe_edit_text(cb.message, "🗳 اختر نوع التصويت المطلوب:", reply_markup=vote_mode_kb())
    elif ctype == ContestType.QUIZ.value:
        await state.set_state(CreateRoulette.await_quiz_questions_count)
        await safe_edit_text(cb.message, "❓ كم عدد الأسئلة المطلوب طرحها؟ (أرسل رقماً):")
    else:
        await state.set_state(CreateRoulette.await_winners)
        await safe_edit_text(cb.message, "🏆 كم عدد الفائزين المطلوب؟ (أرسل رقماً بين 1 و 100):")
    await cb.answer()


@roulette_router.callback_query(F.data == "gate_add")
async def gate_add(cb: CallbackQuery, state: FSMContext) -> None:
    await safe_edit_text(cb.message, "🛡️ اختر نوع الشرط المراد إضافته:", reply_markup=gate_add_menu_kb())
    await cb.answer()


@roulette_router.callback_query(F.data.startswith("gate_type:"))
async def gate_type_select(cb: CallbackQuery, state: FSMContext) -> None:
    gtype = cb.data.split(":")[1]
    await state.update_data(gate_type=gtype)

    if gtype == "channel" or gtype == "group":
        await state.set_state(CreateRoulette.await_gate_target)
        if gtype == "channel":
            text = (
                "📢 لإضافة قناة كشرط:\n"
                "1. أضف البوت مشرفاً فيها.\n"
                "2. أرسل رابطها العام أو قم بتوجيه رسالة منها هنا."
            )
        else:
            text = "👥 لإضافة مجموعة كشرط، يرجى إرسال الـ ID الخاص بها أو توجيه رسالة منها هنا."

        from ..db.models import BotChat

        async for session in get_async_session():
            stmt = select(BotChat).where(BotChat.removed_at.is_(None))
            if gtype == "channel":
                stmt = stmt.where(BotChat.chat_type == "channel")
            else:
                stmt = stmt.where(BotChat.chat_type.in_(["group", "supergroup"]))

            links = (await session.execute(stmt)).scalars().all()
            if not links:
                await safe_edit_text(cb.message, text, reply_markup=back_kb())
                return

            await state.update_data(sub_view="gate_pick")
            items = [(link.channel_id, link.channel_title) for link in links]
            await safe_edit_text(cb.message, "📋 اختر من قنواتك المرتبطة:", reply_markup=gate_pick_list_kb(items))

    elif gtype == "yastahiq":
        await state.update_data(sub_view="gate_sel_yastahiq")
        from ..db.models import BotChat

        async for session in get_async_session():
            links = (
                (
                    await session.execute(
                        select(BotChat).where(
                            (BotChat.chat_type.in_(["group", "supergroup"]))
                            & (BotChat.removed_at.is_(None))
                        )
                    )
                )
                .scalars()
                .all()
            )
            if not links:
                await cb.answer("⚠️ يجب ربط مجموعة أولاً لاستخدام شرط يستحق.", show_alert=True)
                return

            rows = []
            for link in links:
                rows.append(
                    [
                        InlineKeyboardButton(
                            text=link.channel_title or str(link.channel_id),
                            callback_data=f"gate_sel_yastahiq:{link.channel_id}",
                        )
                    ]
                )
            rows.append([InlineKeyboardButton(text="🔙 رجوع", callback_data="back")])
            await safe_edit_text(cb.message,
                "📋 اختر المجموعة التي يجب أن يمتلك فيها المستخدم نقاط تفاعل:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
            )

    elif gtype == "vote" or gtype == "contest":
        await state.update_data(sub_view=f"gate_add_{gtype}")
        async for session in get_async_session():
            stmt = select(Contest).where(Contest.is_open.is_(True))
            if gtype == "vote":
                stmt = stmt.where(Contest.type == ContestType.VOTE)
            else:
                stmt = stmt.where(Contest.type == ContestType.ROULETTE)

            contests = (await session.execute(stmt)).scalars().all()
            if not contests:
                await cb.answer(
                    f"⚠️ لا توجد مسابقات {'تصويت' if gtype == 'vote' else 'روليت'} نشطة حالياً لاستخدامها كشرط.",
                    show_alert=True,
                )
                return

            rows = []
            for c in contests:
                rows.append(
                    [
                        InlineKeyboardButton(
                            text=f"#{c.id} - {c.text_raw[:20]}...",
                            callback_data=f"gate_sel_evt:{gtype}:{c.id}",
                        )
                    ]
                )
            rows.append([InlineKeyboardButton(text="🔙 رجوع", callback_data="back")])
            await safe_edit_text(cb.message,
                f"📋 اختر مسابقة الـ {'تصويت' if gtype == 'vote' else 'روليت'} المطلوبة:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
            )

    await cb.answer()


@roulette_router.callback_query(F.data.startswith("gate_sel_yastahiq:"))
async def gate_yastahiq_selection(cb: CallbackQuery, state: FSMContext) -> None:
    group_id = int(cb.data.split(":")[1])
    async for session in get_async_session():
        stmt = select(Contest).where(
            (Contest.channel_id == group_id)
            & (Contest.type == ContestType.YASTAHIQ)
            & (Contest.is_open.is_(True))
        )
        c = (await session.execute(stmt)).scalar_one_or_none()
        if not c:
            await cb.answer("⚠️ لا توجد مسابقة يستحق نشطة في هذه المجموعة حالياً.", show_alert=True)
            return

        title = "شرط تفاعل مجموعة"
        with suppress(Exception):
            chat = await cb.bot.get_chat(group_id)
            title = chat.title

        data = await state.get_data()
        gates = list(data.get("gate_channels", []))
        gates.append({"type": "yastahiq", "id": c.id, "title": title, "link": None})
        await state.update_data(gate_channels=gates)

    from ..keyboards.common import gates_manage_kb

    await safe_edit_text(cb.message, "🛡️ تم إضافة الشرط بنجاح!", reply_markup=gates_manage_kb(len(gates)))
    await cb.answer()


@roulette_router.callback_query(F.data.startswith("gate_sel_evt:"))
async def gate_event_selection(cb: CallbackQuery, state: FSMContext) -> None:
    parts = cb.data.split(":")
    gtype = parts[1]
    cid = int(parts[2])

    if gtype == "vote":
        await state.update_data(gate_target_id=cid)
        await state.set_state(CreateRoulette.await_gate_target)
        await safe_edit_text(cb.message, "🆔 يرجى إرسال 'رمز المتسابق' الذي يجب التصويت له:")
    else:
        data = await state.get_data()
        gates = list(data.get("gate_channels", []))
        gates.append({"type": "contest", "id": cid, "title": f"مسابقة روليت #{cid}", "link": None})
        await state.update_data(gate_channels=gates)
        from ..keyboards.common import gates_manage_kb

        await safe_edit_text(cb.message,
            "🛡️ تم إضافة الشرط بنجاح!", reply_markup=gates_manage_kb(len(gates))
        )

    await cb.answer()


@roulette_router.message(CreateRoulette.await_gate_target)
async def collect_gate_target_code(message: Message, state: FSMContext) -> None:
    code = (message.text or "").strip().upper()
    data = await state.get_data()
    cid = data.get("gate_target_id")
    gates = list(data.get("gate_channels", []))

    gates.append({"type": "vote", "id": cid, "code": code, "title": f"تصويت لـ {code}"})
    await state.update_data(gate_channels=gates)

    from ..keyboards.common import gates_manage_kb

    await message.answer("🛡️ تم إضافة الشرط بنجاح!", reply_markup=gates_manage_kb(len(gates)))


@roulette_router.callback_query(F.data.startswith("gate_pick_apply:"))
async def gate_pick_apply(cb: CallbackQuery, state: FSMContext) -> None:
    chat_id = int(cb.data.split(":")[1])
    data = await state.get_data()
    gtype = data.get("gate_type", "channel")

    title, link = await _get_channel_title_and_link(cb.bot, chat_id)
    if not link:
        # try creating invite link
        try:
            invite = await cb.bot.create_chat_invite_link(chat_id)
            link = invite.invite_link
        except Exception:
            link = None

    gates = list(data.get("gate_channels", []))
    gates.append({"type": gtype, "id": chat_id, "title": title, "link": link})
    await state.update_data(gate_channels=gates)

    from ..keyboards.common import gates_manage_kb

    await safe_edit_text(cb.message, "🛡️ تم إضافة الشرط بنجاح!", reply_markup=gates_manage_kb(len(gates)))
    await cb.answer()


@roulette_router.message(CreateRoulette.await_gate_target)
async def handle_gate_input(message: Message, state: FSMContext) -> None:
    # Logic for manual link input if needed
    pass


@roulette_router.callback_query(F.data == "gate_done")
async def gate_next(cb: CallbackQuery, state: FSMContext) -> None:
    await gate_skip(cb, state)


@roulette_router.callback_query(F.data.startswith("vmode_"))
async def collect_vote_mode(cb: CallbackQuery, state: FSMContext) -> None:
    mode = cb.data.replace("vmode_", "")
    await state.update_data(vote_mode=mode)
    if mode in ["stars", "both"]:
        from ..keyboards.voting import star_ratio_kb

        await safe_edit_text(cb.message, "⚖️ اختر معدل (نجمة مقابل أصوات):", reply_markup=star_ratio_kb())
    else:
        await state.set_state(CreateRoulette.await_winners)
        await safe_edit_text(cb.message, "🏆 كم عدد الفائزين المطلوب؟ (أرسل رقماً بين 1 و 100):")
    await cb.answer()


@roulette_router.callback_query(F.data.startswith("vratio:"))
async def collect_star_ratio(cb: CallbackQuery, state: FSMContext) -> None:
    ratio = int(cb.data.split(":")[1])
    await state.update_data(star_ratio=ratio)
    await state.set_state(CreateRoulette.await_winners)
    await safe_edit_text(cb.message, "🏆 كم عدد الفائزين المطلوب؟ (أرسل رقماً بين 1 و 100):")
    await cb.answer()


@roulette_router.message(CreateRoulette.await_winners)
async def collect_winners(message: Message, state: FSMContext) -> None:
    val = _parse_int_strict(message.text or "")
    if val is None or val < 1 or val > 100:
        await message.answer("⚠️ يرجى إرسال رقم صحيح بين 1 و 100.")
        return

    await state.update_data(winners=val)
    await state.set_state(CreateRoulette.await_settings)
    data = await state.get_data()
    is_vote = data.get("contest_type") == ContestType.VOTE.value
    await message.answer(
        "⚙️ إعدادات المسابقة الإضافية:",
        reply_markup=roulette_settings_kb(False, False, True, False, False, is_vote),
    )


@roulette_router.message(CreateRoulette.await_quiz_questions_count)
async def collect_quiz_count(message: Message, state: FSMContext) -> None:
    val = _parse_int_strict(message.text or "")
    if val is None or val < 1 or val > 50:
        await message.answer("⚠️ يرجى إرسال رقم صحيح بين 1 و 50.")
        return

    await state.update_data(questions_count=val, winners=1)  # Default winners for quiz
    await state.set_state(CreateRoulette.await_quiz_interval)
    await message.answer("⏱ كم المدة الزمنية بين كل سؤال (بالثواني)؟ مثال: 30")


@roulette_router.message(CreateRoulette.await_quiz_interval)
async def collect_quiz_interval(message: Message, state: FSMContext) -> None:
    val = _parse_int_strict(message.text or "")
    if val is None or val < 5 or val > 300:
        await message.answer("⚠️ يرجى إرسال رقم صحيح بين 5 و 300 ثانية.")
        return

    await state.update_data(interval=val)
    await state.set_state(CreateRoulette.await_settings)
    await message.answer(
        "⚙️ إعدادات المسابقة الإضافية:",
        reply_markup=roulette_settings_kb(False, False, True, True),
    )


@roulette_router.callback_query(F.data.startswith("toggle_"))
async def toggle_settings(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    key = cb.data.replace("toggle_", "")

    mapping = {
        "premium": "is_premium_only",
        "sub_check": "sub_check_disabled",
        "anti_bot": "anti_bot_enabled",
        "leavers": "exclude_leavers_enabled",
        "multiple_votes": "prevent_multiple",
    }
    field = mapping.get(key)
    if field:
        current = data.get(field, False) if "disabled" in field else data.get(field, True)
        if key == "multiple_votes":
            current = data.get(field, False)
        await state.update_data({field: not current})

    data = await state.get_data()
    is_vote = data.get("contest_type") == ContestType.VOTE.value
    await safe_edit_markup(
        cb.message,
        reply_markup=roulette_settings_kb(
            data.get("is_premium_only", False),
            data.get("sub_check_disabled", False),
            data.get("anti_bot_enabled", True),
            data.get("exclude_leavers_enabled", True),
            data.get("prevent_multiple", False),
            is_vote,
        )
    )
    await cb.answer()


@roulette_router.callback_query(F.data == "confirm_settings")
async def confirm_settings(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    is_vote = data.get("contest_type") == ContestType.VOTE.value
    text = (
        f"📝 <b>مراجعة المسابقة قبل النشر:</b>\n\n"
        f"🔹 النوع: {data.get('contest_type')}\n"
        f"📝 النص: {data.get('text_raw')[:50]}...\n"
        f"🏆 عدد الفائزين: {data.get('winners', 1)}\n"
        f"🛡 عدد الشروط: {len(data.get('gate_channels', []))}\n"
        f"👥 المميزين فقط: {'نعم' if data.get('is_premium_only', False) else 'لا'}\n"
        f"🤖 منع الوهمي: {'نعم' if data.get('anti_bot_enabled', True) else 'لا'}\n"
        f"🏃 استبعاد المغادرين: {'نعم' if data.get('exclude_leavers_enabled', True) else 'لا'}"
    )
    if is_vote:
        text += f"\n🚫 منع التصويت المتعدد: {'نعم' if data.get('prevent_multiple', False) else 'لا'}"

    await cb.message.answer(text, reply_markup=confirm_cancel_kb(), parse_mode=ParseMode.HTML)
    await cb.answer()


@roulette_router.callback_query(F.data == "confirm_create")
async def confirm_create_cb(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    channel_id = data["channel_id"]

    async for session in get_async_session():
        # Create Contest

        code = secrets.token_hex(8).upper()
        contest = Contest(
            owner_id=cb.from_user.id,
            channel_id=channel_id,
            unique_code=code,
            type=ContestType(data["contest_type"]),
            text_raw=data["text_raw"],
            text_style=data["style"],
            winners_count=data.get("winners", 1),
            is_premium_only=data.get("is_premium_only", False),
            sub_check_disabled=data.get("sub_check_disabled", False),
            anti_bot_enabled=data.get("anti_bot_enabled", True),
            exclude_leavers_enabled=data.get("exclude_leavers_enabled", False),
            vote_mode=VoteMode(data["vote_mode"]) if data.get("vote_mode") else None,
            prevent_multiple_votes=data.get("prevent_multiple", False),
            star_to_vote_ratio=data.get("star_ratio", 2),
            questions_count=data.get("questions_count"),
            interval_seconds=data.get("interval"),
            is_open=True,
        )
        session.add(contest)
        await session.flush()

        gate_channels = list(data.get("gate_channels", []))
        for g in gate_channels:
            session.add(
                RouletteGate(
                    contest_id=contest.id,
                    channel_id=g.get("id"),
                    channel_title=g.get("title"),
                    invite_link=g.get("link"),
                    gate_type=g.get("type", "channel"),
                    target_id=g.get("id") if g.get("type") in {"contest", "vote"} else None,
                    target_code=g.get("code"),
                )
            )

        # Build Keyboard for Channel
        if contest.type == ContestType.VOTE:
            from ..keyboards.voting import voting_main_kb

            kb = voting_main_kb(contest.id, bot_username=runtime.bot_username)
            text = _build_channel_post_text(contest, 0)
        elif contest.type == ContestType.QUIZ:
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🏆 المتصدرين", callback_data=f"leaderboard:{contest.id}"
                        )
                    ]
                ]
            )
            text = _build_channel_post_text(contest, 0)
        else:
            gate_links = [(g["title"], g["link"]) for g in gate_channels if g.get("link")]
            kb = roulette_controls_kb(contest.id, True, runtime.bot_username, gate_links)
            text = _build_channel_post_text(contest, 0)

        try:
            msg = await cb.bot.send_message(
                chat_id=channel_id,
                text=text,
                reply_markup=kb,
                parse_mode=ParseMode.HTML,
            )
            contest.message_id = msg.message_id
            await session.commit()
            await cb.message.answer(
                f"✅ تم نشر الفعالية بنجاح!\nرابط الرسالة: https://t.me/c/{str(channel_id).replace('-100','')}/{msg.message_id}",
                parse_mode=ParseMode.HTML,
            )

            if contest.type == ContestType.QUIZ:
                from .quiz import _run_quiz_session

                asyncio.create_task(_run_quiz_session(cb.bot, contest.id))

        except Exception as e:
            logging.error(f"Failed to post to channel {channel_id}: {e}")
            await cb.message.answer("❌ فشل نشر المسابقة. تأكد من وجود البوت كمشرف بصلاحية النشر.")

    await state.clear()
    await cb.answer()


@roulette_router.callback_query(F.data == "cancel_create")
async def cancel_create_cb(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    from ..keyboards.common import main_menu_kb

    await cb.message.answer("✅ تم إلغاء إنشاء المسابقة.", reply_markup=main_menu_kb())
    await cb.answer()


# --- Participation Logic (Normal Roulette) ---


@roulette_router.callback_query(F.data.startswith("join:"))
async def handle_join_request(cb: CallbackQuery, state: FSMContext) -> None:
    contest_id = int(cb.data.split(":")[1])

    async for session in get_async_session():
        service = ContestRepository(session)
        c = await service.get_by_id(contest_id)
        if not c or not c.is_open:
            await safe_answer(cb, "⚠️ عذراً، المشاركة مغلقة حالياً.", show_alert=True)
            return

        # Check sub logic
        sub_service = SubscriptionService(cb.bot, AppSettingRepository(session))
        if not c.sub_check_disabled:
            if not await sub_service.check_forced_subscription(cb.from_user.id):
                await cb.message.answer("⚠️ يجب الاشتراك في قناة البوت أولاً!")
                await safe_answer(cb)
                return

        # Check gates
        gates = (
            (await session.execute(select(RouletteGate).where(RouletteGate.contest_id == contest_id)))
            .scalars()
            .all()
        )
        for gate in gates:
            if not await sub_service.check_gate(cb.from_user.id, gate, session):
                if gate.gate_type == "channel":
                    await cb.message.answer(
                        f"⚠️ يجب الانضمام لقناة: {gate.channel_title}\n{gate.invite_link}"
                    )
                elif gate.gate_type == "contest":
                    await cb.message.answer(f"⚠️ يجب الانضمام للمسابقة رقم {gate.target_id} أولاً!")
                elif gate.gate_type == "vote":
                    await cb.message.answer(
                        f"⚠️ يجب التصويت للمتسابق ذو الرمز {gate.target_code} في المسابقة {gate.target_id}!"
                    )
                elif gate.gate_type == "yastahiq":
                    await cb.message.answer(
                        "⚠️ يجب أن يكون لديك نقاط تفاعل في المجموعة لاستكمال هذا الشرط."
                    )
                await safe_answer(cb)
                return

        # Already joined?
        entry_repo = ContestEntryRepository(session)
        existing = await entry_repo.get_entry(contest_id, cb.from_user.id)
        if existing:
            await safe_answer(cb, "✅ أنت مشارك بالفعل في هذا السحب!", show_alert=True)
            return

        # Antibot challenge?
        if c.anti_bot_enabled:
            challenge_text, answer = AntiBotService.generate_math_challenge()
            kb = AntiBotService.get_challenge_keyboard(answer)
            await state.set_state(RouletteFlow.await_antibot)
            await state.update_data(contest_id=contest_id, answer=answer)
            if cb.id == "0":
                await cb.message.answer(challenge_text, reply_markup=kb)
            else:
                await safe_edit_text(cb.message, challenge_text, reply_markup=kb)
            return

        # Finalize join

        code = secrets.token_hex(4).upper()
        entry = ContestEntry(
            contest_id=contest_id,
            user_id=cb.from_user.id,
            entry_name=cb.from_user.full_name,
            unique_code=code,
        )
        session.add(entry)
        await session.commit()
        await cb.message.answer(f"✅ تم انضمامك بنجاح للسحب رقم {contest_id}!")
        await safe_answer(cb)


@roulette_router.callback_query(RouletteFlow.await_antibot, F.data.startswith("antibot_ans:"))
async def handle_antibot_ans(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    correct_ans = data.get("answer")
    contest_id = data.get("contest_id")
    user_ans = int(cb.data.split(":")[1])

    if user_ans != correct_ans:
        await cb.answer("❌ إجابة خاطئة! حاول مجدداً.", show_alert=True)
        return

    async for session in get_async_session():

        code = secrets.token_hex(4).upper()
        entry = ContestEntry(
            contest_id=contest_id,
            user_id=cb.from_user.id,
            entry_name=cb.from_user.full_name,
            unique_code=code,
        )
        session.add(entry)
        await session.commit()
        await safe_edit_text(cb.message, f"✅ تم التحقق بنجاح وانضمامك للسحب رقم {contest_id}!")

    await state.clear()
    await cb.answer()


# --- Admin / Management ---


@roulette_router.callback_query(F.data == "create_vote")
async def create_vote_start(cb: CallbackQuery, state: FSMContext) -> None:
    await start_create_flow(cb, state, ContestType.VOTE)


@roulette_router.callback_query(F.data == "create_yastahiq")
async def create_yastahiq_start(cb: CallbackQuery, state: FSMContext) -> None:
    await start_create_flow(cb, state, ContestType.YASTAHIQ)


@roulette_router.callback_query(F.data == "create_quiz")
async def create_quiz_start(cb: CallbackQuery, state: FSMContext) -> None:
    await start_create_flow(cb, state, ContestType.QUIZ)


@roulette_router.callback_query(F.data.startswith("count_refresh:"))
async def count_refresh_handler(cb: CallbackQuery) -> None:
    contest_id = int(cb.data.split(":")[1])
    async for session in get_async_session():
        entry_repo = ContestEntryRepository(session)
        count = await entry_repo.count_participants(contest_id)
        c = await session.get(Contest, contest_id)
        if c:
            gate_rows = (
                (await session.execute(select(RouletteGate).where(RouletteGate.contest_id == c.id)))
                .scalars()
                .all()
            )
            gate_links = [(g.channel_title, g.invite_link) for g in gate_rows if g.invite_link]

            if c.type == ContestType.VOTE or c.type == ContestType.YASTAHIQ:
                from ..keyboards.voting import voting_main_kb

                kb = voting_main_kb(c.id, bot_username=runtime.bot_username)
            else:
                kb = roulette_controls_kb(c.id, c.is_open, runtime.bot_username, gate_links)
                kb.inline_keyboard[0][0].text = f"📊 عدد المشتركين: {count}"

            with suppress(Exception):
                await cb.bot.edit_message_reply_markup(
                    chat_id=c.channel_id, message_id=c.message_id, reply_markup=kb
                )
    await cb.answer(f"عدد المشاركين الحالي: {count}")


@roulette_router.callback_query(F.data.startswith("gate_remove:"))
async def gate_remove_handler(cb: CallbackQuery, state: FSMContext) -> None:
    idx = int(cb.data.split(":")[1])
    data = await state.get_data()
    gates = list(data.get("gate_channels", []))
    if 0 <= idx < len(gates):
        removed = gates.pop(idx)
        await state.update_data(gate_channels=gates)
        await cb.answer(f"🗑️ تم حذف: {removed.get('title')}")

    if not gates:
        await safe_edit_text(cb.message, "🛡️ إضافة شرط جديد:", reply_markup=gate_add_menu_kb())
    else:
        await safe_edit_text(cb.message,
            "🛡️ إدارة الشروط المضافة:", reply_markup=gates_manage_kb(len(gates))
        )


# --- Management Handlers (Pause, Resume, Draw) ---


@roulette_router.callback_query(F.data.startswith("pause:"))
async def handle_pause(cb: CallbackQuery) -> None:
    contest_id = int(cb.data.split(":")[1])
    async for session in get_async_session():
        c = await session.get(Contest, contest_id)
        if not c or c.owner_id != cb.from_user.id:
            await cb.answer("❌ غير مصرح لك", show_alert=True)
            return
        c.is_open = False
        await session.commit()
        await cb.answer("⏸️ تم إيقاف المشاركة.")

        # Update channel post
        entry_repo = ContestEntryRepository(session)
        count = await entry_repo.count_participants(contest_id)
        text = _build_channel_post_text(c, count)

        gate_rows = (
            (await session.execute(select(RouletteGate).where(RouletteGate.contest_id == c.id)))
            .scalars()
            .all()
        )
        gate_links = [(g.channel_title, g.invite_link) for g in gate_rows if g.invite_link]
        from ..keyboards.channel import roulette_controls_kb

        kb = roulette_controls_kb(c.id, c.is_open, runtime.bot_username, gate_links)

        with suppress(Exception):
            await cb.bot.edit_message_text(
                chat_id=c.channel_id,
                message_id=c.message_id,
                text=text,
                reply_markup=kb,
                parse_mode=ParseMode.HTML,
            )

        # Refresh management view
        from .my import my_roulette

        await my_roulette(cb)


@roulette_router.callback_query(F.data.startswith("resume:"))
async def handle_resume(cb: CallbackQuery) -> None:
    contest_id = int(cb.data.split(":")[1])
    async for session in get_async_session():
        c = await session.get(Contest, contest_id)
        if not c or c.owner_id != cb.from_user.id:
            await cb.answer("❌ غير مصرح لك", show_alert=True)
            return
        c.is_open = True
        await session.commit()
        await cb.answer("▶️ تم استئناف المشاركة.")

        # Update channel post
        entry_repo = ContestEntryRepository(session)
        count = await entry_repo.count_participants(contest_id)
        text = _build_channel_post_text(c, count)

        gate_rows = (
            (await session.execute(select(RouletteGate).where(RouletteGate.contest_id == c.id)))
            .scalars()
            .all()
        )
        gate_links = [(g.channel_title, g.invite_link) for g in gate_rows if g.invite_link]
        from ..keyboards.channel import roulette_controls_kb

        kb = roulette_controls_kb(c.id, c.is_open, runtime.bot_username, gate_links)

        with suppress(Exception):
            await cb.bot.edit_message_text(
                chat_id=c.channel_id,
                message_id=c.message_id,
                text=text,
                reply_markup=kb,
                parse_mode=ParseMode.HTML,
            )

        from .my import my_roulette

        await my_roulette(cb)


@roulette_router.callback_query(F.data.startswith("draw:"))
async def handle_draw(cb: CallbackQuery) -> None:
    contest_id = int(cb.data.split(":")[1])
    async for session in get_async_session():
        c = await session.get(Contest, contest_id)
        if not c or (c.owner_id != cb.from_user.id and cb.from_user.id not in settings.admin_ids):
            await cb.answer("❌ غير مصرح لك", show_alert=True)
            return

        if c.is_open:
            await cb.answer("⚠️ يرجى إيقاف المشاركة أولاً.", show_alert=True)
            return

        if c.closed_at:
            await cb.answer("⚠️ تم إجراء السحب مسبقاً.", show_alert=True)
            return

        stmt = select(ContestEntry).where(ContestEntry.contest_id == contest_id)
        entries = (await session.execute(stmt)).scalars().all()

        if not entries:
            await cb.answer("⚠️ لا يوجد مشاركون للسحب.", show_alert=True)
            return

        eligible = []
        for e in entries:
            if c.exclude_leavers_enabled:
                try:
                    member = await cb.bot.get_chat_member(c.channel_id, e.user_id)
                    if member.status in ["left", "kicked"]:
                        continue
                except Exception:
                    continue
            eligible.append(e)

        if not eligible:
            await cb.answer(
                "⚠️ لا يوجد مشاركون مستوفون للشروط (ربما غادر الجميع).", show_alert=True
            )
            return

        from ..services.security import draw_unique

        winner_indices = draw_unique(range(len(eligible)), c.winners_count)
        winners = [eligible[i] for i in winner_indices]

        # Announcement
        winner_mentions = []
        for idx, w in enumerate(winners, start=1):
            winner_mentions.append(f"{idx}. <a href='tg://user?id={w.user_id}'>{w.entry_name}</a>")

        text = f"🎉 <b>نتائج السحب رقم {contest_id}:</b>\n\n"
        text += "\n".join(winner_mentions)
        text += "\n\nتهانينا للفائزين! 🎊"

        try:
            await cb.bot.send_message(c.channel_id, text, parse_mode=ParseMode.HTML)
            await cb.answer("✅ تم إجراء السحب بنجاح!", show_alert=True)
        except Exception as e:
            logging.error(f"Failed to send winners to channel: {e}")
            await cb.answer("❌ فشل إرسال النتائج للقناة. تأكد من صلاحيات البوت.", show_alert=True)

        # Notify winners
        for w in winners:
            with suppress(Exception):
                await cb.bot.send_message(
                    w.user_id,
                    f"🎊 مبروك! لقد فزت في السحب رقم {contest_id} في قناة {c.channel_id}!",
                )

        c.closed_at = datetime.now(timezone.utc)
        await session.commit()

        from .my import my_roulette

        await my_roulette(cb)
