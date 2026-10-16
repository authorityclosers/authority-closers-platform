#!/usr/bin/env python3
"""Settle stuck provider budget holds at list price; dry-run by default.

Owner-approved data change (17 Oct 2026). See SETTLE-PROVIDER-HOLDS.md.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.provider_hold_settlement import settle_provider_holds


async def execute(
    environment: str,
    database_url: str,
    *,
    apply: bool,
    approver: str,
    issue: str,
    snapshot_sha256: str | None,
) -> dict[str, Any]:
    if (
        apply
        and environment == "production"
        and (snapshot_sha256 is None or re.fullmatch(r"[a-f0-9]{64}", snapshot_sha256) is None)
    ):
        raise ValueError("production_snapshot_required")
    engine = create_async_engine(database_url, echo=False, hide_parameters=True)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db, db.begin():
            result = await settle_provider_holds(
                db, apply=apply, approver=approver, issue=issue, now=datetime.now(UTC)
            )
            return {
                **result,
                "environment": environment,
                "production_snapshot_sha256": snapshot_sha256,
            }
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approver", required=True, help="who approved, and where")
    parser.add_argument("--issue", required=True, help="tracking reference")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--production-snapshot-sha256")
    # Inside a release container the worker's URL file replaces runtime injection.
    parser.add_argument("--database-url-file", type=Path)
    parser.add_argument("--environment", choices=("development", "staging", "production"))
    args = parser.parse_args()
    if (args.database_url_file is None) != (args.environment is None):
        parser.error("--database-url-file and --environment go together")
    try:
        if args.database_url_file is not None:
            environment, url = args.environment, args.database_url_file.read_text().strip()
        else:
            # Runtime injection (AC_ENVIRONMENT, AC_DATABASE_URL); no provider access.
            settings = Settings()
            environment, url = settings.environment, settings.database_url
        result = asyncio.run(
            execute(
                environment,
                url,
                apply=args.apply,
                approver=args.approver[:200],
                issue=args.issue[:100],
                snapshot_sha256=args.production_snapshot_sha256,
            )
        )
    except Exception as error:  # noqa: BLE001 - never echo credentials
        parser.exit(2, f"Settlement refused ({type(error).__name__}); credentials withheld.\n")
    print(json.dumps(result, sort_keys=True, indent=1))


if __name__ == "__main__":
    main()
