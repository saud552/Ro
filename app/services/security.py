import random
from typing import Any, List, Optional
import time

def draw_unique(population_indices: range, k: int) -> List[int]:
    """Securely pick k winners from the population."""
    pop_list = list(population_indices)
    if not pop_list:
        return []
    if k >= len(pop_list):
        return pop_list
    return random.sample(pop_list, k)

class FailureMonitor:
    """Monitors system failures for gates and alerts creators."""

    def __init__(self, redis: Any) -> None:
        self.redis = redis

    async def report_failure(self, contest_id: int, creator_id: int, gate_id: int, bot: Any):
        """Report a system failure (e.g., bot kicked)."""
        if not self.redis:
            return

        key_count = f"fail_count:{contest_id}:{gate_id}"
        key_last_alert = f"fail_alert:{contest_id}:{gate_id}"

        # Increase the failure counter
        await self.redis.incr(key_count)

        # Get count
        val = await self.redis.get(key_count)
        count = int(val) if val else 0

        if count >= 5:
            now = time.time()
            last_alert_val = await self.redis.get(key_last_alert)
            last_alert = float(last_alert_val) if last_alert_val else 0

            if now - last_alert >= 30:
                await self.redis.set(key_last_alert, str(now))

                # Send alert to creator
                alert_text = (
                    f"⚠️ <b>تنبيه عاجل للمنشئ:</b>\n\n"
                    f"هناك مشكلة في أحد شروط المسابقة رقم #{contest_id}.\n"
                    f"يبدو أن البوت قد فقد الصلاحيات في القناة/المجموعة المضافة كشرط.\n"
                    f"يرجى التحقق من صلاحيات البوت لضمان استمرار التصويت."
                )
                try:
                    await bot.send_message(creator_id, alert_text, parse_mode="HTML")
                except:
                    pass

    async def reset_failure(self, contest_id: int, gate_id: int):
        """Reset failure counter when gate passes."""
        if self.redis:
            await self.redis.delete(f"fail_count:{contest_id}:{gate_id}")
