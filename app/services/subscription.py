from __future__ import annotations

from aiogram import Bot
from aiogram.enums import ChatMemberStatus

from ..db.repositories import AppSettingRepository


class SubscriptionService:
    """Service to verify user memberships in channels and groups."""

    def __init__(self, bot: Bot, setting_repo: AppSettingRepository) -> None:
        self.bot = bot
        self.setting_repo = setting_repo

    async def check_forced_subscription(self, user_id: int) -> bool:
        """Check if user is subscribed to the mandatory bot channel."""
        channel = await self.setting_repo.get_value("bot_base_channel")
        if not channel:
            return True  # No restriction if not set

        return await self.is_member(channel, user_id)

    async def get_required_channel(self) -> str | None:
        return await self.setting_repo.get_value("bot_base_channel")

    async def is_member(self, chat_id: int | str, user_id: int) -> bool:
        """Generic membership check."""
        try:
            member = await self.bot.get_chat_member(chat_id, user_id)
            return member.status in {
                ChatMemberStatus.MEMBER,
                ChatMemberStatus.ADMINISTRATOR,
                ChatMemberStatus.CREATOR,
            }
        except Exception:
            return False

    async def check_gate(self, user_id: int, gate: Any, session: Any) -> bool:
        """Check if a specific RouletteGate condition is met."""
        if gate.gate_type == "channel" or gate.gate_type == "group":
            return await self.is_member(gate.channel_id, user_id)

        if gate.gate_type == "vote":
            # Check if user voted for specific contestant code
            from ..db.models import Vote
            from sqlalchemy import select
            stmt = select(Vote).where(
                Vote.contest_id == gate.target_id,
                Vote.voter_id == user_id
            )
            res = await session.execute(stmt)
            return res.scalar_one_or_none() is not None

        if gate.gate_type == "contest":
            # Check if user joined another Roulette
            from ..db.models import ContestEntry
            from sqlalchemy import select
            stmt = select(ContestEntry).where(
                ContestEntry.contest_id == gate.target_id,
                ContestEntry.user_id == user_id
            )
            res = await session.execute(stmt)
            return res.scalar_one_or_none() is not None

        return True
