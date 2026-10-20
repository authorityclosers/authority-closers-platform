"""Saving and reading AI spend settings from the API (async); the guard reads them sync."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.ai_spend import guard, policy
from ac_platform.ai_spend.models import AiSpendSettings


async def read(db: AsyncSession, environment: str) -> tuple[dict[str, Any], int | None]:
    return await db.run_sync(lambda sync: guard.read_settings(sync.connection(), environment))


async def history(db: AsyncSession, limit: int = 20) -> list[dict[str, Any]]:
    rows = (
        await db.scalars(
            select(AiSpendSettings).order_by(AiSpendSettings.revision.desc()).limit(limit)
        )
    ).all()
    return [
        {
            "revision": row.revision,
            "config": row.config,
            "reason": row.reason,
            "by": str(row.created_by_person_id) if row.created_by_person_id else None,
            "at": row.created_at.isoformat(),
        }
        for row in rows
    ]


async def save(
    db: AsyncSession,
    environment: str,
    config: Mapping[str, Any],
    *,
    person_id: UUID | None,
    reason: str | None,
    now: datetime,
) -> int:
    checked = policy.validate(environment, config)
    current = await db.scalar(select(func.max(AiSpendSettings.revision)))
    revision = int(current or 0) + 1
    db.add(
        AiSpendSettings(
            id=uuid4(),
            revision=revision,
            config=checked,
            reason=(reason or "")[:200] or None,
            created_by_person_id=person_id,
            created_at=now,
        )
    )
    await db.flush()
    return revision
