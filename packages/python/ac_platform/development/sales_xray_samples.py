"""Seed fictional, zero-cost Sales Xray sample reports in development only.

These reports are fictional fixtures for route checks. They are not official
scores or evaluations. This command refuses every target except the pinned
loopback development database and dev Sales Xray origin.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import secrets
import stat
import sys
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

import httpx
from fastapi import FastAPI, Request
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.acquisition_sessions import AcquisitionSessions
from ac_platform.conversation_intelligence.acquisition_source import NativeUploadPreflight
from ac_platform.conversation_intelligence.activation_contract import HostedApprovalBundle
from ac_platform.conversation_intelligence.broker_router import FixedProviderRouter, ProviderRoute
from ac_platform.conversation_intelligence.entitlements import (
    BudgetAccount,
    MinuteAccount,
    SettlementReceipt,
    settle,
)
from ac_platform.conversation_intelligence.guest_models import ConversationGuestSubmission
from ac_platform.conversation_intelligence.hosted_runtime import compose_hosted_intake
from ac_platform.conversation_intelligence.inference_worker import (
    ConversationInferenceWorker,
    save_accounts,
)
from ac_platform.conversation_intelligence.models import (
    ConversationBudgetAccount,
    ConversationInferenceTask,
    ConversationMinuteAccount,
    ConversationProcessingPlan,
    ConversationQuote,
    ConversationRecording,
)
from ac_platform.conversation_intelligence.native_runtime import SocketNativeRuntime
from ac_platform.conversation_intelligence.processing_plan import ProcessingPlanScheduler
from ac_platform.conversation_intelligence.worker import HostedConversationWorker
from ac_platform.development.sales_xray_sample_fakes import (
    FictionalReportingBroker,
    fictional_audio,
)
from ac_platform.http.auth import AuthenticatedTransaction
from ac_platform.http.conversation_intake import ConversationIntakeRuntime
from ac_platform.http.conversation_submissions import install_submission_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.application import ResolvedActorContext
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.kernel.authz import ActorContext
from ac_platform.outbox.models import Job
from ac_platform.tenancy.models import Membership, Tenant

_APP_ORIGIN = "https://salesxray-dev.authorityclosers.com"
_DB_HOST = "127.0.0.1"
_DB_PORT = 55432
_DB_NAME = "ac_platform"
_DB_USER = "ac_runtime"
_SAMPLE_NAMESPACE = UUID("01a57a8f-27ac-471d-b4d3-0fd47779ec4d")
_LOCAL_JOB = "conversation.inspect_local.v1"
_DELETE_JOB = "conversation.erase_local.v1"
_INFERENCE_JOB = "conversation.infer_provider.v1"
_ACTIVE_JOB_STATES = ("queued", "retry_wait")
_UPLOAD_FRAME_BYTES = 256 * 1024


class _ChunkedAudio(httpx.AsyncByteStream):
    """Send the generated WAV in bounded frames while keeping its exact length."""

    def __init__(self, audio: bytes) -> None:
        self.audio = audio

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for offset in range(0, len(self.audio), _UPLOAD_FRAME_BYTES):
            yield self.audio[offset : offset + _UPLOAD_FRAME_BYTES]


class SampleRefused(ValueError):
    """A safe, content-free refusal suitable for CLI output."""


def require_sample_target(environ: Mapping[str, str], *, acknowledged: bool) -> None:
    """Validate every development boundary before settings or a database are opened."""
    raw_url = environ.get("AC_DATABASE_URL", "")
    try:
        url = make_url(raw_url)
    except Exception:
        raise SampleRefused("Refusing: AC_DATABASE_URL is not the pinned dev database.") from None
    if (
        environ.get("AC_ENVIRONMENT") != "development"
        or url.drivername != "postgresql+psycopg"
        or url.host != _DB_HOST
        or url.port != _DB_PORT
        or url.database != _DB_NAME
        or url.username != _DB_USER
        or url.query
        or environ.get("AC_SALES_XRAY_APP_URL") != _APP_ORIGIN
        or environ.get("AC_EXTERNAL_SIDE_EFFECTS_HOLD") != "true"
        or not acknowledged
        or any(name.upper().startswith("PG") for name in environ)
    ):
        raise SampleRefused(
            "Refusing: require development, the pinned loopback database and dev origin, "
            "external side effects held, explicit acknowledgement, and no PG* variables."
        )


def build_fake_router(bundle: HostedApprovalBundle, authority: object) -> FixedProviderRouter:
    """Bind every approved stage to the same package-owned, no-network broker."""
    policy = bundle.acquisition_policy
    if policy is None:
        raise SampleRefused("Refusing: approved acquisition stages are unavailable.")
    broker = FictionalReportingBroker()
    routes = {
        provider: ProviderRoute(provider, credential_ref, broker)
        for provider, credential_ref in policy.provider_references()
    }
    if not routes:
        raise SampleRefused("Refusing: no approved acquisition provider stages are available.")
    return FixedProviderRouter(routes, authority=authority)


async def _read_account_actor(
    sessions: async_sessionmaker[AsyncSession], settings: Settings, email: str
) -> ResolvedActorContext:
    tenant_id = settings.public_learner_tenant_id
    if tenant_id is None:
        raise SampleRefused("Refusing: public learner tenant is not configured.")
    now = datetime.now(UTC)
    async with sessions() as db:
        row = (
            await db.execute(
                select(
                    Person.id,
                    Person.revision,
                    IdentitySession.id,
                    IdentitySession.revision,
                    Tenant.revision,
                    Membership.revision,
                )
                .select_from(Person)
                .join(IdentitySession, IdentitySession.person_id == Person.id)
                .join(
                    Membership,
                    (Membership.person_id == Person.id) & (Membership.tenant_id == tenant_id),
                )
                .join(Tenant, Tenant.id == tenant_id)
                .where(
                    func.lower(Person.email) == email.strip().lower(),
                    Person.status == "active",
                    Person.email_verified_at.is_not(None),
                    IdentitySession.audience == "account",
                    IdentitySession.selected_tenant_id == tenant_id,
                    IdentitySession.revoked_at.is_(None),
                    IdentitySession.expires_at > now,
                    Membership.role == "learner",
                    Membership.status == "active",
                    Membership.ended_at.is_(None),
                    Tenant.status == "active",
                )
                .order_by(IdentitySession.expires_at.desc())
                .limit(1)
            )
        ).first()
    if row is None:
        raise SampleRefused("Refusing: that email has no active, signed-in public learner account.")
    person_id, person_revision, session_id, session_revision, tenant_revision, member_revision = row
    return ResolvedActorContext(
        ActorContext(person_id, session_id, tenant_id),
        "learner",
        person_revision,
        session_revision,
        tenant_revision,
        member_revision,
    )


def _install_sample_routes(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    actor: ResolvedActorContext,
) -> tuple[FastAPI, ConversationIntakeRuntime, SocketNativeRuntime]:
    intake = compose_hosted_intake(settings)
    if not isinstance(intake, ConversationIntakeRuntime) or intake.authority is None:
        raise SampleRefused("Refusing: hosted dev upload and report runtime is not ready.")
    if not settings.sales_xray_native_socket_path or not settings.sales_xray_native_image_ref:
        raise SampleRefused("Refusing: the dev native upload helper is not configured.")
    socket_path = Path(settings.sales_xray_native_socket_path)
    try:
        info = socket_path.lstat()
        if not stat.S_ISSOCK(info.st_mode) or info.st_mode & 0o007:
            raise ValueError
    except (OSError, ValueError):
        raise SampleRefused(
            "Refusing: the private dev native upload helper is unavailable."
        ) from None
    native = SocketNativeRuntime(
        socket_path,
        workspace_root=intake.scratch.root,
        expected_image_ref=settings.sales_xray_native_image_ref,
    )

    async def require_actor(request: Request) -> AsyncIterator[AuthenticatedTransaction]:
        # This in-process adapter binds the request to an already active account
        # session selected by ID. It never creates or changes an identity session.
        async with sessions() as db, db.begin():
            yield AuthenticatedTransaction(db, None, actor, "dev-sample-local-actor")  # type: ignore[arg-type]

    require_actor.read_only = require_actor  # type: ignore[attr-defined]
    app = FastAPI(title="Fictional development sample runner", docs_url=None, redoc_url=None)
    register_problem_handlers(app)
    authority = intake.authority
    operations_tenant_id = authority.operations_tenant_id or settings.operations_tenant_id
    policy_revision = settings.sales_xray_acquisition_policy_revision
    if settings.public_learner_tenant_id is None or not policy_revision:
        raise SampleRefused("Refusing: the dev learner upload policy is not configured.")

    def factory(db: AsyncSession) -> AcquisitionSessions:
        return AcquisitionSessions(
            db,
            tenant_id=settings.public_learner_tenant_id,  # type: ignore[arg-type]
            policy_revision=policy_revision,
            tester_policy=authority.tester_policy,
            operations_tenant_id=operations_tenant_id,
        )

    install_submission_http(
        app,
        settings=settings,
        sessions=sessions,
        require_actor=require_actor,
        factory=factory,
        runtime=intake,
        preflight=NativeUploadPreflight(native),
    )
    return app, intake, native


async def _assert_sample_queue_scope(
    sessions: async_sessionmaker[AsyncSession], sample_ids: set[UUID], recording_ids: set[UUID]
) -> None:
    """Fail closed if a global worker could claim another account's queued work."""
    now = datetime.now(UTC)
    async with sessions() as db:
        known_recordings = set(
            (
                await db.scalars(
                    select(ConversationGuestSubmission.recording_id).where(
                        ConversationGuestSubmission.submission_id.in_(sample_ids)
                    )
                )
            ).all()
        )
        recording_ids.update(known_recordings)
        jobs = (
            await db.execute(
                select(Job.kind, Job.payload).where(
                    Job.kind.in_((_LOCAL_JOB, _DELETE_JOB, _INFERENCE_JOB)),
                    Job.status.in_(_ACTIVE_JOB_STATES),
                    Job.available_at <= now,
                )
            )
        ).all()
        for kind, payload in jobs:
            if kind == _LOCAL_JOB:
                allowed = payload.get("recording_id") in {str(value) for value in recording_ids}
            elif kind == _DELETE_JOB:
                allowed = False
            else:
                try:
                    run_id = UUID(str(payload["run_id"]))
                except (KeyError, TypeError, ValueError):
                    allowed = False
                else:
                    recording_id = await db.scalar(
                        select(ConversationInferenceTask.recording_id).where(
                            ConversationInferenceTask.run_id == run_id
                        )
                    )
                    allowed = recording_id in recording_ids
            if not allowed:
                raise SampleRefused(
                    "Refusing: another conversation job is queued; let its owner process it first."
                )
        due_plans = (
            await db.scalars(
                select(ConversationProcessingPlan.recording_id).where(
                    ConversationProcessingPlan.state == "active",
                    ConversationProcessingPlan.next_check_at <= now,
                    ConversationProcessingPlan.erased_at.is_(None),
                )
            )
        ).all()
        if any(recording_id not in recording_ids for recording_id in due_plans):
            raise SampleRefused(
                "Refusing: another processing plan is due; let its owner process it first."
            )


async def _settle_fictional_reservations(
    sessions: async_sessionmaker[AsyncSession],
    recording_ids: set[UUID],
) -> None:
    """Settle only completed reservations backed by this package's zero-use fake."""
    if not recording_ids:
        return
    async with sessions() as db, db.begin():
        tasks = (
            await db.scalars(
                select(ConversationInferenceTask)
                .where(ConversationInferenceTask.recording_id.in_(recording_ids))
                .order_by(ConversationInferenceTask.created_at)
                .with_for_update()
            )
        ).all()
        for task in tasks:
            if task.state != "completed":
                continue
            job = await db.get(Job, task.job_id)
            provider_receipt = None if job is None else job.provider_receipt
            usage = provider_receipt.get("usage") if isinstance(provider_receipt, Mapping) else None
            request_id = (
                provider_receipt.get("provider_request_id")
                if isinstance(provider_receipt, Mapping)
                else None
            )
            response_sha256 = (
                provider_receipt.get("response_sha256")
                if isinstance(provider_receipt, Mapping)
                else None
            )
            if (
                not isinstance(provider_receipt, Mapping)
                or not isinstance(request_id, str)
                or not request_id.startswith("fictional-sample-")
                or not isinstance(response_sha256, str)
                or len(response_sha256) != 64
                or provider_receipt.get("validation_state") != "validated"
                or not isinstance(usage, Mapping)
                or any(
                    type(usage.get(key)) is not int or usage[key] != 0
                    for key in (
                        "prompt_tokens",
                        "completion_tokens",
                        "total_tokens",
                        "input_tokens",
                        "output_tokens",
                        "cached_tokens",
                        "cache_write_tokens",
                        "reasoning_tokens",
                    )
                )
            ):
                raise SampleRefused(
                    "Refusing: a fictional provider result did not prove zero usage."
                )
            recording = await db.get(ConversationRecording, task.recording_id)
            quote_row = await db.get(ConversationQuote, task.quote_id)
            if recording is None or quote_row is None:
                raise SampleRefused("Refusing: a fictional provider reservation is unavailable.")
            minutes = await db.scalar(
                select(ConversationMinuteAccount)
                .where(
                    ConversationMinuteAccount.tenant_id == task.tenant_id,
                    ConversationMinuteAccount.person_id == task.person_id,
                )
                .with_for_update()
            )
            budget = await db.scalar(
                select(ConversationBudgetAccount)
                .where(ConversationBudgetAccount.scope_id == quote_row.budget_scope_id)
                .with_for_update()
            )
            if minutes is None or budget is None:
                raise SampleRefused("Refusing: a fictional provider ledger is unavailable.")
            minute_snapshot = MinuteAccount.from_dict(minutes.snapshot)
            budget_snapshot = BudgetAccount.from_dict(budget.snapshot)
            reservation = next(
                (
                    item
                    for item in minute_snapshot.reservations
                    if item.reservation_id == str(task.run_id)
                ),
                None,
            )
            if reservation is None:
                raise SampleRefused("Refusing: a fictional provider reservation is missing.")
            if reservation.state == "settled":
                if reservation.settlement is None or reservation.settlement.actual_paise != 0:
                    raise SampleRefused("Refusing: a fictional provider reservation was not free.")
                continue
            if reservation.state not in {"in_flight", "uncertain"} or not reservation.attempt_id:
                raise SampleRefused("Refusing: a fictional provider reservation is unresolved.")
            receipt = SettlementReceipt(
                reservation_id=str(task.run_id),
                quote_fingerprint=reservation.quote.fingerprint,
                provider_id=reservation.quote.provider_id,
                attempt_id=reservation.attempt_id,
                actual_seconds=0,
                actual_paise=0,
                receipt_ref=(f"fictional-no-network:{task.run_id}:{response_sha256}"),
            )
            transition = settle(
                minute_snapshot,
                budget_snapshot,
                str(task.run_id),
                receipt,
            )
            save_accounts(minutes, budget, transition)


def quote_within_budget(quote: Mapping[str, Any], budget_cap_paise: int) -> bool:
    """Permit the fake route's approved quote only within the current dev cap."""
    maximum = quote.get("max_cost_paise")
    return (
        type(budget_cap_paise) is int
        and budget_cap_paise >= 0
        and type(maximum) is int
        and 0 <= maximum <= budget_cap_paise
    )


async def seed_account_samples(
    client: httpx.AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    *,
    person_id: UUID,
    count: int,
    budget_cap_paise: int,
    settings: Settings,
    local_worker: object,
    inference_worker: object,
    scheduler: ProcessingPlanScheduler,
    publish_pending: Callable[[], Awaitable[None]] | None = None,
    wait_seconds: int = 240,
) -> tuple[UUID, ...]:
    """Drive real upload, plan, worker and read routes for the numbered labels."""
    base = "/v1/conversation/acquisition"
    origin = str(settings.sales_xray_app_url).rstrip("/")
    headers = {"Origin": origin}
    sample_ids: set[UUID] = set()
    recording_ids: set[UUID] = set()
    completed: list[UUID] = []

    async def request(method: str, path: str, **kwargs: Any) -> httpx.Response:
        response = await client.request(method, base + path, **kwargs)
        if response.status_code not in {200, 201, 202, 204}:
            raise SampleRefused(f"The Sales Xray route returned HTTP {response.status_code}.")
        return response

    async def library_rows() -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        cursor: str | None = None
        seen: set[str] = set()
        while True:
            params = {} if cursor is None else {"before": cursor}
            response = await client.get(base + "/submissions", params=params)
            if response.status_code != 200:
                raise SampleRefused(
                    f"The account library route returned HTTP {response.status_code}."
                )
            page = response.json()
            rows.extend(page["submissions"])
            cursor = page.get("next_cursor")
            if cursor is None:
                return rows
            if cursor in seen:
                raise SampleRefused("The account library cursor did not advance.")
            seen.add(cursor)

    by_label = {item["display_name"]: item for item in await library_rows()}

    for number in range(1, count + 1):
        label = f"Sample call {number} · fictional"
        current = by_label.get(label)
        if current and current.get("state") == "report_ready" and current.get("has_report"):
            submission_id = UUID(str(current["submission_id"]))
            completed.append(submission_id)
            print(f"Skipping existing {label}.")
            continue
        submission_id = (
            UUID(str(current["submission_id"]))
            if current
            else uuid5(_SAMPLE_NAMESPACE, f"{person_id}:{number}")
        )
        sample_ids.add(submission_id)
        audio = fictional_audio(number)
        policy_response = await request("GET", "/upload-policy")
        policy = policy_response.json()
        await request(
            "PUT",
            f"/submissions/{submission_id}/source",
            content=_ChunkedAudio(audio),
            headers={
                **headers,
                "Content-Type": "application/octet-stream",
                "Content-Length": str(len(audio)),
                "X-Source-SHA256": hashlib.sha256(audio).hexdigest(),
                "X-Upload-Policy": policy["policy_sha256"],
                "X-Upload-Consent": "accepted",
            },
        )
        detail = await request("GET", f"/submissions/{submission_id}")
        detail_json = detail.json()
        revision = detail_json["display_name_revision"]
        if detail_json.get("display_name") != label:
            await request(
                "PATCH",
                f"/submissions/{submission_id}/label",
                json={"display_name": label},
                headers={**headers, "If-Match": f'"call-label-{revision}"'},
            )
        async with sessions() as db:
            recording_id = await db.scalar(
                select(ConversationGuestSubmission.recording_id).where(
                    ConversationGuestSubmission.submission_id == submission_id
                )
            )
        if recording_id is not None:
            recording_ids.add(recording_id)
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            await _assert_sample_queue_scope(sessions, sample_ids, recording_ids)
            if publish_pending is not None:
                await publish_pending()
            await _assert_sample_queue_scope(sessions, sample_ids, recording_ids)
            await local_worker.run_once()  # type: ignore[attr-defined]
            detail = (await request("GET", f"/submissions/{submission_id}")).json()
            if detail.get("local_state") == "completed":
                break
            await asyncio.sleep(0.25)
        else:
            raise SampleRefused("The synthetic upload did not pass the local worker in time.")

        quote_key = f"sample-plan-{submission_id.hex}"
        quote = (
            await request(
                "POST",
                f"/submissions/{submission_id}/plan/quote",
                headers={**headers, "Idempotency-Key": quote_key},
            )
        ).json()
        if not quote_within_budget(quote, budget_cap_paise):
            raise SampleRefused("Refusing: the dev report quote exceeds the approved budget cap.")
        approval = {
            "plan_id": quote["id"],
            "plan_fingerprint": quote["plan_fingerprint"],
            "privacy_revision": quote["privacy_revision"],
            "accepted": True,
        }
        await request(
            "POST",
            f"/submissions/{submission_id}/plan",
            json=approval,
            headers={**headers, "Idempotency-Key": f"sample-accept-{submission_id.hex}"},
        )

        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            await _assert_sample_queue_scope(sessions, sample_ids, recording_ids)
            if publish_pending is not None:
                await publish_pending()
            await _assert_sample_queue_scope(sessions, sample_ids, recording_ids)
            await inference_worker.run_once()  # type: ignore[attr-defined]
            await _settle_fictional_reservations(sessions, recording_ids)
            if publish_pending is not None:
                await publish_pending()
            await _assert_sample_queue_scope(sessions, sample_ids, recording_ids)
            await scheduler.step()
            detail = (await request("GET", f"/submissions/{submission_id}")).json()
            if detail.get("state") == "report_ready" and detail.get("has_report"):
                for suffix in ("", "/report", "/transcript"):
                    await request("GET", f"/submissions/{submission_id}{suffix}")
                completed.append(submission_id)
                break
            await asyncio.sleep(0.25)
        else:
            raise SampleRefused("The sample call did not reach report_ready before the time limit.")
    final = await library_rows()
    ready = {
        UUID(str(item["submission_id"]))
        for item in final
        if item.get("state") == "report_ready" and item.get("has_report")
    }
    if not set(completed).issubset(ready):
        raise SampleRefused("The completed sample calls are not visible in the account library.")
    return tuple(completed)


async def _run(settings: Settings, email: str, count: int) -> tuple[UUID, ...]:
    engine = create_async_engine(settings.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        actor = await _read_account_actor(sessions, settings, email)
        app, intake, native = _install_sample_routes(settings, sessions, actor)
        if intake.authority is None:
            raise SampleRefused("Refusing: hosted dev report authority is unavailable.")
        bundle = intake.authority.current(datetime.now(UTC))
        router = build_fake_router(bundle, intake.authority)
        local = HostedConversationWorker(
            sessions,
            storage=intake.storage,
            scratch=intake.scratch,
            environment="development",
            native_runtime=native,
        )
        inference = ConversationInferenceWorker(
            sessions, intake.storage, router, authority=intake.authority
        )
        scheduler = ProcessingPlanScheduler(sessions, intake.authority, intake.storage)
        token = secrets.token_urlsafe(48)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url=_APP_ORIGIN,
            cookies={settings.session_cookie_name: token},
        ) as client:
            return await seed_account_samples(
                client,
                sessions,
                person_id=actor.actor.person_id,
                count=count,
                budget_cap_paise=bundle.budget_cap_paise,
                settings=settings,
                local_worker=local,
                inference_worker=inference,
                scheduler=scheduler,
            )
    finally:
        await engine.dispose()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Seed fictional development calls. Reports are test fixtures, not an official score."
        )
    )
    parser.add_argument(
        "--email", required=True, help="Email for an existing signed-in dev account"
    )
    parser.add_argument("--count", type=int, choices=(1, 2, 3), default=3)
    parser.add_argument(
        "--acknowledge-dev-samples",
        action="store_true",
        help="Confirm that this command writes fictional sample calls into development.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        require_sample_target(os.environ, acknowledged=args.acknowledge_dev_samples)
        settings = Settings(_env_file=None)
        result = asyncio.run(_run(settings, args.email, args.count))
    except SampleRefused as error:
        print(str(error), file=sys.stderr)
        return 2
    except Exception as error:
        print(
            f"Sample call creation failed ({type(error).__name__}). No provider API was contacted.",
            file=sys.stderr,
        )
        return 1
    print(f"Ready: {len(result)} fictional sample calls. No official score was produced.")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by module entrypoint
    raise SystemExit(main())
