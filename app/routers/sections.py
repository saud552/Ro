from __future__ import annotations

from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select

from ..db import get_async_session
from ..db.models import FeatureAccess, User
from ..keyboards.common import main_menu_kb
from ..utils.compat import safe_answer, safe_edit_text

sections_router = Router(name="sections")


@sections_router.callback_query(F.data == "section_roulette")
async def section_roulette(cb: CallbackQuery) -> None:
    text = (
        "🎯 <b>قسم السحب العشوائي (الروليت)</b>\n\n"
        "هذا القسم يتيح لك إنشاء سحوبات احترافية في قناتك مع ميزات:\n"
        "• منع الحسابات الوهمية.\n"
        "• اشتراك إجباري في عدة قنوات.\n"
        "• استبعاد المغادرين تلقائياً.\n"
        "• تحديد عدد الفائزين."
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ إنشاء سحب جديد", callback_data="create_roulette")],
            [InlineKeyboardButton(text="📦 سحوباتي", callback_data="my_draws")],
            [InlineKeyboardButton(text="🔙 رجوع", callback_data="main_menu")],
        ]
    )
    await safe_edit_text(cb.message, text, reply_markup=kb, parse_mode="HTML")
    await cb.answer()


@sections_router.callback_query(F.data == "section_vote")
async def section_vote(cb: CallbackQuery) -> None:
    text = (
        "🗳 <b>قسم مسابقات التصويت</b>\n\n"
        "أنشئ مسابقات تصويت عادلة مع دعم:\n"
        "• التصويت العادي.\n"
        "• التصويت عبر نجوم تلغرام.\n"
        "• منع تكرار التصويت.\n"
        "• لوحة متصدرين حية."
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ إنشاء مسابقة تصويت", callback_data="create_vote")],
            [InlineKeyboardButton(text="📦 مسابقاتي", callback_data="my_draws")],
            [InlineKeyboardButton(text="🔙 رجوع", callback_data="main_menu")],
        ]
    )
    await safe_edit_text(cb.message, text, reply_markup=kb, parse_mode="HTML")
    await cb.answer()


@sections_router.callback_query(F.data == "section_yastahiq")
async def section_yastahiq(cb: CallbackQuery) -> None:
    text = (
        "🔥 <b>قسم مسابقات يستحق</b>\n\n"
        "حوّل التفاعل في مجموعتك إلى مسابقة!\n"
        "البوت يراقب الكلمات مثل 'يستحق' أو 'كفو' ويضيف نقاطاً للمرسل إليه تلقائياً."
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ تفعيل في مجموعة", callback_data="create_yastahiq")],
            [InlineKeyboardButton(text="🔙 رجوع", callback_data="main_menu")],
        ]
    )
    await safe_edit_text(cb.message, text, reply_markup=kb, parse_mode="HTML")
    await cb.answer()


@sections_router.callback_query(F.data == "section_quiz")
async def section_quiz(cb: CallbackQuery) -> None:
    text = (
        "🧠 <b>قسم المسابقات الثقافية (Quiz)</b>\n\n"
        "قم بإدارة مسابقات أسئلة وأجوبة تلقائية:\n"
        "• بنك أسئلة متنوع.\n"
        "• فواصل زمنية بين الأسئلة.\n"
        "• تصحيح تلقائي وحساب للنقاط."
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ إنشاء كويز", callback_data="create_quiz")],
            [InlineKeyboardButton(text="🔙 رجوع", callback_data="main_menu")],
        ]
    )
    await safe_edit_text(cb.message, text, reply_markup=kb, parse_mode="HTML")
    await cb.answer()


@sections_router.callback_query(F.data == "section_channels")
async def section_channels(cb: CallbackQuery) -> None:
    text = (
        "📢 <b>إدارة القنوات والمجموعات</b>\n\n"
        "يمكنك هنا ربط قنواتك لتتمكن من استخدامها في شروط الانضمام للمسابقات."
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔗 ربط قناة جديدة", callback_data="link_channel")],
            [InlineKeyboardButton(text="✂️ فك ارتباط قناة", callback_data="unlink_channel")],
            [InlineKeyboardButton(text="🔙 رجوع", callback_data="main_menu")],
        ]
    )
    await safe_edit_text(cb.message, text, reply_markup=kb, parse_mode="HTML")
    await safe_answer(cb)


@sections_router.callback_query(F.data == "section_referral")
async def section_referral(cb: CallbackQuery) -> None:
    me = await cb.bot.get_me()
    bot_username = me.username
    ref_link = f"https://t.me/{bot_username}?start={cb.from_user.id}"

    async for session in get_async_session():
        stmt = select(User).where(User.id == cb.from_user.id)
        user = (await session.execute(stmt)).scalar_one()
        points = user.points

    text = (
        "💰 <b>نظام الإحالة والارباح</b>\n\n"
        "شارك رابطك الخاص واربح نقاطاً مقابل كل شخص ينضم عبرك!\n\n"
        f"🔗 رابطك: <code>{ref_link}</code>\n"
        f"💎 رصيدك الحالي: <b>{points}</b> نقطة"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔙 رجوع", callback_data="main_menu")],
        ]
    )
    await safe_edit_text(cb.message, text, reply_markup=kb, parse_mode="HTML")
    await safe_answer(cb)


@sections_router.callback_query(F.data == "section_account")
async def section_account(cb: CallbackQuery) -> None:
    async for session in get_async_session():
        stmt = select(FeatureAccess).where(
            (FeatureAccess.user_id == cb.from_user.id)
            & (FeatureAccess.feature_key == "gate_channel")
        )
        access = (await session.execute(stmt)).scalar_one_or_none()

        status = "❌ غير مشترك"
        if access:
            now = datetime.now(timezone.utc)
            expires = access.expires_at
            if expires and expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)

            if expires and expires > now:
                status = f"✅ مشترك (ينتهي: {expires.strftime('%Y-%m-%d')})"
            elif access.one_time_credits > 0:
                status = f"✅ رصيد متاح ({access.one_time_credits} مسابقة)"

    text = (
        "👤 <b>حسابي واشتراكاتي</b>\n\n"
        f"الاسم: <b>{cb.from_user.full_name}</b>\n"
        f"المعرف: <code>{cb.from_user.id}</code>\n\n"
        f"حالة ميزة قنوات الشرط: {status}"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔙 رجوع", callback_data="main_menu")],
        ]
    )
    await safe_edit_text(cb.message, text, reply_markup=kb, parse_mode="HTML")
    await safe_answer(cb)


@sections_router.callback_query(F.data == "section_store")
async def section_store(cb: CallbackQuery) -> None:
    price_once = 50
    price_month = 200

    async for session in get_async_session():
        stmt = select(User).where(User.id == cb.from_user.id)
        user = (await session.execute(stmt)).scalar_one()
        points = user.points

    text = (
        "🛒 <b>متجر النقاط</b>\n\n"
        f"💎 رصيدك الحالي: <b>{points}</b> نقطة\n\n"
        "يمكنك استبدال نقاطك بميزات المسابقات:\n"
        f"1️⃣ إنشاء مسابقة واحدة: <b>{price_once}</b> نقطة\n"
        f"2️⃣ اشتراك شهري كامل: <b>{price_month}</b> نقطة\n\n"
        "<i>(النقاط تُكتسب عبر دعوة الأصدقاء)</i>"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"شراء مسابقة ({price_once}ن)", callback_data="buy_points_once"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"اشتراك شهري ({price_month}ن)", callback_data="buy_points_month"
                )
            ],
            [InlineKeyboardButton(text="🔙 رجوع", callback_data="main_menu")],
        ]
    )
    await safe_edit_text(cb.message, text, reply_markup=kb, parse_mode="HTML")
    await cb.answer()


@sections_router.callback_query(F.data == "main_menu")
async def back_to_main(cb: CallbackQuery) -> None:
    await safe_edit_text(
        cb.message,
        "يرجى اختيار القسم المطلوب من القائمة أدناه:",
        reply_markup=main_menu_kb(),
    )
    await cb.answer()


@sections_router.callback_query(F.data.startswith("buy_points_"))
async def buy_with_points(cb: CallbackQuery) -> None:
    mode = cb.data.replace("buy_points_", "")
    cost = 50 if mode == "once" else 200

    async for session in get_async_session():
        stmt = select(User).where(User.id == cb.from_user.id)
        user = (await session.execute(stmt)).scalar_one()

        if user.points < cost:
            await cb.answer("⚠️ رصيد نقاطك غير كافٍ!", show_alert=True)
            return

        user.points -= cost
        from ..services.payments import grant_monthly, grant_one_time

        if mode == "once":
            await grant_one_time(cb.from_user.id, credits=1)
        else:
            await grant_monthly(cb.from_user.id)

        await session.commit()

    await cb.message.answer(f"✅ تمت العملية بنجاح! تم خصم {cost} نقطة وتفعيل الميزة.")
    await cb.answer()
