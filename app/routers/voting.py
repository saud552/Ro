from __future__ import annotations

import asyncio
import secrets
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)
from sqlalchemy import select

from ..db import get_async_session
from ..db.models import Contest, ContestEntry, ContestType, RouletteGate
from ..db.repositories import AppSettingRepository
from ..keyboards.voting import (
    contestant_vote_kb,
    star_amounts_kb,
    voting_selection_kb,
)
from ..services.antibot import AntiBotService
from ..services.context import runtime
from ..services.payments import PaymentType, log_purchase
from ..services.subscription import SubscriptionService
from ..services.voting import VotingService
from ..utils.compat import safe_answer

voting_router = Router(name="voting")


class VotingFlow(StatesGroup):
    await_contestant_name = State()
    await_voter_antibot = State()


# --- Voting Logic ---


@voting_router.callback_query(F.data.startswith("vote_sel:"))
async def handle_entry_view(cb: CallbackQuery, state: FSMContext) -> None:
    parts = cb.data.split(":")
    contest_id = int(parts[1])
    entry_id = int(parts[2])

    async for session in get_async_session():
        service = VotingService(session)
        c = await service.get_contest(contest_id)
        if not c or not c.is_open:
            await safe_answer(cb, "⚠️ المسابقة مغلقة أو غير موجودة.", show_alert=True)
            return

        entry = await service.entry_repo.get_by_id(entry_id)
        if not entry:
            await safe_answer(cb, "⚠️ المتسابق غير موجود.", show_alert=True)
            return

        # 1. Mandatory Sub Check (Bot channel + Contest channel)
        sub_service = SubscriptionService(cb.bot, AppSettingRepository(session))
        if not c.sub_check_disabled:
            # Bot base channel
            if not await sub_service.check_forced_subscription(cb.from_user.id):
                await cb.message.answer("❌ يرجى الاشتراك في قناة البوت أولاً للمتابعة.")
                await safe_answer(cb)
                return

            # Contest channel/group
            if not await sub_service.is_member(c.channel_id, cb.from_user.id):
                await cb.message.answer(
                    "❌ يجب أن تكون عضواً في القناة/المجموعة المخصصة لهذه المسابقة لتتمكن من التصويت."
                )
                await safe_answer(cb)
                return

        # 2. Gate Check (Advanced conditions)
        gates = (
            (
                await session.execute(
                    select(RouletteGate).where(RouletteGate.contest_id == contest_id)
                )
            )
            .scalars()
            .all()
        )
        for gate in gates:
            if not await sub_service.check_gate(cb.from_user.id, gate, session):
                if gate.gate_type == "channel":
                    await cb.message.answer(f"⚠️ يجب الانضمام لقناة: {gate.channel_title}")
                elif gate.gate_type == "contest":
                    await cb.message.answer(f"⚠️ يجب الانضمام للمسابقة رقم {gate.target_id} أولاً!")
                elif gate.gate_type == "vote":
                    await cb.message.answer(
                        f"⚠️ يجب التصويت للمتسابق ذو الرمز {gate.target_code} في المسابقة {gate.target_id}!"
                    )
                elif gate.gate_type == "yastahiq":
                    await cb.message.answer(
                        "⚠️ يجب أن يكون لديك نقاط تفاعل في المجموعة لاستكمال هذا الشرط."
                    )
                await safe_answer(cb)
                return

        # 3. Antibot Challenge (Voter)
        if c.anti_bot_enabled:
            challenge_text, answer = AntiBotService.generate_math_challenge()
            kb = AntiBotService.get_challenge_keyboard(answer)
            await state.set_state(VotingFlow.await_voter_antibot)
            await state.update_data(cid=contest_id, eid=entry_id, ans=answer)
            if cb.id == "0":
                await cb.message.answer(challenge_text, reply_markup=kb)
            else:
                await cb.message.edit_text(challenge_text, reply_markup=kb)
            return

        await show_voting_options(cb, c, entry)


async def show_voting_options(cb: CallbackQuery, contest: Contest, entry: ContestEntry):
    if contest.type == ContestType.YASTAHIQ:
        text = (
            f"🔥 <b>دعم المتسابق: {entry.entry_name}</b>\n\n"
            f"قم بنسخ أحد النصوص التالية وإرسالها في المجموعة المحددة:\n\n"
            f"1️⃣ <code>يستحق</code>\n"
            f"2️⃣ <code>يستحق {entry.entry_name}</code>\n\n"
            "📌 عند إرسال الكلمة، سيتم احتساب تصويتك تلقائياً."
        )
        reply_markup = None
    else:
        text = (
            f"👤 المتسابق: <b>{entry.entry_name}</b>\n"
            f"🗳 عدد الأصوات: <b>{entry.votes_count}</b>\n"
            f"⭐️ النجوم المستلمة: <b>{entry.stars_received}</b>\n\n"
            "اختر طريقة التصويت:"
        )
        reply_markup = voting_selection_kb(
            contest.id, entry.id, contest.vote_mode.value if contest.vote_mode else "normal"
        )

    try:
        if cb.id == "0" or not cb.message:
            await cb.bot.send_message(
                cb.from_user.id, text, reply_markup=reply_markup, parse_mode=ParseMode.HTML
            )
        else:
            await cb.message.edit_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    except Exception:
        await cb.bot.send_message(
            cb.from_user.id, text, reply_markup=reply_markup, parse_mode=ParseMode.HTML
        )
    await safe_answer(cb)


@voting_router.callback_query(VotingFlow.await_voter_antibot, F.data.startswith("antibot_ans:"))
async def handle_voter_antibot_ans(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    correct = data.get("ans")
    user_ans = int(cb.data.split(":")[1])

    if user_ans != correct:
        await cb.answer("❌ إجابة خاطئة! حاول مجدداً.", show_alert=True)
        return

    contest_id = data.get("cid")
    entry_id = data.get("eid")

    async for session in get_async_session():
        service = VotingService(session)
        c = await service.get_contest(contest_id)
        e = await service.entry_repo.get_by_id(entry_id)
        if c and e:
            await state.clear()
            await show_voting_options(cb, c, e)
        else:
            await cb.message.answer("⚠️ حدث خطأ، المسابقة قد تكون انتهت.")
    await cb.answer()


@voting_router.callback_query(F.data.startswith("vote_norm:"))
async def handle_normal_vote(cb: CallbackQuery) -> None:
    parts = cb.data.split(":")
    contest_id = int(parts[1])
    entry_id = int(parts[2])

    async for session in get_async_session():
        service = VotingService(session)
        success = await service.add_vote(contest_id, entry_id, cb.from_user.id)
        if success:
            await safe_answer(cb, "✅ تم احتساب تصويتك بنجاح!")
            entry = await service.entry_repo.get_by_id(entry_id)
            c = await service.get_contest(contest_id)

            if entry.message_id:
                kb = contestant_vote_kb(
                    contest_id,
                    entry_id,
                    entry.votes_count,
                    entry.stars_received,
                    c.vote_mode.value if c.vote_mode else "normal",
                    runtime.bot_username,
                )
                try:
                    await cb.bot.edit_message_reply_markup(
                        chat_id=c.channel_id, message_id=entry.message_id, reply_markup=kb
                    )
                except Exception:
                    pass

            text = (
                f"👤 المتسابق: <b>{entry.entry_name}</b>\n"
                f"🗳 عدد الأصوات: <b>{entry.votes_count}</b>\n"
                f"⭐️ النجوم المستلمة: <b>{entry.stars_received}</b>\n\n"
                "✅ <b>تم احتساب تصويتك بنجاح!</b>"
            )
            try:
                await cb.message.edit_text(text, reply_markup=None, parse_mode=ParseMode.HTML)
            except Exception:
                pass
        else:
            await safe_answer(
                cb, "⚠️ لا يمكنك التصويت مرة أخرى أو المسابقة مغلقة.", show_alert=True
            )


@voting_router.callback_query(F.data.startswith("vote_star_pre:"))
async def handle_star_vote_prepare(cb: CallbackQuery) -> None:
    parts = cb.data.split(":")
    contest_id = int(parts[1])
    entry_id = int(parts[2])
    try:
        await cb.message.edit_text(
            "⭐️ كم عدد النجوم التي ترغب بدعم المتسابق بها؟",
            reply_markup=star_amounts_kb(contest_id, entry_id),
        )
    except Exception:
        await cb.message.answer(
            "⭐️ كم عدد النجوم التي ترغب بدعم المتسابق بها؟",
            reply_markup=star_amounts_kb(contest_id, entry_id),
        )
    await safe_answer(cb)


@voting_router.callback_query(F.data.startswith("vote_star_pay:"))
async def handle_star_vote_invoice(cb: CallbackQuery) -> None:
    parts = cb.data.split(":")
    contest_id = int(parts[1])
    entry_id = int(parts[2])
    stars_amount = int(parts[3])

    payload = f"{PaymentType.STAR_VOTE.value}:{contest_id}:{entry_id}"

    prices = [LabeledPrice(label="دعم المتسابق بنجوم", amount=stars_amount)]
    try:
        await cb.bot.send_invoice(
            chat_id=cb.from_user.id,
            title="🌟 دعم متسابق",
            description=f"دعم المتسابق بنجوم في مسابقة التصويت رقم {contest_id}",
            payload=payload,
            currency="XTR",
            prices=prices,
        )
    except Exception:
        await cb.message.answer("❌ فشل إنشاء الفاتورة. حاول مجدداً لاحقاً.")
    await safe_answer(cb)


# --- Registration Handlers ---


@voting_router.callback_query(F.data.startswith("reg_contest:"))
async def start_registration(cb: CallbackQuery, state: FSMContext) -> None:
    contest_id = int(cb.data.split(":")[1])
    async for session in get_async_session():
        service = VotingService(session)
        entry = await service.entry_repo.get_entry(contest_id, cb.from_user.id)
        if entry:
            await safe_answer(cb, f"⚠️ أنت مسجل بالفعل باسم: {entry.entry_name}", show_alert=True)
            return

        # Sub check for registration
        sub_service = SubscriptionService(cb.bot, AppSettingRepository(session))
        c = await service.get_contest(contest_id)
        if c and not c.sub_check_disabled:
            if not await sub_service.check_forced_subscription(cb.from_user.id):
                await cb.message.answer("❌ يجب الاشتراك في قناة البوت أولاً للمشاركة.")
                await safe_answer(cb)
                return
            if not await sub_service.is_member(c.channel_id, cb.from_user.id):
                await cb.message.answer("❌ يجب أن تكون عضواً في القناة للمشاركة كمتسابق.")
                await safe_answer(cb)
                return

    await state.set_state(VotingFlow.await_contestant_name)
    await state.update_data(cid=contest_id)
    await cb.message.answer(
        "✍️ يرجى إرسال الاسم الذي ترغب بالمشاركة به في المسابقة أو اضغط الزر أدناه لاستخدام اسم حسابك:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="👤 استخدم اسم حسابي", callback_data=f"reg_use_name:{contest_id}"
                    )
                ]
            ]
        ),
    )
    await safe_answer(cb)


@voting_router.callback_query(F.data.startswith("reg_use_name:"))
async def reg_use_name_callback(cb: CallbackQuery, state: FSMContext) -> None:
    contest_id = int(cb.data.split(":")[1])
    name = cb.from_user.full_name
    async for session in get_async_session():
        service = VotingService(session)
        entry = await service.register_contestant(contest_id, cb.from_user.id, name)

        c = await service.get_contest(contest_id)
        if c:
            text = f"👤 المتسابق: <b>{name}</b>"
            kb = contestant_vote_kb(
                contest_id,
                entry.id,
                0,
                0,
                c.vote_mode.value if c.vote_mode else "normal",
                runtime.bot_username,
            )
            try:
                msg = await cb.bot.send_message(
                    chat_id=c.channel_id, text=text, reply_markup=kb, parse_mode=ParseMode.HTML
                )
                entry.message_id = msg.message_id
                await session.commit()

                link = f"https://t.me/c/{str(c.channel_id).replace('-100','')}/{msg.message_id}"
                await cb.message.answer(
                    f"✅ تم تسجيلك بنجاح!\n🆔 رمز التصويت الخاص بك هو: <code>{entry.unique_code}</code>\n🔗 رابط مشاركتك: {link}",
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                await cb.message.answer(
                    f"✅ تم تسجيلك بنجاح! رمز التصويت الخاص بك هو: <code>{entry.unique_code}</code>",
                    parse_mode=ParseMode.HTML,
                )

    await state.clear()
    await safe_answer(cb)


@voting_router.message(VotingFlow.await_contestant_name)
async def complete_registration(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    contest_id = data.get("cid")
    name = (message.text or "").strip()

    if not name or len(name) > 64:
        await message.answer("⚠️ يرجى إرسال اسم صحيح أقل من 64 حرف.")
        return

    async for session in get_async_session():
        service = VotingService(session)
        entry = await service.register_contestant(contest_id, message.from_user.id, name)

        c = await service.get_contest(contest_id)
        if c:
            text = f"👤 المتسابق: <b>{name}</b>"
            kb = contestant_vote_kb(
                contest_id,
                entry.id,
                0,
                0,
                c.vote_mode.value if c.vote_mode else "normal",
                runtime.bot_username,
            )
            try:
                msg = await message.bot.send_message(
                    chat_id=c.channel_id, text=text, reply_markup=kb, parse_mode=ParseMode.HTML
                )
                entry.message_id = msg.message_id
                await session.commit()

                link = f"https://t.me/c/{str(c.channel_id).replace('-100','')}/{msg.message_id}"
                await message.answer(
                    f"✅ تم تسجيلك بنجاح!\n🆔 رمز التصويت الخاص بك هو: <code>{entry.unique_code}</code>\n🔗 رابط مشاركتك: {link}",
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                await message.answer(
                    f"✅ تم تسجيلك بنجاح! رمز التصويت الخاص بك هو: <code>{entry.unique_code}</code>",
                    parse_mode=ParseMode.HTML,
                )

    await state.clear()


# --- Leaderboard and Display ---


@voting_router.callback_query(F.data.startswith("leaderboard:"))
async def handle_leaderboard_view(cb: CallbackQuery) -> None:
    contest_id = int(cb.data.split(":")[1])

    async for session in get_async_session():
        service = VotingService(session)
        top_entries = await service.get_top_entries(contest_id, limit=15)

        if not top_entries:
            await safe_answer(cb, "⚠️ لا يوجد متسابقون حالياً.", show_alert=True)
            return

        lines = [f"🏆 <b>قائمة المتصدرين في المسابقة #{contest_id}:</b>\n"]
        for idx, entry in enumerate(top_entries, start=1):
            lines.append(f"{idx}. <b>{entry.entry_name}</b>: <b>{entry.votes_count}</b> ❤️")

        text = "\n".join(lines)
        from ..keyboards.common import back_kb

        try:
            await cb.message.edit_text(text, reply_markup=back_kb(), parse_mode=ParseMode.HTML)
        except Exception:
            await cb.message.answer(text, reply_markup=back_kb(), parse_mode=ParseMode.HTML)
    await safe_answer(cb)


@voting_router.callback_query(F.data.startswith("draw_vote:"))
async def handle_vote_draw(cb: CallbackQuery) -> None:
    contest_id = int(cb.data.split(":")[1])

    async for session in get_async_session():
        service = VotingService(session)
        c = await service.get_contest(contest_id)

        if not c or c.closed_at:
            await safe_answer(cb, "⚠️ تم إغلاق التصويت مسبقاً.", show_alert=True)
            return

        if c.is_open:
            await safe_answer(cb, "⏸️ يرجى إيقاف التصويت أولاً.", show_alert=True)
            return

        top_entries = await service.get_top_entries(contest_id, limit=c.winners_count)
        if not top_entries:
            await safe_answer(cb, "⚠️ لا يوجد متسابقون لإعلان فوزهم.", show_alert=True)
            return

        winners_lines = [f"🎉 <b>نتائج مسابقة التصويت رقم {contest_id}:</b>\n"]
        for idx, entry in enumerate(top_entries, start=1):
            name = entry.entry_name
            winners_lines.append(f"{idx}. <b>{name}</b> بمجموع <b>{entry.votes_count}</b> ❤️")

            with asyncio.suppress(Exception):
                await cb.bot.send_message(
                    entry.user_id, f"🎊 تهانينا! لقد فزت في مسابقة التصويت في قناة {c.channel_id}!"
                )

        stars_sum = await service.get_total_stars(contest_id)
        if stars_sum > 0:
            bill_code = secrets.token_hex(6).upper()
            winners_lines.append(f"\n⭐️ إجمالي النجوم المكتسبة: <b>{stars_sum}</b>")
            winners_lines.append(f"🎫 رمز فاتورة الأرباح: <code>{bill_code}</code>")
            await cb.message.answer(
                f"✅ تم إنهاء المسابقة. إجمالي النجوم: {stars_sum}. رمز الفاتورة: {bill_code}. يمكنك التواصل مع الإدارة لتحصيلها."
            )

        announce_text = "\n".join(winners_lines)
        with asyncio.suppress(Exception):
            await cb.bot.send_message(
                c.channel_id,
                announce_text,
                reply_to_message_id=c.message_id,
                parse_mode=ParseMode.HTML,
            )

        c.closed_at = datetime.now(timezone.utc)
        await session.commit()
    await safe_answer(cb, "✅ تم إعلان النتائج بنجاح!")


# --- Global Commands & Payment ---


@voting_router.pre_checkout_query()
async def process_pre_checkout_query(pre_checkout_query: PreCheckoutQuery):
    await pre_checkout_query.answer(ok=True)


@voting_router.message(F.successful_payment)
async def handle_successful_payment(message: Message):
    payload = message.successful_payment.invoice_payload
    stars_amount = message.successful_payment.total_amount
    user_id = message.from_user.id

    if payload.startswith(PaymentType.STAR_VOTE.value):
        parts = payload.split(":")
        contest_id = int(parts[1])
        entry_id = int(parts[2])

        async for session in get_async_session():
            service = VotingService(session)
            success = await service.add_vote(
                contest_id, entry_id, user_id, is_stars=True, stars_amount=stars_amount
            )
            if success:
                await message.answer(
                    f"✅ تم استلام {stars_amount} نجمة واحتسابها كدعم للمتسابق! شكراً لك."
                )
                await log_purchase(user_id, payload, stars_amount)

                entry = await service.entry_repo.get_by_id(entry_id)
                c = await service.get_contest(contest_id)
                if entry and entry.message_id:
                    kb = contestant_vote_kb(
                        contest_id,
                        entry_id,
                        entry.votes_count,
                        entry.stars_received,
                        c.vote_mode.value if c.vote_mode else "normal",
                        runtime.bot_username,
                    )
                    try:
                        await message.bot.edit_message_reply_markup(
                            chat_id=c.channel_id, message_id=entry.message_id, reply_markup=kb
                        )
                    except Exception:
                        pass
            else:
                await message.answer("⚠️ حدث خطأ أثناء احتساب النجوم، يرجى مراجعة الإدارة.")
    else:
        from ..services.payments import grant_monthly, grant_one_time

        if payload == PaymentType.MONTHLY.value:
            await grant_monthly(user_id)
            await message.answer("✅ تم تفعيل الاشتراك الشهري بنجاح!")
        elif payload == PaymentType.ONETIME.value:
            await grant_one_time(user_id)
            await message.answer("✅ تم إضافة رصيد إنشاء مسابقة بنجاح!")
        await log_purchase(user_id, payload, stars_amount)
