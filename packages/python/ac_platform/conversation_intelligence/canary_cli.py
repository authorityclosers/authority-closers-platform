"""Run one fictional guest canary through durable intake and provider processing."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
from importlib import resources
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.application.asyncio_runtime import run_async
from ac_platform.application.release_identity import require_baked_release_id
from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.acquisition_processing import (
    AcquisitionProcessing,
    upload_policy,
)
from ac_platform.conversation_intelligence.acquisition_reports import AcquisitionReports
from ac_platform.conversation_intelligence.acquisition_sessions import AcquisitionSessions
from ac_platform.conversation_intelligence.acquisition_source import (
    MeasuredUpload,
    NativeUploadPreflight,
)
from ac_platform.conversation_intelligence.application import ConversationError
from ac_platform.conversation_intelligence.canary import mark_canary_submission
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.conversation_intelligence.hosted_runtime import (
    compose_hosted_intake,
    load_pinned_approval,
)
from ac_platform.conversation_intelligence.intake import KEEP_FOR_TRAINING_RETENTION_PREFIX
from ac_platform.conversation_intelligence.models import ConversationCheckpoint
from ac_platform.conversation_intelligence.native_runtime import SocketNativeRuntime
from ac_platform.conversation_intelligence.processing_cli import (
    CommandError,
    _Parser,
    validate_environment,
)
from ac_platform.conversation_intelligence.processing_plan import (
    ConversationProcessingPlans,
    PlanAcceptance,
)
from ac_platform.conversation_intelligence.report_overview import DetailedOverview
from ac_platform.conversation_intelligence.worker import _FencedExecutor
from ac_platform.http.conversation_intake import ConversationIntakeRuntime

FIXTURE_SHA256 = "78cb1194e987db6b8d06d0aa2a4d2e66d21bbdf0c3de6960e4e26da36ed207af"


def ownership(db: AsyncSession, settings: Settings) -> GuestOwnership:
    if settings.public_learner_tenant_id is None:
        raise CommandError("The public learner workspace is required.")
    return GuestOwnership(
        AcquisitionSessions(
            db,
            tenant_id=settings.public_learner_tenant_id,
            policy_revision=settings.sales_xray_acquisition_policy_revision or "canary-v1",
            operations_tenant_id=settings.operations_tenant_id,
        )
    )


async def submit(
    owner: GuestOwnership,
    runtime: ConversationIntakeRuntime,
    upload: MeasuredUpload,
    path: Path,
    environment: str,
) -> str:
    """Caller owns the transaction containing visitor, reservation, marker and job."""
    guest = await owner.sessions.issue()
    service = AcquisitionProcessing(owner, runtime)
    actor, quote = await service.prepare(
        upload,
        policy_sha256=upload_policy(runtime.policy)["policy_sha256"],
        token=guest.token,
    )
    await mark_canary_submission(
        owner.database,
        tenant_id=actor.tenant_id,
        submission_id=upload.source.submission_id,
        environment=environment,
        fixture_sha256=upload.source.source_sha256,
        created_at=owner.clock(),
    )
    with path.open("rb") as source:
        await service.application.store_source(
            actor,
            UUID(quote["recording_id"]),
            chunks=iter(lambda: source.read(65536), b""),
            storage=runtime.storage,
        )
    await service.enqueue(actor, quote)
    return guest.token


async def poll(
    sessions: async_sessionmaker[AsyncSession],
    settings: Settings,
    runtime: ConversationIntakeRuntime,
    submission_id: UUID,
    token: str,
    result: dict[str, Any],
) -> None:
    accepted = False
    last = time.monotonic()
    while True:
        async with sessions() as db, db.begin():
            owner = ownership(db, settings)
            reports = AcquisitionReports(owner)
            progress = await reports.progress(submission_id, token=token)
            checkpoints = (
                await db.scalars(
                    select(ConversationCheckpoint).where(
                        ConversationCheckpoint.tenant_id == owner.sessions.tenant_id,
                        ConversationCheckpoint.recording_id == UUID(progress["recording_id"]),
                        ConversationCheckpoint.erased_at.is_(None),
                    )
                )
            ).all()
            stages = [row.stage for row in checkpoints] + [s["stage"] for s in progress["stages"]]
            result["stage_reached"] = max(["C1", *stages])
            now = time.monotonic()
            stage = result["stage_reached"]
            durations = result["seconds_per_stage"]
            durations[stage] = durations.get(stage, 0.0) + now - last
            last = now
            if progress["has_report"]:
                result["report_present"] = True
                report = await reports.report(submission_id, token=token)
                try:
                    DetailedOverview.model_validate(report["report"]["content"].get("overview"))
                except ValueError:
                    result["failure_code"] = "report_contract_invalid"
                    return
                result.update(ok=True, stage_reached="C6")
                return
            if (
                progress["local_state"] in {"failed", "cancelled"}
                or progress["state"] in {"failed", "held", "cancelled"}
                or progress["execution_hold"]
                or any(s["state"] in {"failed", "uncertain"} for s in progress["stages"])
            ):
                result["failure_code"] = progress["failure_code"] or "stage_failed"
                return
            if progress["local_state"] == "completed" and not accepted:
                actor = await owner.resolve_processing_actor(submission_id, token=token)
                if runtime.authority is None:
                    raise CommandError("The approved processing authority is required.")
                plans = ConversationProcessingPlans(
                    reports.application, runtime.authority, runtime.storage
                )
                recording_id = UUID(progress["recording_id"])
                quote = await plans.quote(actor, recording_id, key=f"canary-quote:{submission_id}")
                result["cost_paise"] = quote["max_cost_paise"]
                if result["cost_paise"] > 500:
                    result["failure_code"] = "canary_quote_over_cap"
                    return
                await plans.accept(
                    actor,
                    recording_id,
                    PlanAcceptance(
                        plan_id=UUID(quote["id"]),
                        plan_fingerprint=quote["plan_fingerprint"],
                        privacy_revision=quote["privacy_revision"],
                        accepted=True,
                    ),
                    key=f"canary-accept:{submission_id}",
                )
                accepted = True
        await asyncio.sleep(1)


async def canary(args: argparse.Namespace) -> dict[str, Any]:
    started = time.monotonic()
    environment = validate_environment(args)
    if os.getenv("AC_ENVIRONMENT", "").strip().lower() != environment:
        raise CommandError("An explicit matching AC_ENVIRONMENT is required.")
    if not 1 <= args.timeout_seconds <= 1800:
        raise CommandError("Timeout must be between 1 and 1800 seconds.")
    settings = Settings(environment=environment)
    if environment in {"staging", "production"}:
        require_baked_release_id(settings.release_id)
    result: dict[str, Any] = dict(
        ok=False,
        environment=environment,
        stage_reached="disabled",
        failure_code=None,
        seconds_per_stage={},
        total_seconds=0.0,
        cost_paise=0,
        report_present=False,
    )
    try:
        bundle = load_pinned_approval(settings)
    except ValueError:
        bundle = None
    if (
        bundle is None
        or bundle.acquisition_policy is None
        or not settings.sales_xray_enabled
        or not settings.sales_xray_acquisition_enabled
    ):
        result.update(
            failure_code="analysis_disabled_by_owner", total_seconds=time.monotonic() - started
        )
        return result
    runtime = compose_hosted_intake(settings)
    if (
        runtime is None
        or runtime.policy.retention_days > 7
        or runtime.policy.retention_ref.startswith(KEEP_FOR_TRAINING_RETENTION_PREFIX)
    ):
        raise CommandError("Canary requires the approved standard retention policy.")
    native = SocketNativeRuntime(
        Path(settings.sales_xray_native_socket_path or ""),
        workspace_root=runtime.scratch.root,
        expected_image_ref=settings.sales_xray_native_image_ref or "",
        timeout_seconds=min(args.timeout_seconds, 180),
    )
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        try:
            async with asyncio.timeout(args.timeout_seconds):
                sessions = async_sessionmaker(engine, expire_on_commit=False)
                submission_id = uuid4()
                result["stage_reached"] = "C1"
                async with _FencedExecutor(runtime.storage.root) as fenced:
                    with tempfile.TemporaryDirectory(
                        prefix="work-", dir=runtime.scratch.root
                    ) as work:
                        path = Path(work) / "source.wav"
                        fixture = resources.files("ac_platform.conversation_intelligence").joinpath(
                            "canary_fixture/sales_call_v1.wav"
                        )
                        path.write_bytes(fixture.read_bytes())
                        upload = await fenced.run(
                            NativeUploadPreflight(native).measure,
                            path,
                            submission_id,
                            FIXTURE_SHA256,
                        )
                        async with sessions() as db, db.begin():
                            token = await submit(
                                ownership(db, settings), runtime, upload, path, environment
                            )
                await poll(sessions, settings, runtime, submission_id, token, result)
        finally:
            await engine.dispose()
    except TimeoutError:
        result.update(ok=False, failure_code="timeout")
    except ConversationError:
        result.update(ok=False, failure_code="canary_failed")
    except (ValueError, OSError, SQLAlchemyError):
        raise
    except Exception:
        result.update(ok=False, failure_code="canary_failed")
    result["total_seconds"] = time.monotonic() - started
    return result


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(description=__doc__, allow_abbrev=False)
    parser.add_argument(
        "--environment", required=True, choices=("development", "staging", "production")
    )
    parser.add_argument("--allow-production", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=900)
    try:
        result = run_async(canary(parser.parse_args(argv)))
    except (ValueError, OSError, SQLAlchemyError):
        print("Canary refused; check arguments, configuration and database state.", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0 if result["ok"] or result["stage_reached"] == "disabled" else 1


if __name__ == "__main__":
    raise SystemExit(main())
