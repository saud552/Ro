from __future__ import annotations

from typing import List, Optional

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from sqlalchemy import select

from ..db import get_async_session
from ..db.models import Contest, ContestType, RouletteGate
from ..db.repositories import AppSettingRepository
from ..services.subscription import GateStatus, SubscriptionService
from ..utils.compat import safe_answer, safe_edit_text

system_router = Router(name="system")

class VerificationState(StatesGroup):
    pending = State()

def get_verification_kb(gates: List[GateStatus]) -> InlineKeyboardMarkup:
    """Build keyboard for pending tasks."""
    buttons = []
    for g in gates:
        if not g.is_passed:
            text = f"🔹 {g.gate.channel_title or g.gate.gate_type}"
            url = g.gate.invite_link
            if not url:
                # Custom handling for specific types if link is missing
                if g.gate.gate_type == "vote":
                    # Potentially link to a contest message if we had it
                    pass

            if url:
                buttons.append([InlineKeyboardButton(text=text, url=url)])
            else:
                buttons.append([InlineKeyboardButton(text=f"📌 {text}", callback_data="none")])

    buttons.append([InlineKeyboardButton(text="تم الإنجاز ✅", callback_data="verify_check")])
    buttons.append([InlineKeyboardButton(text="إلغاء ❌", callback_data="verify_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

async def show_verification_interface(cb: CallbackQuery, state: FSMContext, contest_id: int, entry_id: Optional[int], gates: List[GateStatus]):
    """Show the verification UI to the user."""
    await state.set_state(VerificationState.pending)
    await state.update_data(v_cid=contest_id, v_eid=entry_id)

    pending_count = sum(1 for g in gates if not g.is_passed)
    text = (
        f"⏳ <b>يتبقى عليك تنفيذ {pending_count} من المهام:</b>\n\n"
        "يرجى تنفيذ المهام المطلوبة أدناه ثم الضغط على زر التحقق.\n"
        "<i>لن يتم احتساب اشتراكك/تصويتك إلا بعد إتمام جميع المهام.</i>"
    )
    kb = get_verification_kb(gates)
    await safe_edit_text(cb.message, text, reply_markup=kb, parse_mode=ParseMode.HTML)

@system_router.callback_query(VerificationState.pending, F.data == "verify_check")
async def handle_verify_check(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    contest_id = data.get("v_cid")
    entry_id = data.get("v_eid")

    async for session in get_async_session():
        c = await session.get(Contest, contest_id)
        if not c:
            await state.clear()
            await safe_answer(cb, "⚠️ المسابقة غير موجودة.")
            return

        stmt = select(RouletteGate).where(RouletteGate.contest_id == contest_id)
        gates_list = (await session.execute(stmt)).scalars().all()

        sub_service = SubscriptionService(cb.bot, AppSettingRepository(session))
        results = await sub_service.verify_all_gates(cb.from_user.id, gates_list, session)

        pending = [r for r in results if not r.is_passed]
        if not pending:
            await state.clear()
            # Transition back to voting/joining logic
            if c.type == ContestType.VOTE:
                # If it's registration
                if entry_id is None:
                    from .voting import start_registration
                    cb.data = f"reg_contest:{contest_id}"
                    await start_registration(cb, state)
                else:
                    # If it's voting
                    from .voting import handle_normal_vote
                    cb.data = f"vote_norm:{contest_id}:{entry_id}"
                    await handle_normal_vote(cb, state)
            else:
                # Roulette join
                from .roulette import handle_join_request
                cb.data = f"join:{contest_id}"
                await handle_join_request(cb, state)
            return

        # Still have pending gates
        pending_titles = [g.gate.channel_title for g in pending]
        await safe_answer(cb, f"⚠️ يتبقى عليك: {', '.join(pending_titles[:2])}...", show_alert=True)

        # Refresh interface
        await show_verification_interface(cb, state, contest_id, entry_id, results)

@system_router.callback_query(VerificationState.pending, F.data == "verify_cancel")
async def handle_verify_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    from ..keyboards.common import main_menu_kb
    await safe_edit_text(cb.message, "❌ تم إلغاء العملية والعودة للبداية.", reply_markup=main_menu_kb())
    await cb.answer()
