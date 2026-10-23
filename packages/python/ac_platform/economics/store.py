"""Economics settings revisions: read the newest (or the defaults), save a new one."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.economics import policy
from ac_platform.economics.models import EconomicsSettings


async def read(db: AsyncSession) -> tuple[dict[str, Any], int | None]:
    """The newest saved document, checked again, or the defaults (revision None)."""
    row = await db.scalar(
        select(EconomicsSettings).order_by(EconomicsSettings.revision.desc()).limit(1)
    )
    if row is None:
        return policy.validate({}), None
    return policy.validate(row.config), row.revision


async def save(
    db: AsyncSession,
    config: Mapping[str, Any],
    *,
    person_id: UUID | None,
    reason: str | None,
    now: datetime,
) -> int:
    checked = policy.validate(config)
    current = await db.scalar(select(func.max(EconomicsSettings.revision)))
    revision = int(current or 0) + 1
    db.add(
        EconomicsSettings(
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
