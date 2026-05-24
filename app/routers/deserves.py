from __future__ import annotations

import secrets

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ..db import get_async_session
from ..db.models import DeservesCandidate
from ..db.repositories import DeservesRepository
from ..keyboards.deserves import (
    deserves_confirm_kb,
    deserves_controls_kb,
    deserves_section_kb,
)

deserves_router = Router(name="deserves")


class DeservesStates(StatesGroup):
    await_channel_select = State()
    await_group_link = State()
    await_text = State()
    await_confirm = State()


def _generate_vote_code() -> str:
    return secrets.token_hex(8)


@deserves_router.callback_query(F.data == "section_deserves")
async def section_deserves(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    text = (
        '👏 قسم مسابقة "يستحق"\n\n'
        "أنشئ مسابقة تصويت بالتعليقات في المجموعات.\n"
        'المشاركون يضيفون تعليق "يستحق" للتصويتب.\n\n'
        "اختر من القائمة:"
    )
    await cb.message.edit_text(text, reply_markup=deserves_section_kb())
    await cb.answer()


@deserves_router.callback_query(F.data == "deserves_create")
async def create_deserves_contest(cb: CallbackQuery, state: FSMContext) -> None:
    text = "📺 اختر القناة:\n\n" "أعد توجيه رسالة من القناة أو اكتب معرف القناة."
    await cb.message.edit_text(text)
    await state.set_state(DeservesStates.await_channel_select)
    await cb.answer()


@deserves_router.message(StateFilter(DeservesStates.await_channel_select))
async def handle_deserves_channel(message: Message, state: FSMContext) -> None:
    channel_id = 0

    # Try to extract channel ID
    if message.forward_from_chat:
        channel_id = message.forward_from_chat.id
    elif message.text:
        text = message.text.strip()
        if text.startswith("-100") or text.isdigit():
            try:
                channel_id = int(text)
            except ValueError:
                pass

    if not channel_id:
        await message.answer("❌ لم أتمكن من تحديد القناة. حاول مرة أخرى.")
        return

    await state.update_data(channel_id=channel_id)
    await message.answer("👥 الآن اختر المجموعة:\n\n" "أعد توجيه رسالة من المجموعة أو اكتب معرفها.")
    await state.set_state(DeservesStates.await_group_link)


@deserves_router.message(StateFilter(DeservesStates.await_group_link))
async def handle_deserves_group(message: Message, state: FSMContext) -> None:
    group_id = 0

    if message.forward_from_chat:
        group_id = message.forward_from_chat.id
    elif message.text:
        text = message.text.strip()
        if text.startswith("-100") or text.lstrip("-").isdigit():
            try:
                group_id = int(text)
            except ValueError:
                pass

    if not group_id:
        await message.answer("❌ لم أتمكن من تحديد المجموعة. حاول مرة أخرى.")
        return

    await state.update_data(group_id=group_id)
    await message.answer("📝 أدخل نص المسابقة:\n\n" "اكتب النص الذي سيظهر في المسابقة.")
    await state.set_state(DeservesStates.await_text)


@deserves_router.message(StateFilter(DeservesStates.await_text))
async def handle_deserves_text(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    if not text:
        await message.answer("يرجى إدخال نص صحيح.")
        return

    await state.update_data(text_raw=text, text_style="plain")

    text_preview = f"📋 معاينة نص المسابقة:\n\n" f"{text}\n\n" "✅ تأكيد الإنشاء | ❌ إلغاء"
    await message.answer(text_preview, reply_markup=deserves_confirm_kb())
    await state.set_state(DeservesStates.await_confirm)


@deserves_router.callback_query(F.data == "deserves_confirm", StateFilter(DeservesStates))
async def confirm_deserves(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()

    async for session in get_async_session():
        repo = DeservesRepository(session)

        contest = await repo.create_contest(
            owner_id=cb.from_user.id,
            channel_id=data.get("channel_id", 0),
            group_id=data.get("group_id", 0),
            text_raw=data.get("text_raw", ""),
            text_style=data.get("text_style", "plain"),
        )

        # Post to channel
        try:
            from ..services.formatting import StyledText

            text_raw = data.get("text_raw", "")
            text_style = data.get("text_style", "plain")
            styled = StyledText(text_raw, text_style).render()

            msg = await cb.bot.send_message(
                chat_id=contest.channel_id,
                text=f'{styled}\n\n👏 مسابقة "يستحق" مفتوحة!',
                parse_mode=ParseMode.HTML,
            )
            contest.channel_message_id = msg.message_id
            await session.commit()
        except (TelegramBadRequest, TelegramForbiddenError):
            pass

    await state.clear()
    await cb.message.edit_text(
        f"✅ تم إنشاء المسابقة بنجاح!\n\n"
        f"🆔 رقم المسابقة: {contest.id}\n"
        f"👥 المجموعة: {data.get('group_id', 0)}"
    )
    await cb.answer()


@deserves_router.callback_query(F.data == "deserves_cancel", StateFilter(DeservesStates))
async def cancel_deserves(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cb.message.edit_text("❌ تم إلغاء إنشاء المسابقة.")
    await cb.answer()


@deserves_router.callback_query(F.data.startswith("deserves_join:"))
async def join_deserves(cb: CallbackQuery, state: FSMContext) -> None:
    vote_code = cb.data.split(":")[1]

    async for session in get_async_session():
        repo = DeservesRepository(session)
        candidate = await repo.get_candidate_by_code(vote_code)

        if candidate:
            await cb.answer("✅ أنت مسجل بالفعل!", show_alert=True)
            return

        # Create candidate
        try:
            display_name = cb.from_user.first_name or str(cb.from_user.id)
            await repo.add_candidate(
                contest_id=0,
                user_id=cb.from_user.id,
                display_name=display_name,
                vote_code=vote_code,
            )
            await cb.answer("✅ تم التسجيل بنجاح!", show_alert=True)
        except Exception as e:
            await cb.answer(f"❌ خطأ: {e}", show_alert=True)

    await cb.answer()


@deserves_router.callback_query(F.data.startswith("deserves_vote:"))
async def vote_deserves(cb: CallbackQuery) -> None:
    parts = cb.data.split(":")
    contest_id = int(parts[1])
    candidate_id = int(parts[2])

    async for session in get_async_session():
        repo = DeservesRepository(session)

        if await repo.has_voted(contest_id, candidate_id, cb.from_user.id):
            await cb.answer("❌你已经投过!", show_alert=True)
            return

        await repo.add_vote(contest_id, candidate_id, cb.from_user.id)

        # Update vote count
        candidate = await session.get(DeservesCandidate, candidate_id)
        if candidate:
            candidate.vote_count += 1
            await session.commit()

    await cb.answer("👏 تم التصويتب بنجاح!", show_alert=True)


@deserves_router.callback_query(F.data.startswith("deserves_end:"))
async def end_deserves(cb: CallbackQuery) -> None:
    contest_id = int(cb.data.split(":")[1])

    async for session in get_async_session():
        repo = DeservesRepository(session)
        contest = await repo.get_contest(contest_id)

        if not contest:
            await cb.answer("❌ المسابقة غير موجودة", show_alert=True)
            return

        if contest.owner_id != cb.from_user.id:
            await cb.answer("❌ ليس لديك صلاحية", show_alert=True)
            return

        await repo.end_contest(contest_id)

    await cb.answer("🔴 تم إنهاء المسابقة", show_alert=True)


@deserves_router.callback_query(F.data.startswith("deserves_results:"))
async def show_deserves_results(cb: CallbackQuery) -> None:
    contest_id = int(cb.data.split(":")[1])

    async for session in get_async_session():
        repo = DeservesRepository(session)
        contest = await repo.get_contest(contest_id)

        if not contest:
            await cb.answer("❌ المسابقة غير موجودة", show_alert=True)
            return

        from sqlalchemy import select

        from ..db.models import DeservesCandidate

        result = await session.execute(
            select(DeservesCandidate).where(DeservesCandidate.contest_id == contest_id)
        )
        candidates = list(result.scalars().all())

        text = f'📊 نتائج "يستحق" #{contest_id}\n\n'
        for i, c in enumerate(sorted(candidates, key=lambda x: x.vote_count, reverse=True), 1):
            text += f"{i}. {c.display_name}: {c.vote_count} صوت\n"

    await cb.message.edit_text(
        text, reply_markup=deserves_controls_kb(contest_id, contest.is_active)
    )
    await cb.answer()
