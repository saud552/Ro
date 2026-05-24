from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .engine import Base


# ملخص: جدول المستخدمين ومعلوماتهم الأساسية.
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    channel_links: Mapped[list["ChannelLink"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )
    roulettes: Mapped[list["Roulette"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )
    notifications: Mapped[list["Notification"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


# ملخص: ربط قنوات التلغرام بالمستخدم المالك.
class ChannelLink(Base):
    __tablename__ = "channel_links"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    channel_id: Mapped[int] = mapped_column(BigInteger, index=True)
    channel_title: Mapped[str] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    owner: Mapped[User] = relationship(back_populates="channel_links")

    __table_args__ = (UniqueConstraint("owner_id", "channel_id", name="uq_owner_channel"),)


# ملخص: جدول السحوبات (roulette) وخصائصها.
class Roulette(Base):
    __tablename__ = "roulettes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    channel_id: Mapped[int] = mapped_column(BigInteger, index=True)
    channel_message_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    text_raw: Mapped[str] = mapped_column(Text)
    text_style: Mapped[str] = mapped_column(String(16), default="plain")
    winners_count: Mapped[int] = mapped_column(Integer)
    is_open: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    closed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    owner: Mapped[User] = relationship(back_populates="roulettes")
    participants: Mapped[list["Participant"]] = relationship(
        back_populates="roulette", cascade="all, delete-orphan"
    )
    gates: Mapped[list["RouletteGate"]] = relationship(
        back_populates="roulette", cascade="all, delete-orphan"
    )


# ملخص: مشاركة المستخدمين في السحوبات.
class Participant(Base):
    __tablename__ = "participants"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    roulette_id: Mapped[int] = mapped_column(
        ForeignKey("roulettes.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    joined_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    roulette: Mapped[Roulette] = relationship(back_populates="participants")

    __table_args__ = (UniqueConstraint("roulette_id", "user_id", name="uq_roulette_user"),)


# ملخص: إشعارات مرتبطة بالمستخدم والسحب.
class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    roulette_id: Mapped[int] = mapped_column(ForeignKey("roulettes.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    user: Mapped[User] = relationship(back_populates="notifications")


# ملخص: متطلبات الانضمام للسحب كقنوات وروابط دعوة.
class RouletteGate(Base):
    __tablename__ = "roulette_gates"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    roulette_id: Mapped[int] = mapped_column(
        ForeignKey("roulettes.id", ondelete="CASCADE"), index=True
    )
    channel_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True)
    channel_title: Mapped[str] = mapped_column(String(256))
    invite_link: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    roulette: Mapped[Roulette] = relationship(back_populates="gates")


# ملخص: صلاحيات الميزات المدفوعة أو المؤقتة للمستخدمين.
class FeatureAccess(Base):
    __tablename__ = "feature_access"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    feature_key: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    one_time_credits: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("user_id", "feature_key", name="uq_user_feature"),)


# ملخص: سجل عمليات شراء النجوم.
class Purchase(Base):
    __tablename__ = "purchases"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    payload: Mapped[str] = mapped_column(String(64))
    stars_amount: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)


# ملخص: إعدادات عامة للتطبيق (مفتاح/قيمة).
class AppSetting(Base):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(64), unique=True)
    value: Mapped[str] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)


# ملخص: محادثات البوت (مجموعات/قنوات) مع حالة الإضافة/الإزالة.
class BotChat(Base):
    __tablename__ = "bot_chats"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    chat_type: Mapped[str] = mapped_column(String(16))  # group/supergroup/channel
    title: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    added_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    removed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    __table_args__ = (UniqueConstraint("chat_id", name="uq_bot_chat_id"),)


# ملخص: اشتراكات المستخدمين (شهري/مرة واحدة/إحالة).
class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    subscription_type: Mapped[str] = mapped_column(String(16))  # monthly, one_time, referral
    expires_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    one_time_credits: Mapped[int] = mapped_column(Integer, default=0)
    referral_code: Mapped[str] = mapped_column(String(32), unique=True)
    referral_points: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("user_id", name="uq_subscription_user"),)


# ملخص: مسابقات التصويتب (عادي، نجوم، عادي+نجوم).
class VotingContest(Base):
    __tablename__ = "voting_contests"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    channel_id: Mapped[int] = mapped_column(BigInteger, index=True)
    group_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    channel_message_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    text_raw: Mapped[str] = mapped_column(Text)
    text_style: Mapped[str] = mapped_column(String(16), default="plain")
    voting_type: Mapped[str] = mapped_column(String(16), default="normal")  # normal, stars, mixed
    stars_per_vote: Mapped[int] = mapped_column(Integer, default=2)
    allow_multiple_votes: Mapped[bool] = mapped_column(Boolean, default=False)
    require_subscription: Mapped[bool] = mapped_column(Boolean, default=True)
    anti_bot_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    exclude_leavers: Mapped[bool] = mapped_column(Boolean, default=True)
    premium_only: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    ended_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)


# ملخص: متسابقي التصويتب في المسابقة.
class VotingCandidate(Base):
    __tablename__ = "voting_candidates"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    contest_id: Mapped[int] = mapped_column(ForeignKey("voting_contests.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    display_name: Mapped[str] = mapped_column(String(256))
    channel_message_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    vote_code: Mapped[str] = mapped_column(String(32), unique=True)
    normal_votes: Mapped[int] = mapped_column(Integer, default=0)
    star_votes: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("contest_id", "user_id", name="uq_contest_candidate_user"),)


# ملخص: أصوات التصويتب.
class VotingVote(Base):
    __tablename__ = "voting_votes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    contest_id: Mapped[int] = mapped_column(ForeignKey("voting_contests.id", ondelete="CASCADE"), index=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("voting_candidates.id", ondelete="CASCADE"), index=True)
    voter_id: Mapped[int] = mapped_column(BigInteger, index=True)
    is_star_vote: Mapped[bool] = mapped_column(Boolean, default=False)
    stars_amount: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("contest_id", "candidate_id", "voter_id", name="uq_vote_unique"),
    )


# ملخص: مسابقات "يستحق" (التصويتب بالتعليقات).
class DeservesContest(Base):
    __tablename__ = "deserves_contests"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    channel_id: Mapped[int] = mapped_column(BigInteger, index=True)
    group_id: Mapped[int] = mapped_column(BigInteger, index=True)
    channel_message_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    text_raw: Mapped[str] = mapped_column(Text)
    text_style: Mapped[str] = mapped_column(String(16), default="plain")
    require_subscription: Mapped[bool] = mapped_column(Boolean, default=True)
    anti_bot_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    exclude_leavers: Mapped[bool] = mapped_column(Boolean, default=True)
    premium_only: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    ended_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)


# ملخص: متسابقي "يستحق".
class DeservesCandidate(Base):
    __tablename__ = "deserves_candidates"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    contest_id: Mapped[int] = mapped_column(ForeignKey("deserves_contests.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    display_name: Mapped[str] = mapped_column(String(256))
    vote_code: Mapped[str] = mapped_column(String(32), unique=True)
    vote_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)


# ملخص: أصوات "يستحق".
class DeservesVote(Base):
    __tablename__ = "deserves_votes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    contest_id: Mapped[int] = mapped_column(ForeignKey("deserves_contests.id", ondelete="CASCADE"), index=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("deserves_candidates.id", ondelete="CASCADE"), index=True)
    voter_id: Mapped[int] = mapped_column(BigInteger, index=True)
    message_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("contest_id", "candidate_id", "voter_id", name="uq_deserves_vote_unique"),)


# ملخص: مسابقات الأسئلة.
class QuizContest(Base):
    __tablename__ = "quiz_contests"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    channel_id: Mapped[int] = mapped_column(BigInteger, index=True)
    group_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    text_raw: Mapped[str] = mapped_column(Text)
    text_style: Mapped[str] = mapped_column(String(16), default="plain")
    winners_count: Mapped[int] = mapped_column(Integer, default=1)
    question_count: Mapped[int] = mapped_column(Integer, default=10)
    question_interval: Mapped[int] = mapped_column(Integer, default=60)  # seconds
    require_subscription: Mapped[bool] = mapped_column(Boolean, default=True)
    anti_bot_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    exclude_leavers: Mapped[bool] = mapped_column(Boolean, default=True)
    premium_only: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    current_question: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    ended_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)


# ملخص: أسئلة المسابقة.
class QuizQuestion(Base):
    __tablename__ = "quiz_questions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    contest_id: Mapped[int] = mapped_column(ForeignKey("quiz_contests.id", ondelete="CASCADE"), index=True)
    question_number: Mapped[int] = mapped_column(Integer)
    text_raw: Mapped[str] = mapped_column(Text)
    correct_answer: Mapped[str] = mapped_column(String(256))
    time_limit: Mapped[int] = mapped_column(Integer, default=30)  # seconds
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("contest_id", "question_number", name="uq_quiz_contest_question"),)


# ملخص: إجابات المسابقة (للمشاركين).
class QuizAnswer(Base):
    __tablename__ = "quiz_answers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    contest_id: Mapped[int] = mapped_column(ForeignKey("quiz_contests.id", ondelete="CASCADE"), index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("quiz_questions.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    answer_text: Mapped[str] = mapped_column(String(256))
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False)
    answered_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("question_id", "user_id", name="uq_quiz_question_user"),
    )


# ملخص: درجات المشاركين في المسابقة.
class QuizParticipantScore(Base):
    __tablename__ = "quiz_participant_scores"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    contest_id: Mapped[int] = mapped_column(ForeignKey("quiz_contests.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    score: Mapped[int] = mapped_column(Integer, default=0)
    correct_answers: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("contest_id", "user_id", name="uq_quiz_contest_user_score"),)


# ملخص: سجل الإحالات (للمستخدم الذي أحال).
class Referral(Base):
    __tablename__ = "referrals"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    referrer_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    referred_id: Mapped[int] = mapped_column(BigInteger, index=True)
    referral_code: Mapped[str] = mapped_column(String(32), index=True)
    points_earned: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("referred_id", name="uq_referred_user"),)
