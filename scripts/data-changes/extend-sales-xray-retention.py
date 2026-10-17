#!/usr/bin/env python3
"""Keep Sales Xray uploads until their owner deletes them; dry-run by default.

Owner decision (18 Oct 2026): "keep until deleted, delete on request". Production
uploads were sealed with seven-day retention, so after seven days a call drops out
of its owner's Calls list and the retention step erases it. This moves the
retention deadline of every live upload to ten years after its upload (the
keep-until-deleted bound). It needs the owner's "approve data change" for the
environment. See EXTEND-SALES-XRAY-RETENTION.md.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.audit.service import AuditRepository
from ac_platform.conversation_intelligence.models import (
    ConversationPermission,
    ConversationRecording,
)

KEEP_DAYS = 3650
POLICY_REF = "ref:retention/sales-xray-until-deleted-v1"
AUDIT_CHUNK = 50


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


async def extend(
    sessions: async_sessionmaker[AsyncSession],
    *,
    apply: bool,
    approver: str,
    issue: str,
    snapshot_sha256: str | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, Any]:
    """Plan (and with apply, write) the new deadlines in one transaction."""

    now = _utc(clock())
    permission, recording = ConversationPermission, ConversationRecording
    query = (
        select(permission, recording.id, recording.state)
        .join(
            recording,
            (recording.permission_id == permission.id)
            & (recording.tenant_id == permission.tenant_id)
            & (recording.person_id == permission.person_id),
        )
        .where(permission.revoked_at.is_(None))
        .order_by(permission.tenant_id, permission.created_at, permission.id)
    )
    if apply:
        query = query.with_for_update(of=permission)
    async with sessions() as db, db.begin():
        rows = (await db.execute(query)).all()
        planned: dict[Any, list[dict[str, Any]]] = defaultdict(list)
        skipped_erasing = 0
        already_kept = 0
        for row, recording_id, state in rows:
            target = _utc(row.created_at) + timedelta(days=KEEP_DAYS)
            if _utc(row.retention_until) >= target:
                already_kept += 1
                continue
            if state in ("deleting", "deleted"):
                skipped_erasing += 1
                continue
            planned[row.tenant_id].append(
                {
                    "permission_id": str(row.id),
                    "recording_id": str(recording_id),
                    "old_retention_until": _utc(row.retention_until).isoformat(),
                    "new_retention_until": target.isoformat(),
                    "hidden_now": _utc(row.retention_until) <= now,
                    "row": row,
                    "target": target,
                }
            )
        summary = {
            "apply": apply,
            "policy_ref": POLICY_REF,
            "keep_days": KEEP_DAYS,
            "at": now.isoformat(),
            "permissions_to_extend": sum(len(items) for items in planned.values()),
            "hidden_now_restored": sum(
                1 for items in planned.values() for item in items if item["hidden_now"]
            ),
            "already_kept_until_deleted": already_kept,
            "skipped_already_erasing_or_deleted": skipped_erasing,
            "tenants": {
                str(tenant): {
                    "permissions": len(items),
                    "hidden_now": sum(1 for item in items if item["hidden_now"]),
                    "earliest_old_deadline": min(item["old_retention_until"] for item in items),
                    "latest_old_deadline": max(item["old_retention_until"] for item in items),
                }
                for tenant, items in planned.items()
            },
        }
        if not apply:
            return summary
        audit = AuditRepository(db)
        for tenant, items in planned.items():
            for item in items:
                item["row"].retention_until = item["target"]
            await db.flush()
            for start in range(0, len(items), AUDIT_CHUNK):
                chunk = items[start : start + AUDIT_CHUNK]
                await audit.append(
                    tenant_id=tenant,
                    actor_person_id=None,
                    actor_type="system",
                    action="conversation.retention_extended",
                    resource_type="conversation_permission",
                    resource_id=None,
                    payload={
                        "approver": approver,
                        "issue": issue,
                        "policy_ref": POLICY_REF,
                        "keep_days": KEEP_DAYS,
                        "snapshot_sha256": snapshot_sha256,
                        "permissions": [
                            {
                                key: item[key]
                                for key in (
                                    "permission_id",
                                    "recording_id",
                                    "old_retention_until",
                                    "new_retention_until",
                                )
                            }
                            for item in chunk
                        ],
                    },
                    reason="Owner-approved data change: keep Sales Xray uploads until deleted.",
                    now=now,
                )
        return summary


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
        result = await extend(
            async_sessionmaker(engine, expire_on_commit=False),
            apply=apply,
            approver=approver,
            issue=issue,
            snapshot_sha256=snapshot_sha256,
        )
    finally:
        await engine.dispose()
    return {"environment": environment, **result}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--approver", required=True)
    parser.add_argument("--issue", required=True)
    parser.add_argument("--production-snapshot-sha256")
    parser.add_argument("--database-url-file", type=Path)
    parser.add_argument("--environment", choices=("development", "staging", "production"))
    args = parser.parse_args()
    if (args.database_url_file is None) != (args.environment is None):
        parser.error("--database-url-file and --environment go together")
    try:
        if args.database_url_file is not None:
            environment, url = args.environment, args.database_url_file.read_text().strip()
        else:
            from ac_platform.application.settings import Settings

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
        parser.exit(
            2, f"Retention change refused ({type(error).__name__}); credentials withheld.\n"
        )
    print(json.dumps(result, sort_keys=True, indent=1))


if __name__ == "__main__":
    main()
