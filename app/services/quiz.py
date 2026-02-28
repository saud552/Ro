from __future__ import annotations

import asyncio
import json
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Contest, ContestEntry, ContestType, Question
from ..db.repositories import ContestEntryRepository


class QuizService:
    """Service to manage cultural quiz contests and questions."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.entry_repo = ContestEntryRepository(session)

    async def add_question(
        self, contest_id: Optional[int], text: str, correct_answers: List[str], points: int = 1
    ) -> Question:
        """Add a question to a contest or the general bank."""
        q = Question(
            contest_id=contest_id,
            question_text=text,
            correct_answers_json=json.dumps(correct_answers),
            points=points,
        )
        self.session.add(q)
        await self.session.commit()
        return q

    async def get_contest_questions(self, contest_id: int) -> List[Question]:
        """Fetch all questions for a specific quiz contest."""
        stmt = select(Question).where(Question.contest_id == contest_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def submit_answer(self, contest_id: int, user_id: int, question_id: int, answer: str) -> bool:
        """Verify an answer and update the contestant's score."""
        q = await self.session.get(Question, question_id)
        if not q:
            return False

        correct_variants = json.loads(q.correct_answers_json)
        is_correct = any(answer.strip().lower() == v.strip().lower() for v in correct_variants)

        if is_correct:
            entry = await self.entry_repo.get_entry(contest_id, user_id)
            if not entry:
                # Create entry if user participated for the first time
                entry = ContestEntry(contest_id=contest_id, user_id=user_id, score=0)
                self.session.add(entry)
                await self.session.flush()

            entry.score += q.points
            await self.session.commit()
            return True

        return False

    async def get_leaderboard(self, contest_id: int, limit: int = 10) -> List[ContestEntry]:
        """Get top scorers for a quiz."""
        from sqlalchemy import desc
        stmt = (
            select(ContestEntry)
            .where(ContestEntry.contest_id == contest_id)
            .order_by(desc(ContestEntry.score))
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
