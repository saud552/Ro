from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def vote_mode_kb() -> InlineKeyboardMarkup:
    """Keyboard for selecting voting mode."""
    buttons = [
        [InlineKeyboardButton(text="❤️ تصويت عادي", callback_data="vmode_normal")],
        [InlineKeyboardButton(text="⭐️ تصويت نجوم", callback_data="vmode_stars")],
        [InlineKeyboardButton(text="⚖️ مزدوج (عادي + نجوم)", callback_data="vmode_both")],
        [InlineKeyboardButton(text="🔙 رجوع", callback_data="back")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def star_ratio_kb() -> InlineKeyboardMarkup:
    """Keyboard for selecting star-to-vote ratio."""
    buttons = [
        [
            InlineKeyboardButton(text="1 نجمة = 2 صوت", callback_data="vratio:2"),
            InlineKeyboardButton(text="1 نجمة = 5 أصوات", callback_data="vratio:5"),
        ],
        [
            InlineKeyboardButton(text="1 نجمة = 10 أصوات", callback_data="vratio:10"),
            InlineKeyboardButton(text="1 نجمة = 50 صوت", callback_data="vratio:50"),
        ],
        [InlineKeyboardButton(text="🔙 رجوع", callback_data="back")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def voting_main_kb(contest_id: int, bot_username: str = "bot") -> InlineKeyboardMarkup:
    """Initial keyboard for a voting contest in the channel."""
    reg_url = f"https://t.me/{bot_username}?start=reg-{contest_id}"
    notify_url = f"https://t.me/{bot_username}?start=notify-{contest_id}"

    buttons = [
        [InlineKeyboardButton(text="📢 الاشتراك في المسابقة", url=reg_url)],
        [InlineKeyboardButton(text="🏆 المتصدرين", callback_data=f"leaderboard:{contest_id}")],
        [InlineKeyboardButton(text="🔔 ذكّرني إذا فزت", url=notify_url)]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def contestant_vote_kb(contest_id: int, entry_id: int, votes: int, stars: int, mode: str, bot_username: str) -> InlineKeyboardMarkup:
    """Keyboard for an individual contestant's post in the channel."""
    url = f"https://t.me/{bot_username}?start=vote-{contest_id}-{entry_id}"
    buttons = []
    if mode == "stars":
        buttons.append([InlineKeyboardButton(text=f"⭐️ ({stars})", url=url)])
    elif mode == "both":
        buttons.append([
            InlineKeyboardButton(text=f"❤️ ({votes})", url=url),
            InlineKeyboardButton(text=f"⭐️ ({stars})", url=url)
        ])
    else: # normal
        buttons.append([InlineKeyboardButton(text=f"❤️ ({votes})", url=url)])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def voting_selection_kb(contest_id: int, entry_id: int, mode: str = "normal") -> InlineKeyboardMarkup:
    """Keyboard shown when a user clicks on a contestant to vote for them."""
    buttons = []
    if mode in {"normal", "both"}:
        buttons.append(
            [
                InlineKeyboardButton(
                    text="❤️ تصويت عادي", callback_data=f"vote_norm:{contest_id}:{entry_id}"
                )
            ]
        )
    if mode in {"stars", "both"}:
        buttons.append(
            [
                InlineKeyboardButton(
                    text="⭐️ تصويت بالنجوم", callback_data=f"vote_star_pre:{contest_id}:{entry_id}"
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def star_amounts_kb(contest_id: int, entry_id: int) -> InlineKeyboardMarkup:
    """Keyboard for choosing how many stars to spend on a vote."""
    amounts = [1, 5, 10, 50, 100, 500]
    buttons = []
    for i in range(0, len(amounts), 3):
        row = [
            InlineKeyboardButton(
                text=f"{amt} ⭐️", callback_data=f"vote_star_pay:{contest_id}:{entry_id}:{amt}"
            )
            for amt in amounts[i : i + 3]
        ]
        buttons.append(row)
    buttons.append(
        [InlineKeyboardButton(text="🔙 رجوع", callback_data=f"vote_sel:{contest_id}:{entry_id}")]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)
