import asyncio
import logging
import secrets
from contextlib import suppress
from typing import Optional
from urllib.parse import urlparse

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy import delete, func, select

from ..db import get_async_session
from ..db.models import (
    ChannelLink,
    Contest,
    ContestEntry,
    ContestType,
    RouletteGate,
    VoteMode,
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
from ..services.payments import has_gate_access
from ..services.ratelimit import get_rate_limiter
from ..services.subscription import SubscriptionService
from ..db.repositories import AppSettingRepository, ContestRepository, ContestEntryRepository
from ..utils.compat import safe_answer

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
    status_line = "🟢 <b>المشاركة متاحة حالياً</b>" if c.is_open else "🔴 <b>المشاركة متوقفة حالياً</b>"

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
            await cb.message.edit_text(
                "📋 اختر القناة التي تريد نشر الفعالية فيها:", reply_markup=select_channel_kb(items)
            )
        else:
            channel_id = links[0].channel_id
            await state.update_data(channel_id=channel_id)
            await state.set_state(CreateRoulette.await_text)
            await cb.message.edit_text(
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
            rows.append([InlineKeyboardButton(text=label, callback_data=f"unlinkch:{link.channel_id}")])
        rows.append([InlineKeyboardButton(text="🔙 رجوع", callback_data="back")])
        kb = InlineKeyboardMarkup(inline_keyboard=rows)
        await cb.message.answer("🗑️ اختر القناة المراد فك ارتباطها:", reply_markup=kb)
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
    await cb.message.answer("✅ تم فك ارتباط القناة/المجموعة المحددة بنجاح.")
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
            await message.answer("⚠️ يجب أن تكون مشرفاً في الوجهة لربطها.")
            return
        if runtime.bot_id is not None:
            bot_member = await message.bot.get_chat_member(target.id, runtime.bot_id)
            if getattr(bot_member, "status", None) not in {"creator", "administrator"}:
                await message.answer("⚠️ يرجى رفع البوت كمشرف أولاً بصلاحية إدارة الرسائل.")
                return
    except Exception:
        await message.answer("⚠️ تعذر التحقق من الصلاحيات. تأكد من إضافة البوت.")
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
    await message.answer("✅ تم الربط بنجاح! يمكنك الآن النشر في هذه القناة.")


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
            await message.answer("⚠️ هذا المعرف ليس قناة عامة أو مجموعة صالحة.")
            return
        member = await message.bot.get_chat_member(c.id, message.from_user.id)
        if getattr(member, "status", None) not in {"creator", "administrator"}:
            await message.answer("⚠️ يجب أن تكون مشرفاً في الوجهة لربطها.")
            return
        if runtime.bot_id is not None:
            bot_member = await message.bot.get_chat_member(c.id, runtime.bot_id)
            if getattr(bot_member, "status", None) not in {"creator", "administrator"}:
                await message.answer("⚠️ يرجى رفع البوت كمشرف أولاً.")
                return
    except Exception:
        await message.answer("⚠️ تعذر الوصول إلى المعرف. تأكد من صحته.")
        return
    async for session in get_async_session():
        existing = (
            await session.execute(
                select(ChannelLink).where(
                    (ChannelLink.owner_id == message.from_user.id) & (ChannelLink.channel_id == c.id)
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
    await message.answer("✅ تم الربط بنجاح! القناة متاحة الآن لإنشاء المسابقات.")


@roulette_router.callback_query(F.data == "create_roulette")
async def legacy_start_create(cb: CallbackQuery, state: FSMContext) -> None:
    await start_create_flow(cb, state, ContestType.ROULETTE)


@roulette_router.callback_query(F.data.startswith("select_channel:"))
async def select_channel(cb: CallbackQuery, state: FSMContext) -> None:
    try:
        chat_id = int(cb.data.split(":", 1)[1])
    except Exception:
        await cb.answer()
        return
    await state.update_data(channel_id=chat_id)
    await state.set_state(CreateRoulette.await_text)
    await cb.message.answer("📝 أرسل نص كليشة المسابقة.", reply_markup=back_kb())
    await cb.answer()


@roulette_router.callback_query(F.data == "back")
async def go_back(cb: CallbackQuery, state: FSMContext) -> None:
    cur = await state.get_state()
    data = await state.get_data()

    if data.get("sub_view") in {"gate_add", "gate_add_channel", "gate_add_group", "gate_pick", "gate_add_vote", "gate_add_contest", "gate_add_yastahiq"}:
        gates = list(data.get("gate_channels", []))
        await state.update_data(sub_view=None)
        await state.set_state(CreateRoulette.await_gate_choice)
        await cb.message.answer(
            "🔄 أعد اختيار ما إذا كنت ترغب بإضافة قنوات شرط أو المتابعة:",
            reply_markup=gates_manage_kb(len(gates)) if gates else gate_choice_kb(),
        )
        await cb.answer()
        return

    if cur == CreateRoulette.await_confirm:
        await state.set_state(CreateRoulette.await_settings)
        await cb.message.answer(
            "⚙️ تخصيص إعدادات المسابقة:",
            reply_markup=roulette_settings_kb(
                data.get("is_premium_only", False),
                data.get("sub_check_disabled", False),
                data.get("anti_bot_enabled", True),
                data.get("exclude_leavers_enabled", True),
                contest_type=ContestType(data["contest_type"]),
                prevent_multiple=data.get("prevent_multiple", True)
            ),
        )
        await cb.answer()
        return

    if cur == CreateRoulette.await_settings:
        ctype = data.get("contest_type")
        if ctype == ContestType.VOTE.value:
            if data.get("vote_mode") in {VoteMode.STARS.value, VoteMode.BOTH.value}:
                await state.set_state(CreateRoulette.await_star_ratio)
                from ..keyboards.voting import star_ratio_kb
                await cb.message.answer("⚖️ تحديد قيمة التصويت بنجوم (النجم الواحد = كم تصويت عادي؟):", reply_markup=star_ratio_kb())
            else:
                await state.set_state(CreateRoulette.await_vote_mode)
                from ..keyboards.voting import vote_mode_kb
                await cb.message.answer("🗳 اختر نوع التصويت للمسابقة:", reply_markup=vote_mode_kb())
        elif ctype == ContestType.QUIZ.value:
             await state.set_state(CreateRoulette.await_quiz_interval)
             await cb.message.answer("⏳ أدخل المدة الزمنية بين الأسئلة (بالثواني):", reply_markup=back_kb())
        else:
            await state.set_state(CreateRoulette.await_winners)
            await cb.message.answer("🏆 أدخل عدد الفائزين:", reply_markup=back_kb())
        await cb.answer()
        return

    if cur == CreateRoulette.await_star_ratio:
        await state.set_state(CreateRoulette.await_vote_mode)
        from ..keyboards.voting import vote_mode_kb
        await cb.message.answer("🗳 اختر نوع التصويت للمسابقة:", reply_markup=vote_mode_kb())
        await cb.answer()
        return

    if cur == CreateRoulette.await_quiz_interval:
        await state.set_state(CreateRoulette.await_quiz_questions_count)
        await cb.message.answer("❓ أدخل عدد الأسئلة للمسابقة:", reply_markup=back_kb())
        await cb.answer()
        return

    if cur == CreateRoulette.await_winners or cur == CreateRoulette.await_vote_mode or cur == CreateRoulette.await_quiz_questions_count:
        await state.set_state(CreateRoulette.await_gate_choice)
        gates = list(data.get("gate_channels", []))
        await cb.message.answer(
            "🛡️ هل تريد إضافة شرط انضمام؟",
            reply_markup=gates_manage_kb(len(gates)) if gates else gate_choice_kb()
        )
        await cb.answer()
        return

    if cur == CreateRoulette.await_gate_choice:
        await state.set_state(CreateRoulette.await_text)
        await cb.message.answer("📝 أرسل نص كليشة السحب مرة أخرى:", reply_markup=back_kb())
        await cb.answer()
        return

    if cur == CreateRoulette.await_text or cur == CreateRoulette.await_channel:
        await state.clear()
        from ..keyboards.common import main_menu_kb
        await cb.message.answer("✅ تم الإلغاء. اختر من القائمة:", reply_markup=main_menu_kb())
        await cb.answer()
        return

    await cb.answer()


@roulette_router.message(CreateRoulette.await_text)
async def collect_text(message: Message, state: FSMContext) -> None:
    text, style = parse_style_from_text(message.text or "")
    await state.update_data(text_raw=text, style=style)
    await state.set_state(CreateRoulette.await_gate_choice)
    await message.answer("🛡️ هل تريد إضافة شرط انضمام؟", reply_markup=gate_choice_kb())


@roulette_router.callback_query(F.data == "gate_skip")
async def gate_skip(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    ctype = data.get("contest_type")
    if ctype == ContestType.VOTE.value:
        from ..keyboards.voting import vote_mode_kb
        await state.set_state(CreateRoulette.await_vote_mode)
        await cb.message.edit_text("🗳 اختر نوع التصويت للمسابقة:", reply_markup=vote_mode_kb())
    elif ctype == ContestType.QUIZ.value:
        await state.set_state(CreateRoulette.await_quiz_questions_count)
        await cb.message.edit_text("❓ أدخل عدد الأسئلة للمسابقة:", reply_markup=back_kb())
    else:
        await state.set_state(CreateRoulette.await_winners)
        await cb.message.edit_text("🏆 أدخل عدد الفائزين المرجو سحبهم:", reply_markup=back_kb())
    await cb.answer()


@roulette_router.callback_query(F.data == "gate_add")
async def gate_add(cb: CallbackQuery, state: FSMContext) -> None:
    if not await has_gate_access(cb.from_user.id):
        from ..services.payments import get_monthly_price_stars, get_one_time_price_stars

        pm = get_monthly_price_stars()
        po = get_one_time_price_stars()
        text = (
            "🔓 <b>ميزة قنوات الشروط تتطلب اشتراكاً.</b>\n\n"
            f"• اشتراك شهري: {pm} ⭐️\n"
            f"• استخدام لمرة واحدة: {po} ⭐️\n\n"
            "أو يمكنك الحصول عليها مجاناً عبر استبدال النقاط من (حسابي -> متجر النقاط)."
        )
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"💎 اشتراك شهري ({pm} ⭐️)", callback_data="buy_access_monthly"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=f"🪙 استخدام مرة واحدة ({po} ⭐️)", callback_data="buy_access_once"
                    )
                ],
                [InlineKeyboardButton(text="🛒 متجر النقاط", callback_data="section_store")],
                [InlineKeyboardButton(text="🔙 رجوع", callback_data="back")],
            ]
        )
        await cb.message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        await cb.answer()
        return

    await state.update_data(sub_view="gate_add")
    await cb.message.edit_text("🛡️ إضافة شرط جديد:", reply_markup=gate_add_menu_kb())
    await cb.answer()


@roulette_router.callback_query(F.data.startswith("gate_type:"))
async def gate_type_select(cb: CallbackQuery, state: FSMContext) -> None:
    gtype = cb.data.split(":")[1]
    if gtype == "channel":
        await state.update_data(sub_view="gate_add_channel")
        await cb.message.edit_text(
            "📢 لإضافة قناة كشرط:\n1. أضف البوت مشرفاً فيها.\n2. أرسل رابطها العام أو قم بتوجيه رسالة منها هنا.",
            reply_markup=back_kb(),
        )
    elif gtype == "group":
        await state.update_data(sub_view="gate_add_group")
        await cb.message.edit_text(
            "👥 لإضافة مجموعة كشرط:\n1. أضف البوت مشرفاً فيها.\n2. أرسل رابطها العام هنا.",
            reply_markup=back_kb(),
        )
    elif gtype == "pick":
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
                await cb.answer("⚠️ ليس لديك قنوات مرتبطة لاختيارها.", show_alert=True)
                return
            await state.update_data(sub_view="gate_pick")
            items = [(link.channel_id, link.channel_title) for link in links]
            await cb.message.edit_text("📋 اختر من قنواتك المرتبطة:", reply_markup=gate_pick_list_kb(items))

    elif gtype == "vote" or gtype == "contest":
        await state.update_data(sub_view=f"gate_add_{gtype}")
        async for session in get_async_session():
            contests = (await session.execute(select(Contest).where(Contest.owner_id == cb.from_user.id, Contest.is_open.is_(True)))).scalars().all()
            if not contests:
                await cb.answer("⚠️ ليس لديك فعاليات جارية لاستخدامها كشرط.", show_alert=True)
                return

            rows = []
            for c in contests:
                rows.append([InlineKeyboardButton(text=f"{c.type.value} #{c.id}", callback_data=f"gate_sel_evt:{gtype}:{c.id}")])
            rows.append([InlineKeyboardButton(text="🔙 رجوع", callback_data="back")])
            await cb.message.edit_text("📋 اختر الفعالية التي يجب على المستخدم المشاركة فيها:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

    elif gtype == "yastahiq":
        await state.update_data(sub_view="gate_add_yastahiq")
        async for session in get_async_session():
            links = (await session.execute(select(ChannelLink).where(ChannelLink.owner_id == cb.from_user.id))).scalars().all()
            if not links:
                await cb.answer("⚠️ يجب ربط مجموعة أولاً لاستخدام شرط يستحق.", show_alert=True)
                return

            rows = []
            for link in links:
                rows.append([InlineKeyboardButton(text=link.channel_title or str(link.channel_id), callback_data=f"gate_sel_yastahiq:{link.channel_id}")])
            rows.append([InlineKeyboardButton(text="🔙 رجوع", callback_data="back")])
            await cb.message.edit_text("📋 اختر المجموعة التي يجب أن يمتلك فيها المستخدم نقاط تفاعل:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

    await cb.answer()

@roulette_router.callback_query(F.data.startswith("gate_sel_yastahiq:"))
async def gate_yastahiq_selection(cb: CallbackQuery, state: FSMContext) -> None:
    chat_id = int(cb.data.split(":")[1])
    data = await state.get_data()
    gates = list(data.get("gate_channels", []))

    title, link = await _get_channel_title_and_link(cb.bot, chat_id)
    gates.append({"id": chat_id, "title": f"تفاعل في {title}", "link": link, "type": "yastahiq", "target_id": chat_id})
    await state.update_data(gate_channels=gates, sub_view=None)
    await cb.message.edit_text(f"✅ تمت إضافة شرط التفاعل في {title}", reply_markup=gates_manage_kb(len(gates)))
    await cb.answer()

@roulette_router.callback_query(F.data.startswith("gate_sel_evt:"))
async def gate_event_selection(cb: CallbackQuery, state: FSMContext) -> None:
    parts = cb.data.split(":")
    gtype = parts[1]
    evt_id = int(parts[2])

    data = await state.get_data()
    gates = list(data.get("gate_channels", []))

    if gtype == "contest":
        gates.append({"id": evt_id, "title": f"اشتراك في سحب #{evt_id}", "link": None, "type": "contest"})
        await state.update_data(gate_channels=gates, sub_view=None)
        await cb.message.edit_text(f"✅ تمت إضافة شرط الاشتراك في سحب #{evt_id}", reply_markup=gates_manage_kb(len(gates)))

    elif gtype == "vote":
        await state.update_data(gate_tmp_evt=evt_id)
        await state.set_state(CreateRoulette.await_gate_target)
        await cb.message.edit_text("🆔 يرجى إرسال رمز التصويت (Unique Code) للمتسابق الذي يجب التصويت له:")

    await cb.answer()

@roulette_router.message(CreateRoulette.await_gate_target)
async def collect_gate_target_code(message: Message, state: FSMContext) -> None:
    code = (message.text or "").strip().upper()
    data = await state.get_data()
    evt_id = data.get("gate_tmp_evt")
    gates = list(data.get("gate_channels", []))

    gates.append({"id": evt_id, "title": f"تصويت للمتسابق {code}", "link": None, "type": "vote", "code": code})
    await state.update_data(gate_channels=gates, sub_view=None)
    await state.set_state(CreateRoulette.await_gate_choice)
    await message.answer(f"✅ تمت إضافة شرط التصويت للمتسابق {code}", reply_markup=gates_manage_kb(len(gates)))

@roulette_router.callback_query(F.data.startswith("gate_pick_apply:"))
async def gate_pick_apply(cb: CallbackQuery, state: FSMContext) -> None:
    chat_id = int(cb.data.split(":")[1])
    title, link = await _get_channel_title_and_link(cb.bot, chat_id)
    data = await state.get_data()
    gates = list(data.get("gate_channels", []))
    if not any(g["id"] == chat_id for g in gates):
        gates.append({"id": chat_id, "title": title, "link": link, "type": "channel"})
        await state.update_data(gate_channels=gates)
    await state.update_data(sub_view=None)
    await cb.message.edit_text(
        f"✅ تمت إضافة القناة الشرط: {title}", reply_markup=gates_manage_kb(len(gates))
    )
    await cb.answer()


@roulette_router.message(
    StateFilter(CreateRoulette.await_gate_choice),
    (F.forward_from_chat | F.forward_origin | F.text.contains("t.me/")),
)
async def handle_gate_input(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if data.get("sub_view") not in {"gate_add_channel", "gate_add_group"}:
        return

    chat = message.forward_from_chat or (
        getattr(message, "forward_origin", None) and getattr(message.forward_origin, "chat", None)
    )
    chat_id = None
    if chat:
        chat_id = chat.id
    else:
        text = message.text or ""
        if "t.me/" in text:
            username = text.split("t.me/")[-1].split("?")[0].split("/")[0]
            if not username.startswith("@") and not username.startswith("+"):
                username = "@" + username
            try:
                c = await message.bot.get_chat(username)
                chat_id = c.id
            except Exception:
                pass

    if not chat_id:
        await message.answer("⚠️ تعذر التعرف على القناة/المجموعة. تأكد من الرابط أو التوجيه.")
        return

    title, link = await _get_channel_title_and_link(message.bot, chat_id)
    gates = list(data.get("gate_channels", []))
    if not any(g["id"] == chat_id for g in gates):
        gates.append({"id": chat_id, "title": title, "link": link, "type": "channel" if "channel" in data.get("sub_view") else "group"})
        await state.update_data(gate_channels=gates, sub_view=None)
    await message.answer(f"✅ تمت إضافة: {title}", reply_markup=gates_manage_kb(len(gates)))


@roulette_router.callback_query(F.data == "gate_next")
async def gate_next(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    ctype = data.get("contest_type")
    if ctype == ContestType.VOTE.value:
        from ..keyboards.voting import vote_mode_kb
        await state.set_state(CreateRoulette.await_vote_mode)
        await cb.message.edit_text("🗳 اختر نوع التصويت للمسابقة:", reply_markup=vote_mode_kb())
    elif ctype == ContestType.QUIZ.value:
        await state.set_state(CreateRoulette.await_quiz_questions_count)
        await cb.message.edit_text("❓ أدخل عدد الأسئلة للمسابقة:", reply_markup=back_kb())
    else:
        await state.set_state(CreateRoulette.await_winners)
        await cb.message.edit_text("🏆 أدخل عدد الفائزين المرجو سحبهم:", reply_markup=back_kb())
    await cb.answer()


@roulette_router.callback_query(F.data.startswith("vmode_"))
async def collect_vote_mode(cb: CallbackQuery, state: FSMContext) -> None:
    mode_map = {
        "vmode_normal": VoteMode.NORMAL,
        "vmode_stars": VoteMode.STARS,
        "vmode_both": VoteMode.BOTH,
    }
    mode = mode_map.get(cb.data)
    await state.update_data(vote_mode=mode.value)

    if mode in {VoteMode.STARS, VoteMode.BOTH}:
        if not await has_gate_access(cb.from_user.id):
             await cb.answer("⚠️ ميزات النجوم تتطلب اشتراكاً في البوت.", show_alert=True)
             return

    if mode in {VoteMode.STARS, VoteMode.BOTH}:
        from ..keyboards.voting import star_ratio_kb
        await state.set_state(CreateRoulette.await_star_ratio)
        await cb.message.edit_text(
            "⚖️ تحديد قيمة التصويت بنجوم (النجم الواحد = كم تصويت عادي؟):",
            reply_markup=star_ratio_kb()
        )
    else:
        await state.set_state(CreateRoulette.await_settings)
        data = await state.get_data()
        await cb.message.edit_text(
            "⚙️ تخصيص إعدادات المسابقة:",
            reply_markup=roulette_settings_kb(
                data.get("is_premium_only", False),
                data.get("sub_check_disabled", False),
                data.get("anti_bot_enabled", True),
                data.get("exclude_leavers_enabled", True),
                contest_type=ContestType.VOTE
            ),
        )
    await cb.answer()

@roulette_router.callback_query(F.data.startswith("vratio:"))
async def collect_star_ratio(cb: CallbackQuery, state: FSMContext) -> None:
    ratio = int(cb.data.split(":")[1])
    await state.update_data(star_ratio=ratio)
    await state.set_state(CreateRoulette.await_settings)
    data = await state.get_data()
    await cb.message.edit_text(
        "⚙️ تخصيص إعدادات المسابقة:",
        reply_markup=roulette_settings_kb(
            data.get("is_premium_only", False),
            data.get("sub_check_disabled", False),
            data.get("anti_bot_enabled", True),
            data.get("exclude_leavers_enabled", True),
            contest_type=ContestType.VOTE
        ),
    )
    await cb.answer()


@roulette_router.message(CreateRoulette.await_winners)
async def collect_winners(message: Message, state: FSMContext) -> None:
    val = _parse_int_strict(message.text or "")
    if not val:
        await message.answer("⚠️ الرجاء إرسال رقم صحيح.")
        return
    count = max(1, min(100, val))
    await state.update_data(winners=count)
    await state.set_state(CreateRoulette.await_settings)
    data = await state.get_data()
    await message.answer(
        "⚙️ تخصيص إعدادات المسابقة:",
        reply_markup=roulette_settings_kb(
            data.get("is_premium_only", False),
            data.get("sub_check_disabled", False),
            data.get("anti_bot_enabled", True),
            data.get("exclude_leavers_enabled", True),
            contest_type=ContestType(data["contest_type"])
        ),
    )

@roulette_router.message(CreateRoulette.await_quiz_questions_count)
async def collect_quiz_count(message: Message, state: FSMContext) -> None:
    val = _parse_int_strict(message.text or "")
    if not val:
        await message.answer("⚠️ الرجاء إرسال رقم صحيح.")
        return
    await state.update_data(winners=1, questions_count=val)
    await state.set_state(CreateRoulette.await_quiz_interval)
    await message.answer("⏳ أدخل المدة الزمنية بين الأسئلة (بالثواني):", reply_markup=back_kb())

@roulette_router.message(CreateRoulette.await_quiz_interval)
async def collect_quiz_interval(message: Message, state: FSMContext) -> None:
    val = _parse_int_strict(message.text or "")
    if not val:
        await message.answer("⚠️ الرجاء إرسال رقم صحيح.")
        return
    await state.update_data(interval=val)
    await state.set_state(CreateRoulette.await_settings)
    data = await state.get_data()
    await message.answer(
        "⚙️ تخصيص إعدادات المسابقة:",
        reply_markup=roulette_settings_kb(
            data.get("is_premium_only", False),
            data.get("sub_check_disabled", False),
            data.get("anti_bot_enabled", True),
            data.get("exclude_leavers_enabled", True),
            contest_type=ContestType.QUIZ
        ),
    )


@roulette_router.callback_query(F.data.startswith("toggle_"))
async def toggle_settings(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if cb.data == "toggle_premium":
        val = not data.get("is_premium_only", False)
        await state.update_data(is_premium_only=val)
    elif cb.data == "toggle_sub_check":
        val = not data.get("sub_check_disabled", False)
        await state.update_data(sub_check_disabled=val)
    elif cb.data == "toggle_anti_bot":
        val = not data.get("anti_bot_enabled", True)
        await state.update_data(anti_bot_enabled=val)
    elif cb.data == "toggle_leavers":
        val = not data.get("exclude_leavers_enabled", True)
        await state.update_data(exclude_leavers_enabled=val)
    elif cb.data == "toggle_multiple_vote":
        val = not data.get("prevent_multiple", True)
        await state.update_data(prevent_multiple=val)

    # Refresh keyboard
    data = await state.get_data()
    await cb.message.edit_reply_markup(
        reply_markup=roulette_settings_kb(
            data.get("is_premium_only", False),
            data.get("sub_check_disabled", False),
            data.get("anti_bot_enabled", True),
            data.get("exclude_leavers_enabled", True),
            contest_type=ContestType(data["contest_type"]),
            prevent_multiple=data.get("prevent_multiple", True)
        )
    )
    await cb.answer()


@roulette_router.callback_query(F.data == "confirm_settings")
async def confirm_settings(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await state.set_state(CreateRoulette.await_confirm)
    styled = StyledText(data["text_raw"], data["style"]).render()
    ctype = ContestType(data["contest_type"])

    if ctype == ContestType.VOTE:
        text = (
            f"✅ <b>تأكيد إنشاء مسابقة التصويت:</b>\n\n"
            f"📝 النص: {styled}\n"
            f"📊 النوع: {data.get('vote_mode')}\n"
            f"🚫 منع التصويت المتعدد: {'نعم' if data.get('prevent_multiple', True) else 'لا'}\n"
            f"🤖 منع الوهمي: {'مفعل' if data.get('anti_bot_enabled', True) else 'معطل'}"
        )
    elif ctype == ContestType.QUIZ:
         text = (
            f"✅ <b>تأكيد إنشاء مسابقة الأسئلة (Quiz):</b>\n\n"
            f"📝 النص: {styled}\n"
            f"❓ عدد الأسئلة: {data.get('questions_count')}\n"
            f"⏳ الفاصل الزمني: {data.get('interval')} ثانية"
        )
    else:
        text = (
            f"✅ <b>تأكيد إنشاء السحب:</b>\n\n"
            f"📝 النص: {styled}\n"
            f"🏆 عدد الفائزين: {data.get('winners', 1)}\n"
            f"💎 للمميزين فقط: {'نعم' if data.get('is_premium_only') else 'لا'}\n"
            f"🤖 منع الوهمي: {'مفعل' if data.get('anti_bot_enabled', True) else 'معطل'}\n"
            f"🏃 استبعاد المغادرين: {'نعم' if data.get('exclude_leavers_enabled', True) else 'لا'}"
        )
    await cb.message.answer(text, reply_markup=confirm_cancel_kb(), parse_mode=ParseMode.HTML)
    await cb.answer()


@roulette_router.callback_query(F.data == "confirm_create")
async def confirm_create_cb(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    channel_id = int(data.get("channel_id") or 0)
    unique_code = secrets.token_hex(4)

    async for session in get_async_session():
        contest = Contest(
            owner_id=cb.from_user.id,
            channel_id=channel_id,
            unique_code=unique_code,
            type=ContestType(data["contest_type"]),
            text_raw=data["text_raw"],
            text_style=data["style"],
            winners_count=data.get("winners", 1),
            is_premium_only=data.get("is_premium_only", False),
            sub_check_disabled=data.get("sub_check_disabled", False),
            anti_bot_enabled=data.get("anti_bot_enabled", True),
            exclude_leavers_enabled=data.get("exclude_leavers_enabled", True),
            vote_mode=VoteMode(data["vote_mode"]) if data.get("vote_mode") else None,
            prevent_multiple_votes=data.get("prevent_multiple", True),
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
                    target_code=g.get("code")
                )
            )

        # Build Keyboard for Channel
        if contest.type == ContestType.VOTE:
            from ..keyboards.voting import voting_main_kb
            kb = voting_main_kb(contest.id, bot_username=runtime.bot_username)
            text = _build_channel_post_text(contest, 0)
        elif contest.type == ContestType.QUIZ:
             kb = InlineKeyboardMarkup(inline_keyboard=[
                 [InlineKeyboardButton(text="🏆 المتصدرين", callback_data=f"leaderboard:{contest.id}")]
             ])
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
            await cb.message.answer(f"✅ تم نشر الفعالية بنجاح في القناة!\nرابط الرسالة: https://t.me/c/{str(channel_id).replace('-100','')}/{msg.message_id}", parse_mode=ParseMode.HTML)

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
        gates = (await session.execute(select(RouletteGate).where(RouletteGate.contest_id == contest_id))).scalars().all()
        for gate in gates:
            if not await sub_service.check_gate(cb.from_user.id, gate, session):
                 if gate.gate_type == "channel":
                      await cb.message.answer(f"⚠️ يجب الانضمام لقناة: {gate.channel_title}\n{gate.invite_link}")
                 elif gate.gate_type == "contest":
                      await cb.message.answer(f"⚠️ يجب الانضمام للمسابقة رقم {gate.target_id} أولاً!")
                 elif gate.gate_type == "vote":
                      await cb.message.answer(f"⚠️ يجب التصويت للمتسابق ذو الرمز {gate.target_code} في المسابقة {gate.target_id}!")
                 elif gate.gate_type == "yastahiq":
                      await cb.message.answer("⚠️ يجب أن يكون لديك نقاط تفاعل في المجموعة لاستكمال هذا الشرط.")
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
                 await cb.message.edit_text(challenge_text, reply_markup=kb)
             return

        # Finalize join
        import secrets
        code = secrets.token_hex(4).upper()
        entry = ContestEntry(contest_id=contest_id, user_id=cb.from_user.id, entry_name=cb.from_user.full_name, unique_code=code)
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
        import secrets
        code = secrets.token_hex(4).upper()
        entry = ContestEntry(contest_id=contest_id, user_id=cb.from_user.id, entry_name=cb.from_user.full_name, unique_code=code)
        session.add(entry)
        await session.commit()
        await cb.message.edit_text(f"✅ تم التحقق بنجاح وانضمامك للسحب رقم {contest_id}!")

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
        count = (await session.execute(select(func.count()).select_from(ContestEntry).where(ContestEntry.contest_id == contest_id))).scalar_one()
        c = await session.get(Contest, contest_id)
        if c:
            gate_rows = (await session.execute(select(RouletteGate).where(RouletteGate.contest_id == c.id))).scalars().all()
            gate_links = [(g.channel_title, g.invite_link) for g in gate_rows if g.invite_link]

            if c.type == ContestType.VOTE or c.type == ContestType.YASTAHIQ:
                from ..keyboards.voting import voting_main_kb
                kb = voting_main_kb(c.id, bot_username=runtime.bot_username)
            else:
                kb = roulette_controls_kb(c.id, c.is_open, runtime.bot_username, gate_links)
                kb.inline_keyboard[0][0].text = f"📊 عدد المشتركين: {count}"

            with suppress(Exception):
                await cb.bot.edit_message_reply_markup(chat_id=c.channel_id, message_id=c.message_id, reply_markup=kb)
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
        await cb.message.edit_text("🛡️ إضافة شرط جديد:", reply_markup=gate_add_menu_kb())
    else:
        await cb.message.edit_text("🛡️ إدارة الشروط المضافة:", reply_markup=gates_manage_kb(len(gates)))
