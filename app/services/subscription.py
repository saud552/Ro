from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional

from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from sqlalchemy import select

from ..db.models import ContestEntry, RouletteGate, Vote
from ..db.repositories import AppSettingRepository


@dataclass
class GateStatus:
    is_passed: bool
    gate: RouletteGate
    error_type: Optional[str] = None  # "user_failure" or "system_failure"
    reason: Optional[str] = None


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

        passed, _ = await self.is_member_safe(channel, user_id)
        return passed

    async def get_required_channel(self) -> str | None:
        return await self.setting_repo.get_value("bot_base_channel")

    async def is_member_safe(self, chat_id: int | str, user_id: int) -> tuple[bool, bool]:
        """
        Generic membership check.
        Returns (is_member, is_system_error).
        """
        try:
            member = await self.bot.get_chat_member(chat_id, user_id)
            is_member = member.status in {
                ChatMemberStatus.MEMBER,
                ChatMemberStatus.ADMINISTRATOR,
                ChatMemberStatus.CREATOR,
            }
            return is_member, False
        except Exception as e:
            # Check if it's a system error (bot kicked, etc)
            error_str = str(e).lower()
            is_system = any(
                x in error_str
                for x in ["kicked", "forbidden", "chat not found", "not enough rights"]
            )
            return False, is_system

    async def verify_all_gates(
        self, user_id: int, gates: List[RouletteGate], session: Any
    ) -> List[GateStatus]:
        """Verify all gates and return detailed status for each."""
        results = []
        for gate in gates:
            passed, is_sys_error = await self.check_gate_detailed(user_id, gate, session)
            status = GateStatus(
                is_passed=passed,
                gate=gate,
                error_type="system_failure"
                if is_sys_error
                else ("user_failure" if not passed else None),
            )
            results.append(status)
        return results

    async def check_gate_detailed(
        self, user_id: int, gate: RouletteGate, session: Any
    ) -> tuple[bool, bool]:
        """Returns (passed, is_system_error)."""
        if gate.gate_type in {"channel", "group"}:
            return await self.is_member_safe(gate.channel_id, user_id)

        if gate.gate_type == "vote":
            # Check if user voted for specific contestant code
            # If target_id is missing, search globally
            if gate.target_id:
                stmt_e = select(ContestEntry.id).where(
                    ContestEntry.contest_id == gate.target_id,
                    ContestEntry.unique_code == gate.target_code,
                )
            else:
                stmt_e = select(ContestEntry.id, ContestEntry.contest_id).where(
                    ContestEntry.unique_code == gate.target_code
                )

            res_e = await session.execute(stmt_e)
            row = res_e.first()
            if not row:
                return False, False

            entry_id = row[0]
            cid = gate.target_id or row[1]

            stmt = select(Vote).where(
                Vote.contest_id == cid,
                Vote.entry_id == entry_id,
                Vote.voter_id == user_id,
            )
            res = await session.execute(stmt)
            return res.scalar_one_or_none() is not None, False

        if gate.gate_type == "contest":
            if not gate.target_id:
                return True, False
            stmt = select(ContestEntry).where(
                ContestEntry.contest_id == gate.target_id, ContestEntry.user_id == user_id
            )
            res = await session.execute(stmt)
            return res.scalar_one_or_none() is not None, False

        if gate.gate_type == "yastahiq":
            # Check if user has at least 1 vote as a VOTER in target yastahiq contest
            # (Requires YastahiqService to record Votes)
            if not gate.target_id:
                return True, False
            stmt = select(Vote).where(Vote.contest_id == gate.target_id, Vote.voter_id == user_id)
            res = await session.execute(stmt)
            return res.scalar_one_or_none() is not None, False

        return True, False

    async def check_gate(self, user_id: int, gate: Any, session: Any) -> bool:
        """Legacy wrapper."""
        passed, _ = await self.check_gate_detailed(user_id, gate, session)
        return passed
