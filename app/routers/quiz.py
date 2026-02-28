from __future__ import annotations

import asyncio
from aiogram import F, Router, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.enums import ParseMode
from sqlalchemy import select
from datetime import datetime, timezone

from ..db import get_async_session
from ..services.quiz import QuizService
from ..db.models import Contest, ContestType, Question
from .roulette import CreateRoulette, start_create_flow

quiz_router = Router(name="quiz")

class CreateQuiz(StatesGroup):
    await_questions_count = State()
    await_interval = State()

@quiz_router.callback_query(F.data == "create_quiz")
async def start_quiz_creation(cb: CallbackQuery, state: FSMContext) -> None:
    await start_create_flow(cb, state, ContestType.QUIZ)

@quiz_router.callback_query(F.data.startswith("quiz_stop:"))
async def stop_quiz(cb: CallbackQuery) -> None:
    contest_id = int(cb.data.split(":")[1])
    async for session in get_async_session():
        c = await session.get(Contest, contest_id)
        if c and c.owner_id == cb.from_user.id:
            c.is_open = False
            await session.commit()
            await cb.answer("🛑 تم إيقاف الكويز مؤقتاً.", show_alert=True)
        else:
            await cb.answer("غير مصرح", show_alert=True)

@quiz_router.callback_query(F.data.startswith("quiz_finish:"))
async def finish_quiz(cb: CallbackQuery) -> None:
    contest_id = int(cb.data.split(":")[1])
    async for session in get_async_session():
        service = QuizService(session)
        c = await session.get(Contest, contest_id)
        if not c or c.owner_id != cb.from_user.id:
            await cb.answer("غير مصرح", show_alert=True)
            return

        winners = await service.get_leaderboard(contest_id, limit=c.winners_count)

        text = f"🏁 <b>انتهت المسابقة الثقافية!</b>\n\n<b>الفائزون:</b>\n"
        for idx, w in enumerate(winners, start=1):
            text += f"{idx}. <a href='tg://user?id={w.user_id}'>المتسابق</a> — {w.score} نقطة\n"

        await cb.bot.send_message(c.channel_id, text, parse_mode=ParseMode.HTML)
        c.is_open = False
        c.closed_at = datetime.now(timezone.utc)
        await session.commit()
        await cb.answer("✅ تم إعلان النتائج.")

async def _run_quiz_session(bot: Bot, contest_id: int):
    """Background task to manage question posting for a quiz."""
    async for session in get_async_session():
        from ..services.context import runtime
        service = QuizService(session, redis=runtime.redis)
        c = await session.get(Contest, contest_id)
        if not c or not c.is_open:
            return

        questions = await service.get_contest_questions(contest_id)
        if not questions:
            # Fallback to general bank if specific questions not added
            stmt = select(Question).where(Question.contest_id == 0).limit(c.questions_count)
            questions = list((await session.execute(stmt)).scalars().all())

        for i, q in enumerate(questions[:c.questions_count]):
            if not c.is_open:
                break

            await service.set_active_question(c.id, q.id)
            msg = await bot.send_message(
                c.channel_id,
                f"❓ <b>السؤال {i+1}:</b>\n\n{q.question_text}",
                parse_mode=ParseMode.HTML
            )

            # Wait for interval or until solved
            start_time = asyncio.get_event_loop().time()
            while asyncio.get_event_loop().time() - start_time < c.interval_seconds:
                if await runtime.redis.get(f"quiz:{c.id}:solved"):
                    break
                await asyncio.sleep(1)

            await asyncio.sleep(2) # Brief pause before next

        # Finish automatically if all questions asked
        if c.is_open:
            # Trigger finish logic
            pass

@quiz_router.message(F.chat.type.in_({"group", "supergroup"}))
async def handle_quiz_answer_group(message: Message) -> None:
    if not message.text:
        return

    async for session in get_async_session():
        from ..services.context import runtime
        service = QuizService(session, redis=runtime.redis)

        stmt = select(Contest).where(
            Contest.channel_id == message.chat.id,
            Contest.type == ContestType.QUIZ,
            Contest.is_open.is_(True)
        )
        res = await session.execute(stmt)
        c = res.scalar_one_or_none()

        if c:
            question = await service.submit_fastest_answer(c.id, message.from_user.id, message.text)
            if question:
                await message.reply(
                    f"🎯 <b>إجابة صحيحة من <a href='tg://user?id={message.from_user.id}'>{message.from_user.full_name}</a>!</b>\n"
                    f"حصلت على {question.points} نقطة.",
                    parse_mode=ParseMode.HTML
                )
