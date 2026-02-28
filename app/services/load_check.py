from __future__ import annotations

import asyncio
import time
from sqlalchemy import select, func
from ..db import get_async_session
from ..db.models import Contest, ContestEntry, User

async def run_db_sanity_check():
    """Simulate basic load to check connection pool handling."""
    start = time.time()
    counts = {"contests": 0, "entries": 0, "users": 0}

    async for session in get_async_session():
        counts["users"] = (await session.execute(select(func.count()).select_from(User))).scalar_one()
        counts["contests"] = (await session.execute(select(func.count()).select_from(Contest))).scalar_one()
        counts["entries"] = (await session.execute(select(func.count()).select_from(ContestEntry))).scalar_one()

    end = time.time()
    print(f"Sanity check completed in {end - start:.2f}s")
    print(f"Current Load Data: {counts}")
    return counts

if __name__ == "__main__":
    asyncio.run(run_db_sanity_check())
