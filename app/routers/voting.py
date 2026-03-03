from __future__ import annotations

import secrets
from contextlib import suppress
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, PreCheckoutQuery
from sqlalchemy import select

from ..db import get_async_session
from ..db.models import ContestType, RouletteGate
from ..db.repositories import AppSettingRepository
from ..keyboards.common import back_kb
from ..keyboards.voting import (
    contestant_vote_kb,
    registration_confirm_kb,
    voting_selection_kb,
)
from ..services.context import runtime
from ..services.payments import PaymentType, log_purchase
from ..services.subscription import SubscriptionService
from ..services.voting import VotingService
from ..utils.compat import safe_answer, safe_edit_text

voting_router = Router(name="voting")


class VotingFlow(StatesGroup):
    await_contestant_name = State()


# --- Deep Link Entry Points ---


@voting_router.callback_query(F.data.startswith("reg_contest:"))
async def start_registration(cb: CallbackQuery, state: FSMContext) -> None:
    contest_id = int(cb.data.split(":")[1])
    async for session in get_async_session():
        service = VotingService(session)
        c = await service.get_contest(contest_id)
        if not c or not c.is_open:
            await safe_answer(cb, "⚠️ عذراً، التسجيل مغلق حالياً.", show_alert=True)
            return

        # Condition Check
        sub_service = SubscriptionService(cb.bot, AppSettingRepository(session))
        gates = (
            (await session.execute(select(RouletteGate).where(RouletteGate.contest_id == contest_id)))
            .scalars()
            .all()
        )
        results = await sub_service.verify_all_conditions(cb.from_user.id, c, gates, session)

        pending = [r for r in results if not r.is_passed]
        if pending:
            from .system import show_verification_interface

            await show_verification_interface(cb, state, contest_id, None, results)
            return

        # Already registered?
        entry = await service.get_user_entry(contest_id, cb.from_user.id)
        if entry:
            await safe_answer(cb, "✅ أنت مسجل بالفعل في هذه المسابقة!", show_alert=True)
            return

        await state.update_data(cid=contest_id)
        await safe_edit_text(
            cb.message,
            "📝 لتسجيل اشتراكك، هل ترغب في استخدام اسمك الحالي؟",
            reply_markup=registration_confirm_kb(contest_id),
        )
    await safe_answer(cb)


@voting_router.callback_query(F.data.startswith("vote_sel:"))
async def handle_entry_view(cb: CallbackQuery, state: FSMContext) -> None:
    parts = cb.data.split(":")
    contest_id = int(parts[1])
    entry_id = int(parts[2])

    async for session in get_async_session():
        service = VotingService(session)
        c = await service.get_contest(contest_id)
        if not c or not c.is_open:
            await safe_answer(cb, "⚠️ عذراً، التصويت مغلق حالياً.", show_alert=True)
            return

        if c.type == ContestType.YASTAHIQ:
            from .yastahiq import handle_yastahiq_interaction
            cb.data = f"yastahiq_interact:{contest_id}:{entry_id}"
            await handle_yastahiq_interaction(cb, state)
            return

        # Check conditions even before seeing the selection
        sub_service = SubscriptionService(cb.bot, AppSettingRepository(session))
        gates = (
            (await session.execute(select(RouletteGate).where(RouletteGate.contest_id == contest_id)))
            .scalars()
            .all()
        )
        results = await sub_service.verify_all_conditions(cb.from_user.id, c, gates, session)
        pending = [r for r in results if not r.is_passed]
        if pending:
            from .system import show_verification_interface
            await show_verification_interface(cb, state, contest_id, entry_id, results)
            return

        entry = await service.entry_repo.get_by_id(entry_id)
        if not entry:
            await safe_answer(cb, "⚠️ المتسابق غير موجود.", show_alert=True)
            return

        text = (
            f"🗳 <b>التصويت للمتسابق: {entry.entry_name}</b>\n\n"
            f"❤️ الأصوات الحالية: {entry.votes_count}\n"
            f"⭐️ النجوم المستلمة: {entry.stars_received}\n\n"
            "اختر نوع التصويت الذي ترغب به:"
        )
        kb = voting_selection_kb(contest_id, entry_id, c.vote_mode.value if c.vote_mode else "normal")
        await safe_edit_text(cb.message, text, reply_markup=kb, parse_mode=ParseMode.HTML)
    await safe_answer(cb)


# --- Participation and Voting ---


@voting_router.callback_query(F.data.startswith("vote_norm:"))
async def handle_normal_vote(cb: CallbackQuery, state: FSMContext) -> None:
    parts = cb.data.split(":")
    contest_id = int(parts[1])
    entry_id = int(parts[2])

    async for session in get_async_session():
        service = VotingService(session)
        c = await service.get_contest(contest_id)
        if not c or not c.is_open:
            await safe_answer(cb, "⚠️ عذراً، التصويت مغلق حالياً.", show_alert=True)
            return

        # Check conditions
        sub_service = SubscriptionService(cb.bot, AppSettingRepository(session))
        gates = (
            (await session.execute(select(RouletteGate).where(RouletteGate.contest_id == contest_id)))
            .scalars()
            .all()
        )
        results = await sub_service.verify_all_conditions(cb.from_user.id, c, gates, session)

        # Monitor failures
        from ..services.security import FailureMonitor

        monitor = FailureMonitor(runtime.redis)
        for r in results:
            if r.error_type == "system_failure":
                await monitor.report_failure(c.id, c.owner_id, r.gate.id, cb.bot)
            elif r.is_passed:
                await monitor.reset_failure(c.id, r.gate.id)

        pending = [r for r in results if not r.is_passed]
        if pending:
            from .system import show_verification_interface

            await show_verification_interface(cb, state, contest_id, entry_id, results)
            return

        if c.prevent_multiple_votes:
            voted = await service.has_user_voted(contest_id, cb.from_user.id)
            if voted:
                await safe_answer(cb, "⚠️ لقد قمت بالتصويت مسبقاً في هذه المسابقة.", show_alert=True)
                return

        success = await service.add_vote(contest_id, entry_id, cb.from_user.id)
        if success:
            await safe_answer(cb, "✅ تم احتساب صوتك بنجاح! شكراً لك.", show_alert=True)
            entry = await service.entry_repo.get_by_id(entry_id)
            if entry and entry.message_id:
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
            await safe_answer(cb, "⚠️ عذراً، تعذر تسجيل صوتك حالياً.", show_alert=True)


@voting_router.callback_query(F.data.startswith("vote_star_pre:"))
async def handle_stars_vote_prepare(cb: CallbackQuery, state: FSMContext) -> None:
    parts = cb.data.split(":")
    contest_id = int(parts[1])
    entry_id = int(parts[2])

    async for session in get_async_session():
        service = VotingService(session)
        c = await service.get_contest(contest_id)
        if not c or not c.is_open:
            await safe_answer(cb, "⚠️ عذراً، التصويت مغلق حالياً.", show_alert=True)
            return

        # Check conditions
        sub_service = SubscriptionService(cb.bot, AppSettingRepository(session))
        gates = (
            (await session.execute(select(RouletteGate).where(RouletteGate.contest_id == contest_id)))
            .scalars()
            .all()
        )
        results = await sub_service.verify_all_conditions(cb.from_user.id, c, gates, session)

        pending = [r for r in results if not r.is_passed]
        if pending:
            from .system import show_verification_interface

            await show_verification_interface(cb, state, contest_id, entry_id, results)
            return

        from ..keyboards.voting import star_amounts_kb

        await safe_edit_text(
            cb.message, "⭐️ اختر عدد النجوم التي ترغب في دعم المتسابق بها:", reply_markup=star_amounts_kb(contest_id, entry_id)
        )
    await safe_answer(cb)


@voting_router.callback_query(F.data.startswith("vote_star_pay:"))
async def handle_stars_vote_pay(cb: CallbackQuery) -> None:
    parts = cb.data.split(":")
    contest_id = int(parts[1])
    entry_id = int(parts[2])
    amount = int(parts[3])

    async for session in get_async_session():
        service = VotingService(session)
        c = await service.get_contest(contest_id)
        if not c:
            return

        title = "دعم متسابق بالنجوم"
        description = f"دعم المتسابق في المسابقة رقم {contest_id}. كل نجمة تعادل {c.star_to_vote_ratio} أصوات."
        payload = f"{PaymentType.STAR_VOTE.value}:{contest_id}:{entry_id}"
        currency = "XTR"
        prices = [{"label": "Stars", "amount": amount}]

        try:
            await cb.bot.send_invoice(
                chat_id=cb.from_user.id,
                title=title,
                description=description,
                payload=payload,
                provider_token="",
                currency=currency,
                prices=prices,
            )
            await safe_answer(cb, "✅ تم إرسال فاتورة الدفع في الخاص.")
        except Exception:
            await safe_answer(cb, "❌ تعذر إرسال الفاتورة. يرجى التأكد من بدء محادثة مع البوت.")


@voting_router.callback_query(F.data.startswith("reg_custom:"))
async def reg_custom_name(cb: CallbackQuery, state: FSMContext) -> None:
    contest_id = int(cb.data.split(":")[1])
    await state.set_state(VotingFlow.await_contestant_name)
    await state.update_data(cid=contest_id)
    await safe_edit_text(cb.message, "✍️ أرسل الاسم الذي ترغب بالمشاركة به:")
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
                    with suppress(Exception):
                        await message.bot.edit_message_reply_markup(
                            chat_id=c.channel_id, message_id=entry.message_id, reply_markup=kb
                        )
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
