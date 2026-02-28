from __future__ import annotations

import asyncio
from aiogram import F, Router, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.enums import ParseMode

from ..db import get_async_session
from ..services.quiz import QuizService
from ..db.models import Contest, ContestType
from .roulette import CreateRoulette

quiz_router = Router(name="quiz")

class CreateQuiz(StatesGroup):
    await_questions_count = State()
    await_interval = State()
    await_question_entry = State()

@quiz_router.callback_query(F.data == "create_quiz")
async def start_quiz_creation(cb: CallbackQuery, state: FSMContext) -> None:
    # This would be integrated into the main creation flow
    await state.set_state(CreateQuiz.await_questions_count)
    await cb.message.answer("كم عدد الأسئلة التي ترغب بإضافتها للمسابقة؟")
    await cb.answer()

@quiz_router.message(F.text, F.reply_to_message.from_user.id == F.bot.id)
async def handle_quiz_answer(message: Message) -> None:
    """Listen for answers in group/channel if applicable."""
    # Logic to identify which contest/question is active
    # This requires a 'current active question' tracker in Redis or DB
    pass

# Further implementation would include background tasks to post questions
# and a state machine to collect questions from the creator.
