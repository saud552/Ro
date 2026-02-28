from __future__ import annotations

import enum
from typing import List, Optional

from aiogram import Bot
from aiogram.types import LabeledPrice

from ..db.models import PaymentStatus, Purchase
from ..db.repositories import FeatureAccessRepository, UserRepository
from .payments import DEFAULT_MONTHLY_STARS, DEFAULT_ONE_TIME_STARS, GATE_FEATURE_KEY


class PaymentType(enum.Enum):
    MONTHLY = "gate_monthly"
    ONETIME = "gate_onetime"
    STAR_VOTE = "star_vote"


class PaymentService:
    """Service to handle Telegram Stars payments and user entitlements."""

    def __init__(
        self, bot: Bot, user_repo: UserRepository, feature_repo: FeatureAccessRepository
    ) -> None:
        self.bot = bot
        self.user_repo = user_repo
        self.feature_repo = feature_repo

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
        )
        self.feature_repo.session.add(purchase)

        if payload == PaymentType.MONTHLY.value:
            await self.feature_repo.grant_monthly(user_id, GATE_FEATURE_KEY)
        elif payload == PaymentType.ONETIME.value:
            fa = await self.feature_repo.get_user_access(user_id, GATE_FEATURE_KEY)
            if not fa:
                from ..db.models import FeatureAccess

                fa = FeatureAccess(
                    user_id=user_id, feature_key=GATE_FEATURE_KEY, one_time_credits=1
                )
                self.feature_repo.session.add(fa)
            else:
                fa.one_time_credits += 1

        await self.feature_repo.commit()

    async def get_prices(self) -> dict:
        """Fetch current star prices from settings."""
        return {
            "monthly": DEFAULT_MONTHLY_STARS,
            "onetime": DEFAULT_ONE_TIME_STARS,
        }
