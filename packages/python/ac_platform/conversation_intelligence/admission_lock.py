"""The per-tenant admission lock shared by reservations and every capacity-lowering ledger write.

One short transaction-scoped advisory lock serialises first claims, concurrent
tabs and billing closings without relying on SELECT FOR UPDATE over rows that
do not exist yet (ADR 0052, section B "Locking").
"""

from __future__ import annotations

import hashlib
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


def admission_lock_key(tenant_id: UUID) -> int:
    return int.from_bytes(
        hashlib.sha256(b"acquisition:" + tenant_id.bytes).digest()[:8], "big", signed=True
    )


async def take_admission_lock(database: AsyncSession, tenant_id: UUID) -> None:
    """Take the tenant's admission lock for the rest of the transaction (PostgreSQL only)."""

    if database.get_bind().dialect.name != "postgresql":
        raise RuntimeError("Concurrent admission commands require PostgreSQL.")
    await database.execute(select(func.pg_advisory_xact_lock(admission_lock_key(tenant_id))))


__all__ = ["admission_lock_key", "take_admission_lock"]
