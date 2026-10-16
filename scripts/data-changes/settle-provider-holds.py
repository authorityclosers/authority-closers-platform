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
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.provider_hold_settlement import settle_provider_holds


async def execute(
    settings: Settings,
    *,
    apply: bool,
    approver: str,
    issue: str,
    snapshot_sha256: str | None,
) -> dict[str, Any]:
    if (
        apply
        and settings.environment == "production"
        and (snapshot_sha256 is None or re.fullmatch(r"[a-f0-9]{64}", snapshot_sha256) is None)
    ):
        raise ValueError("production_snapshot_required")
    engine = create_async_engine(settings.database_url, echo=False, hide_parameters=True)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db, db.begin():
            result = await settle_provider_holds(
                db, apply=apply, approver=approver, issue=issue, now=datetime.now(UTC)
            )
            return {
                **result,
                "environment": settings.environment,
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
    args = parser.parse_args()
    try:
        # Runtime injection only (AC_ENVIRONMENT, AC_DATABASE_URL); no provider access.
        result = asyncio.run(
            execute(
                Settings(),
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
