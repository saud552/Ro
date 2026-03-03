from __future__ import annotations

import json
from typing import Any, List, Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import ContestEntry, Question
from ..db.repositories import ContestEntryRepository


class QuizService:
    """Service to manage cultural quiz contests, questions, and fastest-answer logic."""

    def __init__(self, session: AsyncSession, redis: Any = None) -> None:
        self.session = session
        self.entry_repo = ContestEntryRepository(session)
        self.redis = redis

    async def add_question(
        self, contest_id: Optional[int], text: str, correct_answers: List[str], points: int = 1
    ) -> Question:
        """Add a question to a contest."""
        q = Question(
            contest_id=contest_id,
            question_text=text,
            correct_answers_json=json.dumps(correct_answers),
            points=points,
        )
        self.session.add(q)
        await self.session.commit()
        return q

    async def bulk_add_questions(self, contest_id: int, data: str) -> int:
        """
        Parse bulk text data for questions.
        Format expected: Question text | answer1, answer2 | points
        """
        count = 0
        for line in data.strip().split("\n"):
            if "|" not in line:
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 2:
                continue

            text = parts[0]
            answers = [a.strip() for a in parts[1].split(",")]
            points = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 1

            q = Question(
                contest_id=contest_id,
                question_text=text,
                correct_answers_json=json.dumps(answers),
                points=points,
            )
            self.session.add(q)
            count += 1

        await self.session.commit()
        return count

    async def get_contest_questions(self, contest_id: int) -> List[Question]:
        """Fetch all questions for a specific quiz contest."""
        stmt = select(Question).where(Question.contest_id == contest_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_next_question(
        self, contest_id: int, exclude_ids: List[int]
    ) -> Optional[Question]:
        """Fetch a question for the contest that hasn't been used yet in this session."""
        stmt = (
            select(Question)
            .where(Question.contest_id == contest_id, ~Question.id.in_(exclude_ids))
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def set_active_question(self, contest_id: int, question_id: int):
        """Mark a question as active in Redis."""
        if self.redis:
            await self.redis.set(f"quiz:{contest_id}:active", question_id, ex=3600)
            await self.redis.delete(f"quiz:{contest_id}:solved")

    async def submit_fastest_answer(
        self, contest_id: int, user_id: int, answer: str
    ) -> Optional[Question]:
        """
        Verify if the user is the first to answer correctly.
        Returns the Question object if successful, None otherwise.
        """
        if not self.redis:
            return None

        active_qid = await self.redis.get(f"quiz:{contest_id}:active")
        if not active_qid:
            return None

        # Check if already solved
        if await self.redis.get(f"quiz:{contest_id}:solved"):
            return None

        q = await self.session.get(Question, int(active_qid))
        if not q:
            return None

        correct_variants = json.loads(q.correct_answers_json)
        # Normalize and compare
        is_correct = any(answer.strip().lower() == v.strip().lower() for v in correct_variants)

        if is_correct:
            # Atomic lock to ensure fastest answer
            is_first = await self.redis.set(f"quiz:{contest_id}:solved", user_id, nx=True, ex=60)
            if is_first:
                entry = await self.entry_repo.get_entry(contest_id, user_id)
                if not entry:
                    entry = ContestEntry(contest_id=contest_id, user_id=user_id, score=0)
                    self.session.add(entry)
                    await self.session.flush()

                entry.score += q.points
                await self.session.commit()
                return q

        return None

    async def get_leaderboard(self, contest_id: int, limit: int = 10) -> List[ContestEntry]:
        stmt = (
            select(ContestEntry)
            .where(ContestEntry.contest_id == contest_id)
            .order_by(desc(ContestEntry.score))
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
