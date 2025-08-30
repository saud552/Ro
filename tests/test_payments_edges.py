from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("BOT_TOKEN", "TEST_TOKEN")
os.environ.setdefault("BOT_CHANNEL", "@test")


class _SP:
    def __init__(self, payload: str, total_amount: int, currency: str):
        self.invoice_payload = payload
        self.total_amount = total_amount
        self.currency = currency


class _Bot:
    def __init__(self):
        self.messages = []

    async def send_message(self, chat_id: int, text: str, **kwargs):
        self.messages.append(text)


@pytest.mark.asyncio
async def test_currency_mismatch_message():
    from app.routers.roulette import on_successful_payment

    bot = _Bot()

    async def _answer(text: str, *args, **kwargs):
        bot.messages.append(text)

    cb_msg = SimpleNamespace(
        from_user=SimpleNamespace(id=77),
        successful_payment=_SP(payload="gate_monthly", total_amount=100, currency="USD"),
        bot=bot,
        answer=_answer,
    )
    await on_successful_payment(cb_msg)
    assert any("غير مدعومة" in m for m in bot.messages)


@pytest.mark.asyncio
async def test_free_tier_grant_when_price_zero(monkeypatch):
    from app.routers.roulette import on_successful_payment
    from app.services import payments as _p

    # Force prices to zero
    async def _zero_month():
        return 0

    async def _zero_once():
        return 0

    monkeypatch.setattr(_p, "get_monthly_price_stars", _zero_month)
    monkeypatch.setattr(_p, "get_one_time_price_stars", _zero_once)

    bot = _Bot()

    async def _answer(text: str, *args, **kwargs):
        bot.messages.append(text)

    cb_msg = SimpleNamespace(
        from_user=SimpleNamespace(id=88),
        successful_payment=_SP(payload="gate_onetime", total_amount=0, currency="XTR"),
        bot=bot,
        answer=_answer,
    )
    await on_successful_payment(cb_msg)
    # Should acknowledge free-tier grant
    assert any("تم إضافة رصيد استخدام واحد" in m or "تم تفعيل اشتراك" in m for m in bot.messages)
