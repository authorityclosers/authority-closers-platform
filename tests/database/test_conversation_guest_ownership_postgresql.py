"""Disposable PostgreSQL proof for guest processing ownership and lease fencing."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, inspect, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.audit.models import AuditEvent
from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionUsage,
    ConversationVisitorClaim,
)
from ac_platform.conversation_intelligence.acquisition_sessions import (
    AcquisitionSessions,
    MeasuredSource,
)
from ac_platform.conversation_intelligence.acquisition_usage import acquisition_seconds
from ac_platform.conversation_intelligence.activation_contract import (
    AcquisitionProviderPolicy,
    AcquisitionStagePolicy,
)
from ac_platform.conversation_intelligence.application import (
    DELETE_JOB,
    LOCAL_JOB,
    ConversationApplication,
    ConversationDenied,
    ConversationNotFound,
)
from ac_platform.conversation_intelligence.authority import ConversationAuthority
from ac_platform.conversation_intelligence.contracts import QuoteAcceptance, RunIntent
from ac_platform.conversation_intelligence.entitlements import BudgetAccount, MinuteAccount
from ac_platform.conversation_intelligence.guest_models import (
    ConversationGuestSubmission,
    ConversationProcessingLease,
    ConversationProcessingPrincipal,
)
from ac_platform.conversation_intelligence.guest_ownership import (
    GuestOwnership,
    admit_processing_actor,
)
from ac_platform.conversation_intelligence.intake import ConversationIntake, IntakePolicy
from ac_platform.conversation_intelligence.models import (
    ConversationBudgetAccount,
    ConversationCheckpoint,
    ConversationCommand,
    ConversationMinuteAccount,
    ConversationPermission,
    ConversationQuoteAcceptance,
    ConversationRecording,
    ConversationRun,
)
from ac_platform.conversation_intelligence.processing_actor import ProcessingActor
from ac_platform.conversation_intelligence.storage import PrivateLocalRecordingStorage
from ac_platform.identity.models import PasswordCredential, ProviderIdentity
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.outbox.models import Job
from ac_platform.tenancy.models import Membership
from tests.database.test_conversation_authority_postgresql import _bundle as authority_bundle
from tests.database.test_conversation_intake_postgresql import make_intent, policy
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed, seed_budget
from tests.database.test_conversation_worker_postgresql import (
    OfflineConversationWorker,
    _reconcile,
    _wav_one_second_48k,
)


@pytest.fixture(scope="module")
def postgres_harness():
    yield from _postgres_harness.__wrapped__()


async def _provision(engine: Any, state: Any) -> UUID:
    async with AsyncSession(engine) as database, database.begin():
        sessions = AcquisitionSessions(
            database,
            tenant_id=state.tenant_id,
            policy_revision="guest-processing-v1",
            clock=lambda: state.now,
        )
        principal_id = await GuestOwnership(sessions).provision(
            operator_reference="operator:guest-test",
            reason="Disposable PostgreSQL guest ownership proof",
        )
        principal = await database.get(ConversationProcessingPrincipal, principal_id)
        assert principal is not None
        # Provisioning creates the canonical empty ledger with no grants. Guest
        # acquisition usage remains the sole source of user-minute ownership.
        minute = await database.get(
            ConversationMinuteAccount, (state.tenant_id, principal.person_id)
        )
        assert minute is not None
        assert MinuteAccount.from_dict(minute.snapshot).available_seconds == 0
        return principal.person_id


async def _guest(
    engine: Any,
    state: Any,
    *,
    duration_seconds: int,
    marker: str,
    source_bytes: bytes | None = None,
):
    source_bytes = source_bytes or f"guest-source-{marker}".encode()
    intent = make_intent(source_bytes).model_copy(update={"duration_ms": duration_seconds * 1000})
    measured = MeasuredSource(
        uuid4(),
        intent.source_sha256,
        duration_seconds * 1000,
        hashlib.sha256((marker + "-duration").encode()).hexdigest(),
    )
    async with AsyncSession(engine) as database, database.begin():
        sessions = AcquisitionSessions(
            database,
            tenant_id=state.tenant_id,
            policy_revision="guest-processing-v1",
            clock=lambda: state.now,
        )
        credential = await sessions.issue()
        usage_id = await sessions.reserve(measured, token=credential.token)
    return credential, measured, intent, usage_id


async def _processing_actor(
    engine: Any,
    state: Any,
    submission_id: UUID,
    token: str,
    *,
    lifetime: timedelta = timedelta(hours=1),
):
    async with AsyncSession(engine) as database, database.begin():
        sessions = AcquisitionSessions(
            database,
            tenant_id=state.tenant_id,
            policy_revision="guest-processing-v1",
            clock=lambda: state.now,
        )
        return await GuestOwnership(sessions).resolve_processing_actor(
            submission_id, token=token, lifetime=lifetime
        )


def _processing_policy(
    state: Any, person_id: UUID, expires_at_epoch: int
) -> AcquisitionProviderPolicy:
    def stage(
        stage_name: str,
        provider_id: str,
        model_id: str,
        recipe_revision: str,
        permission_ref: str,
        *,
        max_cost_paise: int,
        max_completion_tokens: int,
        profile_sha256: str | None,
    ) -> AcquisitionStagePolicy:
        return AcquisitionStagePolicy(
            stage=stage_name,
            configuration_sha256="a" * 64,
            provider_id=provider_id,
            model_id=model_id,
            recipe_revision=recipe_revision,
            permission_ref=permission_ref,
            retention_ref="ref:retention:guest-budget-test",
            professional_gate_ref="ref:professional:guest-budget-test",
            pricing_ref="ref:pricing:guest-budget-test",
            provider_terms_ref="ref:provider-terms:guest-budget-test",
            privacy_ref="ref:privacy:guest-budget-test",
            credential_ref=f"ref:credential/{provider_id}/v1",
            free_allowance_ref=None,
            no_paid_overage_ref="ref:no-paid-overage:guest-budget-test",
            privacy_revision="guest-budget-privacy-v1",
            privacy_notice="Disposable synthetic PostgreSQL budget initialization test.",
            expires_at_epoch=expires_at_epoch,
            max_requests=1,
            entitlement_seconds=None if stage_name == "C2" else 0,
            zero_cost_basis="paid_pricing_evidence",
            price_evidence_sha256="b" * 64,
            max_cost_paise=max_cost_paise,
            max_source_duration_ms=1_800_000,
            max_input_bytes=134_217_728,
            max_completion_tokens=max_completion_tokens,
            profile_sha256=profile_sha256,
        )

    return AcquisitionProviderPolicy(
        schema="ac.sales-xray.acquisition-provider-policy/1",
        id=uuid4(),
        tenant_id=state.tenant_id,
        processing_person_id=person_id,
        authorization_ref="ref:acquisition:guest-budget-test",
        expires_at_epoch=expires_at_epoch,
        max_recordings=64,
        max_source_bytes=134_217_728,
        max_stored_source_bytes=8_589_934_592,
        stages=(
            stage(
                "C2",
                "elevenlabs",
                "scribe_v2",
                "scribe-v2-native-normalized-v1",
                "ref:permission:guest-budget-asr",
                max_cost_paise=50_000,
                max_completion_tokens=0,
                profile_sha256=None,
            ),
            stage(
                "C4",
                "gemini",
                "gemini-3.8-flash",
                "source-fact-chunk-v1",
                "ref:permission:guest-budget-facts",
                max_cost_paise=25_000,
                max_completion_tokens=4_000,
                profile_sha256=None,
            ),
            stage(
                "C5",
                "gemini",
                "gemini-3.8-flash",
                "qualitative-coaching-v1",
                "ref:permission:guest-budget-coaching",
                max_cost_paise=25_000,
                max_completion_tokens=4_000,
                profile_sha256="c" * 64,
            ),
        ),
    )


def _metadata_actor_constraints(postgres_harness: Any) -> None:
    inspector = inspect(postgres_harness)
    for table in (
        "conversation_quote_acceptances",
        "conversation_inference_tasks",
        "conversation_processing_plans",
    ):
        checks = {item["name"] for item in inspector.get_check_constraints(table)}
        assert f"ck_{table}_one_actor" in checks
        foreign_keys = inspector.get_foreign_keys(table)
        constrained = {
            column for foreign_key in foreign_keys for column in foreign_key["constrained_columns"]
        }
        assert {"session_id", "processing_lease_id"} <= constrained


def test_first_guest_acceptance_bootstraps_shared_budget_without_learner_grant(
    postgres_harness: Any,
) -> None:
    """The first processing actor creates only the finite project budget."""

    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        try:
            state = await seed(engine)
            processing_person_id = await _provision(engine, state)
            guest, measured, intent, _ = await _guest(
                engine, state, duration_seconds=7, marker="budget-bootstrap"
            )
            actor = await _processing_actor(engine, state, measured.submission_id, guest.token)
            assert actor.person_id == processing_person_id

            now_epoch = int(state.now.timestamp())
            bundle = authority_bundle(
                state,
                state.source_sha256,
                "a" * 64,
                now_epoch=now_epoch,
                funded=True,
                text_cost_paise=25_000,
            ).model_copy(
                update={
                    "acquisition_policy": _processing_policy(
                        state, processing_person_id, now_epoch + 1_800
                    )
                }
            )
            bundle_box = {"bundle": bundle}
            authority = ConversationAuthority(
                lambda: bundle_box["bundle"],
                environment="test",
                operations_tenant_id=state.tenant_id,
            )
            intake_policy = IntakePolicy(
                budget_scope_id=bundle.budget_scope_id,
                tenant_ids=frozenset({state.tenant_id}),
                authorization_ref=bundle.intake_authorization_ref,
                retention_ref=bundle.intake_retention_ref,
                retention_days=bundle.retention_days,
            )

            async with AsyncSession(engine) as database, database.begin():
                intake = ConversationIntake(
                    ConversationApplication(database, clock=lambda: state.now),
                    intake_policy,
                    authority=authority,
                )
                quote = await intake.prepare(actor, intent, key="guest-budget-bootstrap")
                accepted = await intake.accept(
                    actor,
                    UUID(quote["id"]),
                    QuoteAcceptance(
                        quote_fingerprint=quote["quote_fingerprint"],
                        privacy_revision=quote["privacy_revision"],
                        accepted=True,
                    ),
                )
                replay = await intake.prepare(actor, intent, key="guest-budget-bootstrap")

            assert accepted["state"] == "accepted"
            assert replay["id"] == quote["id"]

            async with AsyncSession(engine) as database, database.begin():
                budget = await database.get(ConversationBudgetAccount, bundle.budget_scope_id)
                assert budget is not None
                snapshot = BudgetAccount.from_dict(budget.snapshot)
                assert snapshot.scope_id == str(bundle.budget_scope_id)
                assert snapshot.cap_paise == 100_000
                assert snapshot.available_paise == 100_000
                assert snapshot.reservations == ()
                assert budget.revision == 1

                processing_minutes = await database.get(
                    ConversationMinuteAccount,
                    (state.tenant_id, processing_person_id),
                )
                assert processing_minutes is not None
                minutes = MinuteAccount.from_dict(processing_minutes.snapshot)
                assert minutes.grants == ()
                assert minutes.available_seconds == 0
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(ConversationMinuteAccount)
                        .where(
                            ConversationMinuteAccount.tenant_id == state.tenant_id,
                            ConversationMinuteAccount.person_id == state.person_id,
                        )
                    )
                    == 0
                )
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(ConversationBudgetAccount)
                        .where(ConversationBudgetAccount.scope_id == bundle.budget_scope_id)
                    )
                    == 1
                )

            # A changed approval/cap cannot mutate the established budget, and
            # the existing retry remains idempotent above.
            bundle_box["bundle"] = bundle.model_copy(
                update={
                    "budget_cap_paise": 99_999,
                    "paid_approval_ref": "ref:approval:guest-budget-changed",
                }
            )
            with pytest.raises(ConversationDenied, match="budget"):
                async with AsyncSession(engine) as database, database.begin():
                    await authority.claim_allowance(
                        ConversationApplication(database, clock=lambda: state.now), actor
                    )
        finally:
            await engine.dispose()

    run(exercise())


def test_guest_processing_principal_is_non_login_and_intake_binds_each_submission(
    postgres_harness: Any,
) -> None:
    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        try:
            state = await seed(engine)
            scope_id = await seed_budget(engine)
            principal_person_id = await _provision(engine, state)
            first, first_source, first_intent, first_usage_id = await _guest(
                engine, state, duration_seconds=7, marker="first"
            )
            second, second_source, second_intent, second_usage_id = await _guest(
                engine, state, duration_seconds=11, marker="second"
            )
            first_actor = await _processing_actor(
                engine, state, first_source.submission_id, first.token
            )
            second_actor = await _processing_actor(
                engine, state, second_source.submission_id, second.token
            )
            assert isinstance(first_actor, ProcessingActor)
            assert first_actor.person_id == principal_person_id
            assert first_actor.session_id is None
            assert first_actor.processing_lease_id != second_actor.processing_lease_id

            async with AsyncSession(engine) as database, database.begin():
                leases = (
                    await database.scalars(
                        select(ConversationProcessingLease)
                        .where(ConversationProcessingLease.tenant_id == state.tenant_id)
                        .order_by(ConversationProcessingLease.created_at)
                    )
                ).all()
                usages = (
                    await database.scalars(
                        select(ConversationAcquisitionUsage)
                        .where(ConversationAcquisitionUsage.tenant_id == state.tenant_id)
                        .order_by(ConversationAcquisitionUsage.created_at)
                    )
                ).all()
                assert {lease.usage_id for lease in leases} == {
                    first_usage_id,
                    second_usage_id,
                }
                assert all(lease.person_id == principal_person_id for lease in leases)
                assert {usage.reserved_seconds for usage in usages} == {7, 11}
                assert all(usage.person_id is None for usage in usages)
                principal = await database.scalar(
                    select(ConversationProcessingPrincipal).where(
                        ConversationProcessingPrincipal.person_id == principal_person_id
                    )
                )
                assert principal is not None
                member = await database.get(Membership, (state.tenant_id, principal_person_id))
                assert member is not None and member.role == "processing"
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(IdentitySession)
                        .where(IdentitySession.person_id == principal_person_id)
                    )
                    == 0
                )
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(PasswordCredential)
                        .where(PasswordCredential.person_id == principal_person_id)
                    )
                    == 0
                )
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(ProviderIdentity)
                        .where(ProviderIdentity.person_id == principal_person_id)
                    )
                    == 0
                )

            _metadata_actor_constraints(postgres_harness)
            intake_policy = policy(scope_id, state.tenant_id)
            async with AsyncSession(engine) as database, database.begin():
                intake = ConversationIntake(
                    ConversationApplication(database, clock=lambda: state.now), intake_policy
                )
                first_view = await intake.prepare(first_actor, first_intent, key="same-browser-key")
                first_replay = await intake.prepare(
                    first_actor, first_intent, key="same-browser-key"
                )
                second_view = await intake.prepare(
                    second_actor, second_intent, key="same-browser-key"
                )
                assert first_replay == first_view
                assert first_view["id"] != second_view["id"]
                assert first_view["recording_id"] != second_view["recording_id"]
                assert first_view["cost_label"] == "₹0 · local audio measurements"
                await intake.accept(
                    first_actor,
                    UUID(first_view["id"]),
                    QuoteAcceptance(
                        quote_fingerprint=first_view["quote_fingerprint"],
                        privacy_revision=first_view["privacy_revision"],
                        accepted=True,
                    ),
                )
                with pytest.raises((ConversationDenied, ConversationNotFound)):
                    await intake.accept(
                        second_actor,
                        UUID(first_view["id"]),
                        QuoteAcceptance(
                            quote_fingerprint=first_view["quote_fingerprint"],
                            privacy_revision=first_view["privacy_revision"],
                            accepted=True,
                        ),
                    )

                linked = await database.get(
                    ConversationGuestSubmission,
                    (state.tenant_id, first_source.submission_id),
                )
                second_linked = await database.get(
                    ConversationGuestSubmission,
                    (state.tenant_id, second_source.submission_id),
                )
                assert linked is not None and second_linked is not None
                assert linked.recording_id == UUID(first_view["recording_id"])
                assert linked.processing_lease_id == first_actor.processing_lease_id
                assert second_linked.recording_id == UUID(second_view["recording_id"])
                assert linked.source_sha256 == first_intent.source_sha256
                assert second_linked.source_sha256 == second_intent.source_sha256
                acceptance = await database.get(ConversationQuoteAcceptance, UUID(first_view["id"]))
                assert acceptance is not None
                assert acceptance.session_id is None
                assert acceptance.processing_lease_id == first_actor.processing_lease_id
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(ConversationMinuteAccount)
                        .where(
                            ConversationMinuteAccount.tenant_id == state.tenant_id,
                            ConversationMinuteAccount.person_id == principal_person_id,
                        )
                    )
                    == 1
                )
                minute = await database.scalar(
                    select(ConversationMinuteAccount).where(
                        ConversationMinuteAccount.tenant_id == state.tenant_id,
                        ConversationMinuteAccount.person_id == principal_person_id,
                    )
                )
                assert (
                    minute is not None
                    and MinuteAccount.from_dict(minute.snapshot).available_seconds == 0
                )
                usage = await database.get(ConversationAcquisitionUsage, first_usage_id)
                assert usage is not None and usage.reserved_seconds == 7

                with pytest.raises(ConversationNotFound):
                    await ConversationApplication(database, clock=lambda: state.now).get(
                        second_actor, UUID(first_view["recording_id"])
                    )
                with pytest.raises(ConversationNotFound):
                    await GuestOwnership(
                        AcquisitionSessions(
                            database,
                            tenant_id=state.tenant_id,
                            policy_revision="guest-processing-v1",
                            clock=lambda: state.now,
                        )
                    ).require_submission_owner(second_source.submission_id, token=first.token)

                # The database one_actor check rejects both identities bound at once.
                acceptance.session_id = state.session_id
                with pytest.raises(DBAPIError):
                    await database.flush()

        finally:
            await engine.dispose()

    run(exercise())


def test_processing_actor_runs_c1_without_double_charging_guest_minutes(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        source = _wav_one_second_48k()
        storage = PrivateLocalRecordingStorage(tmp_path / "guest-source-storage")
        scratch = PrivateLocalRecordingStorage(tmp_path / "guest-source-scratch")
        try:
            state = await seed(engine)
            scope_id = await seed_budget(engine)
            principal_person_id = await _provision(engine, state)
            guest, measured, intent, usage_id = await _guest(
                engine,
                state,
                duration_seconds=1,
                marker="worker",
                source_bytes=source,
            )
            actor = await _processing_actor(engine, state, measured.submission_id, guest.token)
            async with AsyncSession(engine) as database, database.begin():
                intake = ConversationIntake(
                    ConversationApplication(database, clock=lambda: state.now),
                    policy(scope_id, state.tenant_id),
                )
                view = await intake.prepare(actor, intent, key="guest-worker-quote")
                await intake.accept(
                    actor,
                    UUID(view["id"]),
                    QuoteAcceptance(
                        quote_fingerprint=view["quote_fingerprint"],
                        privacy_revision=view["privacy_revision"],
                        accepted=True,
                    ),
                )
                app = ConversationApplication(database, clock=lambda: state.now)
                stored = await app.store_source(
                    actor,
                    UUID(view["recording_id"]),
                    chunks=(source,),
                    storage=storage,
                )
                run_intent = RunIntent(
                    recording_id=UUID(view["recording_id"]),
                    source_revision=stored["source_revision"],
                    quote_id=UUID(view["id"]),
                    recipe_revision=view["recipe_revision"],
                )
                run_view = await app.request_run(actor, run_intent, key="guest-worker-run")
                assert run_view["state"] == "queued"

            async with AsyncSession(engine) as database, database.begin():
                replay = await ConversationApplication(
                    database, clock=lambda: state.now
                ).request_run(actor, run_intent, key="guest-worker-run")
                assert replay == run_view
                commands = (
                    await database.scalars(
                        select(ConversationCommand).where(
                            ConversationCommand.tenant_id == state.tenant_id,
                            ConversationCommand.person_id == actor.person_id,
                            ConversationCommand.action == "run",
                        )
                    )
                ).all()
                assert len(commands) == 1
                assert commands[0].result_id == UUID(run_view["id"])
                jobs = (
                    await database.scalars(
                        select(Job).where(
                            Job.tenant_id == state.tenant_id,
                            Job.kind == LOCAL_JOB,
                        )
                    )
                ).all()
                assert len(jobs) == 1
                assert jobs[0].payload["run_id"] == run_view["id"]
                audit = (
                    await database.scalars(
                        select(AuditEvent).where(
                            AuditEvent.tenant_id == state.tenant_id,
                            AuditEvent.action == "conversation.run",
                            AuditEvent.resource_id == run_view["id"],
                        )
                    )
                ).all()
                assert len(audit) == 1
                assert audit[0].actor_type == "system"
                assert audit[0].actor_person_id == actor.person_id
                assert audit[0].payload["processing_lease_id"] == str(actor.processing_lease_id)

            sessions = async_sessionmaker(engine, expire_on_commit=False)
            await _reconcile(sessions, state)
            worker = OfflineConversationWorker(
                sessions,
                storage=storage,
                scratch=scratch,
                environment="test",
            )
            assert await worker.run_once() is True

            async with AsyncSession(engine) as database:
                run_row = await database.scalar(
                    select(ConversationRun).where(
                        ConversationRun.recording_id == UUID(view["recording_id"])
                    )
                )
                assert run_row is not None and run_row.state == "completed"
                checkpoints = (
                    await database.scalars(
                        select(ConversationCheckpoint)
                        .where(ConversationCheckpoint.recording_id == UUID(view["recording_id"]))
                        .order_by(ConversationCheckpoint.stage)
                    )
                ).all()
                assert [checkpoint.stage for checkpoint in checkpoints] == ["C0", "C1"]
                assert checkpoints[-1].payload is not None
                assert checkpoints[-1].payload["media_duration_ms"] == 1000
                assert (
                    await acquisition_seconds(
                        database, tenant_id=state.tenant_id, visitor_id=guest.visitor_id
                    )
                    == 1
                )
                minute = await database.get(
                    ConversationMinuteAccount, (state.tenant_id, principal_person_id)
                )
                assert minute is not None
                minute_account = MinuteAccount.from_dict(minute.snapshot)
                assert minute_account.available_seconds == 0
                assert all(
                    reservation.committed_seconds == 0
                    for reservation in minute_account.reservations
                )
                assert usage_id
        finally:
            await engine.dispose()

    run(exercise())


@pytest.mark.parametrize("mutation", ["expire", "revoke"])
def test_processing_lease_fence_preserves_claimed_owner_scope(
    postgres_harness: Any, mutation: str
) -> None:
    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        try:
            state = await seed(engine)
            scope_id = await seed_budget(engine)
            await _provision(engine, state)
            guest, measured, intent, _ = await _guest(
                engine, state, duration_seconds=4, marker=f"{mutation}-lease"
            )
            processing_actor = await _processing_actor(
                engine,
                state,
                measured.submission_id,
                guest.token,
                lifetime=timedelta(minutes=5) if mutation == "expire" else timedelta(hours=1),
            )
            async with AsyncSession(engine) as database, database.begin():
                view = await ConversationIntake(
                    ConversationApplication(database, clock=lambda: state.now),
                    policy(scope_id, state.tenant_id),
                ).prepare(processing_actor, intent, key=f"lease-{mutation}")
                await ConversationIntake(
                    ConversationApplication(database, clock=lambda: state.now),
                    policy(scope_id, state.tenant_id),
                ).accept(
                    processing_actor,
                    UUID(view["id"]),
                    QuoteAcceptance(
                        quote_fingerprint=view["quote_fingerprint"],
                        privacy_revision=view["privacy_revision"],
                        accepted=True,
                    ),
                )
            async with AsyncSession(engine) as database, database.begin():
                await AcquisitionSessions(
                    database,
                    tenant_id=state.tenant_id,
                    policy_revision="guest-processing-v1",
                    clock=lambda: state.now,
                ).claim(guest.token, state.actor)
                lease = await database.get(
                    ConversationProcessingLease, processing_actor.processing_lease_id
                )
                assert lease is not None
                if mutation == "revoke":
                    lease.revoked_at = state.now

            async with AsyncSession(engine) as database, database.begin():
                check_now = state.now + timedelta(minutes=6) if mutation == "expire" else state.now
                with pytest.raises(ConversationDenied):
                    await ConversationApplication(database, clock=lambda: check_now).get(
                        processing_actor, UUID(view["recording_id"])
                    )
                scope = await GuestOwnership(
                    AcquisitionSessions(
                        database,
                        tenant_id=state.tenant_id,
                        policy_revision="guest-processing-v1",
                        clock=lambda: state.now,
                    )
                ).require_submission_owner(measured.submission_id, actor=state.actor)
                assert scope.claimed_account is True
                assert scope.recording_id == UUID(view["recording_id"])
                assert scope.processing_lease_id == processing_actor.processing_lease_id
                with pytest.raises(ConversationDenied):
                    await GuestOwnership(
                        AcquisitionSessions(
                            database,
                            tenant_id=state.tenant_id,
                            policy_revision="guest-processing-v1",
                            clock=lambda: state.now,
                        )
                    ).require_submission_owner(measured.submission_id, token=guest.token)
        finally:
            await engine.dispose()

    run(exercise())


def test_processing_actor_rejects_reserved_source_mismatch_and_suspended_claim_owner(
    postgres_harness: Any,
) -> None:
    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        try:
            state = await seed(engine)
            scope_id = await seed_budget(engine)
            principal_person_id = await _provision(engine, state)
            guest, measured, intent, _ = await _guest(
                engine, state, duration_seconds=3, marker="mismatch"
            )
            processing_actor = await _processing_actor(
                engine, state, measured.submission_id, guest.token
            )
            wrong_duration = intent.model_copy(update={"duration_ms": 2_000})
            async with AsyncSession(engine) as database, database.begin():
                intake = ConversationIntake(
                    ConversationApplication(database, clock=lambda: state.now),
                    policy(scope_id, state.tenant_id),
                )
                with pytest.raises(ConversationDenied):
                    await intake.prepare(processing_actor, wrong_duration, key="duration-mismatch")
                view = await intake.prepare(processing_actor, intent, key="duration-match")
                assert view["recording_id"]

            async with AsyncSession(engine) as database, database.begin():
                await AcquisitionSessions(
                    database,
                    tenant_id=state.tenant_id,
                    policy_revision="guest-processing-v1",
                    clock=lambda: state.now,
                ).claim(guest.token, state.actor)
                await database.execute(
                    update(Membership)
                    .where(
                        Membership.tenant_id == state.tenant_id,
                        Membership.person_id == state.person_id,
                    )
                    .values(status="inactive", ended_at=state.now)
                )

            async with AsyncSession(engine) as database, database.begin():
                with pytest.raises(ConversationDenied):
                    await ConversationApplication(database, clock=lambda: state.now).get(
                        processing_actor, UUID(view["recording_id"])
                    )
                principal_member = await database.get(
                    Membership, (state.tenant_id, principal_person_id)
                )
                assert principal_member is not None and principal_member.status == "active"
                claim = await database.get(ConversationVisitorClaim, guest.visitor_id)
                assert claim is not None and claim.person_id == state.person_id
        finally:
            await engine.dispose()

    run(exercise())


def test_claimed_owner_can_delete_after_execution_and_permission_expiry(
    postgres_harness: Any,
) -> None:
    """Deletion remains available to the account owner after worker fencing."""

    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        try:
            state = await seed(engine)
            scope_id = await seed_budget(engine)
            await _provision(engine, state)
            guest, measured, intent, _ = await _guest(
                engine, state, duration_seconds=5, marker="owner-delete"
            )
            processing_actor = await _processing_actor(
                engine, state, measured.submission_id, guest.token
            )
            async with AsyncSession(engine) as database, database.begin():
                intake = ConversationIntake(
                    ConversationApplication(database, clock=lambda: state.now),
                    policy(scope_id, state.tenant_id),
                )
                view = await intake.prepare(processing_actor, intent, key="owner-delete-quote")
                await intake.accept(
                    processing_actor,
                    UUID(view["id"]),
                    QuoteAcceptance(
                        quote_fingerprint=view["quote_fingerprint"],
                        privacy_revision=view["privacy_revision"],
                        accepted=True,
                    ),
                )
                await AcquisitionSessions(
                    database,
                    tenant_id=state.tenant_id,
                    policy_revision="guest-processing-v1",
                    clock=lambda: state.now,
                ).claim(guest.token, state.actor)
                recording = await database.get(ConversationRecording, UUID(view["recording_id"]))
                assert recording is not None
                permission = await database.get(ConversationPermission, recording.permission_id)
                assert permission is not None
                clock_now = state.now + timedelta(hours=2)
                permission.expires_at = clock_now - timedelta(seconds=1)
                permission.retention_until = clock_now - timedelta(seconds=1)

            foreign = await seed(engine, tenant_id=state.tenant_id)
            async with AsyncSession(engine) as database, database.begin():
                with pytest.raises((ConversationDenied, ConversationNotFound)):
                    await GuestOwnership(
                        AcquisitionSessions(
                            database,
                            tenant_id=state.tenant_id,
                            policy_revision="guest-processing-v1",
                            clock=lambda: clock_now,
                        )
                    ).request_deletion(
                        measured.submission_id,
                        token=guest.token,
                        key="wrong-owner-token",
                    )
                with pytest.raises(ConversationNotFound):
                    await GuestOwnership(
                        AcquisitionSessions(
                            database,
                            tenant_id=state.tenant_id,
                            policy_revision="guest-processing-v1",
                            clock=lambda: clock_now,
                        )
                    ).request_deletion(
                        measured.submission_id,
                        actor=foreign.actor,
                        key="wrong-owner-account",
                    )
                with pytest.raises(ConversationDenied):
                    await ConversationApplication(database, clock=lambda: clock_now).get(
                        processing_actor, UUID(view["recording_id"])
                    )

                ownership = GuestOwnership(
                    AcquisitionSessions(
                        database,
                        tenant_id=state.tenant_id,
                        policy_revision="guest-processing-v1",
                        clock=lambda: clock_now,
                    )
                )
                deleted = await ownership.request_deletion(
                    measured.submission_id,
                    actor=state.actor,
                    key="owner-delete",
                )
                replay = await ownership.request_deletion(
                    measured.submission_id,
                    actor=state.actor,
                    key="owner-delete",
                )
                assert (
                    deleted
                    == replay
                    == {
                        "id": view["recording_id"],
                        "state": "deleting",
                    }
                )
                delete_jobs = (
                    await database.scalars(
                        select(Job).where(
                            Job.tenant_id == state.tenant_id,
                            Job.kind == DELETE_JOB,
                        )
                    )
                ).all()
                assert len(delete_jobs) == 1
                commands = (
                    await database.scalars(
                        select(ConversationCommand).where(
                            ConversationCommand.tenant_id == state.tenant_id,
                            ConversationCommand.person_id == processing_actor.person_id,
                            ConversationCommand.action == "delete",
                        )
                    )
                ).all()
                assert len(commands) == 1
                delete_audit = (
                    await database.scalars(
                        select(AuditEvent).where(
                            AuditEvent.tenant_id == state.tenant_id,
                            AuditEvent.action == "conversation.delete",
                            AuditEvent.resource_id == view["recording_id"],
                        )
                    )
                ).all()
                assert len(delete_audit) == 1
                assert delete_audit[0].actor_type == "system"
                assert delete_audit[0].actor_person_id == processing_actor.person_id
                assert delete_audit[0].payload["processing_lease_id"] == str(
                    processing_actor.processing_lease_id
                )
                owner_audit = (
                    await database.scalars(
                        select(AuditEvent).where(
                            AuditEvent.tenant_id == state.tenant_id,
                            AuditEvent.action == "conversation.owner_deletion_requested",
                            AuditEvent.resource_id == view["recording_id"],
                        )
                    )
                ).all()
                assert len(owner_audit) == 1
                assert owner_audit[0].actor_type == "person"
                assert owner_audit[0].actor_person_id == state.person_id
        finally:
            await engine.dispose()

    run(exercise())


def test_processing_admission_does_not_hold_tenant_acquisition_lock(
    postgres_harness: Any,
) -> None:
    """A held source lease cannot stall another guest's issue/reserve."""

    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        try:
            state = await seed(engine)
            await seed_budget(engine)
            await _provision(engine, state)
            guest, measured, _, _ = await _guest(
                engine, state, duration_seconds=2, marker="lock-holder"
            )
            actor = await _processing_actor(engine, state, measured.submission_id, guest.token)
            entered = asyncio.Event()
            release = asyncio.Event()

            async def hold_processing_lease() -> None:
                async with AsyncSession(engine) as database, database.begin():
                    await admit_processing_actor(database, actor, state.now)
                    entered.set()
                    await release.wait()

            async def issue_and_reserve_other_guest() -> tuple[UUID, UUID]:
                async with AsyncSession(engine) as database, database.begin():
                    sessions = AcquisitionSessions(
                        database,
                        tenant_id=state.tenant_id,
                        policy_revision="guest-processing-v1",
                        clock=lambda: state.now,
                    )
                    credential = await sessions.issue()
                    source = MeasuredSource(
                        uuid4(),
                        hashlib.sha256(b"unrelated-guest-source").hexdigest(),
                        1_000,
                        hashlib.sha256(b"unrelated-guest-duration").hexdigest(),
                    )
                    usage_id = await sessions.reserve(source, token=credential.token)
                    return credential.visitor_id, usage_id

            holder = asyncio.create_task(hold_processing_lease())
            try:
                await asyncio.wait_for(entered.wait(), timeout=3)
                visitor_id, usage_id = await asyncio.wait_for(
                    issue_and_reserve_other_guest(), timeout=2
                )
            finally:
                release.set()
                await asyncio.wait_for(holder, timeout=3)
            assert visitor_id != guest.visitor_id
            assert isinstance(usage_id, UUID)
        finally:
            await engine.dispose()

    run(exercise())


@pytest.mark.parametrize("mutation", ["claim", "revoke"])
def test_visitor_read_scope_fences_only_same_visitor(postgres_harness: Any, mutation: str) -> None:
    """A retained read blocks only that visitor's ownership mutation."""

    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        try:
            state = await seed(engine)
            scope_id = await seed_budget(engine)
            await _provision(engine, state)
            first, first_source, first_intent, _ = await _guest(
                engine, state, duration_seconds=2, marker=f"reader-{mutation}"
            )
            second, _, _, _ = await _guest(
                engine, state, duration_seconds=3, marker=f"other-{mutation}"
            )
            actor = await _processing_actor(engine, state, first_source.submission_id, first.token)
            async with AsyncSession(engine) as database, database.begin():
                intake = ConversationIntake(
                    ConversationApplication(database, clock=lambda: state.now),
                    policy(scope_id, state.tenant_id),
                )
                view = await intake.prepare(actor, first_intent, key=f"reader-quote-{mutation}")
                await intake.accept(
                    actor,
                    UUID(view["id"]),
                    QuoteAcceptance(
                        quote_fingerprint=view["quote_fingerprint"],
                        privacy_revision=view["privacy_revision"],
                        accepted=True,
                    ),
                )

            entered = asyncio.Event()
            release = asyncio.Event()
            mutation_done = asyncio.Event()

            async def hold_reader() -> None:
                async with AsyncSession(engine) as database, database.begin():
                    await GuestOwnership(
                        AcquisitionSessions(
                            database,
                            tenant_id=state.tenant_id,
                            policy_revision="guest-processing-v1",
                            clock=lambda: state.now,
                        )
                    ).require_submission_owner(first_source.submission_id, token=first.token)
                    entered.set()
                    await release.wait()

            async def mutate_owner() -> None:
                try:
                    async with AsyncSession(engine) as database, database.begin():
                        sessions = AcquisitionSessions(
                            database,
                            tenant_id=state.tenant_id,
                            policy_revision="guest-processing-v1",
                            clock=lambda: state.now,
                        )
                        if mutation == "claim":
                            await sessions.claim(first.token, state.actor)
                        else:
                            await sessions.revoke(first.token)
                finally:
                    mutation_done.set()

            async def issue_other_guest() -> tuple[UUID, UUID]:
                async with AsyncSession(engine) as database, database.begin():
                    sessions = AcquisitionSessions(
                        database,
                        tenant_id=state.tenant_id,
                        policy_revision="guest-processing-v1",
                        clock=lambda: state.now,
                    )
                    credential = await sessions.issue()
                    source = MeasuredSource(
                        uuid4(),
                        hashlib.sha256(b"visitor-fence-other-source").hexdigest(),
                        1_000,
                        hashlib.sha256(b"visitor-fence-other-duration").hexdigest(),
                    )
                    usage_id = await sessions.reserve(source, token=credential.token)
                    return credential.visitor_id, usage_id

            reader = asyncio.create_task(hold_reader())
            mutation_task: asyncio.Task[None] | None = None
            try:
                await asyncio.wait_for(entered.wait(), timeout=3)
                mutation_task = asyncio.create_task(mutate_owner())
                await asyncio.sleep(0.2)
                assert not mutation_done.is_set()
                visitor_id, usage_id = await asyncio.wait_for(issue_other_guest(), timeout=2)
            finally:
                release.set()
                await asyncio.wait_for(reader, timeout=3)
                if mutation_task is not None:
                    await asyncio.wait_for(mutation_task, timeout=3)
            assert visitor_id != second.visitor_id
            assert isinstance(usage_id, UUID)
        finally:
            await engine.dispose()

    run(exercise())
