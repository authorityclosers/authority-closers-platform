"""The weekly friction report, one environment at a time (owner, 25 Oct 2026: "a weekly
report feeding the redesign loop").

The host job ``ac-telemetry-friction`` runs this inside the environment (the worker
container on staging and production, the active slot on dev) and writes the markdown where
the owner and the builders read it:

  python -m ac_platform.telemetry.friction_cli --database-url-file F --environment E
      [--week YYYY-MM-DD]
      the week that starts on that Monday (default: the last India week that has ended)

It only reads: the transaction is read-only, and it reads Sales X-Ray's analytics events
(counts, timings and code names; telemetry/friction.py). Prints one JSON line with the week,
the number of findings and the markdown, and exits 0; or prints an error and exits 1 (2 for
usage). Admin → Product telemetry → Friction shows the same report, live.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any


def _arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="telemetry.friction_cli")
    parser.add_argument("--database-url-file", required=True, type=Path)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--week", type=date.fromisoformat, default=None)
    return parser.parse_args(argv)


def workspace_kinds() -> dict[str, str]:
    """Personal and the operations workspace by id, where the environment says them."""
    kinds: dict[str, str] = {}
    for variable, kind in (
        ("AC_PUBLIC_LEARNER_TENANT_ID", "personal"),
        ("AC_OPERATIONS_TENANT_ID", "operations"),
    ):
        value = os.environ.get(variable, "").strip()
        if value:
            kinds[value] = kind
    return kinds


async def _run(arguments: argparse.Namespace) -> dict[str, Any]:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from ac_platform.telemetry import friction
    from ac_platform.telemetry.admin_view import read_rows

    now = datetime.now(UTC)
    week = friction.monday(arguments.week) if arguments.week else friction.last_full_week(now)
    start, end = friction.week_window(week)
    earlier, _ = friction.week_window(week - friction.WEEK)
    url = arguments.database_url_file.read_text().strip()
    engine = create_async_engine(url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sessions() as database, database.begin():
            await database.execute(text("SET TRANSACTION READ ONLY"))
            read = await database.run_sync(
                lambda connection: read_rows(
                    connection, since=earlier, until=min(end, now), now=now
                )
            )
    finally:
        await engine.dispose()
    current = [row for row in read.rows if row.at >= start]
    before = [row for row in read.rows if row.at < start]
    report = friction.report(
        current,
        before,
        week=week,
        now=now,
        environment=arguments.environment,
        kinds=workspace_kinds(),
        truncated=read.truncated,
    )
    return {
        "week": report["week"],
        "complete": report["complete"],
        "findings": len(report["findings"]),
        "events": report["coverage"]["events"],
        "markdown": friction.to_markdown(report),
    }


def main(argv: list[str] | None = None) -> int:
    arguments = _arguments(sys.argv[1:] if argv is None else argv)
    try:
        result = asyncio.run(_run(arguments))
    except Exception as error:  # noqa: BLE001 - one plain line for the host job's log
        print(json.dumps({"error": type(error).__name__, "detail": str(error)[:300]}))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
