"""Bug issues for agents, one environment at a time (owner, 25 Oct 2026: mark them fixed
"via bugs api cli"; v0.93).

The host command ``ac-bugs`` runs this inside the environment (the worker container on
staging and production, the active slot on dev), as ``ac-bug-board`` does, so no key or
password is handled anywhere: the database URL file is the environment's own.

  ... list [--new | --open | --solved | --all] [--since ISO] [--limit N]
  ... show ISSUE                       (an issue's number or id)
  ... set ISSUE --status fixing|fixed-in-next-update|solved --as NAME
            [--note TEXT] [--commit SHA] [--release VERSION] [--app-update]
  ... alerts --since ISO              issues with reports made since then (for the Pulse alert)
  ... reports [--status S]            reports, newest first, their words masked (v0.93)
  ... report NUMBER                   one report, with its words
  ... fixed-next                      issues fixed in the next update, with their commits

Reports are joined to their issues first, so a report made before issues existed is not
missed. Never prints a report's words, a name or a number: screens, counts, devices and
versions only. Every change is an issue event naming who made it (--as), as "agent", or as
"release" when --as is "release". Prints JSON; exits 0, 1 on an error, 2 on usage.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

STATUS = {"fixing": "fixing", "fixed-in-next-update": "fixed_next", "solved": "solved"}
LIST_STATUSES = ("open", "new", "triaged", "in_progress", "fixed", "verified", "closed", "all")


def _when(value: str) -> datetime:
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="bug_reports.issues_cli")
    parser.add_argument("--database-url-file", required=True, type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list")
    which = listing.add_mutually_exclusive_group()
    for name in ("new", "open", "solved", "all"):
        which.add_argument(f"--{name}", dest="which", action="store_const", const=name)
    listing.add_argument("--since", type=_when)
    listing.add_argument("--limit", type=int, default=100, choices=range(1, 501))
    show = commands.add_parser("show")
    show.add_argument("issue")
    change = commands.add_parser("set")
    change.add_argument("issue")
    change.add_argument("--status", required=True, choices=sorted(STATUS))
    change.add_argument("--as", dest="actor", required=True)
    change.add_argument("--note")
    change.add_argument("--commit")
    change.add_argument("--release")
    change.add_argument("--app-update", action="store_true")
    alerts = commands.add_parser("alerts")
    alerts.add_argument("--since", type=_when, required=True)
    commands.add_parser("fixed-next")
    reports = commands.add_parser("reports")
    reports.add_argument("--status", default="open", choices=LIST_STATUSES)
    one = commands.add_parser("report")
    one.add_argument("report")
    return parser.parse_args(argv)


async def _run(arguments: argparse.Namespace) -> dict[str, object]:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from ac_platform.bug_reports.issues import IssueStore

    url = arguments.database_url_file.read_text().strip()
    engine = create_async_engine(url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    now = datetime.now(UTC)
    try:
        async with sessions() as database, database.begin():
            store = IssueStore(database)
            linked = await store.link_unlinked(now=now)
            if arguments.command == "list":
                issues = await store.issues(
                    which=arguments.which or "open", since=arguments.since, limit=arguments.limit
                )
                return {"issues": issues, "linked": linked}
            if arguments.command == "show":
                return {"issue": await store.detail(arguments.issue)}
            if arguments.command == "alerts":
                return {"issues": await store.issues(which="all", since=arguments.since)}
            if arguments.command in ("reports", "report"):
                from ac_platform.bug_reports.admin_tools import masked, report_id
                from ac_platform.bug_reports.store import BugReportStore

                reports = BugReportStore(database)
                if arguments.command == "report":
                    found = await reports.detail(await report_id(database, arguments.report))
                    return {"report": masked(found) | {"words": found["words"]}}
                page = await reports.page(
                    status=None if arguments.status == "all" else arguments.status, limit=50
                )
                return {"items": [masked(item) for item in page["items"]], "counts": page["counts"]}
            if arguments.command == "fixed-next":
                issues = await store.issues(which="open", limit=500)
                return {"issues": [item for item in issues if item["status"] == "fixed_next"]}
            name = " ".join(str(arguments.actor).split())[:80]
            if not name:
                raise ValueError("Say who is changing it: --as NAME")
            return {
                "issue": await store.set_status(
                    arguments.issue,
                    status=STATUS[arguments.status],
                    now=now,
                    actor="release" if name == "release" else "agent",
                    actor_name=name,
                    note=arguments.note,
                    commit=arguments.commit,
                    release=arguments.release,
                    app_update=arguments.app_update,
                )
            }
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    arguments = _arguments(sys.argv[1:] if argv is None else argv)
    try:
        result = asyncio.run(_run(arguments))
    except Exception as error:  # noqa: BLE001 - one plain line for the host command
        print(json.dumps({"error": type(error).__name__, "detail": str(error)[:300]}))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
