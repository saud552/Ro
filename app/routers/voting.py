from __future__ import annotations

import secrets
from contextlib import suppress
from datetime import datetime, timezone
from typing import Optional

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
from ..db.models import Contest, RouletteGate
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
from ..utils.compat import safe_answer, safe_edit_text

voting_router = Router(name="voting")


class VotingFlow(StatesGroup):
    await_contestant_name = State()
    await_antibot = State()


# --- Helpers ---


async def _verify_vote_eligibility(
    cb: CallbackQuery,
    c: Contest,
    session,
    entry_id: Optional[int] = None,
    state: Optional[FSMContext] = None,
) -> bool:
    """Check if the user satisfies all conditions and show interface if not."""
    from ..services.security import FailureMonitor
    from .system import show_verification_interface

    # 1. Premium Only check
    if c.is_premium_only and not cb.from_user.is_premium:
        await cb.message.answer("⚠️ هذه المسابقة مخصصة لمستخدمي تلغرام المميزين (Premium) فقط.")
        return False

    # 2. Forced Subscription check
    sub_service = SubscriptionService(cb.bot, AppSettingRepository(session))
    monitor = FailureMonitor(runtime.redis)

    if not c.sub_check_disabled:
        passed, is_sys = await sub_service.is_member_safe(
            await sub_service.get_required_channel() or "telegram", cb.from_user.id
        )
        if not passed:
            # Simple error for forced sub for now, or could be a gate
            pass

    # 3. Custom Gates check
    gates = (
        (await session.execute(select(RouletteGate).where(RouletteGate.contest_id == c.id)))
        .scalars()
        .all()
    )
    results = await sub_service.verify_all_gates(cb.from_user.id, gates, session)

    # Handle system failures
    for r in results:
        if r.error_type == "system_failure":
            await monitor.report_failure(c.id, c.owner_id, r.gate.id, cb.bot)
        elif r.is_passed:
            await monitor.reset_failure(c.id, r.gate.id)

    pending = [r for r in results if not r.is_passed]
    if pending:
        if state:
            await show_verification_interface(cb, state, c.id, entry_id, results)
        else:
            await cb.message.answer("⚠️ لم تحقق جميع الشروط المطلوبة.")
        return False

    return True


# --- Voting Logic ---


@voting_router.callback_query(F.data.startswith("vote_sel:"))
async def handle_entry_view(cb: CallbackQuery, state: Optional[FSMContext] = None) -> None:
    parts = cb.data.split(":")
    contest_id = int(parts[1])
    entry_id = int(parts[2])

    async for session in get_async_session():
        service = VotingService(session)
        c = await service.get_contest(contest_id)
        entry = await service.entry_repo.get_by_id(entry_id)

        if not c or not entry:
            await safe_answer(cb, "⚠️ المسابقة أو المتسابق غير موجود.")
            return

        text = (
            f"👤 <b>المتسابق: {entry.entry_name}</b>\n\n"
            f"📊 عدد الأصوات الحالية: <b>{entry.votes_count}</b> ❤️\n"
            f"⭐️ دعم النجوم: <b>{entry.stars_received}</b>\n\n"
            f"اختر طريقة التصويت المتاحة:"
        )
        kb = voting_selection_kb(
            contest_id, entry_id, c.vote_mode.value if c.vote_mode else "normal"
        )
        await safe_edit_text(cb.message, text, reply_markup=kb, parse_mode=ParseMode.HTML)
    await safe_answer(cb)


@voting_router.callback_query(F.data.startswith("vote_norm:"))
async def handle_normal_vote(cb: CallbackQuery, state: FSMContext) -> None:
    parts = cb.data.split(":")
    contest_id = int(parts[1])
    entry_id = int(parts[2])

    async for session in get_async_session():
        service = VotingService(session)
        c = await service.get_contest(contest_id)
        if not c or not c.is_open:
            await safe_answer(cb, "⚠️ التصويت مغلق حالياً.", show_alert=True)
            return

        if not await _verify_vote_eligibility(cb, c, session, entry_id, state):
            await safe_answer(cb)
            return

        # Check Multiple Vote
        if c.prevent_multiple_votes:
            if await service.vote_repo.has_voted(contest_id, cb.from_user.id):
                await cb.message.answer("⚠️ عذراً، منشئ المسابقة فعل خيار منع التصويت المتعدد.")
                await safe_answer(cb)
                return

        # Antibot check
        if c.anti_bot_enabled:
            challenge_text, answer = AntiBotService.generate_math_challenge()
            kb = AntiBotService.get_challenge_keyboard(answer, prefix="v_ab_ans")
            await state.set_state(VotingFlow.await_antibot)
            await state.update_data(cid=contest_id, eid=entry_id, ans=answer)
            await cb.message.answer(f"🛡 <b>تحقق أمان</b>\n\n{challenge_text}", reply_markup=kb)
            await safe_answer(cb)
            return

        # Perform Vote
        success = await service.add_vote(contest_id, entry_id, cb.from_user.id)
        if success:
            entry = await service.entry_repo.get_by_id(entry_id)
            await cb.message.answer(
                f"✅ تم التصويت بنجاح لـ <b>{entry.entry_name}</b>!", parse_mode=ParseMode.HTML
            )
            # Update channel post if possible
            kb = contestant_vote_kb(
                contest_id,
                entry_id,
                entry.votes_count,
                entry.stars_received,
                c.vote_mode.value if c.vote_mode else "normal",
                runtime.bot_username,
            )
            with suppress(Exception):
                await cb.bot.edit_message_reply_markup(
                    chat_id=c.channel_id, message_id=entry.message_id, reply_markup=kb
                )
        else:
            await cb.message.answer("❌ تعذر احتساب التصويت (ربما قمت بالتصويت مسبقاً).")

    await safe_answer(cb)


@voting_router.callback_query(VotingFlow.await_antibot, F.data.startswith("v_ab_ans:"))
async def handle_voting_antibot(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    correct = data.get("ans")
    contest_id = data.get("cid")
    entry_id = data.get("eid")
    user_ans = int(cb.data.split(":")[1])

    if user_ans != correct:
        await cb.answer("❌ إجابة خاطئة! حاول مجدداً.", show_alert=True)
        return

    async for session in get_async_session():
        service = VotingService(session)
        success = await service.add_vote(contest_id, entry_id, cb.from_user.id)
        if success:
            entry = await service.entry_repo.get_by_id(entry_id)
            c = await service.get_contest(contest_id)
            await safe_edit_text(cb.message, f"✅ تم التحقق والتصويت لـ <b>{entry.entry_name}</b>!")
            kb = contestant_vote_kb(
                contest_id,
                entry_id,
                entry.votes_count,
                entry.stars_received,
                c.vote_mode.value if c.vote_mode else "normal",
                runtime.bot_username,
            )
            with suppress(Exception):
                await cb.bot.edit_message_reply_markup(
                    chat_id=c.channel_id, message_id=entry.message_id, reply_markup=kb
                )
        else:
            await safe_edit_text(cb.message, "❌ تعذر احتساب التصويت.")

    await state.clear()
    await cb.answer()


@voting_router.callback_query(F.data.startswith("vote_star_pre:"))
async def handle_star_vote_pre(cb: CallbackQuery, state: FSMContext) -> None:
    parts = cb.data.split(":")
    contest_id = int(parts[1])
    entry_id = int(parts[2])

    async for session in get_async_session():
        service = VotingService(session)
        c = await service.get_contest(contest_id)

        if not await _verify_vote_eligibility(cb, c, session, entry_id, state):
            await safe_answer(cb)
            return

        await safe_edit_text(
            cb.message,
            "⭐️ <b>التصويت بالنجوم</b>\n\nيرجى اختيار كمية النجوم التي ترغب بدعم المتسابق بها:",
            reply_markup=star_amounts_kb(contest_id, entry_id),
            parse_mode=ParseMode.HTML,
        )
    await safe_answer(cb)


@voting_router.callback_query(F.data.startswith("vote_star_pay:"))
async def handle_star_payment(cb: CallbackQuery) -> None:
    parts = cb.data.split(":")
    contest_id = int(parts[1])
    entry_id = int(parts[2])
    amount = int(parts[3])

    async for session in get_async_session():
        service = VotingService(session)
        entry = await service.entry_repo.get_by_id(entry_id)

        prices = [LabeledPrice(label="دعم نجوم", amount=amount)]
        payload = f"{PaymentType.STAR_VOTE.value}:{contest_id}:{entry_id}"

        await cb.bot.send_invoice(
            chat_id=cb.from_user.id,
            title="دعم متسابق بالنجوم",
            description=f"دعم المتسابق {entry.entry_name} بـ {amount} نجمة",
            prices=prices,
            payload=payload,
            currency="XTR",
        )
    await safe_answer(cb)


# --- Registration ---


@voting_router.callback_query(F.data.startswith("reg_contest:"))
async def start_registration(cb: CallbackQuery, state: FSMContext) -> None:
    contest_id = int(cb.data.split(":")[1])

    async for session in get_async_session():
        service = VotingService(session)
        c = await service.get_contest(contest_id)

        if not c or not c.is_open:
            await safe_answer(cb, "⚠️ التسجيل مغلق حالياً.", show_alert=True)
            return

        # Gate Check for registration
        if not await _verify_vote_eligibility(cb, c, session, None, state):
            await safe_answer(cb)
            return

        # Already registered?
        existing = await service.entry_repo.get_entry(contest_id, cb.from_user.id)
        if existing:
            await safe_answer(cb, "✅ أنت مسجل بالفعل في هذه المسابقة!", show_alert=True)
            return

    await state.set_state(VotingFlow.await_contestant_name)
    await state.update_data(cid=contest_id)
    await cb.message.answer(
        "✍️ يرجى إرسال الاسم الذي ترغب بالمشاركة به في المسابقة "
        "أو اضغط الزر أدناه لاستخدام اسم حسابك:",
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
        c = await service.get_contest(contest_id)
        if not c:
            await safe_answer(cb, "⚠️ المسابقة غير موجودة.")
            return

        entry = await service.register_contestant(c, cb.from_user.id, name)

        if entry:
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
                    f"✅ تم تسجيلك بنجاح!\n🆔 رمز التصويت الخاص بك هو: "
                    f"<code>{entry.unique_code}</code>\n🔗 رابط مشاركتك: {link}",
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                await cb.message.answer(
                    f"✅ تم تسجيلك بنجاح! رمز التصويت الخاص بك هو: "
                    f"<code>{entry.unique_code}</code>",
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
        c = await service.get_contest(contest_id)
        if not c:
            await message.answer("⚠️ المسابقة غير موجودة.")
            return

        entry = await service.register_contestant(c, message.from_user.id, name)

        if entry:
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
                    f"✅ تم تسجيلك بنجاح!\n🆔 رمز التصويت الخاص بك هو: "
                    f"<code>{entry.unique_code}</code>\n🔗 رابط مشاركتك: {link}",
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                await message.answer(
                    f"✅ تم تسجيلك بنجاح! رمز التصويت الخاص بك هو: "
                    f"<code>{entry.unique_code}</code>",
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

        await safe_edit_text(cb.message, text, reply_markup=back_kb(), parse_mode=ParseMode.HTML)
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

        all_entries = await service.get_entries_for_contest(contest_id)
        if not all_entries:
            await safe_answer(cb, "⚠️ لا يوجد متسابقون لإعلان فوزهم.", show_alert=True)
            return

        # Filter and pick winners
        winners = []
        for entry in all_entries:
            if len(winners) >= c.winners_count:
                break

            if c.exclude_leavers_enabled:
                try:
                    member = await cb.bot.get_chat_member(c.channel_id, entry.user_id)
                    if member.status in ["left", "kicked"]:
                        continue
                except Exception:
                    continue
            winners.append(entry)

        if not winners:
            await safe_answer(
                cb, "⚠️ لا يوجد متسابقون مستوفون للشروط (ربما غادر الجميع).", show_alert=True
            )
            return

        winners_lines = [f"🎉 <b>نتائج مسابقة التصويت رقم {contest_id}:</b>\n"]
        for idx, entry in enumerate(winners, start=1):
            name = entry.entry_name
            winners_lines.append(f"{idx}. <b>{name}</b> بمجموع <b>{entry.votes_count}</b> ❤️")

            with suppress(Exception):
                await cb.bot.send_message(
                    entry.user_id, f"🎊 تهانينا! لقد فزت في مسابقة التصويت في قناة {c.channel_id}!"
                )

        stars_sum = await service.get_total_stars(contest_id)
        if stars_sum > 0:
            bill_code = secrets.token_hex(6).upper()
            winners_lines.append(f"\n⭐️ إجمالي النجوم المكتسبة: <b>{stars_sum}</b>")
            winners_lines.append(f"🎫 رمز فاتورة الأرباح: <code>{bill_code}</code>")
            await cb.message.answer(
                f"✅ تم إنهاء المسابقة. إجمالي النجوم: {stars_sum}. رمز الفاتورة: {bill_code}. "
                f"يمكنك التواصل مع الإدارة لتحصيلها."
            )

        announce_text = "\n".join(winners_lines)
        with suppress(Exception):
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
