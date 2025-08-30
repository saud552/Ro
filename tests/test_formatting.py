from __future__ import annotations

import importlib
import sys
import types

import pytest


def _install_aiogram_stub() -> None:
    # Create stub for aiogram.utils.text_decorations.html_decoration
    aiogram_mod = types.ModuleType("aiogram")
    utils_mod = types.ModuleType("aiogram.utils")
    td_mod = types.ModuleType("aiogram.utils.text_decorations")

    class _HD:
        @staticmethod
        def quote(text: str) -> str:
            return text

        @staticmethod
        def bold(text: str) -> str:
            return f"<b>{text}</b>"

        @staticmethod
        def italic(text: str) -> str:
            return f"<i>{text}</i>"

        @staticmethod
        def spoiler(text: str) -> str:
            return f'<span class="tg-spoiler">{text}</span>'

    td_mod.html_decoration = _HD()  # type: ignore[attr-defined]
    sys.modules["aiogram"] = aiogram_mod
    sys.modules["aiogram.utils"] = utils_mod
    sys.modules["aiogram.utils.text_decorations"] = td_mod


def _import_formatting():
    _install_aiogram_stub()
    return importlib.import_module("app.services.formatting")


@pytest.mark.parametrize(
    "input_text,expected_style,expected_inner",
    [
        ("#تشويش hello #تشويش", "spoiler", "hello"),
        ("#عريض hi #عريض", "bold", "hi"),
        ("#مائل ok #مائل", "italic", "ok"),
        ("#اقتباس q #اقتباس", "quote", "q"),
        ("plain text", "plain", "plain text"),
    ],
)
def test_parse_style(input_text: str, expected_style: str, expected_inner: str) -> None:
    fmt = _import_formatting()
    inner, style = fmt.parse_style_from_text(input_text)
    assert style == expected_style
    assert inner == expected_inner


def test_styled_text_render_plain() -> None:
    fmt = _import_formatting()
    rendered = fmt.StyledText("hello", "plain").render()
    assert "hello" in rendered
