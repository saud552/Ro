from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from aiogram import F, Router, Bot
from aiogram.types import CallbackQuery, Message, PreCheckoutQuery, LabeledPrice
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.enums import ParseMode

from ..db import get_async_session
from ..services.voting import VotingService
from ..services.payments import PaymentType, log_purchase
from ..keyboards.voting import (
    voting_main_kb,
    voting_selection_kb,
    star_amounts_kb,
    star_ratio_kb,
    vote_mode_kb,
)
from ..db.models import ContestType, VoteMode, Contest
from .roulette import CreateRoulette

voting_router = Router(name="voting")

class VotingFlow(StatesGroup):
    await_contestant_name = State()
    await_star_amount = State()

# --- Creation Flow Integration ---

@voting_router.callback_query(CreateRoulette.await_vote_mode, F.data.startswith("vmode_"))
async def handle_vote_mode_selection(cb: CallbackQuery, state: FSMContext) -> None:
    mode = cb.data.replace("vmode_", "")
    await state.update_data(vote_mode=mode)

    if mode in {"stars", "both"}:
        await state.set_state(CreateRoulette.await_star_ratio)
        await cb.message.answer("اختر قيمة التحويل (النجمة الواحدة تساوي كم تصويت؟):", reply_markup=star_ratio_kb())
    else:
        await state.set_state(CreateRoulette.await_settings)
        data = await state.get_data()
        from ..keyboards.settings import roulette_settings_kb
        await cb.message.answer("تخصيص إعدادات المسابقة:", reply_markup=roulette_settings_kb(
            data.get("is_premium_only", False),
            data.get("sub_check_disabled", False),
            data.get("anti_bot_enabled", True),
            data.get("exclude_leavers_enabled", True),
        ))
    await cb.answer()

@voting_router.callback_query(CreateRoulette.await_star_ratio, F.data.startswith("vratio:"))
async def handle_star_ratio_selection(cb: CallbackQuery, state: FSMContext) -> None:
    ratio = int(cb.data.split(":")[1])
    await state.update_data(star_ratio=ratio)

    await state.set_state(CreateRoulette.await_settings)
    data = await state.get_data()
    from ..keyboards.settings import roulette_settings_kb
    await cb.message.answer("تخصيص إعدادات المسابقة:", reply_markup=roulette_settings_kb(
        data.get("is_premium_only", False),
        data.get("sub_check_disabled", False),
        data.get("anti_bot_enabled", True),
        data.get("exclude_leavers_enabled", True),
    ))
    await cb.answer()

# --- Voting Interaction Handlers ---

@voting_router.callback_query(F.data.startswith("vote_sel:"))
async def handle_vote_selection(cb: CallbackQuery) -> None:
    parts = cb.data.split(":")
    contest_id = int(parts[1])
    entry_id = int(parts[2])

    async for session in get_async_session():
        service = VotingService(session)
        c = await service.get_contest(contest_id)
        if not c or not c.is_open:
            await cb.answer("⚠️ المسابقة مغلقة أو غير موجودة.", show_alert=True)
            return

        entry = await service.entry_repo.get_by_id(entry_id)
        if not entry:
            await cb.answer("⚠️ المتسابق غير موجود.", show_alert=True)
            return

        text = (
            f"👤 المتسابق: <b>{entry.entry_name}</b>\n"
            f"🗳 عدد الأصوات: <b>{entry.votes_count}</b>\n"
            f"⭐️ النجوم المستلمة: <b>{entry.stars_received}</b>\n\n"
            "اختر طريقة التصويت:"
        )
        await cb.message.edit_text(text, reply_markup=voting_selection_kb(contest_id, entry_id, c.vote_mode.value), parse_mode=ParseMode.HTML)
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
            await cb.answer("✅ تم احتساب تصويتك بنجاح!")
            # Refresh current entry view
            entry = await service.entry_repo.get_by_id(entry_id)
            c = await service.get_contest(contest_id)
            text = (
                f"👤 المتسابق: <b>{entry.entry_name}</b>\n"
                f"🗳 عدد الأصوات: <b>{entry.votes_count}</b>\n"
                f"⭐️ النجوم المستلمة: <b>{entry.stars_received}</b>\n\n"
                "اختر طريقة التصويت:"
            )
            await cb.message.edit_text(text, reply_markup=voting_selection_kb(contest_id, entry_id, c.vote_mode.value), parse_mode=ParseMode.HTML)
        else:
            await cb.answer("⚠️ لا يمكنك التصويت مرة أخرى أو المسابقة مغلقة.", show_alert=True)

@voting_router.callback_query(F.data.startswith("vote_star_pre:"))
async def handle_star_vote_prepare(cb: CallbackQuery) -> None:
    parts = cb.data.split(":")
    contest_id = int(parts[1])
    entry_id = int(parts[2])
    await cb.message.edit_text("كم عدد النجوم التي ترغب بدعم المتسابق بها؟", reply_markup=star_amounts_kb(contest_id, entry_id))
    await cb.answer()

@voting_router.callback_query(F.data.startswith("vote_star_pay:"))
async def handle_star_vote_invoice(cb: CallbackQuery) -> None:
    parts = cb.data.split(":")
    contest_id = int(parts[1])
    entry_id = int(parts[2])
    stars_amount = int(parts[3])

    # Payload for star vote is: star_vote:<contest_id>:<entry_id>
    payload = f"{PaymentType.STAR_VOTE.value}:{contest_id}:{entry_id}"

    prices = [LabeledPrice(label="دعم المتسابق بنجوم", amount=stars_amount)]
    await cb.bot.send_invoice(
        chat_id=cb.from_user.id,
        title="دعم متسابق",
        description=f"دعم المتسابق بنجوم في مسابقة التصويت رقم {contest_id}",
        payload=payload,
        currency="XTR",
        prices=prices
    )
    await cb.answer()

# --- Registration Handlers ---

@voting_router.callback_query(F.data.startswith("reg_contest:"))
async def start_registration(cb: CallbackQuery, state: FSMContext) -> None:
    contest_id = int(cb.data.split(":")[1])
    # Check if already registered
    async for session in get_async_session():
        service = VotingService(session)
        entry = await service.entry_repo.get_entry(contest_id, cb.from_user.id)
        if entry:
            await cb.answer(f"⚠️ أنت مسجل بالفعل باسم: {entry.entry_name}", show_alert=True)
            return

    await state.set_state(VotingFlow.await_contestant_name)
    await state.update_data(cid=contest_id)
    await cb.message.answer("يرجى إرسال الاسم الذي ترغب بالمشاركة به في المسابقة:")
    await cb.answer()

@voting_router.message(VotingFlow.await_contestant_name)
async def complete_registration(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    contest_id = data.get("cid")
    name = message.text.strip()

    if len(name) > 64:
        await message.answer("⚠️ الاسم طويل جداً، يرجى إرسال اسم أقل من 64 حرف.")
        return

    async for session in get_async_session():
        service = VotingService(session)
        entry = await service.register_contestant(contest_id, message.from_user.id, name)
        await message.answer(f"✅ تم تسجيلك بنجاح! رمز التصويت الخاص بك هو: <code>{entry.unique_code}</code>", parse_mode=ParseMode.HTML)

    await state.clear()

# --- Payment Callback Handlers ---

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
            success = await service.add_vote(contest_id, entry_id, user_id, is_stars=True, stars_amount=stars_amount)
            if success:
                await message.answer(f"✅ تم استلام {stars_amount} نجمة واحتسابها كدعم للمتسابق! شكراً لك.")
                await log_purchase(user_id, payload, stars_amount)
            else:
                await message.answer("⚠️ حدث خطأ أثناء احتساب النجوم، يرجى مراجعة الإدارة.")
    else:
        # Fallback to feature access payment logic (could import or handle here)
        from ..services.payments import grant_monthly, grant_one_time
        if payload == PaymentType.MONTHLY.value:
            await grant_monthly(user_id)
            await message.answer("✅ تم تفعيل الاشتراك الشهري بنجاح!")
        elif payload == PaymentType.ONETIME.value:
            await grant_one_time(user_id)
            await message.answer("✅ تم إضافة رصيد إنشاء مسابقة بنجاح!")
        await log_purchase(user_id, payload, stars_amount)

# --- Leaderboard and Display ---

@voting_router.callback_query(F.data.startswith("leaderboard:"))
async def handle_leaderboard_view(cb: CallbackQuery) -> None:
    contest_id = int(cb.data.split(":")[1])

    async for session in get_async_session():
        service = VotingService(session)
        top_entries = await service.get_top_entries(contest_id, limit=15)

        if not top_entries:
            await cb.answer("⚠️ لا يوجد متسابقون حالياً.", show_alert=True)
            return

        lines = [f"🏆 <b>قائمة المتصدرين في مسابقة {contest_id}:</b>\n"]
        for idx, entry in enumerate(top_entries, start=1):
            lines.append(f"{idx}. <b>{entry.entry_name}</b>: <b>{entry.votes_count}</b> ❤️")

        text = "\n".join(lines)
        await cb.message.edit_text(text, reply_markup=voting_main_kb(contest_id, top_entries), parse_mode=ParseMode.HTML)
    await cb.answer()

@voting_router.callback_query(F.data.startswith("vote_refresh:"))
async def handle_vote_refresh(cb: CallbackQuery) -> None:
    contest_id = int(cb.data.split(":")[1])

    async for session in get_async_session():
        service = VotingService(session)
        entries = await service.get_top_entries(contest_id, limit=10)
        c = await service.get_contest(contest_id)

        text = (
            f"🗳 <b>مسابقة التصويت جارية!</b>\n"
            f"يمكنك التصويت لأحد المتسابقين أدناه:\n"
            f"⭐️ النجوم متاحة: {'نعم' if c.vote_mode in {VoteMode.STARS, VoteMode.BOTH} else 'لا'}"
        )
        await cb.message.edit_text(text, reply_markup=voting_main_kb(contest_id, entries), parse_mode=ParseMode.HTML)
    await cb.answer()

@voting_router.callback_query(F.data.startswith("draw_vote:"))
async def handle_vote_draw(cb: CallbackQuery) -> None:
    contest_id = int(cb.data.split(":")[1])

    async for session in get_async_session():
        service = VotingService(session)
        c = await service.get_contest(contest_id)

        if not c or c.closed_at:
            await cb.answer("⚠️ تم إغلاق التصويت مسبقاً.", show_alert=True)
            return

        if c.is_open:
            await cb.answer("⏸️ يرجى إيقاف التصويت أولاً.", show_alert=True)
            return

        top_entries = await service.get_top_entries(contest_id, limit=c.winners_count)
        if not top_entries:
            await cb.answer("⚠️ لا يوجد متسابقون لإعلان فوزهم.", show_alert=True)
            return

        winners_lines = [f"🎉 <b>نتائج مسابقة التصويت رقم {contest_id}:</b>\n"]
        for idx, entry in enumerate(top_entries, start=1):
            name = entry.entry_name
            winners_lines.append(f"{idx}. <b>{name}</b> بمجموع <b>{entry.votes_count}</b> ❤️")

            # Notify winners
            with asyncio.suppress(Exception):
                await cb.bot.send_message(entry.user_id, f"🎊 تهانينا! لقد فزت في مسابقة التصويت في قناة {c.channel_id}!")

        announce_text = "\n".join(winners_lines)
        with asyncio.suppress(Exception):
            await cb.bot.send_message(c.channel_id, announce_text, reply_to_message_id=c.message_id, parse_mode=ParseMode.HTML)

        c.closed_at = datetime.now(timezone.utc)
        await session.commit()
    await cb.answer("✅ تم إعلان النتائج بنجاح!")
