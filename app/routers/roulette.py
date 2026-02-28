from __future__ import annotations

import asyncio
import unicodedata
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from html import escape
from typing import Optional
from urllib.parse import urlparse

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command, StateFilter
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
from loguru import logger
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from ..db import get_async_session
from ..db.models import BotChat, ChannelLink, Notification, Participant, Roulette, RouletteGate
from ..keyboards.channel import link_instruction_kb, roulette_controls_kb
from ..keyboards.common import (
    back_kb,
    confirm_cancel_kb,
    gate_add_menu_kb,
    gate_choice_kb,
    gate_pick_list_kb,
    gates_manage_kb,
)
from ..keyboards.my import manage_draw_kb
from ..services.context import runtime
from ..services.formatting import StyledText, parse_style_from_text
from ..services.payments import grant_monthly, grant_one_time, has_gate_access, log_purchase
from ..services.ratelimit import get_rate_limiter
from ..services.security import draw_unique

# ملخص: أقفال داخلية بسيطة لمنع تنفيذ متزامن لنفس العملية (داخل العملية فقط).
_inproc_locks: dict[str, bool] = {}

# Markdown (legacy) escape for link text
_DEF_MD_ESC = set("_*[]()")

def _escape_md(text: str) -> str:
    res = []
    for ch in text:
        if ch in _DEF_MD_ESC:
            res.append("\" + ch)
        else:
            res.append(ch)
    return "".join(res)


roulette_router = Router(name="roulette")


class CreateRoulette(StatesGroup):
    await_channel = State()
    await_text = State()
    await_gate_choice = State()
    await_winners = State()
    await_confirm = State()


@dataclass
class PendingRoulette:
    text_raw: str
    style: str
    winners: int
    channel_id: int


async def _allow(user_id: int, action: str, max_calls: int = 3, period_seconds: int = 5) -> bool:
    limiter = get_rate_limiter(runtime.redis)
    return await limiter.allow(f"{user_id}:{action}", max_calls, period_seconds)


async def _get_user_channel_id(user_id: int) -> Optional[int]:
    async for session in get_async_session():
        row = (
            (
                await session.execute(
                    select(ChannelLink)
                    .where(ChannelLink.owner_id == user_id)
                    .order_by(ChannelLink.id.desc())
                )
            )
            .scalars()
            .first()
        )
        return row.channel_id if row else None


# ===== Helpers =====

def _build_channel_post_text(r: Roulette, participants_count: int) -> str:
    """Compose channel post text with styling, status line, and participants count."""
    styled = StyledText(r.text_raw, r.text_style).render()
    status_line = (
        "المشاركة في السحب متاحة حالياً"
        if r.is_open
        else "المشاركة في السحب متوقفة حالياً"
    )
    return f"{styled}\n\n{status_line}\nعدد المشاركين: {participants_count}"


async def _get_channel_title_and_link(bot, chat_id: int) -> tuple[str, Optional[str]]:
    """Resolve channel/group title and a usable link.

    - Prefer public username link if available
    - Else try export_chat_invite_link (primary)
    - Else create a new invite link
    """
    title = f"Channel {chat_id}"
    link: Optional[str] = None
    try:
        c = await bot.get_chat(chat_id)
        title = getattr(c, "title", None) or title
        uname = getattr(c, "username", None)
        if uname:
            link = f"https://t.me/{uname}"
            return title, link
        # no public username -> try export primary invite link
        try:
            link = await bot.export_chat_invite_link(chat_id)
        except Exception:
            link = None
        if link:
            return title, link
        # fallback: create one
        try:
            inv = await bot.create_chat_invite_link(chat_id=chat_id, creates_join_request=False)
            link = getattr(inv, "invite_link", None)
        except Exception:
            link = None
        return title, link
    except Exception:
        return title, None


def _username_from_link(link: str) -> Optional[str]:
    """Extract @username from a public t.me link if available.

    Returns value like "@channelusername" or None if not a public username link.
    """
    text = (link or "").strip()
    if not text:
        return None
    if text.startswith("t.me/"):
        text = "https://" + text
    try:
        u = urlparse(text)
    except Exception:
        return None
    if u.netloc not in {"t.me", "telegram.me", "telegram.dog"}:
        return None
    path = u.path.strip("/ ")
    if not path:
        return None
    # Skip joinchat/+hash/private forms
    if path.startswith("+") or path.startswith("joinchat/") or path.startswith("c/"):
        return None
    username = path.split("/", 1)[0]
    if username:
        return f"@{username.lstrip('@')}"
    return None


def _parse_int_strict(text: str) -> Optional[int]:
    """Parse integer from text with support for Unicode digits (e.g., Arabic-Indic).
    Ignores whitespace; fails if any non-digit present.
    """
    s = (text or "").strip()
    if not s:
        return None
    digits: list[str] = []
    for ch in s:
        if ch.isspace():
            continue
        if ch.isdigit():
            try:
                digits.append(str(unicodedata.digit(ch)))
            except Exception:
                return None
        else:
            return None
    return int("".join(digits)) if digits else None


async def _is_admin_in_channel(bot, chat_id: int, user_id: int) -> bool:
    """Return True if user is creator/administrator in channel, else False."""
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return getattr(member, "status", None) in {"creator", "administrator"}
    except Exception:
        return False
