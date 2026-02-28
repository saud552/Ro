from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import FeatureAccess, Purchase


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