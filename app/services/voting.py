from __future__ import annotations

from typing import Optional, Sequence

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Contest, ContestEntry, Vote
from ..db.repositories import ContestEntryRepository, ContestRepository, VoteRepository


class VotingService:
    """Service to handle voting logic (Normal, Stars, and Dual mode)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.contest_repo = ContestRepository(session)
        self.entry_repo = ContestEntryRepository(session)
        self.vote_repo = VoteRepository(session)

    async def get_contest(self, contest_id: int) -> Optional[Contest]:
        """Fetch a contest by its ID."""
        return await self.contest_repo.get_by_id(contest_id)

    async def register_contestant(
        self, contest_id: int, user_id: int, entry_name: str
    ) -> ContestEntry:
        """Register a user as a contestant in a voting contest."""
        import secrets

        unique_code = secrets.token_hex(4).upper()

        entry = ContestEntry(
            contest_id=contest_id, user_id=user_id, entry_name=entry_name, unique_code=unique_code
        )
        self.session.add(entry)
        await self.session.flush()
        await self.session.commit()
        return entry

    async def get_entries_for_contest(self, contest_id: int) -> Sequence[ContestEntry]:
        """Fetch all contestants for a specific contest."""
        stmt = (
            select(ContestEntry)
            .where(ContestEntry.contest_id == contest_id)
            .order_by(desc(ContestEntry.votes_count))
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_top_entries(self, contest_id: int, limit: int = 10) -> Sequence[ContestEntry]:
        """Fetch top contestants for leaderboard."""
        stmt = (
            select(ContestEntry)
            .where(ContestEntry.contest_id == contest_id)
            .order_by(desc(ContestEntry.votes_count))
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_entry_by_code(self, contest_id: int, code: str) -> Optional[ContestEntry]:
        """Fetch a contestant by their unique code within a contest."""
        stmt = select(ContestEntry).where(
            ContestEntry.contest_id == contest_id, ContestEntry.unique_code == code
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def add_vote(
        self,
        contest_id: int,
        entry_id: int,
        voter_id: int,
        is_stars: bool = False,
        stars_amount: int = 0,
    ) -> bool:
        """Add a vote to a contestant, handling normal and stars modes."""
        contest = await self.contest_repo.get_by_id(contest_id)
        if not contest or not contest.is_open:
            return False

        # 1. Enforcement of "Prevent Multiple Voting" (Normal Votes)
        # If enabled: User can have ONLY 1 normal vote in the entire contest.
        # If disabled: User can vote multiple times.
        if not is_stars and contest.prevent_multiple_votes:
            if await self.vote_repo.has_voted(contest_id, voter_id):
                return False

        entry = await self.entry_repo.get_by_id(entry_id)
        if not entry:
            return False

        # Create vote record
        vote = Vote(
            contest_id=contest_id,
            entry_id=entry_id,
            voter_id=voter_id,
            is_stars=is_stars,
            stars_amount=stars_amount,
        )
        self.session.add(vote)

        # Update entry counts
        if is_stars:
            entry.stars_received += stars_amount
            # Increment votes based on ratio (default 1 star = 2 votes)
            entry.votes_count += stars_amount * (contest.star_to_vote_ratio or 2)
        else:
            entry.votes_count += 1

        await self.session.commit()
        return True

    async def get_total_stars(self, contest_id: int) -> int:
        """Calculate total stars received in a contest."""
        stmt = select(func.sum(Vote.stars_amount)).where(
            Vote.contest_id == contest_id, Vote.is_stars.is_(True)
        )
        result = await self.session.execute(stmt)
        return result.scalar() or 0
