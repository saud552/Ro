from __future__ import annotations

import secrets
from contextlib import suppress

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from ..db import get_async_session
from ..db.models import VotingContest, VotingCandidate
from ..db.repositories import VotingRepository
from ..keyboards.voting import (
    voting_confirm_kb,
    voting_controls_kb,
    voting_join_kb,
    voting_settings_kb,
    voting_type_kb,
    voting_vote_kb,
)
from ..services.context import runtime
from ..services.formatting import StyledText, parse_style_from_text

voting_router = Router(name="voting")


class VotingStates(StatesGroup):
    await_channel_select = State()
    await_group_link = State()
    await_text = State()
    await_customization = State()
    await_confirm = State()
    await_candidate_name = State()


def _generate_vote_code() -> str:
    return secrets.token_hex(8)


async def _is_admin_in_channel(bot, chat_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return getattr(member, "status", None) in {"creator", "administrator"}
    except Exception:
        return False


@voting_router.callback_query(F.data == "section_voting")
async def section_voting(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    text = (
        "🏆 قسم مسابقات التصويتب\n\n"
        "اختر نوع المسابقة:\n\n"
        "🗳️ تصويتب عادي - تصويتب مجاني\n"
        "⭐ تصويتب نجوم - تصويتب مدفوع بالنجوم\n"
        "🗳️⭐ تصويتب عادي + نجوم - كلاهما"
    )
    await cb.message.edit_text(text, reply_markup=voting_type_kb())
    await cb.answer()


@voting_router.callback_query(F.data == "voting_normal")
async def create_normal_voting(cb: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(voting_type="normal", stars_per_vote=0)
    text = "📺 اختر القناة التي ستُنشر فيها المسابقة:\n\n" "أعد توجيه رسالة من القناة أو اكتب معرفها (-100xxxxxxxxxx)."
    await cb.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[]))
    await state.set_state(VotingStates.await_channel_select)
    await cb.answer()


@voting_router.callback_query(F.data == "voting_stars")
async def create_stars_voting(cb: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(voting_type="stars", stars_per_vote=2)
    text = "⭐ تصويتب نجوم\n\n" "كم نجمة لكل تصويتب؟ (الافتراضي: 2)"
    await cb.message.answer("📺 اختر القناة:\n\n" "أعد توجيه رسالة من القناة أو اكتب معرفها (-100xxxxxxxxxx).")
    await state.set_state(VotingStates.await_channel_select)
    await cb.answer()


@voting_router.callback_query(F.data == "voting_mixed")
async def create_mixed_voting(cb: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(voting_type="mixed", stars_per_vote=2)
    text = "🗳️⭐ تصويتب عادي + نجوم\n\n" "كم نجمة للتصويتب المدفوع؟ (الافتراضي: 2)"
    await cb.message.answer("📺 اختر القناة:\n\n" "أعد توجيه رسالة من القناة أو اكتب معرفها (-100xxxxxxxxxx).")
    await state.set_state(VotingStates.await_channel_select)
    await cb.answer()


@voting_router.message(StateFilter(VotingStates.await_channel_select))
async def handle_voting_channel(message: Message, state: FSMContext) -> None:
    channel_id = 0
    
    if message.forward_from_chat:
        channel_id = message.forward_from_chat.id
    elif message.text:
        text = message.text.strip()
        if text.startswith("-100") or text.lstrip("-").isdigit():
            try:
                channel_id = int(text)
            except ValueError:
                pass
    
    if not channel_id:
        await message.answer("❌ لم أتمكن من تحديد القناة. حاول مرة أخرى.")
        return
    
    await state.update_data(channel_id=channel_id)
    await state.set_state(VotingStates.await_customization)
    
    data = await state.get_data()
    voting_type = data.get("voting_type", "normal")
    
    text = (
        f"📋 نوع المسابقة: {voting_type}\n\n"
        f"⚙️ إعدادات الأمان:\n\n"
        f"1️⃣ هل يتطلب اشتراك؟ (نعم/لا)"
    )
    await message.answer(text, reply_markup=voting_settings_kb())


@voting_router.callback_query(F.data.in_(["voting_setting_yes", "voting_setting_no"]), StateFilter(VotingStates))
async def handle_voting_setting(cb: CallbackQuery, state: FSMContext) -> None:
    setting = cb.data.split("_")[-1]
    data = await state.get_data()
    
    if "settings" not in data:
        data["settings"] = {}
    
    # Cycle through settings: require_subscription -> anti_bot -> exclude_leavers -> premium
    current_settings = list(data["settings"].keys())
    
    if len(current_settings) < 4:
        setting_keys = ["require_subscription", "anti_bot_enabled", "exclude_leavers", "premium_only"]
        next_setting = setting_keys[len(current_settings)]
        data["settings"][next_setting] = (setting == "yes")
        await state.update_data(data)
        
        remaining = [s for s in setting_keys if s not in data["settings"]]
        if remaining:
            text = f"⚙️ إعداد: {remaining[0].replace('_', ' ')}\n" "✅ تفعيل | ❌ تعطيل"
            await cb.message.edit_text(text, reply_markup=voting_settings_kb())
        else:
            await cb.message.edit_text("✅ تم حفظ الإعدادات، أدخل نص المسابقة:")
            await state.set_state(VotingStates.await_text)
    await cb.answer()


@voting_router.message(StateFilter(VotingStates.await_text))
async def handle_voting_text(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    if not text:
        await message.answer("يرجى إدخال نص صحيح.")
        return
    
    await state.update_data(text_raw=text, text_style="plain")
    await message.answer(
        "✅ تم حفظ النص!\n\n" "اضغط تأكيد لإنشاء المسابقة أو إلغاء.",
        reply_markup=voting_confirm_kb(),
    )
    await state.set_state(VotingStates.await_confirm)


@voting_router.callback_query(F.data == "voting_confirm", StateFilter(VotingStates))
async def confirm_voting(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    
    async for session in get_async_session():
        repo = VotingRepository(session)
        
        voting_type = data.get("voting_type", "normal")
        stars_per_vote = data.get("stars_per_vote", 0)
        text_raw = data.get("text_raw", "")
        text_style = data.get("text_style", "plain")
        settings = data.get("settings", {})
        
        contest = await repo.create_contest(
            owner_id=cb.from_user.id,
            channel_id=data.get("channel_id", 0),
            text_raw=text_raw,
            text_style=text_style,
            voting_type=voting_type,
            stars_per_vote=stars_per_vote,
            require_subscription=settings.get("require_subscription", True),
            anti_bot_enabled=settings.get("anti_bot_enabled", True),
            exclude_leavers=settings.get("exclude_leavers", True),
            premium_only=settings.get("premium_only", False),
        )
        
        # Post to channel
        styled = StyledText(text_raw, text_style).render()
        join_kb = voting_join_kb("")
        
        try:
            msg = await cb.bot.send_message(
                chat_id=contest.channel_id,
                text=f"{styled}\n\n🗳️ المسابقة مفتوحة للتصويتب!",
                parse_mode=ParseMode.HTML,
                reply_markup=join_kb,
            )
            contest.channel_message_id = msg.message_id
            await session.commit()
        except (TelegramBadRequest, TelegramForbiddenError):
            pass
    
    await state.clear()
    await cb.message.edit_text(
        f"✅ تم إنشاء المسابقة بنجاح!\n\n" f"🆔 رقم المسابقة: {contest.id}\n" f"📺 نوع التصويتب: {voting_type}"
    )
    await cb.answer()


@voting_router.callback_query(F.data == "voting_cancel", StateFilter(VotingStates))
async def cancel_voting(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cb.message.edit_text("❌ تم إلغاء إنشاء المسابقة.")
    await cb.answer()


@voting_router.callback_query(F.data.startswith("voting_join:"))
async def join_voting_contest(cb: CallbackQuery, state: FSMContext) -> None:
    vote_code = cb.data.split(":")[1]
    
    async for session in get_async_session():
        repo = VotingRepository(session)
        candidate = await repo.get_candidate_by_code(vote_code)
        
        if candidate:
            contest = await repo.get_contest(candidate.contest_id)
            if contest and contest.is_active:
                await cb.answer("✅ أنت مسجل في المسابقة بالفعل!", show_alert=True)
                return
        
        # Ask for display name
        await state.update_data(vote_code=vote_code, candidate_id=None)
        await cb.message.answer("📛 أدخل اسمك أو لقبك للمشاركة:")
        await state.set_state(VotingStates.await_candidate_name)
    
    await cb.answer()


@voting_router.message(StateFilter(VotingStates.await_candidate_name))
async def handle_candidate_name(message: Message, state: FSMContext) -> None:
    display_name = message.text.strip()
    if len(display_name) < 2:
        await message.answer("يرجى إدخال اسم صحيح (حرفين على الأقل).")
        return
    
    data = await state.get_data()
    vote_code = data.get("vote_code")
    
    async for session in get_async_session():
        repo = VotingRepository(session)
        
        candidate = await repo.get_candidate_by_code(vote_code)
        if candidate:
            await message.answer("✅ أنت مسجل بالفعل!")
            await state.clear()
            return
        
        # Create new candidate
        await repo.add_candidate(
            contest_id=0,  # Will be set based on vote_code
            user_id=message.from_user.id,
            display_name=display_name,
            vote_code=vote_code,
        )
        
        await message.answer(f"✅ تم التسجيل بنجاح!\n\n📛 الاسم: {display_name}\n🔖 كود التصويت: {vote_code}")
    
    await state.clear()


@voting_router.callback_query(F.data.startswith("vote_normal:"))
async def vote_normal(cb: CallbackQuery) -> None:
    parts = cb.data.split(":")
    contest_id = int(parts[1])
    candidate_id = int(parts[2])
    
    async for session in get_async_session():
        repo = VotingRepository(session)
        
        if await repo.has_voted(contest_id, candidate_id, cb.from_user.id):
            await cb.answer("❌你已经投过票了!", show_alert=True)
            return
        
        await repo.add_vote(contest_id, candidate_id, cb.from_user.id, is_star_vote=False)
        
        # Update candidate vote count
        candidate = await session.get(VotingCandidate, candidate_id)
        if candidate:
            candidate.normal_votes += 1
            await session.commit()
    
    await cb.answer("✅ تم التصويتب بنجاح!", show_alert=True)


@voting_router.callback_query(F.data.startswith("vote_stars:"))
async def vote_stars(cb: CallbackQuery) -> None:
    parts = cb.data.split(":")
    contest_id = int(parts[1])
    candidate_id = int(parts[2])
    stars_amount = int(parts[3]) if len(parts) > 3 else 2
    
    async for session in get_async_session():
        repo = VotingRepository(session)
        
        if await repo.has_voted(contest_id, candidate_id, cb.from_user.id):
            await cb.answer("❌你已经投过票了!", show_alert=True)
            return
        
        await repo.add_vote(contest_id, candidate_id, cb.from_user.id, is_star_vote=True, stars_amount=stars_amount)
        
        # Update candidate
        candidate = await session.get(VotingCandidate, candidate_id)
        if candidate:
            candidate.star_votes += 1
            await session.commit()
    
    await cb.answer(f"✅ تم التصويتب بـ {stars_amount} ⭐ بنجاح!", show_alert=True)


@voting_router.callback_query(F.data.startswith("voting_end:"))
async def end_voting_contest(cb: CallbackQuery) -> None:
    contest_id = int(cb.data.split(":")[1])
    
    async for session in get_async_session():
        repo = VotingRepository(session)
        contest = await repo.get_contest(contest_id)
        
        if not contest:
            await cb.answer("❌ المسابقة غير موجودة", show_alert=True)
            return
        
        if contest.owner_id != cb.from_user.id:
            await cb.answer("❌ ليس لديك صلاحية", show_alert=True)
            return
        
        await repo.end_contest(contest_id)
    
    await cb.answer("🔴 تم إنهاء المسابقة", show_alert=True)
    await cb.message.edit_text("🔴 تم إنهاء المسابقة.")


@voting_router.callback_query(F.data.startswith("voting_results:"))
async def show_voting_results(cb: CallbackQuery) -> None:
    contest_id = int(cb.data.split(":")[1])
    
    async for session in get_async_session():
        repo = VotingRepository(session)
        contest = await repo.get_contest(contest_id)
        
        if not contest:
            await cb.answer("❌ المسابقة غير موجودة", show_alert=True)
            return
        
        from sqlalchemy import select
        from ..db.models import VotingCandidate
        
        result = await session.execute(
            select(VotingCandidate).where(VotingCandidate.contest_id == contest_id)
        )
        candidates = list(result.scalars().all())
        
        text = f"📊 نتائج المسابقة #{contest_id}\n\n"
        for i, c in enumerate(sorted(candidates, key=lambda x: x.normal_votes + x.star_votes, reverse=True), 1):
            total_votes = c.normal_votes + c.star_votes
            text += f"{i}. {c.display_name}: {total_votes} صوت ({c.normal_votes} عادي, {c.star_votes} ⭐)\n"
    
    await cb.message.edit_text(text, reply_markup=voting_controls_kb(contest_id, contest.is_active))
    await cb.answer()