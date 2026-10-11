"""Operations-admin analysis health (AUT-1798): read-only, bounded, no repair.

For one window of days: Sales Xray job states and retries per stage, the
failed (dead-letter) jobs with their stored failure codes, stuck work from the
watchdog's overdue alarm, how long analyses took, and an estimated provider
cost per analysed minute from the stored provider receipts, overall and per
prompt version and Report model (to compare versions as they change). Costs are the
admin pricing estimate, never a settlement. Failure text that is not a stored
code is withheld: provider and media messages never reach this view.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta
from statistics import median
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.conversation_intelligence.admin_pricing import estimate_provider_usage
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationDenied,
    ConversationError,
    utc,
)
from ac_platform.conversation_intelligence.models import (
    ConversationInferenceTask,
    ConversationPlanStageAuthorization,
    ConversationProcessingPlan,
    ConversationRun,
)
from ac_platform.conversation_intelligence.plan_facts import plan_facts
from ac_platform.conversation_intelligence.provider_admin import ConversationProviderAdmin
from ac_platform.conversation_intelligence.run_budget_alarm import overdue_processing_plans
from ac_platform.kernel.authz import ActorContext
from ac_platform.outbox.models import Job

MAX_DAYS = 30
MAX_JOBS = 5_000
MAX_VERSIONS = 20
CONVERSATION_KINDS = ("conversation.inspect_local.v1", "conversation.infer_provider.v1")
JOB_STATUSES = ("queued", "leased", "retry_wait", "held", "succeeded", "dead_letter")
_CODE = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,119}$")


def failure_code(job: Job) -> str:
    """A stored failure code, or a neutral label; never free-form error text."""

    detail = job.failure_detail if isinstance(job.failure_detail, dict) else {}
    for key in ("code", "reason", "kind"):
        value = detail.get(key)
        if isinstance(value, str) and _CODE.fullmatch(value):
            return value
    if isinstance(job.last_error, str) and _CODE.fullmatch(job.last_error):
        return job.last_error
    return "not_recorded" if not job.last_error else "withheld"


def failed_job_view(job: Job, *, stage: str, recording_id: UUID | None) -> dict[str, Any]:
    """One dead-lettered job as the console shows it: stored codes, never error text."""

    return {
        "job_id": str(job.id),
        "stage": stage,
        "recording_id": None if recording_id is None else str(recording_id),
        "attempts": job.attempt_count,
        "code": failure_code(job),
        "created_at": utc(job.created_at).isoformat(),
        "failed_at": None
        if job.dead_lettered_at is None
        else utc(job.dead_lettered_at).isoformat(),
        # The retry route refuses work that already reached a provider.
        "retryable": job.dispatch_started_at is None
        and job.provider_receipt is None
        and job.delivery_ambiguous_at is None,
    }


def _manifest(plan: ConversationProcessingPlan) -> dict[str, Any]:
    return plan.manifest if isinstance(plan.manifest, dict) else {}


def _version(plan: ConversationProcessingPlan) -> tuple[str | None, str | None, str | None]:
    """(coaching prompt revision, Report provider, Report model) as the plan recorded them."""

    facts = plan_facts(plan)

    def text(value: Any) -> str | None:
        return value if isinstance(value, str) and value else None

    return text(facts["prompt_revision"]), text(facts["provider"]), text(facts["model"])


def version_rows(
    jobs: Sequence[Job],
    job_plan: Mapping[UUID, UUID],
    plans: Mapping[UUID, ConversationProcessingPlan],
    stage: Callable[[Job], str],
) -> list[dict[str, Any]]:
    """Analyses per prompt version and Report model: outcomes, Report time, cost per minute.

    Operational only (finished, failed, how long, how costly), never report quality.
    Steps reach a version through their plan's quotes, so a failed audio check
    (which runs before any plan step) counts only in the overall failed jobs.
    """

    groups: dict[tuple[str | None, str | None, str | None], dict[str, Any]] = {}
    for plan in plans.values():
        groups.setdefault(
            _version(plan),
            {
                "plans": set(),
                "failed": 0,
                "retried": 0,
                "report_ms": [],
                "paise": 0,
                "priced": set(),
            },
        )["plans"].add(plan.id)
    for job in jobs:
        plan_id = job_plan.get(job.id)
        owner = None if plan_id is None else plans.get(plan_id)
        if owner is None:
            continue
        group = groups[_version(owner)]
        if job.status == "dead_letter":
            group["failed"] += 1
        if job.attempt_count > 1:
            group["retried"] += 1
        if (
            stage(job) == "C5"
            and job.dispatch_started_at is not None
            and job.receipt_recorded_at is not None
            and job.receipt_recorded_at >= job.dispatch_started_at
        ):
            group["report_ms"].append(
                (utc(job.receipt_recorded_at) - utc(job.dispatch_started_at)).total_seconds() * 1000
            )
        receipt = job.provider_receipt if isinstance(job.provider_receipt, dict) else None
        if job.status != "succeeded" or receipt is None:
            continue
        duration = _manifest(owner).get("duration_ms")
        estimate = estimate_provider_usage(
            receipt.get("provider") if isinstance(receipt.get("provider"), str) else None,
            receipt.get("model") if isinstance(receipt.get("model"), str) else None,
            receipt.get("usage") if isinstance(receipt.get("usage"), dict) else None,
            duration_ms=duration if isinstance(duration, int) else None,
        )
        if isinstance(estimate.get("paise"), int):
            group["paise"] += estimate["paise"]
            group["priced"].add(owner.id)

    rows = []
    for (prompt, provider, model), group in groups.items():
        member = [plans[item] for item in group["plans"]]
        minutes = (
            sum(
                value
                for item in group["priced"]
                if isinstance(value := _manifest(plans[item]).get("duration_ms"), int) and value > 0
            )
            / 60_000
        )
        rows.append(
            {
                "prompt_revision": prompt,
                "provider": provider,
                "model": model,
                "analyses": len(member),
                "completed": sum(1 for plan in member if plan.state == "completed"),
                "running": sum(1 for plan in member if plan.state == "active"),
                "held": sum(1 for plan in member if plan.state == "held"),
                "failed_steps": group["failed"],
                "retried_steps": group["retried"],
                "report_p50_ms": round(median(group["report_ms"])) if group["report_ms"] else None,
                "priced_minutes": round(minutes, 2),
                "paise_per_minute": None if minutes <= 0 else round(group["paise"] / minutes, 1),
            }
        )
    rows.sort(key=lambda row: (-row["analyses"], row["prompt_revision"] or "", row["model"] or ""))
    return rows[:MAX_VERSIONS]


def _percentile(values: list[float], share: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(share * (len(ordered) - 1))))
    return ordered[index]


class AdminAnalysisHealth:
    def __init__(
        self,
        application: ConversationApplication,
        operations_tenant_id: UUID,
        *,
        recording_tenant_ids: tuple[UUID, ...],
    ) -> None:
        self.application = application
        self.database: AsyncSession = application.database
        self.operations_tenant_id = operations_tenant_id
        self.recording_tenant_ids = tuple(
            item for item in dict.fromkeys(recording_tenant_ids) if item != operations_tenant_id
        )

    async def _admit(self, actor: ActorContext) -> datetime:
        if actor.tenant_id != self.operations_tenant_id:
            raise ConversationDenied("Analysis health requires the AC operations workspace.")
        await ConversationProviderAdmin(self.application).admit(actor)
        return utc(self.application.clock())

    async def summary(self, actor: ActorContext, *, days: int = 7) -> dict[str, Any]:
        now = await self._admit(actor)
        if type(days) is not int or not 1 <= days <= MAX_DAYS:
            raise ConversationError("Choose a window between 1 and 30 days.")
        since = now - timedelta(days=days)
        scope = self.recording_tenant_ids

        jobs = list(
            (
                await self.database.scalars(
                    select(Job)
                    .where(Job.kind.in_(CONVERSATION_KINDS), Job.created_at >= since)
                    .order_by(Job.created_at.desc())
                    .limit(MAX_JOBS + 1)
                )
            ).all()
        )
        truncated = len(jobs) > MAX_JOBS
        jobs = jobs[:MAX_JOBS]
        job_ids = [job.id for job in jobs]
        tasks = (
            list(
                (
                    await self.database.scalars(
                        select(ConversationInferenceTask).where(
                            ConversationInferenceTask.tenant_id.in_(scope),
                            ConversationInferenceTask.job_id.in_(job_ids),
                        )
                    )
                ).all()
            )
            if job_ids
            else []
        )
        runs = (
            list(
                (
                    await self.database.scalars(
                        select(ConversationRun).where(
                            ConversationRun.tenant_id.in_(scope),
                            ConversationRun.job_id.in_(job_ids),
                        )
                    )
                ).all()
            )
            if job_ids
            else []
        )
        task_by_job = {task.job_id: task for task in tasks}
        run_by_job = {run.job_id: run for run in runs}
        # Only jobs of served recordings; another tenant's work never shows here.
        in_scope = [job for job in jobs if job.id in task_by_job or job.id in run_by_job]

        def stage(job: Job) -> str:
            task = task_by_job.get(job.id)
            return task.stage if task is not None else "C1"

        def recording(job: Job) -> UUID | None:
            task = task_by_job.get(job.id)
            if task is not None:
                return task.recording_id
            run = run_by_job.get(job.id)
            return None if run is None else run.recording_id

        by_stage: dict[str, Counter[str]] = defaultdict(Counter)
        retried: Counter[str] = Counter()
        for job in in_scope:
            by_stage[stage(job)][job.status] += 1
            if job.attempt_count > 1:
                retried[stage(job)] += 1
        totals: Counter[str] = Counter(job.status for job in in_scope)

        failed = [
            failed_job_view(job, stage=stage(job), recording_id=recording(job))
            for job in in_scope
            if job.status == "dead_letter"
        ][:50]
        held = [
            {
                "job_id": str(job.id),
                "stage": stage(job),
                "recording_id": None if recording(job) is None else str(recording(job)),
                "reason": job.hold_reason
                if job.hold_reason and _CODE.fullmatch(job.hold_reason)
                else "held",
                "held_at": None if job.held_at is None else utc(job.held_at).isoformat(),
            }
            for job in in_scope
            if job.status == "held"
        ][:50]

        # Durations: provider time per stage, and whole runs from start to finish.
        provider_ms: dict[str, list[float]] = defaultdict(list)
        for job in in_scope:
            if job.dispatch_started_at is not None and job.receipt_recorded_at is not None:
                elapsed = (
                    utc(job.receipt_recorded_at) - utc(job.dispatch_started_at)
                ).total_seconds() * 1000
                if elapsed >= 0:
                    provider_ms[stage(job)].append(elapsed)
        finished = list(
            (
                await self.database.scalars(
                    select(ConversationRun).where(
                        ConversationRun.tenant_id.in_(scope),
                        ConversationRun.completed_at.is_not(None),
                        ConversationRun.completed_at >= since,
                    )
                )
            ).all()
        )
        run_ms = [
            (utc(run.completed_at) - utc(run.created_at)).total_seconds() * 1000
            for run in finished
            if run.completed_at is not None and run.completed_at >= run.created_at
        ]

        # Cost per analysed minute: provider receipts priced by the admin estimate.
        recording_ids = {
            recording(job)
            for job in in_scope
            if job.status == "succeeded" and isinstance(job.provider_receipt, dict)
        } - {None}
        durations: dict[UUID, int] = {}
        if recording_ids:
            for plan in (
                await self.database.scalars(
                    select(ConversationProcessingPlan).where(
                        ConversationProcessingPlan.tenant_id.in_(scope),
                        ConversationProcessingPlan.recording_id.in_(recording_ids),
                    )
                )
            ).all():
                manifest = plan.manifest if isinstance(plan.manifest, dict) else {}
                value = manifest.get("duration_ms")
                if isinstance(value, int) and value > 0:
                    durations[plan.recording_id] = value
        cost_paise = 0
        priced: set[UUID] = set()
        unpriced = 0
        for job in in_scope:
            receipt = job.provider_receipt if isinstance(job.provider_receipt, dict) else None
            target = recording(job)
            if job.status != "succeeded" or receipt is None or target is None:
                continue
            estimate = estimate_provider_usage(
                receipt.get("provider") if isinstance(receipt.get("provider"), str) else None,
                receipt.get("model") if isinstance(receipt.get("model"), str) else None,
                receipt.get("usage") if isinstance(receipt.get("usage"), dict) else None,
                duration_ms=durations.get(target),
            )
            if isinstance(estimate.get("paise"), int):
                cost_paise += estimate["paise"]
                priced.add(target)
            else:
                unpriced += 1
        priced_minutes = sum(durations.get(item, 0) for item in priced) / 60_000

        # Per prompt version: each step's job reaches its plan through the step's quote.
        quote_by_job = {task.job_id: task.quote_id for task in tasks}
        plan_by_quote: dict[UUID, UUID] = {}
        if quote_by_job:
            links = await self.database.execute(
                select(
                    ConversationPlanStageAuthorization.quote_id,
                    ConversationPlanStageAuthorization.plan_id,
                ).where(
                    ConversationPlanStageAuthorization.tenant_id.in_(scope),
                    ConversationPlanStageAuthorization.quote_id.in_(set(quote_by_job.values())),
                )
            )
            plan_by_quote = {quote_id: plan_id for quote_id, plan_id in links.all()}
        job_plan = {
            job_id: plan_by_quote[quote_id]
            for job_id, quote_id in quote_by_job.items()
            if quote_id in plan_by_quote
        }
        version_plans = (
            {
                plan.id: plan
                for plan in (
                    await self.database.scalars(
                        select(ConversationProcessingPlan).where(
                            ConversationProcessingPlan.tenant_id.in_(scope),
                            ConversationProcessingPlan.id.in_(set(job_plan.values())),
                        )
                    )
                ).all()
            }
            if job_plan
            else {}
        )
        versions = version_rows(in_scope, job_plan, version_plans, stage)

        overdue = await overdue_processing_plans(self.database, limit=50, now=now)
        stuck = [item for item in overdue["overdue"] if UUID(item["tenant_id"]) in scope]
        unfinished = [
            item for item in overdue["released_unfinished_runs"] if UUID(item["tenant_id"]) in scope
        ]

        daily: dict[str, Counter[str]] = defaultdict(Counter)
        for job in in_scope:
            day = utc(job.created_at).date().isoformat()
            if job.status == "succeeded" and stage(job) == "C5":
                daily[day]["analysed"] += 1
            if job.status == "dead_letter":
                daily[day]["failed"] += 1
        series = []
        for offset in range(days - 1, -1, -1):
            day = (now - timedelta(days=offset)).date().isoformat()
            series.append(
                {"day": day, "analysed": daily[day]["analysed"], "failed": daily[day]["failed"]}
            )

        def stats(values: list[float]) -> dict[str, Any]:
            return {
                "count": len(values),
                "p50_ms": None if not values else round(median(values)),
                "p90_ms": None if not values else round(_percentile(values, 0.9) or 0),
                "max_ms": None if not values else round(max(values)),
            }

        return {
            "window": {"days": days, "since": since.isoformat(), "truncated": truncated},
            "jobs": {
                "total": len(in_scope),
                "by_status": {status: totals.get(status, 0) for status in JOB_STATUSES},
                "by_stage": {
                    name: {status: counts.get(status, 0) for status in JOB_STATUSES}
                    for name, counts in sorted(by_stage.items())
                },
                "retried": dict(sorted(retried.items())),
            },
            "failed": failed,
            "held": held,
            "stuck": {
                "plans": stuck,
                "unfinished_runs": unfinished,
                "truncated": bool(overdue["truncated"] or overdue["runs_truncated"]),
            },
            "durations": {
                "runs": stats(run_ms),
                "provider_by_stage": {
                    name: stats(values) for name, values in sorted(provider_ms.items())
                },
            },
            "cost": {
                "estimated_paise": cost_paise,
                "priced_minutes": round(priced_minutes, 2),
                "paise_per_minute": None
                if priced_minutes <= 0
                else round(cost_paise / priced_minutes, 1),
                "unpriced_jobs": unpriced,
                "basis": "admin_pricing_estimate_not_settlement",
            },
            "daily": series,
            "versions": versions,
        }
