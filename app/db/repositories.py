from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    DeservesCandidate,
    DeservesContest,
    DeservesVote,
    FeatureAccess,
    Purchase,
    QuizAnswer,
    QuizContest,
    QuizParticipantScore,
    QuizQuestion,
    Referral,
    Subscription,
    VotingCandidate,
    VotingContest,
    VotingVote,
)


# ملخص: مستودع للوصول إلى ميزات المستخدم وإدارة عمليات الشراء.
class FeatureAccessRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ملخص: يجلب سجل الوصول لميزة محددة للمستخدم إذا وُجد.
    async def get_user_feature_access(
        self, user_id: int, feature_key: str
    ) -> Optional[FeatureAccess]:
        result = await self._session.execute(
            select(FeatureAccess).where(
                FeatureAccess.user_id == user_id,
                FeatureAccess.feature_key == feature_key,
            )
        )
        return result.scalar_one_or_none()

    # ملخص: يتحقق من وجود صلاحية بوابة للمستخدم مع استهلاك رصيد مرة واحدة اختيارياً.
    async def has_gate_access(
        self, user_id: int, feature_key: str, *, consume_one_time: bool = False
    ) -> bool:
        fa = await self.get_user_feature_access(user_id, feature_key)
        from datetime import datetime

        now = datetime.utcnow()
        if fa is None:
            return False
        if fa.expires_at and fa.expires_at > now:
            return True
        if fa.one_time_credits > 0:
            if consume_one_time:
                fa.one_time_credits -= 1
                await self._session.commit()
            return True
        return False

    # ملخص: يمنح/يمدد الاشتراك الشهري لمدة 30 يوماً.
    async def grant_monthly(self, user_id: int, feature_key: str) -> None:
        from datetime import datetime, timedelta

        fa = await self.get_user_feature_access(user_id, feature_key)
        now = datetime.utcnow()
        if fa is None:
            fa = FeatureAccess(
                user_id=user_id,
                feature_key=feature_key,
                expires_at=now + timedelta(days=30),
                one_time_credits=0,
            )
            self._session.add(fa)
        else:
            base = fa.expires_at if fa.expires_at and fa.expires_at > now else now
            fa.expires_at = base + timedelta(days=30)
        await self._session.commit()

    # ملخص: يضيف رصيداً لمرة واحدة للمستخدم.
    async def grant_one_time(self, user_id: int, feature_key: str, *, credits: int = 1) -> None:
        fa = await self.get_user_feature_access(user_id, feature_key)
        if fa is None:
            fa = FeatureAccess(user_id=user_id, feature_key=feature_key, expires_at=None, one_time_credits=credits)
            self._session.add(fa)
        else:
            fa.one_time_credits += credits
        await self._session.commit()

    # ملخص: يسجل عملية شراء نجوم للمستخدم.
    async def log_purchase(self, user_id: int, payload: str, stars_amount: int) -> None:
        self._session.add(Purchase(user_id=user_id, payload=payload, stars_amount=stars_amount))
        await self._session.commit()


# ملخص: مستودع الاشتراكات.
class SubscriptionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_user_id(self, user_id: int) -> Optional[Subscription]:
        result = await self._session.execute(
            select(Subscription).where(Subscription.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def create(self, user_id: int, subscription_type: str, referral_code: str) -> Subscription:
        sub = Subscription(
            user_id=user_id,
            subscription_type=subscription_type,
            referral_code=referral_code,
        )
        self._session.add(sub)
        await self._session.commit()
        return sub

    async def update_credits(self, user_id: int, credits: int) -> None:
        sub = await self.get_by_user_id(user_id)
        if sub:
            sub.one_time_credits += credits
            await self._session.commit()

    async def update_points(self, user_id: int, points: int) -> None:
        sub = await self.get_by_user_id(user_id)
        if sub:
            sub.referral_points += points
            await self._session.commit()


# ملخص: مستودع مسابقات التصويتب.
class VotingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_contest(
        self,
        owner_id: int,
        channel_id: int,
        text_raw: str,
        text_style: str,
        voting_type: str = "normal",
        stars_per_vote: int = 2,
        **kwargs,
    ) -> VotingContest:
        contest = VotingContest(
            owner_id=owner_id,
            channel_id=channel_id,
            text_raw=text_raw,
            text_style=text_style,
            voting_type=voting_type,
            stars_per_vote=stars_per_vote,
            **kwargs,
        )
        self._session.add(contest)
        await self._session.commit()
        return contest

    async def get_contest(self, contest_id: int) -> Optional[VotingContest]:
        result = await self._session.execute(
            select(VotingContest).where(VotingContest.id == contest_id)
        )
        return result.scalar_one_or_none()

    async def get_user_contests(self, owner_id: int) -> list[VotingContest]:
        result = await self._session.execute(
            select(VotingContest)
            .where(VotingContest.owner_id == owner_id)
            .order_by(VotingContest.created_at.desc())
        )
        return list(result.scalars().all())

    async def add_candidate(
        self,
        contest_id: int,
        user_id: int,
        display_name: str,
        vote_code: str,
    ) -> VotingCandidate:
        candidate = VotingCandidate(
            contest_id=contest_id,
            user_id=user_id,
            display_name=display_name,
            vote_code=vote_code,
        )
        self._session.add(candidate)
        await self._session.commit()
        return candidate

    async def get_candidate_by_code(self, vote_code: str) -> Optional[VotingCandidate]:
        result = await self._session.execute(
            select(VotingCandidate).where(VotingCandidate.vote_code == vote_code)
        )
        return result.scalar_one_or_none()

    async def add_vote(
        self,
        contest_id: int,
        candidate_id: int,
        voter_id: int,
        is_star_vote: bool = False,
        stars_amount: int = 0,
    ) -> VotingVote:
        vote = VotingVote(
            contest_id=contest_id,
            candidate_id=candidate_id,
            voter_id=voter_id,
            is_star_vote=is_star_vote,
            stars_amount=stars_amount,
        )
        self._session.add(vote)
        await self._session.commit()
        return vote

    async def has_voted(self, contest_id: int, candidate_id: int, voter_id: int) -> bool:
        result = await self._session.execute(
            select(VotingVote).where(
                VotingVote.contest_id == contest_id,
                VotingVote.candidate_id == candidate_id,
                VotingVote.voter_id == voter_id,
            )
        )
        return result.scalar_one_or_none() is not None

    async def end_contest(self, contest_id: int) -> None:
        contest = await self.get_contest(contest_id)
        if contest:
            from datetime import datetime

            contest.is_active = False
            contest.ended_at = datetime.utcnow()
            await self._session.commit()


# ملخص: مستودع مسابقات "يستحق".
class DeservesRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_contest(
        self,
        owner_id: int,
        channel_id: int,
        group_id: int,
        text_raw: str,
        text_style: str,
        **kwargs,
    ) -> DeservesContest:
        contest = DeservesContest(
            owner_id=owner_id,
            channel_id=channel_id,
            group_id=group_id,
            text_raw=text_raw,
            text_style=text_style,
            **kwargs,
        )
        self._session.add(contest)
        await self._session.commit()
        return contest

    async def get_contest(self, contest_id: int) -> Optional[DeservesContest]:
        result = await self._session.execute(
            select(DeservesContest).where(DeservesContest.id == contest_id)
        )
        return result.scalar_one_or_none()

    async def get_active_contest_for_group(self, group_id: int) -> Optional[DeservesContest]:
        result = await self._session.execute(
            select(DeservesContest).where(
                DeservesContest.group_id == group_id,
                DeservesContest.is_active == True,
            )
        )
        return result.scalar_one_or_none()

    async def add_candidate(
        self,
        contest_id: int,
        user_id: int,
        display_name: str,
        vote_code: str,
    ) -> DeservesCandidate:
        candidate = DeservesCandidate(
            contest_id=contest_id,
            user_id=user_id,
            display_name=display_name,
            vote_code=vote_code,
        )
        self._session.add(candidate)
        await self._session.commit()
        return candidate

    async def get_candidate_by_code(self, vote_code: str) -> Optional[DeservesCandidate]:
        result = await self._session.execute(
            select(DeservesCandidate).where(DeservesCandidate.vote_code == vote_code)
        )
        return result.scalar_one_or_none()

    async def add_vote(
        self,
        contest_id: int,
        candidate_id: int,
        voter_id: int,
        message_id: Optional[int] = None,
    ) -> DeservesVote:
        vote = DeservesVote(
            contest_id=contest_id,
            candidate_id=candidate_id,
            voter_id=voter_id,
            message_id=message_id,
        )
        self._session.add(vote)
        await self._session.commit()
        return vote

    async def has_voted(self, contest_id: int, candidate_id: int, voter_id: int) -> bool:
        result = await self._session.execute(
            select(DeservesVote).where(
                DeservesVote.contest_id == contest_id,
                DeservesVote.candidate_id == candidate_id,
                DeservesVote.voter_id == voter_id,
            )
        )
        return result.scalar_one_or_none() is not None

    async def end_contest(self, contest_id: int) -> None:
        contest = await self.get_contest(contest_id)
        if contest:
            from datetime import datetime

            contest.is_active = False
            contest.ended_at = datetime.utcnow()
            await self._session.commit()


# ملخص: مستودع مسابقات الأسئلة.
class QuizRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_contest(
        self,
        owner_id: int,
        channel_id: int,
        text_raw: str,
        text_style: str,
        winners_count: int = 1,
        question_count: int = 10,
        question_interval: int = 60,
        **kwargs,
    ) -> QuizContest:
        contest = QuizContest(
            owner_id=owner_id,
            channel_id=channel_id,
            text_raw=text_raw,
            text_style=text_style,
            winners_count=winners_count,
            question_count=question_count,
            question_interval=question_interval,
            **kwargs,
        )
        self._session.add(contest)
        await self._session.commit()
        return contest

    async def get_contest(self, contest_id: int) -> Optional[QuizContest]:
        result = await self._session.execute(
            select(QuizContest).where(QuizContest.id == contest_id)
        )
        return result.scalar_one_or_none()

    async def get_user_contests(self, owner_id: int) -> list[QuizContest]:
        result = await self._session.execute(
            select(QuizContest)
            .where(QuizContest.owner_id == owner_id)
            .order_by(QuizContest.created_at.desc())
        )
        return list(result.scalars().all())

    async def add_question(
        self,
        contest_id: int,
        question_number: int,
        text_raw: str,
        correct_answer: str,
        time_limit: int = 30,
    ) -> QuizQuestion:
        question = QuizQuestion(
            contest_id=contest_id,
            question_number=question_number,
            text_raw=text_raw,
            correct_answer=correct_answer,
            time_limit=time_limit,
        )
        self._session.add(question)
        await self._session.commit()
        return question

    async def get_question(self, question_id: int) -> Optional[QuizQuestion]:
        result = await self._session.execute(
            select(QuizQuestion).where(QuizQuestion.id == question_id)
        )
        return result.scalar_one_or_none()

    async def get_next_question(self, contest_id: int, current_number: int) -> Optional[QuizQuestion]:
        result = await self._session.execute(
            select(QuizQuestion).where(
                QuizQuestion.contest_id == contest_id,
                QuizQuestion.question_number == current_number + 1,
            )
        )
        return result.scalar_one_or_none()

    async def submit_answer(
        self,
        contest_id: int,
        question_id: int,
        user_id: int,
        answer_text: str,
    ) -> QuizAnswer:
        from datetime import datetime

        # Check if correct
        question = await self.get_question(question_id)
        is_correct = question and question.correct_answer.strip().lower() == answer_text.strip().lower()

        answer = QuizAnswer(
            contest_id=contest_id,
            question_id=question_id,
            user_id=user_id,
            answer_text=answer_text,
            is_correct=is_correct,
            answered_at=datetime.utcnow(),
        )
        self._session.add(answer)
        await self._session.commit()
        return answer

    async def update_score(self, contest_id: int, user_id: int, correct: bool) -> None:
        from datetime import datetime

        result = await self._session.execute(
            select(QuizParticipantScore).where(
                QuizParticipantScore.contest_id == contest_id,
                QuizParticipantScore.user_id == user_id,
            )
        )
        score = result.scalar_one_or_none()
        if score:
            score.score += 1 if correct else 0
            score.correct_answers += 1 if correct else 0
            score.updated_at = datetime.utcnow()
        else:
            score = QuizParticipantScore(
                contest_id=contest_id,
                user_id=user_id,
                score=1 if correct else 0,
                correct_answers=1 if correct else 0,
                updated_at=datetime.utcnow(),
            )
            self._session.add(score)
        await self._session.commit()

    async def end_contest(self, contest_id: int) -> None:
        contest = await self.get_contest(contest_id)
        if contest:
            contest.is_active = False
            from datetime import datetime

            contest.ended_at = datetime.utcnow()
            await self._session.commit()


# ملخص: مستودع الإحالات والنقاط.
class PointsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_referral(
        self,
        referrer_id: int,
        referred_id: int,
        referral_code: str,
        points_earned: int = 0,
    ) -> Referral:
        referral = Referral(
            referrer_id=referrer_id,
            referred_id=referred_id,
            referral_code=referral_code,
            points_earned=points_earned,
        )
        self._session.add(referral)
        await self._session.commit()
        return referral

    async def get_referral_by_code(self, referral_code: str) -> Optional[Referral]:
        result = await self._session.execute(
            select(Referral).where(Referral.referral_code == referral_code)
        )
        return result.scalar_one_or_none()

    async def get_user_referrals(self, referrer_id: int) -> list[Referral]:
        result = await self._session.execute(
            select(Referral).where(Referral.referrer_id == referrer_id)
        )
        return list(result.scalars().all())

    async def count_referrals(self, referrer_id: int) -> int:
        result = await self._session.execute(
            select(Referral).where(Referral.referrer_id == referrer_id)
        )
        return len(result.scalars().all())