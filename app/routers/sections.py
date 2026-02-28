from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery

from ..keyboards.common import main_menu_kb

sections_router = Router(name="sections")


@sections_router.callback_query(F.data.startswith("section_"))
async def handle_sections(cb: CallbackQuery) -> None:
    section = cb.data.replace("section_", "")

    # For now, most sections are placeholders for the upcoming phases
    messages = {
        "roulette": "🎰 قسم الروليت: استخدم الأوامر لإنشاء سحب جديد أو إدارة سحوباتك.",
        "voting": "🗳️ قسم مسابقات التصويت: ستتم إضافة هذه الميزة في المرحلة الرابعة.",
        "yastahiq": "🏆 مسابقة 'يستحق': ستتم إضافة هذه الميزة في المرحلة الرابعة.",
        "quiz": "❓ قسم مسابقة الأسئلة: ستتم إضافة هذه الميزة في المرحلة الخامسة.",
        "manage_chats": "⚙️ إدارة المجموعات أو القنوات: يمكنك ربط قنواتك من خلال تحويل رسالة منها للبوت.",
        "subscription": "💎 قسم إدارة الاشتراك: يمكنك ترقية حسابك للحصول على ميزات إضافية.",
        "my_contests": "📊 إدارة سحوباتي ومسابقاتي: استخدم زر 'سحوباتي' في القائمة السابقة (سيتم دمجه هنا لاحقاً).",
        "points": "💰 قسم كسب النقاط: شارك رابط الإحالة الخاص بك لكسب النقاط.",
    }

    text = messages.get(section, "قريباً...")
    await cb.message.answer(text)
    await cb.answer()
