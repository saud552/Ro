from __future__ import annotations

from typing import List, Optional

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select

from ..db import get_async_session
from ..db.models import RouletteGate
from ..db.repositories import AppSettingRepository, ContestRepository
from ..services.subscription import GateStatus, SubscriptionService
from ..utils.compat import safe_edit_text

system_router = Router(name="system")


async def show_verification_interface(
    cb: CallbackQuery,
    state: FSMContext,
    contest_id: int,
    entry_id: Optional[int],
    results: List[GateStatus],
) -> None:
    """Displays the task list UI for unmet conditions."""
    lines = ["⚠️ <b>يجب إكمال المهام التالية للمتابعة:</b>\n"]
    rows = []

    for r in results:
        if not r.is_passed:
            status_icon = "❌"
            if r.error_type == "system_failure":
                status_icon = "⚠️ (مشكلة تقنية)"

            lines.append(f"{status_icon} {r.gate_title}")

            if r.gate_link:
                rows.append([InlineKeyboardButton(text=f"🔗 {r.gate_title}", url=r.gate_link)])

    rows.append(
        [
            InlineKeyboardButton(
                text="تم الإنجاز، استمرار ✅",
                callback_data=f"gate_done:{contest_id}:{entry_id}",
            )
        ]
    )

    text = "\n".join(lines)
    text += "\n\nبعد إكمال المهام، اضغط على الزر أدناه للتحقق."

    if cb.id == "0":  # From deep link
        await cb.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    else:
        await safe_edit_text(cb.message, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@system_router.callback_query(F.data.startswith("gate_done:"))
async def handle_verification_done(cb: CallbackQuery, state: FSMContext) -> None:
    parts = cb.data.split(":")
    contest_id = int(parts[1])
    entry_val = parts[2]
    entry_id = int(entry_val) if entry_val != "None" else None

    async for session in get_async_session():
        repo = ContestRepository(session)
        c = await repo.get_by_id(contest_id)
        if not c:
            await cb.answer("⚠️ المسابقة لم تعد موجودة.", show_alert=True)
            return

        gates = (
            (
                await session.execute(
                    select(RouletteGate).where(RouletteGate.contest_id == contest_id)
                )
            )
            .scalars()
            .all()
        )
        sub_service = SubscriptionService(cb.bot, AppSettingRepository(session))
        results = await sub_service.verify_all_conditions(cb.from_user.id, c, gates, session)

        pending = [r for r in results if not r.is_passed]
        if pending:
            await cb.answer("⚠️ لم يتم إكمال جميع المهام بعد!", show_alert=True)
            await show_verification_interface(cb, state, contest_id, entry_id, results)
            return

        # Success! Dispatch back to original logic
        await cb.answer("✅ تم التحقق بنجاح!", show_alert=True)

        if entry_id:
            from .voting import handle_normal_vote

            cb.data = f"vote_norm:{contest_id}:{entry_id}"
            await handle_normal_vote(cb, state)
        else:
            from ..db.models import ContestType

            if c.type == ContestType.VOTE:
                from .voting import start_registration

                cb.data = f"reg_contest:{contest_id}"
                await start_registration(cb, state)
            else:
                from .roulette import handle_join_request

                cb.data = f"join:{contest_id}"
                await handle_join_request(cb, state)
