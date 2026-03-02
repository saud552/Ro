from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Optional

from aiogram import Bot
from aiogram.types import LabeledPrice
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_async_session
from ..db.models import AppSetting, FeatureAccess, PaymentStatus, Purchase
from ..db.repositories import FeatureAccessRepository, UserRepository

GATE_FEATURE_KEY = "gate_channel"
DEFAULT_MONTHLY_STARS = 100
DEFAULT_ONE_TIME_STARS = 10


class PaymentType(enum.Enum):
    MONTHLY = "gate_monthly"
    ONETIME = "gate_onetime"
    STAR_VOTE = "star_vote"


# --- Internal Core Logic (Unified) ---


async def _get_monthly_price(session: AsyncSession) -> int:
    row = (
        await session.execute(select(AppSetting).where(AppSetting.key == "price_month_value"))
    ).scalar_one_or_none()
    if row and str(row.value).isdigit():
        return int(row.value)
    return DEFAULT_MONTHLY_STARS


async def _get_onetime_price(session: AsyncSession) -> int:
    row = (
        await session.execute(select(AppSetting).where(AppSetting.key == "price_once_value"))
    ).scalar_one_or_none()
    if row and str(row.value).isdigit():
        return int(row.value)
    return DEFAULT_ONE_TIME_STARS


async def _has_gate_access(user_id: int, consume_one_time: bool, session: AsyncSession) -> bool:
    repo = FeatureAccessRepository(session)
    return await repo.has_access(user_id, GATE_FEATURE_KEY, consume_one_time=consume_one_time)


async def _grant_monthly(user_id: int, session: AsyncSession) -> None:
    repo = FeatureAccessRepository(session)
    await repo.grant_monthly(user_id, GATE_FEATURE_KEY)


async def _grant_one_time(user_id: int, credits: int, session: AsyncSession) -> None:
    repo = FeatureAccessRepository(session)
    fa = await repo.get_user_access(user_id, GATE_FEATURE_KEY)
    if not fa:
        fa = FeatureAccess(user_id=user_id, feature_key=GATE_FEATURE_KEY, one_time_credits=credits)
        await repo.add(fa)
    else:
        fa.one_time_credits += credits
    await repo.commit()


async def _log_purchase(
    user_id: int, payload: str, stars_amount: int, session: AsyncSession
) -> None:
    purchase = Purchase(
        user_id=user_id,
        stars_amount=stars_amount,
        payload=payload,
        status=PaymentStatus.PAID,
        created_at=datetime.now(timezone.utc),
    )
    session.add(purchase)
    await session.commit()


# --- Unified Service Class ---


class PaymentService:
    """Unified service to handle Telegram Stars payments and user entitlements."""

    def __init__(
        self, bot: Bot, user_repo: UserRepository, feature_repo: FeatureAccessRepository
    ) -> None:
        self.bot = bot
        self.user_repo = user_repo
        self.feature_repo = feature_repo

    async def get_monthly_price(self) -> int:
        return await _get_monthly_price(self.feature_repo.session)

    async def get_onetime_price(self) -> int:
        return await _get_onetime_price(self.feature_repo.session)

    async def create_star_invoice(
        self,
        user_id: int,
        title: str,
        description: str,
        payload: str,
        stars_amount: int,
    ) -> None:
        """Sends an invoice to the user for Telegram Stars payment."""
        prices = [LabeledPrice(label=title, amount=stars_amount)]
        await self.bot.send_invoice(
            chat_id=user_id,
            title=title,
            description=description,
            payload=payload,
            currency="XTR",
            prices=prices,
        )

    async def process_successful_payment(
        self, user_id: int, payload: str, stars_amount: int
    ) -> None:
        """Handle logic after payment confirmation."""
        session = self.feature_repo.session
        await _log_purchase(user_id, payload, stars_amount, session)

        if payload == PaymentType.MONTHLY.value:
            await _grant_monthly(user_id, session)
        elif payload == PaymentType.ONETIME.value:
            await _grant_one_time(user_id, 1, session)

        await self.feature_repo.commit()


# --- Standalone Compatibility API ---


async def get_monthly_price_stars(session: Optional[AsyncSession] = None) -> int:
    if session:
        return await _get_monthly_price(session)
    async for s in get_async_session():
        return await _get_monthly_price(s)
    return DEFAULT_MONTHLY_STARS


async def get_one_time_price_stars(session: Optional[AsyncSession] = None) -> int:
    if session:
        return await _get_onetime_price(session)
    async for s in get_async_session():
        return await _get_onetime_price(s)
    return DEFAULT_ONE_TIME_STARS


async def has_gate_access(
    user_id: int, consume_one_time: bool = False, session: Optional[AsyncSession] = None
) -> bool:
    if session:
        return await _has_gate_access(user_id, consume_one_time, session)
    async for s in get_async_session():
        return await _has_gate_access(user_id, consume_one_time, s)
    return False


async def grant_monthly(user_id: int, session: Optional[AsyncSession] = None) -> None:
    if session:
        await _grant_monthly(user_id, session)
    else:
        async for s in get_async_session():
            await _grant_monthly(user_id, s)


async def grant_one_time(
    user_id: int, credits: int = 1, session: Optional[AsyncSession] = None
) -> None:
    if session:
        await _grant_one_time(user_id, credits, session)
    else:
        async for s in get_async_session():
            await _grant_one_time(user_id, credits, s)


async def log_purchase(
    user_id: int, payload: str, stars_amount: int, session: Optional[AsyncSession] = None
) -> None:
    if session:
        await _log_purchase(user_id, payload, stars_amount, session)
    else:
        async for s in get_async_session():
            await _log_purchase(user_id, payload, stars_amount, s)
