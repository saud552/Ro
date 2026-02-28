from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .engine import Base


class ContestType(enum.Enum):
    ROULETTE = "roulette"
    VOTE = "vote"
    YASTAHIQ = "yastahiq"
    QUIZ = "quiz"


class VoteMode(enum.Enum):
    NORMAL = "normal"
    STARS = "stars"
    BOTH = "both"


class PaymentStatus(enum.Enum):
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"


# ملخص: جدول المستخدمين مع دعم نظام الإحالة والنقاط.
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    points: Mapped[int] = mapped_column(Integer, default=0)
    referred_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    channel_links: Mapped[List["ChannelLink"]] = relationship(back_populates="owner")
    contests: Mapped[List["Contest"]] = relationship(back_populates="owner")
    entries: Mapped[List["ContestEntry"]] = relationship(back_populates="user")
    votes: Mapped[List["Vote"]] = relationship(back_populates="voter")
    purchases: Mapped[List["Purchase"]] = relationship(back_populates="user")


# ملخص: ربط قنوات التلغرام بالمستخدم المالك.
class ChannelLink(Base):
    __tablename__ = "channel_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    channel_id: Mapped[int] = mapped_column(BigInteger, index=True)
    channel_title: Mapped[str] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    owner: Mapped["User"] = relationship(back_populates="channel_links")

    __table_args__ = (UniqueConstraint("owner_id", "channel_id", name="uq_owner_channel"),)


# ملخص: جدول المسابقات الموحد (روليت، تصويت، يستحق، أسئلة).
class Contest(Base):
    __tablename__ = "contests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    channel_id: Mapped[int] = mapped_column(BigInteger, index=True)
    chat_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)  # Associated group
    message_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    unique_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)

    type: Mapped[ContestType] = mapped_column(Enum(ContestType))
    text_raw: Mapped[str] = mapped_column(Text)
    text_style: Mapped[str] = mapped_column(String(16), default="plain")

    # Settings
    winners_count: Mapped[int] = mapped_column(Integer, default=1)
    is_premium_only: Mapped[bool] = mapped_column(Boolean, default=False)
    sub_check_disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    anti_bot_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    exclude_leavers_enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    # Specific to Vote
    vote_mode: Mapped[Optional[VoteMode]] = mapped_column(Enum(VoteMode), nullable=True)
    prevent_multiple_votes: Mapped[bool] = mapped_column(Boolean, default=True)
    star_to_vote_ratio: Mapped[int] = mapped_column(Integer, default=2)

    # Specific to Quiz
    questions_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    interval_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    is_open: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    owner: Mapped["User"] = relationship(back_populates="contests")
    gates: Mapped[List["RouletteGate"]] = relationship(back_populates="contest")
    entries: Mapped[List["ContestEntry"]] = relationship(back_populates="contest")
    questions: Mapped[List["Question"]] = relationship(back_populates="contest")


# ملخص: متسابق في مسابقة (للروليت، التصويت، يستحق).
class ContestEntry(Base):
    __tablename__ = "contest_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contest_id: Mapped[int] = mapped_column(Integer, ForeignKey("contests.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    entry_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    unique_code: Mapped[Optional[str]] = mapped_column(String(32), unique=True, index=True)

    # Results
    votes_count: Mapped[int] = mapped_column(Integer, default=0)
    stars_received: Mapped[int] = mapped_column(Integer, default=0)
    score: Mapped[int] = mapped_column(Integer, default=0)  # For Quiz points

    joined_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    contest: Mapped["Contest"] = relationship(back_populates="entries")
    user: Mapped["User"] = relationship(back_populates="entries")
    votes_received: Mapped[List["Vote"]] = relationship(back_populates="entry")

    __table_args__ = (UniqueConstraint("contest_id", "user_id", name="uq_contest_user"),)


# ملخص: سجل التصويت.
class Vote(Base):
    __tablename__ = "votes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contest_id: Mapped[int] = mapped_column(Integer, ForeignKey("contests.id", ondelete="CASCADE"))
    entry_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("contest_entries.id", ondelete="CASCADE")
    )
    voter_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))

    is_stars: Mapped[bool] = mapped_column(Boolean, default=False)
    stars_amount: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    entry: Mapped["ContestEntry"] = relationship(back_populates="votes_received")
    voter: Mapped["User"] = relationship(back_populates="votes")


# ملخص: بوابة الاشتراك الإجباري لمسابقة معينة.
class RouletteGate(Base):
    __tablename__ = "roulette_gates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contest_id: Mapped[int] = mapped_column(Integer, ForeignKey("contests.id", ondelete="CASCADE"))
    channel_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    channel_title: Mapped[str] = mapped_column(String(256))
    invite_link: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    gate_type: Mapped[str] = mapped_column(
        String(16), default="channel"
    )  # channel/group/contest/vote

    contest: Mapped["Contest"] = relationship(back_populates="gates")


# ملخص: بنك الأسئلة لمسابقات الأسئلة.
class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contest_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("contests.id", ondelete="SET NULL"), nullable=True
    )
    question_text: Mapped[str] = mapped_column(Text)
    correct_answers_json: Mapped[str] = mapped_column(Text)  # JSON list of correct variants
    points: Mapped[int] = mapped_column(Integer, default=1)

    contest: Mapped["Contest"] = relationship(back_populates="questions")


# ملخص: صلاحيات الميزات المدفوعة.
class FeatureAccess(Base):
    __tablename__ = "feature_access"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    feature_key: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    one_time_credits: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (UniqueConstraint("user_id", "feature_key", name="uq_user_feature"),)


# ملخص: سجل المشتريات والمدفوعات (Telegram Stars).
class Purchase(Base):
    __tablename__ = "purchases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    stars_amount: Mapped[int] = mapped_column(Integer)
    payload: Mapped[str] = mapped_column(String(128))
    status: Mapped[PaymentStatus] = mapped_column(Enum(PaymentStatus), default=PaymentStatus.PAID)
    invoice_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    user: Mapped["User"] = relationship(back_populates="purchases")


# ملخص: إشعارات مرتبطة بالمستخدم والمسابقة.
class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    contest_id: Mapped[int] = mapped_column(Integer, ForeignKey("contests.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


# ملخص: إعدادات التطبيق العامة.
class AppSetting(Base):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(64), unique=True)
    value: Mapped[str] = mapped_column(Text)


# ملخص: سجل العمليات (Audit Logs).
class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    action: Mapped[str] = mapped_column(String(128))
    metadata_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


# ملخص: المحادثات التي يتواجد فيها البوت.
class BotChat(Base):
    __tablename__ = "bot_chats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    chat_type: Mapped[str] = mapped_column(String(16))
    title: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    removed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
