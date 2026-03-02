from __future__ import annotations

from contextlib import suppress
from typing import List, Set, Tuple

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command, StateFilter
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import func, select

from ..db import get_async_session
from ..db.models import Contest, ContestEntry, ContestType, RouletteGate
from ..keyboards.my import my_channels_kb, my_manage_kb, my_roulettes_kb
from ..services.formatting import StyledText
from ..services.context import runtime

my_router = Router(name="my")


async def _is_admin_in_channel(bot, chat_id: int, user_id: int) -> bool:
    with suppress(Exception):
        m = await bot.get_chat_member(chat_id, user_id)
        return getattr(m, "status", None) in {"creator", "administrator"}
    return False


async def _list_manageable_channels(bot, user_id: int) -> List[Tuple[int, str]]:
    channels: Set[int] = set()
    owner_channels: Set[int] = set()
    async for session in get_async_session():
        rows = (
            await session.execute(
                select(Contest.channel_id, Contest.owner_id).where(Contest.is_open.is_(True))
            )
        ).all()
        for ch_id, owner_id in rows:
            channels.add(ch_id)
            if owner_id == user_id:
                owner_channels.add(ch_id)
    results: List[Tuple[int, str]] = []
    for ch_id in sorted(channels):
        if (ch_id in owner_channels) or (await _is_admin_in_channel(bot, ch_id, user_id)):
            title = None
            with suppress(Exception):
                c = await bot.get_chat(ch_id)
                title = getattr(c, "title", None)
            if not title:
                title = f"قناة {ch_id}"
            results.append((ch_id, title))
    return results


async def _list_open_contests(channel_id: int) -> List[Tuple[int, str]]:
    async for session in get_async_session():
        rows = (
            await session.execute(
                select(Contest.id, Contest.text_raw, Contest.type)
                .where(
                    (Contest.channel_id == channel_id)
                    & (Contest.is_open.is_(True))
                )
                .order_by(Contest.id.desc())
            )
        ).all()
        res: List[Tuple[int, str]] = []
        for rid, text, ctype in rows:
            preview = (text or "").strip()
            type_label = "سحب" if ctype == ContestType.ROULETTE else "تصويت"
            label = f"{type_label} #{rid} — {preview}"
            if len(label) > 32:
                label = label[:29] + "..."
            res.append((rid, label))
        return res
    return []


async def _can_manage(bot, user_id: int, c: Contest) -> bool:
    return (c.owner_id == user_id) or (await _is_admin_in_channel(bot, c.channel_id, user_id))


@my_router.message(StateFilter(None), Command(commands=["my", "mydraws"]))
async def my_entry(message: Message) -> None:
    chs = await _list_manageable_channels(message.bot, message.from_user.id)
    if not chs:
        await message.answer("⚠️ لا توجد مسابقات فعّالة حالياً.")
        return
    await message.answer("📋 اختر قناة لإدارة سحوباتها وتصويتاتها:", reply_markup=my_channels_kb(chs))


@my_router.callback_query(F.data.startswith("mych:"))
async def my_channel_jump_latest(cb: CallbackQuery) -> None:
    try:
        chat_id = int(cb.data.split(":", 1)[1])
    except Exception:
        await cb.answer()
        return
    chs = await _list_manageable_channels(cb.bot, cb.from_user.id)
    if chat_id not in {c for c, _ in chs}:
        await cb.answer("❌ غير مصرح لك")
        return
    async for session in get_async_session():
        r = (
            (
                await session.execute(
                    select(Contest)
                    .where(
                        (Contest.channel_id == chat_id)
                        & (Contest.is_open.is_(True))
                    )
                    .order_by(Contest.id.desc())
                )
            )
            .scalars()
            .first()
        )
        if not r:
            await cb.message.edit_text(
                "⚠️ لا توجد مسابقات مفتوحة حالياً في هذه القناة.", reply_markup=my_channels_kb(chs)
            )
            await cb.answer()
            return
        if not await _can_manage(cb.bot, cb.from_user.id, r):
            await cb.answer("❌ غير مصرح لك", show_alert=True)
            return
        count = (
            await session.execute(
                select(func.count())
                .select_from(ContestEntry)
                .where(ContestEntry.contest_id == r.id)
            )
        ).scalar_one()
        text = f"⚙️ <b>إدارة الفعالية #{r.id}</b>\n\n{StyledText(r.text_raw, r.text_style).render()}\n\n🔹 النوع: {r.type.value}\n🔹 الحالة: {'✅ مفتوح' if r.is_open else '⏸️ موقوف'}\n👥 عدد المشاركين: {count}"
        await cb.message.edit_text(
            text,
            reply_markup=my_manage_kb(r.id, r.is_open, r.channel_id, count, r.type),
            parse_mode=ParseMode.HTML,
        )
        await cb.answer()


@my_router.callback_query(F.data.startswith("mychlist:"))
async def my_channel_list(cb: CallbackQuery) -> None:
    try:
        chat_id = int(cb.data.split(":", 1)[1])
    except Exception:
        await cb.answer()
        return
    chs = await _list_manageable_channels(cb.bot, cb.from_user.id)
    if chat_id not in {c for c, _ in chs}:
        await cb.answer("❌ غير مصرح لك")
        return
    rlist = await _list_open_contests(chat_id)
    if not rlist:
        await cb.message.edit_text(
            "⚠️ لا توجد مسابقات مفتوحة حالياً في هذه القناة.", reply_markup=my_channels_kb(chs)
        )
        await cb.answer()
        return
    await cb.message.edit_text("📋 اختر المسابقة لإدارتها:", reply_markup=my_roulettes_kb(chat_id, rlist))
    await cb.answer()


@my_router.callback_query(F.data.startswith("myr:"))
async def my_roulette(cb: CallbackQuery) -> None:
    try:
        rid = int(cb.data.split(":", 1)[1])
    except Exception:
        await cb.answer()
        return
    async for session in get_async_session():
        r = (await session.execute(select(Contest).where(Contest.id == rid))).scalar_one_or_none()
        if not r:
            await cb.answer("⚠️ المسابقة غير موجودة", show_alert=True)
            return
        if not await _can_manage(cb.bot, cb.from_user.id, r):
            await cb.answer("❌ غير مصرح لك", show_alert=True)
            return
        count = (
            await session.execute(
                select(func.count())
                .select_from(ContestEntry)
                .where(ContestEntry.contest_id == r.id)
            )
        ).scalar_one()
        text = f"⚙️ <b>إدارة الفعالية #{r.id}</b>\n\n{StyledText(r.text_raw, r.text_style).render()}\n\n🔹 النوع: {r.type.value}\n🔹 الحالة: {'✅ مفتوح' if r.is_open else '⏸️ موقوف'}\n👥 عدد المشاركين: {count}"
        await cb.message.edit_text(
            text,
            reply_markup=my_manage_kb(r.id, r.is_open, r.channel_id, count, r.type),
            parse_mode=ParseMode.HTML,
        )
        await cb.answer()

# --- Deletion and Renewal ---

@my_router.callback_query(F.data.startswith("renew_pub:"))
async def renew_publication(cb: CallbackQuery) -> None:
    contest_id = int(cb.data.split(":")[1])
    async for session in get_async_session():
        c = await session.get(Contest, contest_id)
        if not c or not await _can_manage(cb.bot, cb.from_user.id, c):
             await cb.answer("❌ غير مصرح لك", show_alert=True)
             return

        gate_rows = (await session.execute(select(RouletteGate).where(RouletteGate.contest_id == c.id))).scalars().all()
        gate_links = [(g.channel_title, g.invite_link) for g in gate_rows if g.invite_link]

        from ..keyboards.channel import roulette_controls_kb
        from ..keyboards.voting import voting_main_kb

        if c.type == ContestType.VOTE:
            kb = voting_main_kb(c.id, bot_username=runtime.bot_username)
        elif c.type == ContestType.QUIZ:
             kb = InlineKeyboardMarkup(inline_keyboard=[
                 [InlineKeyboardButton(text="🏆 المتصدرين", callback_data=f"leaderboard:{c.id}")]
             ])
        elif c.type == ContestType.YASTAHIQ:
            from ..keyboards.voting import voting_main_kb
            kb = voting_main_kb(c.id, bot_username=runtime.bot_username) # Yastahiq also uses registration button
        else:
            kb = roulette_controls_kb(c.id, c.is_open, runtime.bot_username, gate_links)

        from ..routers.roulette import _build_channel_post_text
        participants_count = (await session.execute(select(func.count()).select_from(ContestEntry).where(ContestEntry.contest_id == c.id))).scalar_one()
        text = _build_channel_post_text(c, participants_count)

        try:
            msg = await cb.bot.send_message(chat_id=c.channel_id, text=text, reply_markup=kb, parse_mode=ParseMode.HTML)
            c.message_id = msg.message_id
            await session.commit()
            await cb.message.answer("✅ تم تجديد نشر الفعالية في القناة بنجاح.")
        except Exception:
            await cb.message.answer("❌ فشل تجديد النشر. تأكد من وجود البوت كمشرف وصلاحيات الإرسال.")
    await cb.answer()

@my_router.callback_query(F.data.startswith("cancel_evt_ask:"))
async def cancel_event_ask(cb: CallbackQuery) -> None:
    contest_id = int(cb.data.split(":")[1])
    text = "⚠️ <b>تنبيه هام!</b>\n\nأنت على وشك حذف هذه الفعالية نهائياً. سيؤدي هذا إلى حذف جميع البيانات المرتبطة بها (المشاركين، الأصوات، الشروط) ولن تتمكن من استعادتها.\n\nهل أنت متأكد من قرار الإلغاء؟"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑️ نعم، احذف الفعالية", callback_data=f"cancel_evt_exec:{contest_id}")],
        [InlineKeyboardButton(text="🔙 تراجع", callback_data=f"myr:{contest_id}")]
    ])
    await cb.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    await cb.answer()

@my_router.callback_query(F.data.startswith("cancel_evt_exec:"))
async def cancel_event_exec(cb: CallbackQuery) -> None:
    contest_id = int(cb.data.split(":")[1])
    async for session in get_async_session():
        c = await session.get(Contest, contest_id)
        if not c or not await _can_manage(cb.bot, cb.from_user.id, c):
             await cb.answer("❌ غير مصرح لك", show_alert=True)
             return

        await session.delete(c)
        await session.commit()

    await cb.message.edit_text("✅ تم حذف وإلغاء الفعالية بنجاح.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 العودة للمسابقات", callback_data="my_draws")]
    ]))
    await cb.answer()

# --- Global Commands ---

@my_router.callback_query(F.data == "my_draws")
async def back_to_my_draws(cb: CallbackQuery) -> None:
    # Use the same logic as my_entry but edit text
    chs = await _list_manageable_channels(cb.bot, cb.from_user.id)
    if not chs:
        await cb.message.edit_text("⚠️ لا توجد مسابقات فعّالة حالياً.")
        await cb.answer()
        return
    await cb.message.edit_text("📋 اختر قناة لإدارة سحوباتها وتصويتاتها:", reply_markup=my_channels_kb(chs))
    await cb.answer()

@my_router.callback_query(F.data == "noop")
async def noop_cb(cb: CallbackQuery) -> None:
    await cb.answer()
