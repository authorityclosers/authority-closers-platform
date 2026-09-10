"""Host-authoritative tenant pilot attempts and earned-only, balanced rewards.

Every mutation and its audit/journal use one caller-owned transaction. Person
locks serialize timezone, attempts and awards; clients supply neither time nor
completion/reward claims. This domain does not write official learning state.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from functools import lru_cache
from typing import Any, cast
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import SessionTransactionOrigin

from ac_platform.audit.service import AuditRepository
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.kernel.authz import ActorContext
from ac_platform.practice.arcade import check_snapshot_response, public_snapshot, set_snapshot
from ac_platform.practice.models import (
    PracticeAttempt,
    PracticeCommand,
    PracticeFeedbackAck,
    PracticeLedgerEntry,
    PracticeParticipation,
    PracticeProfile,
    PracticeResponse,
    PracticeRewardClaim,
    PracticeSetVersion,
)
from ac_platform.tenancy.models import Membership, Tenant

POLICY_VERSION = "arcade-earned-pilot-2026-09-08-v1"


class PracticeError(ValueError):
    status = 422


class PracticeDenied(PracticeError):
    status = 403


class PracticeNotFound(PracticeError):
    status = 404


class PracticeConflict(PracticeError):
    status = 409


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def iso(value: datetime | None) -> str | None:
    return None if value is None else utc(value).isoformat()


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@lru_cache(maxsize=1)
def _iana_names() -> frozenset[str]:
    return frozenset(available_timezones())


def validated_timezone(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_+\-/]{1,64}", value):
        raise PracticeError("Choose a valid IANA timezone explicitly.")
    if value not in _iana_names():
        raise PracticeError("Choose a valid IANA timezone explicitly.")
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise PracticeError("Choose a valid IANA timezone explicitly.") from None
    return value


def buckets(now: datetime, timezone: str) -> tuple[date, date]:
    day = utc(now).astimezone(ZoneInfo(timezone)).date()
    return day, day - timedelta(days=day.weekday())


class PracticeApplication:
    def __init__(
        self,
        database: AsyncSession,
        *,
        academy_tenant_id: UUID | None,
        environment: str,
        preview_enabled: bool,
        pilot_enabled: bool = False,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        local_preview = preview_enabled and environment in {"local", "test"}
        deployment_pilot = pilot_enabled and environment in {"test", "staging", "production"}
        if (
            (preview_enabled and pilot_enabled)
            or not (local_preview or deployment_pilot)
            or academy_tenant_id is None
        ):
            raise PracticeDenied("The editorial practice pilot is unavailable.")
        self.database = database
        self.tenant_id = academy_tenant_id
        self.clock = clock

    async def _admit(self, actor: ActorContext) -> datetime:
        tx = self.database.get_transaction()
        sync = None if tx is None else tx.sync_transaction
        if sync is None or sync.origin is not SessionTransactionOrigin.BEGIN:
            raise PracticeError("Practice requires a caller-owned transaction.")
        if actor.tenant_id != self.tenant_id:
            raise PracticeDenied("Select your academy to open practice.")
        person = await self.database.scalar(
            select(Person)
            .where(Person.id == actor.person_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        session = await self.database.scalar(
            select(IdentitySession)
            .where(
                IdentitySession.id == actor.session_id, IdentitySession.person_id == actor.person_id
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        tenant = await self.database.scalar(
            select(Tenant)
            .where(Tenant.id == self.tenant_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        member = await self.database.scalar(
            select(Membership)
            .where(Membership.tenant_id == self.tenant_id, Membership.person_id == actor.person_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        now = utc(self.clock())
        if (
            person is None
            or person.status != "active"
            or person.email_verified_at is None
            or session is None
            or session.revoked_at is not None
            or utc(session.expires_at) <= now
            or session.selected_tenant_id != self.tenant_id
            or tenant is None
            or tenant.status != "active"
            or member is None
            or member.status != "active"
            or member.ended_at is not None
            or member.role not in {"learner", "admin", "owner"}
        ):
            raise PracticeDenied("A current academy session is required.")
        return now

    async def _profile(self, actor: ActorContext) -> PracticeProfile | None:
        return cast(
            PracticeProfile | None,
            await self.database.scalar(
                select(PracticeProfile)
                .where(
                    PracticeProfile.tenant_id == self.tenant_id,
                    PracticeProfile.person_id == actor.person_id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            ),
        )

    @staticmethod
    def _profile_view(profile: PracticeProfile | None, now: datetime) -> dict[str, Any]:
        if profile is None:
            return {
                "timezone": None,
                "revision": 0,
                "pending_timezone": None,
                "pending_effective_at": None,
            }
        effective = (
            profile.pending_effective_at is not None and utc(profile.pending_effective_at) <= now
        )
        return {
            "timezone": profile.pending_timezone if effective else profile.timezone,
            "revision": profile.revision,
            "pending_timezone": None if effective else profile.pending_timezone,
            "pending_effective_at": None if effective else iso(profile.pending_effective_at),
        }

    async def profile(self, actor: ActorContext) -> dict[str, Any]:
        now = await self._admit(actor)
        return self._profile_view(await self._profile(actor), now)

    async def _replay(
        self, actor: ActorContext, key: str, operation: str, intent: Any
    ) -> PracticeCommand | None:
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_.:\-]{1,128}", key):
            raise PracticeError("A valid Idempotency-Key is required.")
        row = await self.database.scalar(
            select(PracticeCommand).where(
                PracticeCommand.tenant_id == self.tenant_id,
                PracticeCommand.person_id == actor.person_id,
                PracticeCommand.key == key,
            )
        )
        if row is not None and (row.operation != operation or row.intent_digest != digest(intent)):
            raise PracticeConflict("This request key was already used for a different action.")
        return row

    async def _record(
        self,
        actor: ActorContext,
        key: str,
        operation: str,
        intent: Any,
        result_id: UUID | None,
        now: datetime,
        payload: dict[str, Any] | None = None,
    ) -> UUID:
        audit = await AuditRepository(self.database).append_for_actor(
            actor,
            action=f"practice.{operation}",
            resource_type="practice_attempt" if result_id else "practice_profile",
            resource_id=result_id,
            payload={"policy_version": POLICY_VERSION, **(payload or {})},
            now=now,
        )
        self.database.add(
            PracticeCommand(
                id=uuid4(),
                tenant_id=self.tenant_id,
                person_id=actor.person_id,
                key=key,
                operation=operation,
                intent_digest=digest(intent),
                result_id=result_id,
                audit_event_id=audit.id,
                created_at=now,
            )
        )
        await self.database.flush()
        return audit.id

    @staticmethod
    def _revision(actual: int, expected: int) -> None:
        if type(expected) is not int or expected < 0:
            raise PracticeError("A nonnegative revision is required.")
        if actual != expected:
            raise PracticeConflict("Practice changed. Refresh this attempt before continuing.")

    async def save_profile(
        self, actor: ActorContext, *, key: str, timezone: str, expected_revision: int
    ) -> dict[str, Any]:
        now = await self._admit(actor)
        timezone = validated_timezone(timezone)
        intent = {"timezone": timezone, "revision": expected_revision}
        replay = await self._replay(actor, key, "timezone_saved", intent)
        profile = await self._profile(actor)
        if replay:
            return self._profile_view(profile, now)
        self._revision(0 if profile is None else profile.revision, expected_revision)
        before = self._profile_view(profile, now)
        if profile is None:
            profile = PracticeProfile(
                tenant_id=self.tenant_id,
                person_id=actor.person_id,
                timezone=timezone,
                revision=1,
                updated_at=now,
            )
            self.database.add(profile)
        else:
            if before["pending_timezone"] is not None and timezone != before["pending_timezone"]:
                raise PracticeConflict("A timezone change is already scheduled for next week.")
            if before["pending_timezone"] is None:
                profile.timezone = before["timezone"]
                profile.pending_timezone = None
                profile.pending_effective_at = None
                if timezone != profile.timezone:
                    local = now.astimezone(ZoneInfo(profile.timezone))
                    next_monday = local.date() + timedelta(days=7 - local.weekday())
                    profile.pending_timezone = timezone
                    profile.pending_effective_at = datetime.combine(
                        next_monday, time.min, ZoneInfo(profile.timezone)
                    ).astimezone(UTC)
            profile.revision += 1
            profile.updated_at = now
        after = self._profile_view(profile, now)
        await self._record(
            actor, key, "timezone_saved", intent, None, now, {"before": before, "after": after}
        )
        return after

    async def _attempt(self, actor: ActorContext, attempt_id: UUID) -> PracticeAttempt:
        row = await self.database.scalar(
            select(PracticeAttempt)
            .where(
                PracticeAttempt.id == attempt_id,
                PracticeAttempt.tenant_id == self.tenant_id,
                PracticeAttempt.person_id == actor.person_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise PracticeNotFound("This practice attempt is unavailable.")
        return row

    async def _version(self, attempt: PracticeAttempt) -> PracticeSetVersion:
        row = await self.database.scalar(
            select(PracticeSetVersion).where(
                PracticeSetVersion.id == attempt.set_version_id,
                PracticeSetVersion.tenant_id == self.tenant_id,
            )
        )
        if row is None:
            raise PracticeNotFound("This practice version is unavailable.")
        if digest(row.snapshot) != row.content_digest:
            raise PracticeConflict("The saved practice definition could not be verified.")
        return row

    async def _items(
        self, attempt: PracticeAttempt
    ) -> tuple[dict[str, PracticeResponse], set[UUID]]:
        responses = await self.database.scalars(
            select(PracticeResponse)
            .where(
                PracticeResponse.attempt_id == attempt.id,
                PracticeResponse.tenant_id == self.tenant_id,
                PracticeResponse.person_id == attempt.person_id,
            )
            .order_by(PracticeResponse.sequence)
        )
        latest = {row.item_id: row for row in responses}
        acknowledged = set(
            await self.database.scalars(
                select(PracticeFeedbackAck.response_id).where(
                    PracticeFeedbackAck.attempt_id == attempt.id,
                    PracticeFeedbackAck.tenant_id == self.tenant_id,
                    PracticeFeedbackAck.person_id == attempt.person_id,
                )
            )
        )
        return latest, acknowledged

    async def issue(self, actor: ActorContext, *, set_id: str, key: str) -> dict[str, Any]:
        now = await self._admit(actor)
        intent = {"set_id": set_id}
        replay = await self._replay(actor, key, "attempt_issued", intent)
        if replay and replay.result_id:
            return await self._view(await self._attempt(actor, replay.result_id))
        if await self._profile(actor) is None:
            raise PracticeConflict("Save your timezone before starting practice.")
        snapshot = set_snapshot(set_id)
        content_digest = digest(snapshot)
        version_id = uuid5(NAMESPACE_URL, f"ac-practice:{self.tenant_id}:{content_digest}")
        values = dict(
            id=version_id,
            tenant_id=self.tenant_id,
            family_id=set_id,
            definition_version=str(snapshot["version"]),
            content_digest=content_digest,
            snapshot=snapshot,
            created_at=now,
        )
        dialect = self.database.get_bind().dialect.name
        if dialect not in {"postgresql", "sqlite"}:
            raise PracticeError("The practice database is unsupported.")
        insert = pg_insert if dialect == "postgresql" else sqlite_insert
        await self.database.execute(
            insert(PracticeSetVersion)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["tenant_id", "content_digest"])
        )
        attempt = PracticeAttempt(
            id=uuid4(),
            tenant_id=self.tenant_id,
            person_id=actor.person_id,
            set_version_id=version_id,
            revision=0,
            state="in_progress",
            issued_at=now,
            updated_at=now,
        )
        self.database.add(attempt)
        await self.database.flush()
        await self._record(
            actor,
            key,
            "attempt_issued",
            intent,
            attempt.id,
            now,
            {"set_id": set_id, "content_digest": content_digest},
        )
        return await self._view(attempt)

    async def attempt(self, actor: ActorContext, attempt_id: UUID) -> dict[str, Any]:
        await self._admit(actor)
        return await self._view(await self._attempt(actor, attempt_id))

    async def respond(
        self,
        actor: ActorContext,
        attempt_id: UUID,
        *,
        key: str,
        item_id: str,
        selections: list[int],
        expected_revision: int,
    ) -> dict[str, Any]:
        now = await self._admit(actor)
        intent = {
            "attempt_id": str(attempt_id),
            "item_id": item_id,
            "selections": selections,
            "revision": expected_revision,
        }
        replay = await self._replay(actor, key, "response_saved", intent)
        attempt = await self._attempt(actor, attempt_id)
        if replay:
            return await self._view(attempt)
        self._revision(attempt.revision, expected_revision)
        if attempt.state != "in_progress":
            raise PracticeConflict("This practice attempt is already complete.")
        version = await self._version(attempt)
        latest, acknowledged = await self._items(attempt)
        current = next(
            (
                item["id"]
                for item in version.snapshot["items"]
                if item["id"] not in latest or latest[item["id"]].id not in acknowledged
            ),
            None,
        )
        if item_id != current:
            raise PracticeConflict("Finish the current prompt before continuing.")
        feedback = check_snapshot_response(version.snapshot, item_id, selections)
        if (
            item_id in latest
            and latest[item_id].feedback["kind"] == "continue"
            and selections[:-1] != latest[item_id].selections
        ):
            raise PracticeConflict("Continue the saved conversation from its current step.")
        if feedback["kind"] == "feedback":
            feedback["responses_stored"] = True
        if attempt.revision >= 256:
            raise PracticeConflict("Start a new attempt to continue practicing.")
        attempt.revision += 1
        attempt.updated_at = now
        self.database.add(
            PracticeResponse(
                id=uuid4(),
                tenant_id=self.tenant_id,
                person_id=actor.person_id,
                attempt_id=attempt.id,
                item_id=item_id,
                sequence=attempt.revision,
                selections=list(selections),
                feedback=feedback,
                created_at=now,
            )
        )
        await self._record(
            actor, key, "response_saved", intent, attempt.id, now, {"item_id": item_id}
        )
        return await self._view(attempt)

    async def acknowledge(
        self,
        actor: ActorContext,
        attempt_id: UUID,
        response_id: UUID,
        *,
        key: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        now = await self._admit(actor)
        intent = {
            "attempt_id": str(attempt_id),
            "response_id": str(response_id),
            "revision": expected_revision,
        }
        replay = await self._replay(actor, key, "feedback_acknowledged", intent)
        attempt = await self._attempt(actor, attempt_id)
        if replay:
            return await self._view(attempt)
        self._revision(attempt.revision, expected_revision)
        latest, acknowledged = await self._items(attempt)
        response = next((row for row in latest.values() if row.id == response_id), None)
        if (
            attempt.state != "in_progress"
            or response is None
            or response.id in acknowledged
            or response.feedback["kind"] != "feedback"
        ):
            raise PracticeConflict("That feedback is not awaiting acknowledgment.")
        self.database.add(
            PracticeFeedbackAck(
                id=uuid4(),
                tenant_id=self.tenant_id,
                person_id=actor.person_id,
                attempt_id=attempt.id,
                response_id=response.id,
                created_at=now,
            )
        )
        acknowledged.add(response.id)
        version = await self._version(attempt)
        completed = all(
            item["id"] in latest and latest[item["id"]].id in acknowledged
            for item in version.snapshot["items"]
        )
        attempt.revision += 1
        attempt.updated_at = now
        if completed:
            attempt.state = "completed"
            attempt.completed_at = now
        audit_id = await self._record(
            actor,
            key,
            "feedback_acknowledged",
            intent,
            attempt.id,
            now,
            {"completed": completed, "response_id": str(response_id)},
        )
        if completed:
            await self._complete(actor, attempt, version, now, audit_id)
            from ac_platform.practice.focus import FocusApplication

            await FocusApplication(self).complete_locked(actor, attempt, now)
        return await self._view(attempt)

    async def _complete(
        self,
        actor: ActorContext,
        attempt: PracticeAttempt,
        version: PracticeSetVersion,
        now: datetime,
        audit_id: UUID,
    ) -> None:
        profile = await self._profile(actor)
        if profile is None:
            raise PracticeConflict("A saved timezone is required to finish practice.")
        timezone = str(self._profile_view(profile, now)["timezone"])
        day, week = buckets(now, timezone)
        participation = PracticeParticipation(
            id=uuid4(),
            tenant_id=self.tenant_id,
            person_id=actor.person_id,
            attempt_id=attempt.id,
            local_day=day,
            week_start=week,
            timezone=timezone,
            policy_version=POLICY_VERSION,
            audit_event_id=audit_id,
            created_at=now,
        )
        self.database.add(participation)
        await self.database.flush()
        daily = list(
            await self.database.scalars(
                select(PracticeRewardClaim).where(
                    PracticeRewardClaim.tenant_id == self.tenant_id,
                    PracticeRewardClaim.person_id == actor.person_id,
                    PracticeRewardClaim.kind == "daily_set",
                    PracticeRewardClaim.local_day == day,
                )
            )
        )
        dedup = f"{day}:{version.family_id}"
        if len(daily) < 2 and not any(row.dedup_key == dedup for row in daily):
            await self._award(
                participation, kind="daily_set", dedup=dedup, slot=len(daily) + 1, credits=10, xp=30
            )
        days = await self.database.scalar(
            select(func.count(func.distinct(PracticeParticipation.local_day))).where(
                PracticeParticipation.tenant_id == self.tenant_id,
                PracticeParticipation.person_id == actor.person_id,
                PracticeParticipation.week_start == week,
            )
        )
        weekly = await self.database.scalar(
            select(PracticeRewardClaim.id).where(
                PracticeRewardClaim.tenant_id == self.tenant_id,
                PracticeRewardClaim.person_id == actor.person_id,
                PracticeRewardClaim.kind == "weekly_rhythm",
                PracticeRewardClaim.dedup_key == str(week),
            )
        )
        if (days or 0) >= 3 and weekly is None:
            await self._award(
                participation, kind="weekly_rhythm", dedup=str(week), slot=None, credits=40, xp=0
            )

    async def _award(
        self,
        participation: PracticeParticipation,
        *,
        kind: str,
        dedup: str,
        slot: int | None,
        credits: int,
        xp: int,
    ) -> None:
        claim = PracticeRewardClaim(
            id=uuid4(),
            tenant_id=participation.tenant_id,
            person_id=participation.person_id,
            participation_id=participation.id,
            kind=kind,
            dedup_key=dedup,
            credits=credits,
            xp=xp,
            daily_slot=slot,
            local_day=participation.local_day,
            week_start=participation.week_start,
            policy_version=POLICY_VERSION,
            audit_event_id=participation.audit_event_id,
            created_at=participation.created_at,
        )
        self.database.add(claim)
        await self.database.flush()
        for unit, amount in (("credits", credits), ("xp", xp)):
            if amount:
                for account, signed in (("issuance", -amount), ("available", amount)):
                    self.database.add(
                        PracticeLedgerEntry(
                            id=uuid4(),
                            tenant_id=claim.tenant_id,
                            person_id=claim.person_id,
                            claim_id=claim.id,
                            unit=unit,
                            account=account,
                            amount=signed,
                            created_at=claim.created_at,
                        )
                    )
        await self.database.flush()

    @staticmethod
    def _receipt(row: PracticeRewardClaim) -> dict[str, Any]:
        return {
            "id": str(row.id),
            "kind": row.kind,
            "credits": row.credits,
            "xp": row.xp,
            "local_day": str(row.local_day),
            "week_start": str(row.week_start),
            "created_at": iso(row.created_at),
        }

    async def _view(self, attempt: PracticeAttempt) -> dict[str, Any]:
        version = await self._version(attempt)
        latest, acknowledged = await self._items(attempt)
        states = []
        for item in version.snapshot["items"]:
            row = latest.get(item["id"])
            states.append(
                {
                    "item_id": item["id"],
                    "response_id": str(row.id) if row else None,
                    "selections": row.selections if row else None,
                    "feedback": row.feedback if row else None,
                    "acknowledged": row is not None and row.id in acknowledged,
                }
            )
        receipts = await self.database.scalars(
            select(PracticeRewardClaim)
            .join(
                PracticeParticipation,
                PracticeRewardClaim.participation_id == PracticeParticipation.id,
            )
            .where(
                PracticeParticipation.attempt_id == attempt.id,
                PracticeRewardClaim.tenant_id == self.tenant_id,
                PracticeRewardClaim.person_id == attempt.person_id,
            )
            .order_by(PracticeRewardClaim.created_at, PracticeRewardClaim.id)
        )
        return {
            "id": str(attempt.id),
            "set_id": version.family_id,
            "set_version": version.snapshot["version"],
            "content_digest": version.content_digest,
            "state": attempt.state,
            "revision": attempt.revision,
            "issued_at": iso(attempt.issued_at),
            "completed_at": iso(attempt.completed_at),
            "set": public_snapshot(version.snapshot),
            "acknowledged_item_ids": [item["item_id"] for item in states if item["acknowledged"]],
            "item_states": states,
            "reward_receipts": [self._receipt(row) for row in receipts],
            "responses_stored": True,
            "course_progress_affected": False,
        }

    async def progress(self, actor: ActorContext) -> dict[str, Any]:
        now = await self._admit(actor)
        profile = self._profile_view(await self._profile(actor), now)
        balance_rows = (
            await self.database.execute(
                select(PracticeLedgerEntry.unit, func.sum(PracticeLedgerEntry.amount))
                .where(
                    PracticeLedgerEntry.tenant_id == self.tenant_id,
                    PracticeLedgerEntry.person_id == actor.person_id,
                    PracticeLedgerEntry.account == "available",
                )
                .group_by(PracticeLedgerEntry.unit)
            )
        ).all()
        balances = {unit: int(amount) for unit, amount in balance_rows}
        days = 0
        if profile["timezone"]:
            _, week = buckets(now, profile["timezone"])
            days = (
                await self.database.scalar(
                    select(func.count(func.distinct(PracticeParticipation.local_day))).where(
                        PracticeParticipation.tenant_id == self.tenant_id,
                        PracticeParticipation.person_id == actor.person_id,
                        PracticeParticipation.week_start == week,
                    )
                )
            ) or 0
        attempts = list(
            await self.database.scalars(
                select(PracticeAttempt)
                .where(
                    PracticeAttempt.tenant_id == self.tenant_id,
                    PracticeAttempt.person_id == actor.person_id,
                )
                .order_by(PracticeAttempt.updated_at.desc(), PracticeAttempt.id.desc())
                .limit(20)
            )
        )
        versions: dict[UUID, PracticeSetVersion] = {}
        acknowledged_counts: dict[UUID, int] = {}
        if attempts:
            versions = {
                version.id: version
                for version in await self.database.scalars(
                    select(PracticeSetVersion).where(
                        PracticeSetVersion.tenant_id == self.tenant_id,
                        PracticeSetVersion.id.in_({attempt.set_version_id for attempt in attempts}),
                    )
                )
            }
            # Match _items' latest-response rule, not all historical feedback.
            # This batches only bounded recent attempt IDs and selects no private
            # answer/feedback payloads for the progress summary.
            latest = (
                select(
                    PracticeResponse.attempt_id,
                    PracticeResponse.item_id,
                    func.max(PracticeResponse.sequence).label("latest_sequence"),
                )
                .where(
                    PracticeResponse.tenant_id == self.tenant_id,
                    PracticeResponse.person_id == actor.person_id,
                    PracticeResponse.attempt_id.in_([attempt.id for attempt in attempts]),
                )
                .group_by(PracticeResponse.attempt_id, PracticeResponse.item_id)
                .subquery("latest_practice_responses")
            )
            count_rows = await self.database.execute(
                select(PracticeResponse.attempt_id, func.count(PracticeFeedbackAck.id))
                .join(
                    latest,
                    (PracticeResponse.attempt_id == latest.c.attempt_id)
                    & (PracticeResponse.item_id == latest.c.item_id)
                    & (PracticeResponse.sequence == latest.c.latest_sequence),
                )
                .join(
                    PracticeFeedbackAck,
                    (PracticeFeedbackAck.response_id == PracticeResponse.id)
                    & (PracticeFeedbackAck.attempt_id == PracticeResponse.attempt_id)
                    & (PracticeFeedbackAck.tenant_id == PracticeResponse.tenant_id)
                    & (PracticeFeedbackAck.person_id == PracticeResponse.person_id),
                )
                .where(
                    PracticeResponse.tenant_id == self.tenant_id,
                    PracticeResponse.person_id == actor.person_id,
                )
                .group_by(PracticeResponse.attempt_id)
            )
            acknowledged_counts = {attempt_id: int(count) for attempt_id, count in count_rows.all()}
        recent = []
        for attempt in attempts:
            version = versions.get(attempt.set_version_id)
            if version is None:
                raise PracticeNotFound("This practice version is unavailable.")
            if digest(version.snapshot) != version.content_digest:
                raise PracticeConflict("The saved practice definition could not be verified.")
            recent.append(
                {
                    "id": str(attempt.id),
                    "set_id": version.family_id,
                    "set_version": version.snapshot["version"],
                    "title": version.snapshot["title"],
                    "state": attempt.state,
                    "revision": attempt.revision,
                    "acknowledged_count": acknowledged_counts.get(attempt.id, 0),
                    "item_count": len(version.snapshot["items"]),
                    "issued_at": iso(attempt.issued_at),
                    "completed_at": iso(attempt.completed_at),
                }
            )
        awards = await self.database.scalars(
            select(PracticeRewardClaim)
            .where(
                PracticeRewardClaim.tenant_id == self.tenant_id,
                PracticeRewardClaim.person_id == actor.person_id,
            )
            .order_by(PracticeRewardClaim.created_at.desc(), PracticeRewardClaim.id.desc())
            .limit(50)
        )
        return {
            "profile": profile,
            "credits_balance": balances.get("credits", 0),
            "xp_total": balances.get("xp", 0),
            "actual_practice_days_this_week": days,
            "policy_version": POLICY_VERSION,
            "recent_attempts": recent,
            "recent_awards": [self._receipt(row) for row in awards],
            "purchases_enabled": False,
            "course_progress_affected": False,
        }
