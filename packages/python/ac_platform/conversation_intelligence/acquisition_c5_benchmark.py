"""Exact owner-bound acquisition C5 benchmark helpers.

The benchmark is a separate, immutable coaching run. It never changes the
ordinary acquisition route and never supplies prompt content from the owner.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select

from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionUsage,
    ConversationVisitorClaim,
)
from ac_platform.conversation_intelligence.activation_contract import (
    AcquisitionC5BenchmarkApproval,
    HostedApprovalBundle,
    StageApproval,
)
from ac_platform.conversation_intelligence.analysis_settings import (
    AnalysisSettings,
    settings_from_row,
)
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationConflict,
    ConversationDenied,
)
from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.entitlements import Quote
from ac_platform.conversation_intelligence.guest_models import (
    ConversationGuestSubmission,
    ConversationProcessingLease,
    ConversationProcessingPrincipal,
)
from ac_platform.conversation_intelligence.inference import ConversationInference
from ac_platform.conversation_intelligence.models import (
    ConversationAnalysisSettings,
    ConversationCheckpoint,
    ConversationCommand,
    ConversationQuote,
    ConversationRecording,
)
from ac_platform.conversation_intelligence.processing_actor import (
    ConversationActor,
    ProcessingActor,
)
from ac_platform.conversation_intelligence.qualitative_pack import (
    load_qualitative_pack_for_revision,
)
from ac_platform.conversation_intelligence.report_overview import stage_completion_limit
from ac_platform.conversation_intelligence.reporting_pipeline import (
    FACT_RECIPE,
    ReportingPipeline,
    StageRequest,
)
from ac_platform.conversation_intelligence.reports import FactPacket, load_report_profile
from ac_platform.identity.models import Person
from ac_platform.tenancy.models import Membership


def benchmark_by_id(
    bundle: HostedApprovalBundle, identifier: UUID
) -> AcquisitionC5BenchmarkApproval:
    values = tuple(item for item in bundle.acquisition_c5_benchmarks if item.id == identifier)
    if len(values) != 1:
        raise ConversationDenied("This exact acquisition benchmark is not approved.")
    return values[0]


def benchmark_for_submission(
    bundle: HostedApprovalBundle,
    *,
    tenant_id: UUID,
    owner_person_id: UUID,
    submission_id: UUID,
    recording_id: UUID,
    processing_person_id: UUID,
    processing_lease_id: UUID,
    usage_id: UUID,
    source_sha256: str,
) -> AcquisitionC5BenchmarkApproval:
    values = tuple(
        item
        for item in bundle.acquisition_c5_benchmarks
        if (
            item.tenant_id,
            item.owner_person_id,
            item.submission_id,
            item.recording_id,
            item.processing_person_id,
            item.processing_lease_id,
            item.usage_id,
            item.source_sha256,
        )
        == (
            tenant_id,
            owner_person_id,
            submission_id,
            recording_id,
            processing_person_id,
            processing_lease_id,
            usage_id,
            source_sha256,
        )
    )
    if len(values) != 1:
        raise ConversationDenied("This exact acquisition benchmark is not approved.")
    return values[0]


def stage_approval_for_benchmark(
    bundle: HostedApprovalBundle,
    benchmark: AcquisitionC5BenchmarkApproval,
) -> StageApproval:
    values = tuple(item for item in bundle.stages if item.id == benchmark.stage_approval_id)
    if len(values) != 1:
        raise ConversationDenied("This exact acquisition benchmark route is unavailable.")
    return values[0]


async def validate_benchmark_scope(
    app: ConversationApplication,
    actor: ConversationActor,
    recording: ConversationRecording,
    bundle: HostedApprovalBundle,
    benchmark: AcquisitionC5BenchmarkApproval,
    now: datetime,
    *,
    require_owner_quote: bool = False,
    quote: ConversationQuote | None = None,
    require_owner_acceptance: bool = False,
) -> StageApproval:
    """Recheck exact owner, source, lease, settings, route and owner consent."""

    if not isinstance(actor, ProcessingActor):
        raise ConversationDenied("The acquisition benchmark requires its processing lease.")
    if not benchmark.issued_at_epoch <= int(now.timestamp()) < benchmark.expires_at_epoch:
        raise ConversationDenied("This acquisition benchmark authorization has expired.")
    if (
        bundle.environment not in {"staging", "test"}
        or bundle.expires_at_epoch <= int(now.timestamp())
        or benchmark.tenant_id != actor.tenant_id
        or benchmark.processing_person_id != actor.person_id
        or benchmark.processing_lease_id != actor.processing_lease_id
        or benchmark.tenant_id != recording.tenant_id
        or benchmark.recording_id != recording.id
        or benchmark.source_sha256 != recording.source_sha256
        or benchmark.source_revision != recording.source_revision
        or benchmark.generation != recording.generation
        or recording.state != "ready"
    ):
        raise ConversationDenied("The recording no longer matches its benchmark approval.")

    stage = stage_approval_for_benchmark(bundle, benchmark)
    if (
        stage.tenant_id != actor.tenant_id
        or stage.person_id != actor.person_id
        or stage.source_sha256 != recording.source_sha256
        or stage.stage != "C5"
        or stage.provider_id != "openai"
        or stage.model_id != "gpt-6-luna"
        or stage.configuration_sha256 != benchmark.configuration_sha256
        or stage.max_requests != 1
        or stage.max_cost_paise != benchmark.max_cost_paise
        or stage.max_completion_tokens != benchmark.max_completion_tokens
        or stage.profile_sha256 != benchmark.profile_sha256
        or stage.expires_at_epoch < benchmark.expires_at_epoch
    ):
        raise ConversationDenied("The current C5 route differs from its benchmark approval.")

    link = await app.database.get(
        ConversationGuestSubmission, (benchmark.tenant_id, benchmark.submission_id)
    )
    usage = await app.database.get(ConversationAcquisitionUsage, benchmark.usage_id)
    lease = await app.database.get(ConversationProcessingLease, benchmark.processing_lease_id)
    principal = (
        None
        if lease is None
        else await app.database.get(ConversationProcessingPrincipal, lease.principal_id)
    )
    claim = (
        None
        if usage is None or usage.visitor_id is None
        else await app.database.get(ConversationVisitorClaim, usage.visitor_id)
    )
    current_owner = (
        usage.person_id
        if usage is not None and usage.visitor_id is None
        else claim.person_id
        if claim is not None
        else None
    )
    owner = await app.database.get(Person, benchmark.owner_person_id)
    membership = await app.database.get(
        Membership, (benchmark.tenant_id, benchmark.owner_person_id)
    )
    if (
        link is None
        or usage is None
        or lease is None
        or principal is None
        or link.tenant_id != benchmark.tenant_id
        or link.submission_id != benchmark.submission_id
        or link.recording_id != recording.id
        or link.person_id != actor.person_id
        or link.processing_lease_id != actor.processing_lease_id
        or link.usage_id != benchmark.usage_id
        or link.source_sha256 != recording.source_sha256
        or usage.tenant_id != benchmark.tenant_id
        or usage.submission_id != benchmark.submission_id
        or usage.source_sha256 != recording.source_sha256
        or usage.visitor_id is not None
        and claim is None
        or current_owner != benchmark.owner_person_id
        or lease.tenant_id != actor.tenant_id
        or lease.person_id != actor.person_id
        or lease.usage_id != benchmark.usage_id
        or lease.revoked_at is not None
        or principal.tenant_id != actor.tenant_id
        or principal.person_id != actor.person_id
        or principal.revoked_at is not None
        or owner is None
        or owner.status != "active"
        or owner.email_verified_at is None
        or membership is None
        or membership.status != "active"
        or membership.ended_at is not None
        or membership.role == "processing"
    ):
        raise ConversationDenied("The acquisition owner or processing source is unavailable.")

    settings_row = await app.database.scalar(
        select(ConversationAnalysisSettings).where(
            ConversationAnalysisSettings.tenant_id == bundle.provider_control_tenant_id,
            ConversationAnalysisSettings.revision == benchmark.analysis_settings_revision,
        )
    )
    settings = settings_from_row(settings_row)
    if (
        settings_row is None
        or content_hash(settings.effective_values()) != benchmark.analysis_settings_sha256
        or settings.c5_coaching_prompt_revision != benchmark.coaching_prompt_revision
        or settings.report_language_default != benchmark.report_language
        or settings.c5_output_profile != benchmark.output_profile
        or settings.c5_max_completion_tokens < benchmark.max_completion_tokens
    ):
        raise ConversationDenied("The saved C5 coaching profile no longer matches approval.")
    profile = load_report_profile()
    if content_hash(profile) != benchmark.profile_sha256:
        raise ConversationDenied("The approved coaching profile is unavailable.")

    if require_owner_quote or require_owner_acceptance:
        if quote is None:
            raise ConversationDenied("The owner-approved benchmark quote is unavailable.")
        fingerprint = Quote.from_dict(quote.quote).fingerprint
        common: dict[str, object] = {
            "purpose": "acquisition_c5_benchmark",
            "benchmark_approval_id": str(benchmark.id),
            "submission_id": str(benchmark.submission_id),
            "recording_id": str(recording.id),
            "processing_lease_id": str(actor.processing_lease_id),
            "quote_id": str(quote.id),
        }
        expected = [
            (
                "acquisition_c5_benchmark_quote_issued",
                f"acquisition-c5-benchmark-quote:{quote.id}",
                {**common, "quote_fingerprint": fingerprint},
            )
        ]
        if require_owner_acceptance:
            expected.append(
                (
                    "acquisition_c5_benchmark_accepted",
                    f"acquisition-c5-benchmark-accepted:{quote.id}",
                    {
                        **common,
                        "quote_fingerprint": fingerprint,
                        "accepted": True,
                    },
                )
            )
        for action, key, intent in expected:
            command = await app.database.scalar(
                select(ConversationCommand).where(
                    ConversationCommand.tenant_id == benchmark.tenant_id,
                    ConversationCommand.person_id == benchmark.owner_person_id,
                    ConversationCommand.key == key,
                )
            )
            if (
                command is None
                or command.action != action
                or command.result_id != quote.id
                or command.intent_sha256 != content_hash(intent)
            ):
                raise ConversationDenied("The exact owner-approved C5 benchmark is required.")
    return stage


async def record_owner_benchmark_receipt(
    app: ConversationApplication,
    owner: ConversationActor,
    actor: ProcessingActor,
    recording: ConversationRecording,
    benchmark: AcquisitionC5BenchmarkApproval,
    quote_id: UUID,
    quote_fingerprint: str,
    now: datetime,
    *,
    accepted: bool,
) -> None:
    """Append the real account owner's quote or explicit acceptance receipt."""

    if owner.tenant_id != benchmark.tenant_id or owner.person_id != benchmark.owner_person_id:
        raise ConversationDenied("The account owner does not match the benchmark approval.")
    common = {
        "purpose": "acquisition_c5_benchmark",
        "benchmark_approval_id": str(benchmark.id),
        "submission_id": str(benchmark.submission_id),
        "recording_id": str(recording.id),
        "processing_lease_id": str(actor.processing_lease_id),
        "quote_id": str(quote_id),
        "quote_fingerprint": quote_fingerprint,
    }
    action = (
        "acquisition_c5_benchmark_accepted" if accepted else "acquisition_c5_benchmark_quote_issued"
    )
    key = (
        f"acquisition-c5-benchmark-accepted:{quote_id}"
        if accepted
        else f"acquisition-c5-benchmark-quote:{quote_id}"
    )
    intent = {**common, **({"accepted": True} if accepted else {})}
    existing = await app._replay(owner, key, action, intent)
    if existing is None:
        await app._receipt(
            owner,
            key,
            action,
            intent,
            quote_id,
            now,
            resource_type="conversation_c5_benchmark",
        )
    elif existing.result_id != quote_id:
        raise ConversationDenied("The benchmark quote receipt no longer matches.")


async def build_benchmark_request(
    app: ConversationApplication,
    actor: ProcessingActor,
    bundle: HostedApprovalBundle,
    benchmark: AcquisitionC5BenchmarkApproval,
    recording: ConversationRecording,
) -> StageRequest:
    """Select only the verified retained C2/C4 checkpoints for this source."""

    stage = stage_approval_for_benchmark(bundle, benchmark)
    if stage.profile_sha256 != benchmark.profile_sha256:
        raise ConversationDenied("The approved C5 profile differs from this source.")
    settings_row = await app.database.scalar(
        select(ConversationAnalysisSettings).where(
            ConversationAnalysisSettings.tenant_id == bundle.provider_control_tenant_id,
            ConversationAnalysisSettings.revision == benchmark.analysis_settings_revision,
        )
    )
    settings: AnalysisSettings = settings_from_row(settings_row)
    if (
        settings_row is None
        or content_hash(settings.effective_values()) != benchmark.analysis_settings_sha256
        or settings.c5_coaching_prompt_revision != benchmark.coaching_prompt_revision
        or settings.report_language_default != benchmark.report_language
        or settings.c5_output_profile != benchmark.output_profile
        or settings.c5_max_completion_tokens < benchmark.max_completion_tokens
    ):
        raise ConversationDenied("The saved C5 coaching profile no longer matches approval.")

    profile = load_report_profile()
    if content_hash(profile) != benchmark.profile_sha256:
        raise ConversationDenied("The approved coaching profile is unavailable.")
    inference = ConversationInference(app)
    pipeline = ReportingPipeline(inference)

    transcript_rows = (
        await app.database.scalars(
            select(ConversationCheckpoint).where(
                ConversationCheckpoint.tenant_id == actor.tenant_id,
                ConversationCheckpoint.person_id == actor.person_id,
                ConversationCheckpoint.recording_id == recording.id,
                ConversationCheckpoint.stage == "C2",
                ConversationCheckpoint.erased_at.is_(None),
            )
        )
    ).all()
    valid_transcripts: list[ConversationCheckpoint] = []
    for row in transcript_rows:
        try:
            await pipeline.provider_task(recording, row)
            valid_transcripts.append(row)
        except ConversationConflict:
            continue
    if len(valid_transcripts) != 1:
        raise ConversationConflict("A single verified retained transcript is required.")
    transcript_row = valid_transcripts[0]
    _, transcript = await pipeline.checkpoint(recording, transcript_row.id, "C2")

    fact_rows = (
        await app.database.scalars(
            select(ConversationCheckpoint).where(
                ConversationCheckpoint.tenant_id == actor.tenant_id,
                ConversationCheckpoint.person_id == actor.person_id,
                ConversationCheckpoint.recording_id == recording.id,
                ConversationCheckpoint.stage == "C4",
                ConversationCheckpoint.erased_at.is_(None),
            )
        )
    ).all()
    packets: list[tuple[FactPacket, ConversationCheckpoint]] = []
    for row in fact_rows:
        try:
            _, checkpoint = await pipeline.checkpoint(recording, row.id, "C4")
            if (
                checkpoint.revision != FACT_RECIPE
                or dict(checkpoint.parents).get("C2") != transcript.manifest_sha256
            ):
                continue
            await pipeline.provider_task(recording, row)
            if not isinstance(row.payload, dict):
                continue
            packets.append((FactPacket.model_validate(row.payload), row))
        except (ConversationConflict, ValueError, TypeError):
            continue
    packets.sort(key=lambda item: item[0].chunk_index)
    if not packets:
        raise ConversationConflict("Completed fact checkpoints for this transcript are required.")
    expected_count = packets[0][0].chunk_count
    if (
        type(expected_count) is not int
        or not 1 <= expected_count <= 64
        or len(packets) != expected_count
        or [item.chunk_index for item, _ in packets] != list(range(1, expected_count + 1))
        or any(item.chunk_count != expected_count for item, _ in packets)
    ):
        raise ConversationConflict("Complete, unambiguous fact checkpoints are required.")

    qualitative_pack_sha256 = load_qualitative_pack_for_revision(
        benchmark.coaching_prompt_revision
    ).sha256
    return StageRequest(
        stage="C5",
        transcript_checkpoint_id=transcript_row.id,
        fact_checkpoint_ids=tuple(row.id for _, row in packets),
        provider=stage.provider_id,
        model=stage.model_id,
        max_input_chars=16_000,
        max_completion_tokens=stage_completion_limit(
            "C5",
            min(stage.max_completion_tokens, benchmark.max_completion_tokens),
            provider=stage.provider_id,
            model=stage.model_id,
        ),
        coaching_prompt_revision=benchmark.coaching_prompt_revision,
        report_language=benchmark.report_language,
        qualitative_pack_sha256=qualitative_pack_sha256,
        output_profile=benchmark.output_profile,
        profile=profile,
        acquisition_c5_benchmark_approval_id=benchmark.id,
    )


__all__ = [
    "benchmark_by_id",
    "benchmark_for_submission",
    "build_benchmark_request",
    "record_owner_benchmark_receipt",
    "stage_approval_for_benchmark",
    "validate_benchmark_scope",
]
