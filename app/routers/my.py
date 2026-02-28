from __future__ import annotations

from contextlib import suppress
from typing import List, Set, Tuple

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command, StateFilter
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select

from ..db import get_async_session
from ..db.models import Contest, ContestEntry, ContestType
from ..keyboards.my import my_channels_kb, my_manage_kb, my_roulettes_kb
from ..services.formatting import StyledText

my_router = Router(name="my")


async def _is_admin_in_channel(bot, chat_id: int, user_id: int) -> bool:
    with suppress(Exception):
        m = await bot.get_chat_member(chat_id, user_id)
        return getattr(m, "status", None) in {"creator", "administrator"}
    return False


async def _list_manageable_channels(bot, user_id: int) -> List[Tuple[int, str]]:
    # Gather channels with open contests
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
            # Resolve title
            title = None
            with suppress(Exception):
                c = await bot.get_chat(ch_id)
                title = getattr(c, "title", None)
            if not title:
                title = f"قناة {ch_id}"
            results.append((ch_id, title))
    return results


async def _list_open_roulettes(channel_id: int) -> List[Tuple[int, str]]:
    """Legacy helper for tests."""
    async for session in get_async_session():
        rows = (
            await session.execute(
                select(Contest.id, Contest.text_raw)
                .where(
                    (Contest.channel_id == channel_id)
                    & (Contest.is_open.is_(True))
                    & (Contest.type == ContestType.ROULETTE)
                )
                .order_by(Contest.id.desc())
            )
        ).all()
        res: List[Tuple[int, str]] = []
        for rid, text in rows:
            preview = (text or "").strip()
            label = f"سحب #{rid} — {preview}"
            if len(label) > 32:
                label = label[:29] + "..."
            res.append((rid, label))
        return res
    return []


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
        await message.answer("لا توجد مسابقات فعّالة حالياً.")
        return
    await message.answer("اختر قناة لإدارة سحوباتها وتصويتاتها:", reply_markup=my_channels_kb(chs))


@my_router.callback_query(F.data.startswith("mych:"))
async def my_channel_jump_latest(cb: CallbackQuery) -> None:
    try:
        chat_id = int(cb.data.split(":", 1)[1])
    except Exception:
        await cb.answer()
        return
    chs = await _list_manageable_channels(cb.bot, cb.from_user.id)
    if chat_id not in {c for c, _ in chs}:
        await cb.answer("غير مصرح")
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
                "لا توجد مسابقات مفتوحة حالياً في هذه القناة.", reply_markup=my_channels_kb(chs)
            )
            await cb.answer()
            return
        if not await _can_manage(cb.bot, cb.from_user.id, r):
            await cb.answer("غير مصرح", show_alert=True)
            return
        count = (
            await session.execute(
                select(func.count())
                .select_from(ContestEntry)
                .where(ContestEntry.contest_id == r.id)
            )
        ).scalar_one()
        text = f"{StyledText(r.text_raw, r.text_style).render()}\n\nالنوع: {'روليت' if r.type == ContestType.ROULETTE else 'تصويت'}\nالحالة: {'مفتوح' if r.is_open else 'موقوف'}\nعدد المشاركين: {count}"
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
        await cb.answer("غير مصرح")
        return
    rlist = await _list_open_contests(chat_id)
    if not rlist:
        await cb.message.edit_text(
            "لا توجد مسابقات مفتوحة حالياً في هذه القناة.", reply_markup=my_channels_kb(chs)
        )
        await cb.answer()
        return
    await cb.message.edit_text("اختر المسابقة لإدارتها:", reply_markup=my_roulettes_kb(chat_id, rlist))
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
            await cb.answer("المسابقة غير موجودة", show_alert=True)
            return
        if not await _can_manage(cb.bot, cb.from_user.id, r):
            await cb.answer("غير مصرح", show_alert=True)
            return
        count = (
            await session.execute(
                select(func.count())
                .select_from(ContestEntry)
                .where(ContestEntry.contest_id == r.id)
            )
        ).scalar_one()
        text = f"{StyledText(r.text_raw, r.text_style).render()}\n\nالنوع: {'روليت' if r.type == ContestType.ROULETTE else 'تصويت'}\nالحالة: {'مفتوح' if r.is_open else 'موقوف'}\nعدد المشاركين: {count}"
        await cb.message.edit_text(
            text,
            reply_markup=my_manage_kb(r.id, r.is_open, r.channel_id, count, r.type),
            parse_mode=ParseMode.HTML,
        )
        await cb.answer()


@my_router.callback_query(F.data == "noop")
async def noop_cb(cb: CallbackQuery) -> None:
    await cb.answer()
