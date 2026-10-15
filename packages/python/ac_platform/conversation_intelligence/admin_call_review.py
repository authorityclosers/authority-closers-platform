"""Operations-admin call review console reads (AUT-1798).

Three read-only views over the served Sales Xray recordings, for the same
operations control accounts that may open Admin reports today:

* ``queue``: the newest calls in a bounded window, filterable by organisation,
  rep, report language, provider, coaching prompt revision, status and upload
  date;
* ``call``: one recording with every analysis run (prompt version, provider
  and whether a report exists), for comparing runs, and its failed steps
  (stored codes only) for the existing admin job retry;
* ``bundle``: one run's report and transcript, withheld per the recording's
  sensitive-segment marks and audited like ``admin_report_view``.

``playback`` describes the private source for the admin audio route. Nothing
here writes conversation state or calls a provider.
"""

from __future__ import annotations

import base64
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionUsage,
    ConversationVisitorClaim,
)
from ac_platform.conversation_intelligence.admin_analysis_health import failed_job_view
from ac_platform.conversation_intelligence.admin_recordings import _owner_view
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationDenied,
    ConversationError,
    ConversationNotFound,
    utc,
)
from ac_platform.conversation_intelligence.call_metrics import compute_call_metrics
from ac_platform.conversation_intelligence.canary import recording_is_canary
from ac_platform.conversation_intelligence.guest_models import ConversationGuestSubmission
from ac_platform.conversation_intelligence.measurement_view import ConversationMeasurements
from ac_platform.conversation_intelligence.models import (
    ConversationInferenceTask,
    ConversationPlanStageAuthorization,
    ConversationProcessingPlan,
    ConversationRecording,
    ConversationReportDraft,
    ConversationRun,
)
from ac_platform.conversation_intelligence.plan_facts import plan_facts as _plan_facts
from ac_platform.conversation_intelligence.provider_admin import ConversationProviderAdmin
from ac_platform.conversation_intelligence.report_store import ConversationReports
from ac_platform.conversation_intelligence.report_story import report_story
from ac_platform.conversation_intelligence.review_labels import (
    REVIEW_STATES,
    ReviewLabels,
    review_state,
)
from ac_platform.conversation_intelligence.review_service import ConversationReviewService
from ac_platform.conversation_intelligence.sensitive_segments import withhold
from ac_platform.conversation_intelligence.sensitive_segments_store import withheld_plan_for
from ac_platform.identity.models import Person
from ac_platform.kernel.authz import ActorContext
from ac_platform.outbox.models import Job
from ac_platform.tenancy.models import Tenant

QUEUE_WINDOW = 500
MAX_PAGE = 100
MAX_FAILED_JOBS = 20
STATUSES = ("ready", "analysing", "failed", "uploaded")
LANGUAGES = ("en", "hi-Deva+en", "mr-Deva+en")


def _cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(f"o:{offset}".encode()).decode().rstrip("=")


def _offset(cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        if not raw.startswith("o:"):
            raise ValueError
        value = int(raw[2:])
    except (ValueError, UnicodeDecodeError):
        raise ConversationError("Use the queue cursor the service returned.") from None
    if not 0 <= value < QUEUE_WINDOW:
        raise ConversationError("Use the queue cursor the service returned.")
    return value


def _iso(value: datetime | None) -> str | None:
    return None if value is None else utc(value).isoformat()


def _status(
    latest_run: ConversationRun | None,
    latest_plan: ConversationProcessingPlan | None,
    has_report: bool,
) -> str:
    if latest_plan is not None and latest_plan.state in {"active", "held"}:
        return "analysing"
    if latest_run is not None and latest_run.state in {"queued", "running"}:
        return "analysing"
    if has_report:
        return "ready"
    if latest_run is not None and latest_run.state in {"failed", "cancelled", "uncertain"}:
        return "failed"
    if latest_plan is not None and latest_plan.state in {"failed", "cancelled", "expired"}:
        return "failed"
    return "uploaded"


class AdminCallReview:
    """Read-only console views; the actor is re-admitted on every call."""

    def __init__(
        self,
        application: ConversationApplication,
        operations_tenant_id: UUID,
        *,
        recording_tenant_ids: Sequence[UUID],
    ) -> None:
        self.application = application
        self.database: AsyncSession = application.database
        self.operations_tenant_id = operations_tenant_id
        self.recording_tenant_ids = tuple(
            dict.fromkeys(item for item in recording_tenant_ids if item != operations_tenant_id)
        )

    async def _admit(self, actor: ActorContext) -> datetime:
        if actor.tenant_id != self.operations_tenant_id:
            raise ConversationDenied("Call review requires the AC operations workspace.")
        await ConversationProviderAdmin(self.application).admit(actor)
        return utc(self.application.clock())

    # ---------- Shared loaders ----------

    async def _owners(
        self, recordings: Sequence[ConversationRecording]
    ) -> dict[UUID, dict[str, Any]]:
        if not recordings:
            return {}
        ids = [row.id for row in recordings]
        scope = self.recording_tenant_ids
        guests = {
            row.recording_id: row
            for row in (
                await self.database.scalars(
                    select(ConversationGuestSubmission).where(
                        ConversationGuestSubmission.tenant_id.in_(scope),
                        ConversationGuestSubmission.recording_id.in_(ids),
                    )
                )
            ).all()
        }
        usage_ids = [row.usage_id for row in guests.values()]
        usages = (
            {
                row.id: row
                for row in (
                    await self.database.scalars(
                        select(ConversationAcquisitionUsage).where(
                            ConversationAcquisitionUsage.tenant_id.in_(scope),
                            ConversationAcquisitionUsage.id.in_(usage_ids),
                        )
                    )
                ).all()
            }
            if usage_ids
            else {}
        )
        visitor_ids = [row.visitor_id for row in usages.values() if row.visitor_id is not None]
        claims = (
            {
                row.visitor_id: row
                for row in (
                    await self.database.scalars(
                        select(ConversationVisitorClaim).where(
                            ConversationVisitorClaim.tenant_id.in_(scope),
                            ConversationVisitorClaim.visitor_id.in_(visitor_ids),
                        )
                    )
                ).all()
            }
            if visitor_ids
            else {}
        )
        person_ids = {row.person_id for row in recordings}
        person_ids.update(row.person_id for row in usages.values() if row.person_id is not None)
        person_ids.update(row.person_id for row in claims.values())
        people = {
            row.id: row
            for row in (
                await self.database.scalars(select(Person).where(Person.id.in_(person_ids)))
            ).all()
        }
        owners: dict[UUID, dict[str, Any]] = {}
        for recording in recordings:
            guest = guests.get(recording.id)
            usage = usages.get(guest.usage_id) if guest is not None else None
            claim = (
                claims.get(usage.visitor_id)
                if usage is not None and usage.visitor_id is not None
                else None
            )
            owners[recording.id] = _owner_view(recording, guest, usage, claim, people)
        return owners

    async def _organisations(self, tenant_ids: Iterable[UUID]) -> dict[UUID, str]:
        ids = list(set(tenant_ids))
        if not ids:
            return {}
        rows = await self.database.execute(select(Tenant.id, Tenant.name).where(Tenant.id.in_(ids)))
        return {identifier: name for identifier, name in rows.all()}

    async def _runs(self, recording_ids: Sequence[UUID]) -> dict[UUID, list[ConversationRun]]:
        grouped: dict[UUID, list[ConversationRun]] = defaultdict(list)
        if not recording_ids:
            return grouped
        for run in (
            await self.database.scalars(
                select(ConversationRun).where(
                    ConversationRun.tenant_id.in_(self.recording_tenant_ids),
                    ConversationRun.recording_id.in_(recording_ids),
                )
            )
        ).all():
            grouped[run.recording_id].append(run)
        for runs in grouped.values():
            runs.sort(key=lambda run: (utc(run.created_at), str(run.id)), reverse=True)
        return grouped

    async def _plans(
        self, recording_ids: Sequence[UUID]
    ) -> dict[UUID, list[ConversationProcessingPlan]]:
        grouped: dict[UUID, list[ConversationProcessingPlan]] = defaultdict(list)
        if not recording_ids:
            return grouped
        for plan in (
            await self.database.scalars(
                select(ConversationProcessingPlan).where(
                    ConversationProcessingPlan.tenant_id.in_(self.recording_tenant_ids),
                    ConversationProcessingPlan.recording_id.in_(recording_ids),
                )
            )
        ).all():
            grouped[plan.recording_id].append(plan)
        for plans in grouped.values():
            plans.sort(key=lambda plan: (utc(plan.created_at), str(plan.id)), reverse=True)
        return grouped

    async def _reports(self, recording_ids: Sequence[UUID]) -> dict[UUID, dict[UUID, UUID]]:
        """recording -> run -> latest report id. Columns only: payloads stay unread."""

        reports: dict[UUID, dict[UUID, UUID]] = defaultdict(dict)
        if not recording_ids:
            return reports
        rows = await self.database.execute(
            select(
                ConversationReportDraft.recording_id,
                ConversationReportDraft.run_id,
                ConversationReportDraft.id,
                ConversationReportDraft.created_at,
            ).where(
                ConversationReportDraft.tenant_id.in_(self.recording_tenant_ids),
                ConversationReportDraft.recording_id.in_(recording_ids),
            )
        )
        latest: dict[tuple[UUID, UUID], tuple[datetime, UUID]] = {}
        for recording_id, run_id, report_id, created_at in rows.all():
            key = (recording_id, run_id)
            stamp = (utc(created_at), report_id)
            if key not in latest or stamp > latest[key]:
                latest[key] = stamp
        for (recording_id, run_id), (_, report_id) in latest.items():
            reports[recording_id][run_id] = report_id
        return reports

    async def _run_plans(self, run_ids: Sequence[UUID]) -> dict[UUID, UUID]:
        """run -> plan, through the run's inference tasks and the plan's quotes."""

        if not run_ids:
            return {}
        rows = await self.database.execute(
            select(ConversationInferenceTask.run_id, ConversationPlanStageAuthorization.plan_id)
            .join(
                ConversationPlanStageAuthorization,
                ConversationPlanStageAuthorization.quote_id == ConversationInferenceTask.quote_id,
            )
            .where(
                ConversationInferenceTask.tenant_id.in_(self.recording_tenant_ids),
                ConversationInferenceTask.run_id.in_(run_ids),
            )
        )
        return {run_id: plan_id for run_id, plan_id in rows.all()}

    async def _failed_jobs(
        self, recording_id: UUID, runs: Sequence[ConversationRun]
    ) -> list[dict[str, Any]]:
        """One call's dead-lettered steps, newest first: the local run job and its stages."""

        stage_by_job: dict[UUID, str] = {run.job_id: "C1" for run in runs}
        rows = await self.database.execute(
            select(ConversationInferenceTask.job_id, ConversationInferenceTask.stage).where(
                ConversationInferenceTask.tenant_id.in_(self.recording_tenant_ids),
                ConversationInferenceTask.recording_id == recording_id,
            )
        )
        stage_by_job.update({job_id: stage for job_id, stage in rows.all()})
        if not stage_by_job:
            return []
        jobs = (
            await self.database.scalars(
                select(Job)
                .where(Job.id.in_(stage_by_job), Job.status == "dead_letter")
                .order_by(Job.created_at.desc())
                .limit(MAX_FAILED_JOBS)
            )
        ).all()
        return [
            failed_job_view(job, stage=stage_by_job[job.id], recording_id=recording_id)
            for job in jobs
        ]

    # ---------- Views ----------

    async def queue(
        self,
        actor: ActorContext,
        *,
        organisation: UUID | None = None,
        rep: UUID | None = None,
        language: str | None = None,
        provider: str | None = None,
        prompt: str | None = None,
        status: str | None = None,
        review: str | None = None,
        since: date | None = None,
        until: date | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        await self._admit(actor)
        if type(limit) is not int or not 1 <= limit <= MAX_PAGE:
            raise ConversationError("Use a queue page size between 1 and 100.")
        if status is not None and status not in STATUSES:
            raise ConversationError("Use a known call status.")
        if review is not None and review not in REVIEW_STATES:
            raise ConversationError("Use a known review state.")
        if language is not None and language not in LANGUAGES:
            raise ConversationError("Use a known report language.")
        if since is not None and until is not None and until < since:
            raise ConversationError("The end date is before the start date.")
        offset = _offset(cursor)

        query = select(ConversationRecording).where(
            ConversationRecording.tenant_id.in_(self.recording_tenant_ids),
            ConversationRecording.state != "deleted",
            ~recording_is_canary(),
        )
        if organisation is not None:
            query = query.where(ConversationRecording.tenant_id == organisation)
        if since is not None:
            query = query.where(
                ConversationRecording.created_at >= datetime.combine(since, time.min, tzinfo=UTC)
            )
        if until is not None:
            query = query.where(
                ConversationRecording.created_at
                < datetime.combine(until + timedelta(days=1), time.min, tzinfo=UTC)
            )
        window = (
            await self.database.scalars(
                query.order_by(
                    ConversationRecording.created_at.desc(), ConversationRecording.id.desc()
                ).limit(QUEUE_WINDOW + 1)
            )
        ).all()
        truncated = len(window) > QUEUE_WINDOW
        window = window[:QUEUE_WINDOW]
        ids = [row.id for row in window]
        owners = await self._owners(window)
        organisations = await self._organisations(row.tenant_id for row in window)
        runs = await self._runs(ids)
        plans = await self._plans(ids)
        reports = await self._reports(ids)
        label_rows = await ReviewLabels(
            self.application,
            self.operations_tenant_id,
            recording_tenant_ids=self.recording_tenant_ids,
        ).rows(ids)

        items: list[dict[str, Any]] = []
        for recording in window:
            recording_runs = runs.get(recording.id, [])
            recording_plans = plans.get(recording.id, [])
            report_runs = reports.get(recording.id, {})
            latest_run = recording_runs[0] if recording_runs else None
            latest_plan = recording_plans[0] if recording_plans else None
            report_run = next((run for run in recording_runs if run.id in report_runs), None)
            facts = _plan_facts(latest_plan)
            items.append(
                {
                    "recording_id": str(recording.id),
                    "uploaded_at": _iso(recording.created_at),
                    "organisation": {
                        "id": str(recording.tenant_id),
                        "name": organisations.get(recording.tenant_id, "Unknown organisation"),
                    },
                    "rep": owners.get(recording.id),
                    "status": _status(latest_run, latest_plan, report_run is not None),
                    "language": facts["language"],
                    "duration_ms": facts["duration_ms"],
                    "provider": facts["provider"],
                    "model": facts["model"],
                    "prompt_revision": facts["prompt_revision"],
                    # Every prompt this call was analysed with, latest or not.
                    "prompt_revisions": sorted(
                        {
                            value
                            for plan in recording_plans
                            if isinstance(value := _plan_facts(plan)["prompt_revision"], str)
                            and value
                        }
                    ),
                    "runs": len(recording_runs),
                    "latest_run": None
                    if latest_run is None
                    else {
                        "id": str(latest_run.id),
                        "state": latest_run.state,
                        "created_at": _iso(latest_run.created_at),
                        "completed_at": _iso(latest_run.completed_at),
                    },
                    "report_run_id": None if report_run is None else str(report_run.id),
                    "review": review_state(label_rows.get(recording.id, [])),
                }
            )

        facets = _facets(items)
        if rep is not None:
            items = [item for item in items if (item["rep"] or {}).get("person_id") == str(rep)]
        if language is not None:
            items = [item for item in items if item["language"] == language]
        if provider is not None:
            items = [item for item in items if item["provider"] == provider]
        if prompt is not None:
            items = [item for item in items if prompt in item["prompt_revisions"]]
        counts = {name: 0 for name in STATUSES}
        review_counts = {name: 0 for name in REVIEW_STATES}
        for item in items:
            counts[item["status"]] += 1
            review_counts[item["review"]] += 1
        if status is not None:
            items = [item for item in items if item["status"] == status]
        if review is not None:
            items = [item for item in items if item["review"] == review]
        page = items[offset : offset + limit]
        following = offset + limit
        return {
            "items": page,
            "total": len(items),
            "counts": counts,
            "review_counts": review_counts,
            "facets": facets,
            "next_cursor": _cursor(following) if following < len(items) else None,
            "window": {"size": QUEUE_WINDOW, "truncated": truncated},
        }

    async def call(self, actor: ActorContext, recording_id: UUID) -> dict[str, Any]:
        await self._admit(actor)
        recording = await self.database.scalar(
            select(ConversationRecording).where(
                ConversationRecording.id == recording_id,
                ConversationRecording.tenant_id.in_(self.recording_tenant_ids),
                ConversationRecording.state != "deleted",
            )
        )
        if recording is None:
            raise ConversationNotFound("Call not found.")
        owners = await self._owners([recording])
        organisations = await self._organisations([recording.tenant_id])
        runs = (await self._runs([recording.id])).get(recording.id, [])
        plans = {
            plan.id: plan for plan in (await self._plans([recording.id])).get(recording.id, [])
        }
        reports = (await self._reports([recording.id])).get(recording.id, {})
        run_plans = await self._run_plans([run.id for run in runs])
        latest_plan = max(
            plans.values(), key=lambda plan: (utc(plan.created_at), str(plan.id)), default=None
        )
        return {
            "recording_id": str(recording.id),
            "uploaded_at": _iso(recording.created_at),
            "state": recording.state,
            "content_type": recording.content_type,
            "source_bytes": recording.source_bytes,
            "organisation": {
                "id": str(recording.tenant_id),
                "name": organisations.get(recording.tenant_id, "Unknown organisation"),
            },
            "rep": owners.get(recording.id),
            "status": _status(
                runs[0] if runs else None,
                latest_plan,
                any(run.id in reports for run in runs),
            ),
            "runs": [
                {
                    "id": str(run.id),
                    "state": run.state,
                    "generation": run.generation,
                    "recipe_revision": run.recipe_revision,
                    "created_at": _iso(run.created_at),
                    "completed_at": _iso(run.completed_at),
                    "report_id": None if run.id not in reports else str(reports[run.id]),
                    **_plan_facts(plans.get(run_plans[run.id]) if run.id in run_plans else None),
                }
                for run in runs
            ],
            "failed_jobs": await self._failed_jobs(recording.id, runs),
        }

    async def bundle(self, actor: ActorContext, run_id: UUID) -> dict[str, Any]:
        now = await self._admit(actor)
        run = await self.database.scalar(
            select(ConversationRun).where(
                ConversationRun.id == run_id,
                ConversationRun.tenant_id.in_(self.recording_tenant_ids),
            )
        )
        if run is None:
            raise ConversationNotFound("Run not found.")
        review = ConversationReviewService(
            self.application, operations_tenant_id=self.operations_tenant_id
        )
        evidence = await review._evidence(run_id, now)
        report, transcript = ConversationReports(self.application)._validated(
            evidence.draft, evidence.recording
        )
        await review._review_audit(
            actor,
            tenant_id=evidence.recording.tenant_id,
            action="admin_call_review_view",
            resource_type="conversation_report_draft",
            resource_id=evidence.draft.id,
            intent={
                "run_id": str(evidence.run.id),
                "recording_id": str(evidence.recording.id),
                "report_id": str(evidence.draft.id),
            },
            now=now,
        )
        try:
            # The persisted C1 loudness envelope; older calls may not have one.
            waveform: dict[str, Any] | None = await ConversationMeasurements(
                self.application
            ).waveform_from_recording(evidence.recording)
        except ConversationError:
            waveform = None
        try:
            # call-metrics/2, the rep's Report twin: numbers and segment ids only, no text.
            duration = waveform.get("duration_ms") if waveform else None
            metrics: dict[str, Any] | None = dict(
                compute_call_metrics(
                    list(transcript.get("segments") or []),
                    duration if isinstance(duration, int) else None,
                )
            )
        except (AttributeError, TypeError, ValueError, KeyError):
            metrics = None
        plan = await withheld_plan_for(
            self.database,
            recording_id=evidence.recording.id,
            served_revisions=(report.transcript_revision, str(transcript.get("revision", ""))),
        )
        return withhold(
            {
                "run_id": str(evidence.run.id),
                "recording_id": str(evidence.recording.id),
                "report_id": str(evidence.draft.id),
                "retention_until": evidence.retention_until.isoformat(),
                "report": report.model_dump(mode="json"),
                # The same story projection the rep's Report reads (six pillars).
                "story": report_story(report),
                "transcript": transcript,
                "waveform": waveform,
                "metrics": metrics,
                "audio_source_url": f"/v1/admin/conversation/runs/{evidence.run.id}/source",
            },
            plan,
        )

    async def playback(self, actor: ActorContext, run_id: UUID) -> dict[str, Any]:
        now = await self._admit(actor)
        run = await self.database.scalar(
            select(ConversationRun).where(
                ConversationRun.id == run_id,
                ConversationRun.tenant_id.in_(self.recording_tenant_ids),
            )
        )
        if run is None:
            raise ConversationNotFound("Run not found.")
        review = ConversationReviewService(
            self.application, operations_tenant_id=self.operations_tenant_id
        )
        evidence = await review._evidence(run_id, now)
        recording = evidence.recording
        return {
            "id": str(recording.id),
            "tenant_id": str(recording.tenant_id),
            "source_bytes": recording.source_bytes,
            "source_sha256": recording.source_sha256,
            "content_type": recording.content_type,
        }


def _facets(items: Sequence[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Filter choices that exist in the window, with how many calls each has."""

    def tally(key: Any) -> list[dict[str, Any]]:
        counted: dict[str, dict[str, Any]] = {}
        for item in items:
            found = key(item)
            if found is None:
                continue
            value, label = found
            entry = counted.setdefault(value, {"value": value, "label": label, "count": 0})
            entry["count"] += 1
        return sorted(counted.values(), key=lambda entry: (-entry["count"], entry["label"]))

    return {
        "organisations": tally(
            lambda item: (item["organisation"]["id"], item["organisation"]["name"])
        ),
        "reps": tally(
            lambda item: (
                (item["rep"]["person_id"], item["rep"]["label"])
                if item["rep"] and item["rep"].get("person_id")
                else None
            )
        ),
        "languages": tally(
            lambda item: (item["language"], item["language"]) if item["language"] else None
        ),
        "providers": tally(
            lambda item: (item["provider"], item["provider"]) if item["provider"] else None
        ),
        "prompts": _multi_tally(item["prompt_revisions"] for item in items),
    }


def _multi_tally(groups: Iterable[Sequence[str]]) -> list[dict[str, Any]]:
    """Calls per value when a call can have several (e.g. the prompts it was analysed with)."""

    counted: dict[str, int] = defaultdict(int)
    for values in groups:
        for value in set(values):
            counted[value] += 1
    return [
        {"value": value, "label": value, "count": count}
        for value, count in sorted(counted.items(), key=lambda entry: (-entry[1], entry[0]))
    ]
