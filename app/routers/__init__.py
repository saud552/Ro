from __future__ import annotations

from aiogram import Dispatcher

from .admin import admin_router
from .my import my_router
from .roulette import roulette_router
from .start import start_router
from .system import system_router


# ملخص: تسجيل جميع الراوترات ضمن الـ Dispatcher.
def setup_routers(dp: Dispatcher) -> None:
    dp.include_router(start_router)
    dp.include_router(roulette_router)
    dp.include_router(admin_router)
    dp.include_router(system_router)
    dp.include_router(my_router)
