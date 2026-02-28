from __future__ import annotations

import random
from typing import Tuple

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


class AntiBotService:
    """Service to generate and verify anti-bot challenges."""

    @staticmethod
    def generate_math_challenge() -> Tuple[str, int]:
        """Generates a simple addition challenge."""
        a = random.randint(1, 10)
        b = random.randint(1, 10)
        return f"يرجى حل المسألة التالية للتأكد من أنك لست روبوت:\n\n{a} + {b} = ؟", a + b

    @staticmethod
    def get_challenge_keyboard(correct_answer: int) -> InlineKeyboardMarkup:
        """Generates a keyboard with options, including the correct answer."""
        options = {correct_answer}
        while len(options) < 4:
            options.add(random.randint(1, 20))

        sorted_options = sorted(list(options))
        buttons = []
        row = []
        for opt in sorted_options:
            row.append(InlineKeyboardButton(text=str(opt), callback_data=f"antibot_ans:{opt}"))
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)

        return InlineKeyboardMarkup(inline_keyboard=buttons)
