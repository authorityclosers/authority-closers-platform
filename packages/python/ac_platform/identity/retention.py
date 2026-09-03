"""Bounded retention for short-lived identity authorization artifacts.

The caller owns the transaction and the schedule.  This boundary intentionally
does not purge browser sessions or audit-bearing identity records: their
retention policy requires a separate controlled decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import delete, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import SessionTransactionOrigin

from ac_platform.identity.models import AuthenticationReplay, ProviderAuthorizationTransaction
from ac_platform.identity.services import IdentityServiceError


class IdentityRetentionTransactionRequiredError(IdentityServiceError):
    """Retention was invoked without an explicit caller-owned transaction."""


@dataclass(frozen=True, slots=True)
class IdentityRetentionResult:
    provider_authorization_transactions: int
    authentication_replays: int

    @property
    def deleted(self) -> int:
        return self.provider_authorization_transactions + self.authentication_replays


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _require_outer_transaction(session: AsyncSession) -> None:
    transaction = session.get_transaction()
    sync_transaction = None if transaction is None else transaction.sync_transaction
    if sync_transaction is None or sync_transaction.origin is not SessionTransactionOrigin.BEGIN:
        raise IdentityRetentionTransactionRequiredError(
            "identity retention requires an explicit caller-owned AsyncSession transaction"
        )


def _validate_policy(*, retain_for: timedelta, batch_size: int) -> None:
    if retain_for < timedelta(0):
        raise ValueError("retain_for must not be negative")
    if batch_size < 1 or batch_size > 10_000:
        raise ValueError("batch_size must be between 1 and 10000")


async def purge_expired_identity_artifacts(
    session: AsyncSession,
    *,
    now: datetime,
    retain_for: timedelta,
    batch_size: int = 1_000,
) -> IdentityRetentionResult:
    """Delete one bounded batch of expired OAuth transactions and replay keys.

    ``retain_for`` is deliberately required so deployment policy remains
    explicit. Rows are locked with ``SKIP LOCKED`` before deletion, allowing
    multiple maintenance workers to run safely without unbounded statements.
    """

    _require_outer_transaction(session)
    _validate_policy(retain_for=retain_for, batch_size=batch_size)
    cutoff = _as_utc(now) - retain_for

    transaction_ids = tuple(
        (
            await session.scalars(
                select(ProviderAuthorizationTransaction.id)
                .where(ProviderAuthorizationTransaction.expires_at <= cutoff)
                .order_by(
                    ProviderAuthorizationTransaction.expires_at,
                    ProviderAuthorizationTransaction.id,
                )
                .limit(batch_size)
                .with_for_update(skip_locked=True)
            )
        ).all()
    )
    deleted_transactions = 0
    if transaction_ids:
        result = cast(
            CursorResult[Any],
            await session.execute(
                delete(ProviderAuthorizationTransaction).where(
                    ProviderAuthorizationTransaction.id.in_(transaction_ids)
                )
            ),
        )
        deleted_transactions = int(result.rowcount or 0)

    replay_keys = tuple(
        (
            await session.scalars(
                select(AuthenticationReplay.replay_key)
                .where(AuthenticationReplay.expires_at <= cutoff)
                .order_by(AuthenticationReplay.expires_at, AuthenticationReplay.replay_key)
                .limit(batch_size)
                .with_for_update(skip_locked=True)
            )
        ).all()
    )
    deleted_replays = 0
    if replay_keys:
        result = cast(
            CursorResult[Any],
            await session.execute(
                delete(AuthenticationReplay).where(AuthenticationReplay.replay_key.in_(replay_keys))
            ),
        )
        deleted_replays = int(result.rowcount or 0)

    return IdentityRetentionResult(
        provider_authorization_transactions=deleted_transactions,
        authentication_replays=deleted_replays,
    )


__all__ = [
    "IdentityRetentionResult",
    "IdentityRetentionTransactionRequiredError",
    "purge_expired_identity_artifacts",
]
