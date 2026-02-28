from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Generic, List, Optional, Sequence, Type, TypeVar

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    AppSetting,
    AuditLog,
    BotChat,
    Contest,
    ContestEntry,
    FeatureAccess,
    Purchase,
    Question,
    User,
    Vote,
)

T = TypeVar("T")


class BaseRepository(Generic[T]):
    """Base repository with common database operations."""

    def __init__(self, session: AsyncSession, model: Type[T]) -> None:
        self.session = session
        self.model = model

    async def get_by_id(self, id: int | str) -> Optional[T]:
        """Fetch a record by primary key."""
        return await self.session.get(self.model, id)

    async def get_all(self, limit: int = 100, offset: int = 0) -> Sequence[T]:
        """Fetch all records with pagination."""
        stmt = select(self.model).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def add(self, entity: T) -> T:
        """Add a new entity and flush to get its ID."""
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def delete(self, entity: T) -> None:
        """Delete an entity from the database."""
        await self.session.delete(entity)

    async def commit(self) -> None:
        """Commit the current transaction."""
        await self.session.commit()


class UserRepository(BaseRepository[User]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, User)

    async def get_or_create(self, user_id: int, username: Optional[str] = None) -> User:
        """Fetch user by ID or create if not exists, updating username."""
        user = await self.get_by_id(user_id)
        if user:
            if username and user.username != username:
                user.username = username
            return user

        user = User(id=user_id, username=username)
        await self.add(user)
        return user


class ContestRepository(BaseRepository[Contest]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Contest)

    async def get_by_code(self, code: str) -> Optional[Contest]:
        """Fetch a contest by its unique code."""
        stmt = select(Contest).where(Contest.unique_code == code)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()


class ContestEntryRepository(BaseRepository[ContestEntry]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, ContestEntry)

    async def get_entry(self, contest_id: int, user_id: int) -> Optional[ContestEntry]:
        """Fetch specific user entry in a contest."""
        stmt = select(ContestEntry).where(
            ContestEntry.contest_id == contest_id, ContestEntry.user_id == user_id
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def count_participants(self, contest_id: int) -> int:
        """Return total participant count for a contest."""
        stmt = (
            select(func.count())
            .select_from(ContestEntry)
            .where(ContestEntry.contest_id == contest_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()


class VoteRepository(BaseRepository[Vote]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Vote)

    async def has_voted(self, contest_id: int, voter_id: int) -> bool:
        """Check if user has already voted in a specific contest."""
        stmt = select(Vote).where(Vote.contest_id == contest_id, Vote.voter_id == voter_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None


class FeatureAccessRepository(BaseRepository[FeatureAccess]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, FeatureAccess)

    async def get_user_access(self, user_id: int, feature_key: str) -> Optional[FeatureAccess]:
        """Fetch user entitlement for a feature."""
        stmt = select(FeatureAccess).where(
            FeatureAccess.user_id == user_id, FeatureAccess.feature_key == feature_key
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def has_access(
        self, user_id: int, feature_key: str, consume_one_time: bool = False
    ) -> bool:
        """Check if user has valid monthly or one-time credit access."""
        fa = await self.get_user_access(user_id, feature_key)
        if not fa:
            return False

        now = datetime.now(timezone.utc)
        expires_at = fa.expires_at
        if expires_at:
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at > now:
                return True

        if fa.one_time_credits > 0:
            if consume_one_time:
                fa.one_time_credits -= 1
                await self.session.commit()
            return True

        return False

    async def grant_monthly(self, user_id: int, feature_key: str, days: int = 30) -> None:
        """Grant or extend monthly access."""
        fa = await self.get_user_access(user_id, feature_key)
        now = datetime.now(timezone.utc)
        if not fa:
            fa = FeatureAccess(
                user_id=user_id, feature_key=feature_key, expires_at=now + timedelta(days=days)
            )
            await self.add(fa)
        else:
            base = fa.expires_at
            if base:
                if base.tzinfo is None:
                    base = base.replace(tzinfo=timezone.utc)
                base = max(base, now)
            else:
                base = now
            fa.expires_at = base + timedelta(days=days)
        await self.session.commit()


class AppSettingRepository(BaseRepository[AppSetting]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, AppSetting)

    async def get_value(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Fetch a setting value by key."""
        stmt = select(AppSetting.value).where(AppSetting.key == key)
        result = await self.session.execute(stmt)
        val = result.scalar_one_or_none()
        return val if val is not None else default

    async def set_value(self, key: str, value: str) -> None:
        """Upsert a setting value."""
        stmt = select(AppSetting).where(AppSetting.key == key)
        result = await self.session.execute(stmt)
        setting = result.scalar_one_or_none()
        if setting:
            setting.value = value
        else:
            await self.add(AppSetting(key=key, value=value))
        await self.session.commit()


class AuditRepository(BaseRepository[AuditLog]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, AuditLog)

    async def log(
        self, action: str, user_id: Optional[int] = None, metadata: Optional[dict] = None
    ) -> None:
        """Log a system action with metadata."""
        log_entry = AuditLog(
            user_id=user_id,
            action=action,
            metadata_json=json.dumps(metadata) if metadata else None,
        )
        await self.add(log_entry)
        await self.session.commit()
