#!/usr/bin/env python3
"""Export private, content-free Sales Xray recovery and 14-day timing evidence."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.application.asyncio_runtime import run_async
from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.analysis_diagnostics import (
    analysis_inventory,
    summarize_timings,
)
from ac_platform.conversation_intelligence.processing_cli import _Parser


async def audit(args: argparse.Namespace) -> dict:
    if os.getenv("AC_ENVIRONMENT") != args.environment or not os.getenv("AC_DATABASE_URL"):
        raise ValueError("Matching injected runtime required.")
    settings = Settings(_env_file=None, environment=args.environment)
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as database, database.begin():
            await database.execute(text("SET TRANSACTION READ ONLY"))
            await database.execute(text("SET LOCAL statement_timeout = '30s'"))
            now = await database.scalar(select(func.clock_timestamp()))
            assert now is not None
            inventory = await analysis_inventory(database, now=now, days=args.days)
            return {
                "schema": "ac.sales-xray.analysis-audit/1",
                "environment": args.environment,
                **inventory,
                "timings": summarize_timings(inventory),
            }
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--environment", required=True, choices=("staging", "production"))
    parser.add_argument("--days", type=int, default=14, choices=range(1, 31))
    parser.add_argument("--output", type=Path, required=True)
    try:
        args = parser.parse_args(argv)
        result = run_async(audit(args))
        # Refuse overwriting any earlier evidence, including a linked file.
        with args.output.open("x", encoding="utf-8") as stream:
            os.chmod(args.output, 0o600)
            json.dump(result, stream, default=str, indent=2)
            stream.write("\n")
    except (ValueError, OSError, SQLAlchemyError):
        print(
            "Audit unavailable; check runtime access and a new private output path.",
            file=sys.stderr,
        )
        return 2
    print("Read-only analysis audit saved; no application state changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
