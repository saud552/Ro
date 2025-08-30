from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


# ملخص: سياق وقت التشغيل لتخزين معلومات مشتركة على مستوى البوت.
@dataclass
class RuntimeContext:
    bot_username: str = ""
    bot_id: Optional[int] = None
    redis: Any = None


runtime = RuntimeContext()
