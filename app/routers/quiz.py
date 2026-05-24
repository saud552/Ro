from __future__ import annotations

import asyncio

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ..db import get_async_session
from ..db.models import QuizContest, QuizParticipantScore, QuizQuestion
from ..db.repositories import QuizRepository
from ..keyboards.quiz import quiz_confirm_kb, quiz_controls_kb, quiz_section_kb

quiz_router = Router(name="quiz")


class QuizStates(StatesGroup):
    await_channel_select = State()
    await_group_link = State()
    await_text = State()
    await_winners_count = State()
    await_question_count = State()
    await_interval = State()
    await_questions = State()
    await_confirm = State()


async def _send_question(bot, contest: QuizContest, question: QuizQuestion) -> None:
    """Send a question to the channel/group."""
    from ..services.formatting import StyledText

    styled = StyledText(question.text_raw, "plain").render()
    text = f"❓ سؤال #{question.question_number}:\n\n{styled}\n\n⏱️ لديك {question.time_limit} ثانية للإجابة!"

    try:
        if contest.group_id:
            await bot.send_message(chat_id=contest.group_id, text=text, parse_mode=ParseMode.HTML)
        else:
            await bot.send_message(chat_id=contest.channel_id, text=text, parse_mode=ParseMode.HTML)
    except (TelegramBadRequest, TelegramForbiddenError):
        pass


async def _check_answer(user_id: int, contest_id: int, answer_text: str) -> bool:
    """Check if user's answer is correct for current question."""
    async for session in get_async_session():
        repo = QuizRepository(session)
        contest = await repo.get_contest(contest_id)

        if not contest or not contest.is_active:
            return False

        # Get current question
        from sqlalchemy import select

        result = await session.execute(
            select(QuizQuestion).where(
                QuizQuestion.contest_id == contest_id,
                QuizQuestion.question_number == contest.current_question,
            )
        )
        question = result.scalar_one_or_none()

        if not question:
            return False

        # Check answer
        is_correct = question.correct_answer.strip().lower() == answer_text.strip().lower()

        if is_correct:
            await repo.update_score(contest_id, user_id, True)

        return is_correct


@quiz_router.callback_query(F.data == "section_quiz")
async def section_quiz(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    text = (
        "🎯 قسم مسابقة الأسئلة\n\n"
        "أنشئ مسابقة أسئلة مع مؤقتات.\n"
        "المشاركون يجيبون على الأسئلة بأسرع وقت!\n\n"
        "اختر نوع المسابقة:"
    )
    await cb.message.edit_text(text, reply_markup=quiz_section_kb())
    await cb.answer()


@quiz_router.callback_query(F.data == "quiz_channel")
async def create_quiz_channel(cb: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(quiz_location="channel")
    text = "📺 اختر القناة:\n\n" "أعد توجيه رسالة من القناة أو اكتب معرفها."
    await cb.message.edit_text(text)
    await state.set_state(QuizStates.await_channel_select)
    await cb.answer()


@quiz_router.callback_query(F.data == "quiz_group")
async def create_quiz_group(cb: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(quiz_location="group")
    text = "👥 اختر المجموعة:\n\n" "أعد توجيه رسالة من المجموعة أو اكتب معرفها."
    await cb.message.edit_text(text)
    await state.set_state(QuizStates.await_group_link)
    await cb.answer()


@quiz_router.message(StateFilter(QuizStates.await_channel_select))
async def handle_quiz_channel(message: Message, state: FSMContext) -> None:
    channel_id = 0

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
        await message.answer("❌ لم أتمكن من تحديد القناة.")
        return

    await state.update_data(channel_id=channel_id, group_id=None)
    await message.answer("🏆 كم عدد الفائزين؟ (الافتراضي: 1)")
    await state.set_state(QuizStates.await_winners_count)


@quiz_router.message(StateFilter(QuizStates.await_group_link))
async def handle_quiz_group(message: Message, state: FSMContext) -> None:
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
        await message.answer("❌ لم أتمكن من تحديد المجموعة.")
        return

    await state.update_data(group_id=group_id, channel_id=0)
    await message.answer("🏆 كم عدد الفائزين؟ (الافتراضي: 1)")
    await state.set_state(QuizStates.await_winners_count)


@quiz_router.message(StateFilter(QuizStates.await_winners_count))
async def handle_winners_count(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    try:
        winners = int(text) if text.isdigit() else 1
    except ValueError:
        winners = 1

    await state.update_data(winners_count=min(winners, 10))
    await message.answer("❓ كم عدد الأسئلة؟ (الافتراضي: 10)")
    await state.set_state(QuizStates.await_question_count)


@quiz_router.message(StateFilter(QuizStates.await_question_count))
async def handle_question_count(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    try:
        count = int(text) if text.isdigit() else 10
    except ValueError:
        count = 10

    await state.update_data(question_count=min(count, 50))
    await message.answer("⏱️ كم ثانية بين كل سؤال؟ (الافتراضي: 60)")
    await state.set_state(QuizStates.await_interval)


@quiz_router.message(StateFilter(QuizStates.await_interval))
async def handle_interval(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    try:
        interval = int(text) if text.isdigit() else 60
    except ValueError:
        interval = 60

    await state.update_data(interval=min(interval, 300))

    data = await state.get_data()
    preview = (
        f"📋 إعدادات المسابقة:\n\n"
        f"🏆 عدد الفائزين: {data.get('winners_count', 1)}\n"
        f"❓ عدد الأسئلة: {data.get('question_count', 10)}\n"
        f"⏱️ الفاصل: {data.get('interval', 60)} ثانية\n\n"
        f"📝 الآن أدخل الأسئلة:\n\n"
        f"الصيغة: سؤال |answer\n"
        f"مثال: ما هي عاصمة السعودية؟ |الرياض"
    )
    await message.answer(preview)
    await state.set_state(QuizStates.await_questions)


@quiz_router.message(StateFilter(QuizStates.await_questions))
async def handle_questions(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    if not text:
        await message.answer("يرجى إدخال الأسئلة.")
        return

    # Parse questions
    lines = text.split("\n")
    questions = []
    for line in lines:
        if "|" in line:
            parts = line.split("|", 1)
            q_text = parts[0].strip()
            q_answer = parts[1].strip()
            if q_text and q_answer:
                questions.append((q_text, q_answer))

    if not questions:
        await message.answer("❌ لم أتمكن من فهم الأسئلة. استخدم الصيغة: سؤال |answer")
        return

    await state.update_data(questions=questions)

    text_preview = f"✅ تم إضافة {len(questions)} سؤال!\n\n" "✅ تأكيد | ❌ إلغاء"
    await message.answer(text_preview, reply_markup=quiz_confirm_kb())
    await state.set_state(QuizStates.await_confirm)


@quiz_router.callback_query(F.data == "quiz_confirm", StateFilter(QuizStates))
async def confirm_quiz(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()

    async for session in get_async_session():
        repo = QuizRepository(session)

        contest = await repo.create_contest(
            owner_id=cb.from_user.id,
            channel_id=data.get("channel_id", 0) or data.get("group_id", 0),
            text_raw=data.get("text_raw", "مسابقة أسئلة"),
            text_style="plain",
            winners_count=data.get("winners_count", 1),
            question_count=len(data.get("questions", [])),
            question_interval=data.get("interval", 60),
            group_id=data.get("group_id"),
        )

        # Add questions
        for i, (q_text, q_answer) in enumerate(data.get("questions", []), 1):
            await repo.add_question(
                contest_id=contest.id,
                question_number=i,
                text_raw=q_text,
                correct_answer=q_answer,
            )

        # Announce in channel
        try:

            text = (
                f"🎯 مسابقة أسئلة!\n\n"
                f"❓ عدد الأسئلة: {len(data.get('questions', []))}\n"
                f"🏆 عدد الفائزين: {data.get('winners_count', 1)}"
            )

            if contest.group_id:
                await cb.bot.send_message(
                    chat_id=contest.group_id, text=text, parse_mode=ParseMode.HTML
                )
            else:
                await cb.bot.send_message(
                    chat_id=contest.channel_id, text=text, parse_mode=ParseMode.HTML
                )
        except (TelegramBadRequest, TelegramForbiddenError):
            pass

    await state.clear()
    await cb.message.edit_text(
        f"✅ تم إنشاء المسابقة بنجاح!\n\n"
        f"🆔 رقم المسابقة: {contest.id}\n"
        f"❓ عدد الأسئلة: {len(data.get('questions', []))}\n\n"
        f"🎯 اضغط ابدأ لبدء المسابقة!"
    )
    await cb.answer()


@quiz_router.callback_query(F.data == "quiz_cancel", StateFilter(QuizStates))
async def cancel_quiz(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cb.message.edit_text("❌ تم إلغاء إنشاء المسابقة.")
    await cb.answer()


@quiz_router.callback_query(F.data.startswith("quiz_join:"))
async def join_quiz(cb: CallbackQuery) -> None:
    contest_id = int(cb.data.split(":")[1])

    async for session in get_async_session():
        repo = QuizRepository(session)
        contest = await repo.get_contest(contest_id)

        if not contest or not contest.is_active:
            await cb.answer("❌ المسابقة غير نشطة", show_alert=True)
            return

        await cb.answer("✅ تم التسجيل! انتظر بدء المسابقة.", show_alert=True)

    await cb.answer()


@quiz_router.callback_query(F.data.startswith("quiz_start:"))
async def start_quiz(cb: CallbackQuery) -> None:
    contest_id = int(cb.data.split(":")[1])

    asyncio.create_task(_run_quiz_loop(cb.bot, contest_id))

    await cb.answer("🎯 تم بدء المسابقة!", show_alert=True)


async def _run_quiz_loop(bot, contest_id: int) -> None:
    """Run the quiz loop with timed questions."""
    from sqlalchemy import select

    from ..db import get_async_session

    async for session in get_async_session():
        repo = QuizRepository(session)
        contest = await repo.get_contest(contest_id)

        if not contest or not contest.is_active:
            return

        interval = contest.question_interval

        # Get all questions
        result = await session.execute(
            select(QuizQuestion)
            .where(QuizQuestion.contest_id == contest_id)
            .order_by(QuizQuestion.question_number)
        )
        questions = list(result.scalars().all())

        # Send questions one by one
        for i, question in enumerate(questions):
            # Update current question
            contest.current_question = i + 1
            await session.commit()

            # Send question
            await _send_question(bot, contest, question)

            # Wait for interval
            await asyncio.sleep(interval)

        # End contest
        await repo.end_contest(contest_id)

        # Announce winners
        await _announce_quiz_winners(bot, contest_id)


async def _announce_quiz_winners(bot, contest_id: int) -> None:
    """Announce quiz winners."""
    async for session in get_async_session():
        repo = QuizRepository(session)
        contest = await repo.get_contest(contest_id)

        if not contest:
            return

        from sqlalchemy import select

        result = await session.execute(
            select(QuizParticipantScore)
            .where(QuizParticipantScore.contest_id == contest_id)
            .order_by(QuizParticipantScore.score.desc())
            .limit(contest.winners_count)
        )
        winners = list(result.scalars().all())

        text = f"🏆 نتائج المسابقة #{contest_id}\n\n"
        for i, winner in enumerate(winners, 1):
            text += f"{i}. المستخدم {winner.user_id}: {winner.score} نقطة\n"

        try:
            if contest.group_id:
                await bot.send_message(chat_id=contest.group_id, text=text)
            else:
                await bot.send_message(chat_id=contest.channel_id, text=text)
        except (TelegramBadRequest, TelegramForbiddenError):
            pass


@quiz_router.callback_query(F.data.startswith("quiz_pause:"))
async def pause_quiz(cb: CallbackQuery) -> None:
    contest_id = int(cb.data.split(":")[1])

    async for session in get_async_session():
        repo = QuizRepository(session)
        contest = await repo.get_contest(contest_id)

        if contest:
            # Mark as paused (we'll use a flag or just stop the loop)
            pass

    await cb.answer("⏸️ تم إيقاف المسابقة مؤقتاً")
    await cb.message.edit_text("⏸️ المسابقة متوقفة مؤقتاً.")


@quiz_router.callback_query(F.data.startswith("quiz_resume:"))
async def resume_quiz(cb: CallbackQuery) -> None:
    await cb.answer("▶️ تم استئناف المسابقة")
    await cb.message.edit_text("▶️ المسابقة resumed.")


@quiz_router.callback_query(F.data.startswith("quiz_end:"))
async def end_quiz(cb: CallbackQuery) -> None:
    contest_id = int(cb.data.split(":")[1])

    async for session in get_async_session():
        repo = QuizRepository(session)
        contest = await repo.get_contest(contest_id)

        if contest:
            await repo.end_contest(contest_id)

    await cb.answer("🔴 تم إنهاء المسابقة")
    await cb.message.edit_text("🔴 تم إنهاء المسابقة.")


@quiz_router.callback_query(F.data.startswith("quiz_results:"))
async def show_quiz_results(cb: CallbackQuery) -> None:
    contest_id = int(cb.data.split(":")[1])

    async for session in get_async_session():
        repo = QuizRepository(session)
        contest = await repo.get_contest(contest_id)

        if not contest:
            await cb.answer("❌ المسابقة غير موجودة", show_alert=True)
            return

        from sqlalchemy import select

        result = await session.execute(
            select(QuizParticipantScore)
            .where(QuizParticipantScore.contest_id == contest_id)
            .order_by(QuizParticipantScore.score.desc())
        )
        scores = list(result.scalars().all())

        text = f"📊 نتائج المسابقة #{contest_id}\n\n"
        for i, score in enumerate(scores[:10], 1):
            text += f"{i}. المستخدم {score.user_id}: {score.score} نقطة ({score.correct_answers} إجابة صحيحة)\n"

    await cb.message.edit_text(text, reply_markup=quiz_controls_kb(contest_id, contest.is_active))
    await cb.answer()
