from __future__ import annotations

import time
from typing import Dict, List

try:
    from redis.asyncio import Redis as AsyncRedis
except Exception:
    AsyncRedis = None  # type: ignore


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._store: Dict[str, List[float]] = {}

    async def allow(self, key: str, max_calls: int, period_seconds: int) -> bool:
        now = time.monotonic()
        window_start = now - period_seconds
        bucket = self._store.setdefault(key, [])
        # prune
        self._store[key] = [t for t in bucket if t >= window_start]
        if len(self._store[key]) >= max_calls:
            return False
        self._store[key].append(now)
        return True


class RedisRateLimiter:
    def __init__(self, redis: AsyncRedis) -> None:
        self._redis = redis

    async def allow(self, key: str, max_calls: int, period_seconds: int) -> bool:
        # Fixed-window counter: INCR and set TTL
        counter_key = f"rl:{key}:{int(time.time() // period_seconds)}"
        count = await self._redis.incr(counter_key)
        # ensure expiry
        if count == 1:
            await self._redis.expire(counter_key, period_seconds)
        return count <= max_calls


def get_rate_limiter(redis: AsyncRedis | None) -> InMemoryRateLimiter | RedisRateLimiter:
    if redis is not None:
        return RedisRateLimiter(redis)
    return InMemoryRateLimiter()
