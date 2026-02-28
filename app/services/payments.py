from __future__ import annotations

import enum
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from aiogram import Bot
from aiogram.types import LabeledPrice
from sqlalchemy import select

from ..db import get_async_session
from ..db.models import AppSetting, PaymentStatus, Purchase
from ..db.repositories import FeatureAccessRepository, UserRepository

GATE_FEATURE_KEY = "gate_channel"
DEFAULT_MONTHLY_STARS = 100
DEFAULT_ONE_TIME_STARS = 10


class PaymentType(enum.Enum):
    MONTHLY = "gate_monthly"
    ONETIME = "gate_onetime"
    STAR_VOTE = "star_vote"


class PaymentService:
    """Unified service to handle Telegram Stars payments and user entitlements."""

    def __init__(
        self, bot: Bot, user_repo: UserRepository, feature_repo: FeatureAccessRepository
    ) -> None:
        self.bot = bot
        self.user_repo = user_repo
        self.feature_repo = feature_repo

    async def get_monthly_price(self) -> int:
        async for session in get_async_session():
            row = (
                await session.execute(
                    select(AppSetting).where(AppSetting.key == "price_month_value")
                )
            ).scalar_one_or_none()
            if row and str(row.value).isdigit():
                return int(row.value)
        return DEFAULT_MONTHLY_STARS

    async def get_onetime_price(self) -> int:
        async for session in get_async_session():
            row = (
                await session.execute(
                    select(AppSetting).where(AppSetting.key == "price_once_value")
                )
            ).scalar_one_or_none()
            if row and str(row.value).isdigit():
                return int(row.value)
        return DEFAULT_ONE_TIME_STARS

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
        purchase = Purchase(
            user_id=user_id,
            stars_amount=stars_amount,
            payload=payload,
            status=PaymentStatus.PAID,
            created_at=datetime.now(timezone.utc),
        )
        self.feature_repo.session.add(purchase)

        if payload == PaymentType.MONTHLY.value:
            await self.feature_repo.grant_monthly(user_id, GATE_FEATURE_KEY)
        elif payload == PaymentType.ONETIME.value:
            fa = await self.feature_repo.get_user_access(user_id, GATE_FEATURE_KEY)
            if not fa:
                from ..db.models import FeatureAccess

                fa = FeatureAccess(
                    user_id=user_id,
                    feature_key=GATE_FEATURE_KEY,
                    one_time_credits=1,
                )
                self.feature_repo.session.add(fa)
            else:
                fa.one_time_credits += 1

        await self.feature_repo.commit()


# --- Legacy Compatibility Helpers (to be phased out) ---


async def get_monthly_price_stars() -> int:
    async for session in get_async_session():
        row = (
            await session.execute(select(AppSetting).where(AppSetting.key == "price_month_value"))
        ).scalar_one_or_none()
        if row and str(row.value).isdigit():
            return int(row.value)
    return DEFAULT_MONTHLY_STARS


async def get_one_time_price_stars() -> int:
    async for session in get_async_session():
        row = (
            await session.execute(select(AppSetting).where(AppSetting.key == "price_once_value"))
        ).scalar_one_or_none()
        if row and str(row.value).isdigit():
            return int(row.value)
    return DEFAULT_ONE_TIME_STARS


async def has_gate_access(user_id: int, consume_one_time: bool = False) -> bool:
    async for session in get_async_session():
        repo = FeatureAccessRepository(session)
        return await repo.has_access(user_id, GATE_FEATURE_KEY, consume_one_time=consume_one_time)
    return False


async def grant_monthly(user_id: int) -> None:
    async for session in get_async_session():
        repo = FeatureAccessRepository(session)
        await repo.grant_monthly(user_id, GATE_FEATURE_KEY)


async def grant_one_time(user_id: int, credits: int = 1) -> None:
    async for session in get_async_session():
        repo = FeatureAccessRepository(session)
        fa = await repo.get_user_access(user_id, GATE_FEATURE_KEY)
        if not fa:
            from ..db.models import FeatureAccess

            fa = FeatureAccess(
                user_id=user_id, feature_key=GATE_FEATURE_KEY, one_time_credits=credits
            )
            await repo.add(fa)
        else:
            fa.one_time_credits += credits
        await repo.commit()


async def log_purchase(user_id: int, payload: str, stars_amount: int) -> None:
    async for session in get_async_session():
        repo = FeatureAccessRepository(session)
        await repo.log_purchase(user_id, payload, stars_amount)
