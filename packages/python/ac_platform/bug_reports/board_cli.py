"""Bug reports to the team's work board, one environment at a time (owner, 23 Oct 2026).

The host job ``ac-bug-board`` runs this inside the environment (the worker container on
staging and production, the active slot on dev) and does the board side itself:

  python -m ac_platform.bug_reports.board_cli --database-url-file F pending [--limit 10]
      reports with no board card yet, oldest first, as JSON (no names or emails)
  python -m ac_platform.bug_reports.board_cli --database-url-file F mark BUG_ID CARD
      records the card (e.g. AUT-2301) as the report's board event; a second card for the
      same report is refused, so a retried run never raises two

Prints JSON and exits 0, or prints an error and exits 1 (2 for usage).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID


def _arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="bug_reports.board_cli")
    parser.add_argument("--database-url-file", required=True, type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    pending = commands.add_parser("pending")
    pending.add_argument("--limit", type=int, default=10, choices=range(1, 51))
    mark = commands.add_parser("mark")
    mark.add_argument("bug_id", type=UUID)
    mark.add_argument("card")
    return parser.parse_args(argv)


async def _run(arguments: argparse.Namespace) -> dict[str, object]:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from ac_platform.bug_reports.store import BugReportStore

    url = arguments.database_url_file.read_text().strip()
    engine = create_async_engine(url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sessions() as database, database.begin():
            store = BugReportStore(database)
            if arguments.command == "pending":
                return {"reports": await store.without_card(limit=arguments.limit)}
            recorded = await store.record_card(
                arguments.bug_id, arguments.card, now=datetime.now(UTC)
            )
            return {"bug_id": str(arguments.bug_id), "card": arguments.card, "recorded": recorded}
    finally:
        await engine.dispose()


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
