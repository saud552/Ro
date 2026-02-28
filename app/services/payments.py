from __future__ import annotations

from datetime import datetime, timedelta, timezone
from sqlalchemy import select

from ..db import get_async_session
from ..db.models import AppSetting
from ..db.repositories import FeatureAccessRepository

GATE_FEATURE_KEY = "gate_channel"
DEFAULT_MONTHLY_STARS = 100
DEFAULT_ONE_TIME_STARS = 10


# ملخص: إرجاع سعر الاشتراك الشهري بالنجوم من الإعدادات أو القيمة الافتراضية.
async def get_monthly_price_stars() -> int:
    async for session in get_async_session():
        row = (
            await session.execute(select(AppSetting).where(AppSetting.key == "price_month_value"))
        ).scalar_one_or_none()
        if row and str(row.value).isdigit():
            return int(row.value)
    return DEFAULT_MONTHLY_STARS


# ملخص: إرجاع سعر الرصيد لمرة واحدة بالنجوم من الإعدادات أو القيمة الافتراضية.
async def get_one_time_price_stars() -> int:
    async for session in get_async_session():
        row = (
            await session.execute(select(AppSetting).where(AppSetting.key == "price_once_value"))
        ).scalar_one_or_none()
        if row and str(row.value).isdigit():
            return int(row.value)
    return DEFAULT_ONE_TIME_STARS


# ملخص: يتحقق من صلاحية البوابة للمستخدم مع خيار استهلاك رصيد لمرة واحدة.
async def has_gate_access(user_id: int, consume_one_time: bool = False) -> bool:
    """Check if user has valid gate access."""
    async for session in get_async_session():
        repo = FeatureAccessRepository(session)
        return await repo.has_access(user_id, GATE_FEATURE_KEY, consume_one_time=consume_one_time)
    return False


# ملخص: يمنح أو يمدد اشتراك المستخدم لمدة 30 يوماً.
async def grant_monthly(user_id: int) -> None:
    """Grant or extend monthly access by 30 days."""
    async for session in get_async_session():
        repo = FeatureAccessRepository(session)
        await repo.grant_monthly(user_id, GATE_FEATURE_KEY)


# ملخص: يضيف رصيد دخول لمرة واحدة للمستخدم.
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


# ملخص: يسجّل عملية شراء النجوم في قاعدة البيانات.
async def log_purchase(user_id: int, payload: str, stars_amount: int) -> None:
    async for session in get_async_session():
        repo = FeatureAccessRepository(session)
        await repo.log_purchase(user_id, payload, stars_amount)
