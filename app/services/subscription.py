from __future__ import annotations

from typing import Optional

from aiogram import Bot
from aiogram.enums import ChatMemberStatus

from ..db.repositories import AppSettingRepository


class SubscriptionService:
    """Service to handle forced subscription checks and membership verification."""

    def __init__(self, bot: Bot, setting_repo: AppSettingRepository) -> None:
        self.bot = bot
        self.setting_repo = setting_repo

    async def get_required_channel(self) -> Optional[str]:
        """Fetch the bot's base/forced subscription channel username or ID."""
        return await self.setting_repo.get_value("bot_base_channel")

    async def is_subscribed(self, user_id: int, chat_id: str | int) -> bool:
        """Check if a user is a member/admin in a specific channel or group."""
        try:
            member = await self.bot.get_chat_member(chat_id, user_id)
            return member.status in {
                ChatMemberStatus.MEMBER,
                ChatMemberStatus.CREATOR,
                ChatMemberStatus.ADMINISTRATOR,
            }
        except Exception:
            return False

    async def check_forced_subscription(self, user_id: int) -> bool:
        """Verify if the user is subscribed to the bot's mandatory channel, if configured."""
        channel = await self.get_required_channel()
        if not channel:
            return True
        return await self.is_subscribed(user_id, channel)
