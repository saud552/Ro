from __future__ import annotations

import re
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Contest, ContestEntry, ContestType
from ..db.repositories import ContestEntryRepository


class YastahiqService:
    """Service for monitoring 'Yastahiq' (deserved) comments in groups."""

    KEYWORDS = {"يستحق", "تستحق", "استحق", "كفو", "يستاهل", "تستاهل"}

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.entry_repo = ContestEntryRepository(session)

    async def get_active_contest(self, chat_id: int) -> Optional[Contest]:
        """Find the active 'Yastahiq' contest for this chat."""
        stmt = select(Contest).where(
            Contest.channel_id == chat_id, # In group contests, channel_id stores the group ID
            Contest.type == ContestType.YASTAHIQ,
            Contest.is_open.is_(True),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def add_vote_by_reply(self, contest_id: int, target_user_id: int) -> bool:
        """Add a vote to a contestant identified by their user ID (via reply)."""
        entry = await self.entry_repo.get_entry(contest_id, target_user_id)
        if entry:
            entry.votes_count += 1
            await self.session.commit()
            return True
        return False

    async def add_vote_by_name(self, contest_id: int, name: str) -> bool:
        """Add a vote to a contestant identified by their entry name/code."""
        stmt = select(ContestEntry).where(
            ContestEntry.contest_id == contest_id,
            (ContestEntry.entry_name == name) | (ContestEntry.unique_code == name)
        )
        result = await self.session.execute(stmt)
        entry = result.scalar_one_or_none()
        if entry:
            entry.votes_count += 1
            await self.session.commit()
            return True
        return False

    def contains_keyword(self, text: str) -> Optional[str]:
        """Check if text starts with one of the allowed keywords."""
        text = (text or "").lower().strip()
        for kw in self.KEYWORDS:
            if text.startswith(kw):
                return kw
        return None
