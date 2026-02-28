from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def voting_main_kb(contest_id: int, entries: list) -> InlineKeyboardMarkup:
    """Main keyboard for a voting contest in the channel."""
    buttons = []
    for entry in entries:
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"❤️ {entry.entry_name} ({entry.votes_count})",
                    callback_data=f"vote:{contest_id}:{entry.id}",
                )
            ]
        )

    buttons.append(
        [InlineKeyboardButton(text="🏆 عرض المتصدرين", callback_data=f"leaderboard:{contest_id}")]
    )
    buttons.append(
        [
            InlineKeyboardButton(
                text="📢 اشترك في المسابقة", callback_data=f"reg_contest:{contest_id}"
            )
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def voting_dual_kb(contest_id: int, entry_id: int, votes: int, stars: int) -> InlineKeyboardMarkup:
    """Keyboard for a single contestant in dual mode (Normal + Stars)."""
    buttons = [
        [
            InlineKeyboardButton(
                text=f"❤️ تصويت عادي ({votes})", callback_data=f"vote_norm:{contest_id}:{entry_id}"
            ),
            InlineKeyboardButton(
                text=f"⭐️ تصويت نجوم ({stars})", callback_data=f"vote_star:{contest_id}:{entry_id}"
            ),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)
