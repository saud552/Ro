from __future__ import annotations

from datetime import datetime, timezone

from aiogram import Router
from aiogram.enums import ChatMemberStatus
from aiogram.types import ChatMemberUpdated
from sqlalchemy import select

from ..db import get_async_session
from ..db.models import BotChat

system_router = Router(name="system")


@system_router.my_chat_member()
async def handle_my_chat_member(update: ChatMemberUpdated) -> None:
    chat = update.chat
    chat_id = chat.id
    chat_type = getattr(chat, "type", "")
    title = getattr(chat, "title", None)
    new_status = getattr(update.new_chat_member, "status", None)
    if not new_status:
        return
    async for session in get_async_session():
        rec = (
            await session.execute(select(BotChat).where(BotChat.chat_id == chat_id))
        ).scalar_one_or_none()
        if new_status in {
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.CREATOR,
        }:
            if rec is None:
                rec = BotChat(
                    chat_id=chat_id,
                    chat_type=str(chat_type),
                    title=title,
                    added_at=datetime.now(timezone.utc),
                    removed_at=None,
                )
                session.add(rec)
            else:
                rec.chat_type = str(chat_type)
                rec.title = title
                rec.removed_at = None
            await session.commit()
        elif new_status in {
            ChatMemberStatus.LEFT,
            ChatMemberStatus.KICKED,
            ChatMemberStatus.RESTRICTED,
        }:
            if rec is not None:
                rec.removed_at = datetime.now(timezone.utc)
                await session.commit()
        else:
            # ignore other transitions
            return
