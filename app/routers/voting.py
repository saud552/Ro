from __future__ import annotations

import asyncio

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ..db import get_async_session
from ..db.models import ContestType
from ..keyboards.voting import voting_dual_kb, voting_main_kb
from ..services.voting import VotingService

voting_router = Router(name="voting")


class VotingFlow(StatesGroup):
    await_contestant_name = State()
    await_star_amount = State()


@voting_router.callback_query(F.data.startswith("vote:"))
async def handle_normal_vote(cb: CallbackQuery) -> None:
    parts = cb.data.split(":")
    contest_id = int(parts[1])
    entry_id = int(parts[2])

    async for session in get_async_session():
        service = VotingService(session)
        success = await service.add_vote(contest_id, entry_id, cb.from_user.id)
        if success:
            await cb.answer("✅ تم احتساب تصويتك بنجاح!")
        else:
            await cb.answer("⚠️ لا يمكنك التصويت مرة أخرى أو المسابقة مغلقة.", show_alert=True)


@voting_router.callback_query(F.data.startswith("reg_contest:"))
async def start_registration(cb: CallbackQuery, state: FSMContext) -> None:
    contest_id = int(cb.data.split(":")[1])
    await state.set_state(VotingFlow.await_contestant_name)
    await state.update_data(cid=contest_id)
    await cb.message.answer("يرجى إرسال الاسم الذي ترغب بالمشاركة به في المسابقة:")
    await cb.answer()


@voting_router.message(VotingFlow.await_contestant_name)
async def complete_registration(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    contest_id = data.get("cid")
    name = message.text.strip()

    async for session in get_async_session():
        service = VotingService(session)
        entry = await service.register_contestant(contest_id, message.from_user.id, name)
        await message.answer(f"✅ تم تسجيلك بنجاح! رمز التصويت الخاص بك هو: `{entry.unique_code}`")

    await state.clear()
