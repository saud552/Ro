from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Contest, ContestEntry, ContestType
from ..db.repositories import ContestEntryRepository


class YastahiqService:
    """Service for monitoring 'Yastahiq' comments in groups."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.entry_repo = ContestEntryRepository(session)

    async def process_comment(self, chat_id: int, user_id: int, text: str) -> bool:
        """
        Process a group comment.
        If text is 'يستحق' or 'يستحق <name>', update the corresponding entry.
        """
        text = (text or "").strip()
        if not text.startswith("يستحق"):
            return False

        # Find the active 'Yastahiq' contest for this chat
        stmt = select(Contest).where(
            Contest.chat_id == chat_id,
            Contest.type == ContestType.YASTAHIQ,
            Contest.is_open.is_(True),
        )
        result = await self.session.execute(stmt)
        contest = result.scalar_one_or_none()
        if not contest:
            return False

        # If it's just 'يستحق', we need to know who it's for.
        # Typically, this is used in response to a contestant's message.
        # For simplicity in this initial logic, we'll look for an entry name in the text.
        target_name = text.replace("يستحق", "").strip()

        if target_name:
            # Find entry by name in this contest
            stmt_entry = select(ContestEntry).where(
                ContestEntry.contest_id == contest.id, ContestEntry.entry_name == target_name
            )
            entry_result = await self.session.execute(stmt_entry)
            entry = entry_result.scalar_one_or_none()
            if entry:
                entry.votes_count += 1
                await self.session.commit()
                return True

        return False
