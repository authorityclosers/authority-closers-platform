"""What to fix next from real use, one environment at a time (orchestrator for the owner, 27 Oct
2026: "card errors, dead taps and crashes from real use, the same carding as the radar").

The host job ``ac-bug-radar telemetry`` runs this inside the environment (the worker container
on staging and production, the active slot on dev) and turns the findings into AC Pulse cards:

  python -m ac_platform.telemetry.fix_next_cli --database-url-file F --environment E
      [--window 24h|7d|30d] [--limit N]
      the window up to now against the one before it (default 7d), the top N findings (25)

It only reads: the transaction is read-only, and it reads Sales X-Ray's analytics events
(counts, timings, code names and pseudonyms; telemetry/improvement.py fix_next). Prints one
JSON line, the same answer as Admin → Product telemetry → Fix next, and exits 0; or prints an
error and exits 1 (2 for usage).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="telemetry.fix_next_cli")
    parser.add_argument("--database-url-file", required=True, type=Path)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--window", choices=("24h", "7d", "30d"), default="7d")
    parser.add_argument("--limit", type=int, default=25)
    return parser.parse_args(argv)


async def _run(arguments: argparse.Namespace) -> dict[str, Any]:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from ac_platform.telemetry.admin_view import WINDOWS, read_rows
    from ac_platform.telemetry.improvement import fix_next

    now = datetime.now(UTC)
    since = now - WINDOWS[arguments.window]
    earlier = since - WINDOWS[arguments.window]
    url = arguments.database_url_file.read_text().strip()
    engine = create_async_engine(url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sessions() as database, database.begin():
            await database.execute(text("SET TRANSACTION READ ONLY"))
            read = await database.run_sync(
                lambda connection: read_rows(connection, since=earlier, until=now, now=now)
            )
    finally:
        await engine.dispose()
    answer = fix_next(
        [row for row in read.rows if row.at >= since],
        [row for row in read.rows if row.at < since],
        now=now,
        window=arguments.window,
        environment=arguments.environment,
        limit=arguments.limit,
    )
    return {**answer, "truncated": read.truncated}


def main(argv: list[str] | None = None) -> int:
    arguments = _arguments(sys.argv[1:] if argv is None else argv)
    try:
        result = asyncio.run(_run(arguments))
    except Exception as error:  # noqa: BLE001 - one plain line for the host job's log
        print(json.dumps({"error": type(error).__name__, "detail": str(error)[:300]}))
        return 1
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
