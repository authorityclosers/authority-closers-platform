"""Read-only watchdog check: exit 1 for overdue runs, 2 for unavailable checks."""

from __future__ import annotations

import json
import os
import sys

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine

from ac_platform.application.asyncio_runtime import run_async
from ac_platform.conversation_intelligence.run_budget_alarm import overdue_processing_plans


async def check() -> dict[str, object]:
    url = os.environ.get("AC_DATABASE_URL", "")
    if not url:
        raise ValueError("Database configuration required.")
    timeout_option = (
        "timeout" if make_url(url).get_driver_name() == "asyncpg" else "connect_timeout"
    )
    engine = create_async_engine(
        url, pool_pre_ping=True, pool_timeout=10, connect_args={timeout_option: 10}
    )
    try:
        from sqlalchemy.ext.asyncio import AsyncSession

        async with AsyncSession(engine) as database, database.begin():
            await database.execute(text("SET TRANSACTION READ ONLY"))
            await database.execute(text("SET LOCAL statement_timeout = '10s'"))
            return await overdue_processing_plans(database)
    finally:
        await engine.dispose()


def main() -> int:
    try:
        inventory = run_async(check())
    except (ValueError, OSError, SQLAlchemyError):
        # Driver exceptions can contain connection credentials.
        print("Run budget check unavailable.", file=sys.stderr)
        return 2
    print(json.dumps(inventory, sort_keys=True))
    return int(
        bool(
            inventory["overdue"]
            or inventory["overdue_sources"]
            or inventory["released_unfinished_runs"]
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
