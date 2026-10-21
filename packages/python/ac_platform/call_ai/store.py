"""AI-on-calls settings and what they decide for one call.

Settings are revisions (newest wins); the call's level is decided where the money is
spent: the processing plan asks ``level_for_call`` before it starts transcription (C2)
and again before facts (C4), and the background readers that follow a transcript (the
deep call data pipeline, one pass) ask ``level_for_call_sync``. Each reads the same
rows, so a call gets one answer everywhere:

1. a release check's own call (canary) always runs in full;
2. a "Get full report" on the call (an 'upgraded' decision) runs it in full;
3. else the seller's own level, else the organisation's default, else full.

The seller is the account that owns the upload (never the processing service).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.call_ai import policy
from ac_platform.call_ai.models import CallAiDecision, CallAiSettings


class SettingsConflict(Exception):
    """Someone saved these settings since they were read."""


@dataclass(frozen=True, slots=True)
class Settings:
    revision: int | None  # None: never saved, so the defaults
    config: dict[str, Any]


@dataclass(frozen=True, slots=True)
class CallLevel:
    level: str  # the chosen level: off, data_only, auto or full
    source: str  # person | organisation | upgrade | canary
    person_id: UUID | None
    settings_revision: int | None

    @property
    def effective(self) -> str:
        return policy.effective(self.level)

    @property
    def skipped_from(self) -> str | None:
        return policy.skipped_from(self.level)


_TABLE = "SELECT to_regclass('call_ai_settings') IS NOT NULL"
_SETTINGS = text(
    "SELECT revision, config FROM call_ai_settings WHERE tenant_id = :tenant"
    " ORDER BY revision DESC LIMIT 1"
)
_CANARY = text(
    "SELECT EXISTS (SELECT 1 FROM conversation_canary_submissions k"
    " JOIN conversation_guest_submissions s"
    " ON s.tenant_id = k.tenant_id AND s.submission_id = k.submission_id"
    " WHERE s.tenant_id = :tenant AND s.recording_id = :recording)"
)
_UPGRADED = text(
    "SELECT EXISTS (SELECT 1 FROM call_ai_decisions"
    " WHERE recording_id = :recording AND decision = 'upgraded')"
)
# The upload's account (direct, or the person who claimed a guest upload); a call with
# no upload link (an operator import) is its recording's own person. An unclaimed
# guest upload has no seller, so the organisation's default applies.
_SELLER = text(
    "SELECT CASE WHEN s.recording_id IS NULL THEN r.person_id"
    " ELSE coalesce(u.person_id, c.person_id) END AS person_id"
    " FROM conversation_recordings r"
    " LEFT JOIN conversation_guest_submissions s"
    " ON s.tenant_id = r.tenant_id AND s.recording_id = r.id"
    " LEFT JOIN conversation_acquisition_usage u ON u.id = s.usage_id"
    " LEFT JOIN conversation_visitor_claims c ON c.visitor_id = u.visitor_id"
    " WHERE r.id = :recording AND r.tenant_id = :tenant"
    " LIMIT 1"
)


def _settings(row: Any) -> Settings:
    if row is None:
        return Settings(None, policy.defaults())
    try:
        return Settings(int(row.revision), policy.validate(row.config or {}))
    except policy.SettingsError:
        # A saved document that no longer validates runs calls as before (full).
        return Settings(int(row.revision), policy.defaults())


def _decide(
    settings: Settings, person_id: UUID | None, *, canary: bool, upgraded: bool
) -> CallLevel:
    if canary:
        return CallLevel("full", "canary", person_id, settings.revision)
    if upgraded:
        return CallLevel("full", "upgrade", person_id, settings.revision)
    level, source = policy.resolve(settings.config, person_id)
    return CallLevel(level, source, person_id, settings.revision)


# ----- async (the API and the processing plan) ------------------------------------


async def read(db: AsyncSession, tenant_id: UUID) -> Settings:
    if not await db.scalar(text(_TABLE)):
        return Settings(None, policy.defaults())
    return _settings((await db.execute(_SETTINGS, {"tenant": tenant_id})).first())


async def save(
    db: AsyncSession,
    tenant_id: UUID,
    config: dict[str, Any],
    *,
    expected_revision: int | None,
    actor_person_id: UUID,
    now: datetime,
) -> tuple[Settings, Settings]:
    """(before, after): a new revision, if nobody saved since ``expected_revision``."""
    # One writer per organisation at a time; the unique revision is the backstop.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"call_ai_settings:{tenant_id}"},
    )
    before = await read(db, tenant_id)
    if before.revision != expected_revision:
        raise SettingsConflict
    checked = policy.validate(config)
    revision = (before.revision or 0) + 1
    db.add(
        CallAiSettings(
            id=uuid4(),
            tenant_id=tenant_id,
            revision=revision,
            config=checked,
            created_by_person_id=actor_person_id,
            created_at=now,
        )
    )
    await db.flush()
    return before, Settings(revision, checked)


async def seller(db: AsyncSession, tenant_id: UUID, recording_id: UUID) -> UUID | None:
    row = (await db.execute(_SELLER, {"tenant": tenant_id, "recording": recording_id})).first()
    return None if row is None else cast(UUID | None, row.person_id)


async def level_for_call(db: AsyncSession, tenant_id: UUID, recording_id: UUID) -> CallLevel:
    params = {"tenant": tenant_id, "recording": recording_id}
    person_id = await seller(db, tenant_id, recording_id)
    if not await db.scalar(text(_TABLE)):
        return CallLevel(policy.DEFAULT_LEVEL, "organisation", person_id, None)
    return _decide(
        await read(db, tenant_id),
        person_id,
        canary=bool(await db.scalar(_CANARY, params)),
        upgraded=bool(await db.scalar(_UPGRADED, params)),
    )


async def record_skip(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    recording_id: UUID,
    plan_id: UUID,
    call: CallLevel,
    stage: str,
    now: datetime,
    reason: str = "level",
) -> None:
    """One 'skipped' row per plan: the call, its level, the first stage left out and why
    (the seller's level, or the short-call rule)."""
    await db.execute(
        pg_insert(CallAiDecision)
        .values(
            id=uuid4(),
            tenant_id=tenant_id,
            recording_id=recording_id,
            plan_id=plan_id,
            person_id=call.person_id,
            level=call.level,
            decision="skipped",
            stage=stage,
            settings_revision=call.settings_revision,
            actor_person_id=None,
            created_at=now,
            reason=reason,
        )
        .on_conflict_do_nothing(constraint="uq_call_ai_decision_plan")
    )


async def record_upgrade(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    recording_id: UUID,
    call: CallLevel,
    actor_person_id: UUID,
    now: datetime,
) -> UUID:
    identifier = uuid4()
    db.add(
        CallAiDecision(
            id=identifier,
            tenant_id=tenant_id,
            recording_id=recording_id,
            plan_id=None,
            person_id=call.person_id,
            level=call.level,
            decision="upgraded",
            stage=None,
            settings_revision=call.settings_revision,
            actor_person_id=actor_person_id,
            created_at=now,
        )
    )
    await db.flush()
    return identifier


# ----- sync (background readers on a plain connection) ------------------------------


def level_for_call_sync(connection: Any, tenant_id: UUID, recording_id: UUID) -> CallLevel:
    params = {"tenant": tenant_id, "recording": recording_id}
    row = connection.execute(_SELLER, params).first()
    person_id = None if row is None else cast(UUID | None, row.person_id)
    if not connection.scalar(text(_TABLE)):
        return CallLevel(policy.DEFAULT_LEVEL, "organisation", person_id, None)
    return _decide(
        _settings(connection.execute(_SETTINGS, {"tenant": tenant_id}).first()),
        person_id,
        canary=bool(connection.scalar(_CANARY, params)),
        upgraded=bool(connection.scalar(_UPGRADED, params)),
    )


_NEWEST_PLAN_CODE = text(
    "SELECT progress ->> 'failure_code' FROM conversation_processing_plans"
    " WHERE recording_id = :recording AND erased_at IS NULL"
    " ORDER BY created_at DESC, id DESC LIMIT 1"
)


def runs_beyond_transcript(connection: Any, tenant_id: UUID, recording_id: UUID) -> bool:
    """False when the call stops at its transcript, by its level (Off or Data only) or
    because its plan was held as a short call: readers that would analyse the call
    further (deep call data, one pass) leave it alone."""
    if level_for_call_sync(connection, tenant_id, recording_id).skipped_from is not None:
        return False
    code = connection.scalar(_NEWEST_PLAN_CODE, {"recording": recording_id})
    return code not in set(policy.SHORT_CODES.values())


async def in_organisation(db: AsyncSession, tenant_id: UUID) -> bool:
    """The short-call rule is for organisations; a personal workspace runs as before."""
    return bool(
        await db.scalar(
            text("SELECT EXISTS (SELECT 1 FROM organisations WHERE tenant_id = :tenant)"),
            {"tenant": tenant_id},
        )
    )
