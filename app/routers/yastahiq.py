from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message
from aiogram.enums import ChatType

from ..db import get_async_session
from ..services.yastahiq import YastahiqService

yastahiq_router = Router(name="yastahiq")

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
        # 1. Try by reply
        if message.reply_to_message:
            target_uid = message.reply_to_message.from_user.id
            success = await service.add_vote_by_reply(contest.id, target_uid)

        # 2. Try by name/code if not success or if it contains more text
        if not success:
            # Extract target name (text after keyword)
            target = text.replace(keyword, "", 1).strip()
            if target:
                success = await service.add_vote_by_name(contest.id, target)

        if success:
            # Optionally react or send a small confirmation
            # await message.react([{"type": "emoji", "emoji": "🔥"}])
            pass
