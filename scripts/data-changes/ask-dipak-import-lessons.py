#!/usr/bin/env python3
"""Put Dipak's edited lessons into Ask Dipak, from his docs, with no code release.

Owner, 16 Nov 2026: Dipak's edits should reach the app as "a database update kind of
situation". Migration 0157 keeps an append-only history of imported libraries
(``sales_xray_ask_dipak_library_versions``); the newest row is what the app, the API, MCP and
the CLI teach. This script adds one row from a lessons bundle, after
``ask_dipak.library.check`` has confirmed it is one whole lesson for each of Dipak's 150
questions. A bundle identical to the library being served adds nothing, so a rerun is safe.

Owner-approved data change (AGENTS.md): dry run by default, before and after printed (the
version, the lesson count and which lessons change), one transaction, idempotent, and an
audit event ``ask_dipak.library_imported`` naming the approver and the issue. The lessons are
Dipak's teaching text only: no person, workspace or call data.

1. Fetch his docs as text and build the bundle on the host (any checkout of the release):

       sudo rclone --config /root/ac-drive/rclone.conf copy acdrive: <dir> \\
         --drive-root-folder-id 13ZJcal0YxPUh_sZokPHtB0PXw3FtLbHn --drive-export-formats txt
       python scripts/ask-dipak/import_dipak_docs.py --docs <dir> --bundle /tmp/ask-dipak.json

2. Copy it into the deployed API container and run this script there (its environment holds
   the database URL and the operations workspace):

       docker cp /tmp/ask-dipak.json ac-application-<env>-api-1:/tmp/ask-dipak.json
       docker exec -i ac-application-<env>-api-1 python - --environment <env> \\
         --bundle /tmp/ask-dipak.json --approver "<who approved>" --issue <reference> \\
         [--allow-production] [--apply] < scripts/data-changes/ask-dipak-import-lessons.py

On production: take a database snapshot before ``--apply`` and show the owner the dry run.
Then open one changed lesson in the app to check it.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

DATA_CHANGE = "scripts/data-changes/ask-dipak-import-lessons.py"
ACTION = "ask_dipak.library_imported"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ask-dipak-import-lessons", allow_abbrev=False)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--allow-production", action="store_true")
    parser.add_argument("--bundle", type=Path, required=True, help="from import_dipak_docs.py")
    parser.add_argument("--approver", required=True)
    parser.add_argument("--issue", required=True)
    parser.add_argument("--apply", action="store_true")
    return parser


def load_bundle(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    data = json.loads(path.read_text("utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("lessons"), dict):
        raise ValueError("the bundle must be import_dipak_docs.py --bundle output")
    return data["lessons"], dict(data.get("source") or {})


async def change(
    database: Any,
    *,
    lessons: dict[str, Any],
    source: dict[str, Any],
    approver: str,
    issue: str,
    operations_tenant_id: Any,
    apply: bool,
    now: datetime,
) -> dict[str, Any]:
    from ac_platform.ask_dipak import library
    from ac_platform.audit.service import AuditRepository

    run_id = str(uuid4())
    result = await library.record_import(
        database,
        lessons=lessons,
        source={**source, "data_change": DATA_CHANGE, "run_id": run_id},
        approved_by=approver,
        issue=issue,
        now=now,
        apply=apply,
    )
    result |= {"run_id": run_id, "approver": approver, "issue": issue}
    if result["applied"]:
        await AuditRepository(database).append(
            tenant_id=operations_tenant_id,
            actor_person_id=None,
            actor_type="data_change",
            action=ACTION,
            resource_type="sales_xray_ask_dipak_library_version",
            resource_id=result["row_id"],
            payload={
                "run_id": run_id,
                "approver": approver,
                "issue": issue,
                "data_change": DATA_CHANGE,
                "before": result["before"],
                "after": result["after"],
                "changed_lessons": result["changed_lessons"],
            },
            reason="Dipak's lessons imported from his docs (owner-approved data change)",
            now=now,
        )
    return result


async def execute(args: argparse.Namespace) -> dict[str, Any]:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from ac_platform.application.settings import Settings

    settings = Settings()
    if settings.environment != args.environment:
        raise ValueError("--environment must name this runtime's environment")
    if settings.environment == "production" and not args.allow_production:
        raise ValueError("production needs --allow-production (after a snapshot)")
    if settings.operations_tenant_id is None:
        raise ValueError("an explicit operations workspace is required for the audit event")
    lessons, source = load_bundle(args.bundle)
    engine = create_async_engine(settings.database_url, echo=False, hide_parameters=True)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db, db.begin():
            result = await change(
                db,
                lessons=lessons,
                source=source,
                approver=args.approver,
                issue=args.issue,
                operations_tenant_id=settings.operations_tenant_id,
                apply=args.apply,
                now=datetime.now(UTC),
            )
            result["environment"] = settings.environment
            return result
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    print(json.dumps(asyncio.run(execute(args)), ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
