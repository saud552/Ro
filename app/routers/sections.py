from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from .roulette import CreateRoulette, start_create_flow
from ..db.models import ContestType

sections_router = Router(name="sections")


@sections_router.callback_query(F.data.startswith("section_"))
async def handle_sections(cb: CallbackQuery, state: FSMContext) -> None:
    section = cb.data.replace("section_", "")

    if section == "roulette":
        await start_create_flow(cb, state, ContestType.ROULETTE)
    elif section == "voting":
        await start_create_flow(cb, state, ContestType.VOTE)
    elif section == "yastahiq":
        await start_create_flow(cb, state, ContestType.YASTAHIQ)
    elif section == "quiz":
        await cb.message.answer("❓ قسم مسابقة الأسئلة: ستتم إضافة هذه الميزة في المرحلة الخامسة.")
    elif section == "manage_chats":
        await cb.message.answer(
            "⚙️ إدارة المجموعات أو القنوات: يمكنك ربط قنواتك من خلال تحويل رسالة منها للبوت."
        )
    elif section == "subscription":
        await cb.message.answer("💎 قسم إدارة الاشتراك: يمكنك ترقية حسابك للحصول على ميزات إضافية.")
    elif section == "my_contests":
        from .my import my_entry
        await my_entry(cb.message)
    elif section == "points":
        await cb.message.answer("💰 قسم كسب النقاط: شارك رابط الإحالة الخاص بك لكسب النقاط.")
    else:
        await cb.message.answer("قريباً...")

    await cb.answer()
