from __future__ import annotations

import asyncio
from aiogram import F, Router
from aiogram.types import Message, CallbackQuery
from aiogram.enums import ChatType, ParseMode

from ..db import get_async_session
from ..services.yastahiq import YastahiqService

yastahiq_router = Router(name="yastahiq")

@yastahiq_router.callback_query(F.data.startswith("yastahiq_interact:"))
async def handle_yastahiq_interaction(cb: CallbackQuery) -> None:
    """Show copyable text for Yastahiq contestants."""
    parts = cb.data.split(":")
    contest_id = int(parts[1])
    entry_id = int(parts[2])

    async for session in get_async_session():
        from ..db.models import ContestEntry
        entry = await session.get(ContestEntry, entry_id)
        if not entry:
            await cb.answer("⚠️ المتسابق غير موجود.")
            return

        text = (
            f"🔥 <b>دعم المتسابق: {entry.entry_name}</b>\n\n"
            f"قم بنسخ أحد النصوص التالية وإرسالها في المجموعة المحددة:\n\n"
            f"1️⃣ <code>يستحق</code>\n"
            f"2️⃣ <code>يستحق {entry.entry_name}</code>\n\n"
            "📌 عند إرسال الكلمة، سيتم احتساب تصويتك تلقائياً."
        )
        await cb.message.answer(text, parse_mode=ParseMode.HTML)
    await cb.answer()

@yastahiq_router.message(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def handle_group_message(message: Message) -> None:
    """Listener for keywords in groups to support 'Yastahiq' contests."""
    text = message.text or message.caption
    if not text:
        return

    async for session in get_async_session():
        service = YastahiqService(session)
        keyword = service.contains_keyword(text)
        if not keyword:
            continue

        contest = await service.get_active_contest(message.chat.id)
        if not contest:
            continue

        success = False
        target_name = ""

        # 1. Try by reply
        if message.reply_to_message:
            target_uid = message.reply_to_message.from_user.id
            success = await service.add_vote_by_reply(contest.id, target_uid)
            target_name = message.reply_to_message.from_user.full_name

        # 2. Try by name/code if not success
        if not success:
            target = text.replace(keyword, "", 1).strip()
            if target:
                success = await service.add_vote_by_name(contest.id, target)
                target_name = target

        if success:
            await message.reply(
                f"✅ تم احتساب تصويتك لـ <a href='tg://user?id={message.from_user.id}'>{target_name}</a> بنجاح!",
                parse_mode=ParseMode.HTML
            )
