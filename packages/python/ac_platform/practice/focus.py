"""Optional pilot Focus runs. Only an explicit end can consume a charge.

Person admission/locking is shared with practice: completion, timezone changes,
and Focus commands serialize together. The append-only event stream is the
balance authority, not telemetry or the earned reward journal.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import select

from ac_platform.audit.service import AuditRepository
from ac_platform.kernel.authz import ActorContext
from ac_platform.practice.application import (
    PracticeApplication,
    PracticeConflict,
    PracticeNotFound,
    buckets,
    digest,
    iso,
)
from ac_platform.practice.focus_models import PracticeFocusEvent, PracticeFocusRun
from ac_platform.practice.models import PracticeAttempt, PracticeCommand, PracticeFeedbackAck

FOCUS_POLICY_VERSION = "arcade-focus-local-2026-09-08-v1"


class FocusConflict(PracticeConflict):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


class FocusApplication:
    def __init__(self, practice: PracticeApplication) -> None:
        # PracticeApplication enforces an explicit local preview or tenant pilot.
        self.practice = practice
        self.database = practice.database
        self.tenant_id = practice.tenant_id

    async def _latest(self, actor: ActorContext) -> PracticeFocusEvent | None:
        return cast(
            PracticeFocusEvent | None,
            await self.database.scalar(
                select(PracticeFocusEvent)
                .where(
                    PracticeFocusEvent.tenant_id == self.tenant_id,
                    PracticeFocusEvent.person_id == actor.person_id,
                )
                .order_by(PracticeFocusEvent.revision.desc())
                .limit(1)
            ),
        )

    async def _day(self, actor: ActorContext, now: datetime) -> tuple[date | None, str | None]:
        profile = self.practice._profile_view(await self.practice._profile(actor), now)
        zone = profile["timezone"]
        return (None, None) if zone is None else (buckets(now, zone)[0], zone)

    async def _active(self, actor: ActorContext) -> PracticeFocusRun | None:
        return cast(
            PracticeFocusRun | None,
            await self.database.scalar(
                select(PracticeFocusRun)
                .where(
                    PracticeFocusRun.tenant_id == self.tenant_id,
                    PracticeFocusRun.person_id == actor.person_id,
                    PracticeFocusRun.state == "active",
                )
                .execution_options(populate_existing=True)
            ),
        )

    async def _run(self, actor: ActorContext, run_id: UUID | None) -> PracticeFocusRun:
        run = await self.database.scalar(
            select(PracticeFocusRun)
            .where(
                PracticeFocusRun.id == run_id,
                PracticeFocusRun.tenant_id == self.tenant_id,
                PracticeFocusRun.person_id == actor.person_id,
            )
            .execution_options(populate_existing=True)
        )
        if run is None:
            raise PracticeNotFound("This Focus Run is unavailable.")
        return run

    async def _run_view(self, actor: ActorContext, run: PracticeFocusRun) -> dict[str, Any]:
        attempt = await self.practice._attempt(actor, run.attempt_id)
        version = await self.practice._version(attempt)
        return {
            "id": str(run.id),
            "attempt_id": str(run.attempt_id),
            "set_id": version.family_id,
            "state": run.state,
            "started_at": iso(run.started_at),
            "finished_at": iso(run.finished_at),
            "exit_cost": run.exit_cost,
            "completion_restore": run.completion_restore,
        }

    @staticmethod
    def _charges(latest: PracticeFocusEvent | None, day: date | None) -> int:
        if latest is None or (day is not None and day > latest.reset_day):
            return 3
        return latest.charges_after

    async def _summary(self, actor: ActorContext, now: datetime) -> dict[str, Any]:
        latest = await self._latest(actor)
        day, zone = await self._day(actor, now)
        active = await self._active(actor)
        return {
            "policy_version": FOCUS_POLICY_VERSION,
            "charges": self._charges(latest, day),
            "capacity": 3,
            "revision": 0 if latest is None else latest.revision,
            "local_day": None if day is None else str(day),
            "timezone": zone,
            "active_run": None if active is None else await self._run_view(actor, active),
        }

    async def summary(self, actor: ActorContext) -> dict[str, Any]:
        return await self._summary(actor, await self.practice._admit(actor))

    async def _result(
        self, actor: ActorContext, run: PracticeFocusRun, now: datetime
    ) -> dict[str, Any]:
        return {"summary": await self._summary(actor, now), "run": await self._run_view(actor, run)}

    @staticmethod
    def _revision(actual: int, expected: int) -> None:
        if type(expected) is not int or expected != actual:
            raise FocusConflict("revision_conflict", "Practice changed. Refresh before continuing.")

    async def _event(
        self,
        actor: ActorContext,
        latest: PracticeFocusEvent | None,
        *,
        run: PracticeFocusRun | None,
        kind: str,
        after: int,
        day: date,
        zone: str,
        now: datetime,
    ) -> PracticeFocusEvent:
        before = 3 if latest is None else latest.charges_after
        audit = await AuditRepository(self.database).append_for_actor(
            actor,
            action=f"practice.focus_{kind}",
            resource_type="practice_focus",
            resource_id=None if run is None else run.id,
            payload={
                "policy_version": FOCUS_POLICY_VERSION,
                "charges_before": before,
                "charges_after": after,
                "local_day": str(day),
                "timezone": zone,
                "attempt_id": None if run is None else str(run.attempt_id),
            },
            now=now,
        )
        entry = PracticeFocusEvent(
            id=uuid4(),
            tenant_id=self.tenant_id,
            person_id=actor.person_id,
            run_id=None if run is None else run.id,
            revision=1 if latest is None else latest.revision + 1,
            kind=kind,
            charges_before=before,
            charges_after=after,
            local_day=day,
            # A timezone shift/clock rollback never reissues an already visited day.
            reset_day=day if latest is None else max(day, latest.reset_day),
            timezone=zone,
            policy_version=FOCUS_POLICY_VERSION,
            audit_event_id=audit.id,
            created_at=now,
        )
        self.database.add(entry)
        await self.database.flush()
        return entry

    async def _normalize(
        self, actor: ActorContext, latest: PracticeFocusEvent | None, now: datetime
    ) -> tuple[PracticeFocusEvent | None, date, str]:
        day, zone = await self._day(actor, now)
        if day is None or zone is None:
            raise FocusConflict(
                "not_eligible", "Save your practice timezone before starting Focus."
            )
        if latest is not None and day > latest.reset_day:
            latest = await self._event(
                actor, latest, run=None, kind="day_reset", after=3, day=day, zone=zone, now=now
            )
        return latest, day, zone

    async def _command(
        self, actor: ActorContext, key: str, operation: str, intent: Any, entry: PracticeFocusEvent
    ) -> None:
        self.database.add(
            PracticeCommand(
                id=uuid4(),
                tenant_id=self.tenant_id,
                person_id=actor.person_id,
                key=key,
                operation=operation,
                intent_digest=digest(intent),
                result_id=entry.run_id,
                audit_event_id=entry.audit_event_id,
                created_at=entry.created_at,
            )
        )
        await self.database.flush()

    async def start(
        self,
        actor: ActorContext,
        attempt_id: UUID,
        *,
        key: str,
        expected_revision: int,
        expected_attempt_revision: int,
    ) -> dict[str, Any]:
        now = await self.practice._admit(actor)
        intent = {
            "attempt_id": str(attempt_id),
            "revision": expected_revision,
            "attempt_revision": expected_attempt_revision,
        }
        replay = await self.practice._replay(actor, key, "focus_started", intent)
        if replay:
            return await self._result(actor, await self._run(actor, replay.result_id), now)
        attempt = await self.practice._attempt(actor, attempt_id)
        if attempt.revision != 0:
            raise FocusConflict(
                "attempt_started", "Choose Focus before answering the first prompt."
            )
        if attempt.state != "in_progress":
            raise FocusConflict("not_eligible", "This attempt cannot start a Focus Run.")
        self._revision(attempt.revision, expected_attempt_revision)
        previous = await self.database.scalar(
            select(PracticeFocusRun.id).where(
                PracticeFocusRun.attempt_id == attempt.id,
                PracticeFocusRun.tenant_id == self.tenant_id,
                PracticeFocusRun.person_id == actor.person_id,
            )
        )
        if previous is not None:
            raise FocusConflict("not_eligible", "This attempt has already used its Focus Run.")
        if await self._active(actor) is not None:
            raise FocusConflict(
                "active_run_conflict", "Resume or end your current Focus Run first."
            )
        latest = await self._latest(actor)
        self._revision(0 if latest is None else latest.revision, expected_revision)
        latest, day, zone = await self._normalize(actor, latest, now)
        charges = 3 if latest is None else latest.charges_after
        if charges == 0:
            raise FocusConflict(
                "focus_empty", "Focus refreshes next practice day. Standard practice is available."
            )
        run = PracticeFocusRun(
            id=uuid4(),
            tenant_id=self.tenant_id,
            person_id=actor.person_id,
            attempt_id=attempt.id,
            state="active",
            started_at=now,
            exit_cost=0,
            completion_restore=0,
        )
        self.database.add(run)
        await self.database.flush()
        entry = await self._event(
            actor, latest, run=run, kind="started", after=charges, day=day, zone=zone, now=now
        )
        await self._command(actor, key, "focus_started", intent, entry)
        return await self._result(actor, run, now)

    async def end(
        self,
        actor: ActorContext,
        run_id: UUID,
        *,
        key: str,
        expected_revision: int,
        expected_attempt_revision: int,
    ) -> dict[str, Any]:
        now = await self.practice._admit(actor)
        intent = {
            "run_id": str(run_id),
            "revision": expected_revision,
            "attempt_revision": expected_attempt_revision,
        }
        replay = await self.practice._replay(actor, key, "focus_ended", intent)
        run = await self._run(actor, run_id)
        if replay:
            return await self._result(actor, run, now)
        attempt = await self.practice._attempt(actor, run.attempt_id)
        self._revision(attempt.revision, expected_attempt_revision)
        if run.state != "active" or attempt.state != "in_progress":
            raise FocusConflict("not_eligible", "This Focus Run has already finished.")
        latest = await self._latest(actor)
        self._revision(0 if latest is None else latest.revision, expected_revision)
        latest, day, zone = await self._normalize(actor, latest, now)
        if latest is None:
            raise PracticeConflict("This Focus history is unavailable.")
        acknowledged = await self.database.scalar(
            select(PracticeFeedbackAck.id)
            .where(
                PracticeFeedbackAck.attempt_id == attempt.id,
                PracticeFeedbackAck.tenant_id == self.tenant_id,
                PracticeFeedbackAck.person_id == actor.person_id,
            )
            .limit(1)
        )
        run.state, run.finished_at = "ended", now
        run.exit_cost = int(acknowledged is not None)
        entry = await self._event(
            actor,
            latest,
            run=run,
            kind="ended",
            after=latest.charges_after - run.exit_cost,
            day=day,
            zone=zone,
            now=now,
        )
        await self._command(actor, key, "focus_ended", intent, entry)
        return await self._result(actor, run, now)

    async def complete_locked(
        self, actor: ActorContext, attempt: PracticeAttempt, now: datetime
    ) -> None:
        """Only called by host completion inside admitted acknowledgment transaction."""
        run = await self._active(actor)
        if run is None or run.attempt_id != attempt.id:
            return
        if attempt.state != "completed":
            raise PracticeConflict("Focus can only complete with its practice attempt.")
        latest, day, zone = await self._normalize(actor, await self._latest(actor), now)
        if latest is None:
            raise PracticeConflict("This Focus history is unavailable.")
        after = min(3, latest.charges_after + 1)
        run.state, run.finished_at = "completed", now
        run.completion_restore = after - latest.charges_after
        await self._event(
            actor, latest, run=run, kind="completed", after=after, day=day, zone=zone, now=now
        )
