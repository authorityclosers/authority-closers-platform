"""Disposable-loopback PostgreSQL proof for local conversation intake."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from ac_platform.conversation_intelligence.application import (
    AUDIOATLAS_RECIPE,
    ConversationApplication,
    ConversationConflict,
    ConversationDenied,
)
from ac_platform.conversation_intelligence.contracts import IntakeIntent, QuoteAcceptance, RunIntent
from ac_platform.conversation_intelligence.entitlements import (
    MinuteAccount,
    MinuteGrant,
    grant_minutes,
)
from ac_platform.conversation_intelligence.intake import ConversationIntake, IntakePolicy
from ac_platform.conversation_intelligence.models import (
    ConversationCheckpoint,
    ConversationCommand,
    ConversationMinuteAccount,
    ConversationQuote,
    ConversationQuoteAcceptance,
    ConversationRecording,
)
from ac_platform.conversation_intelligence.storage import PrivateLocalRecordingStorage
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.outbox.models import Job
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed, seed_budget


@pytest.fixture(scope="module")
def postgres_harness():
    yield from _postgres_harness.__wrapped__()


def policy(scope_id: UUID, *tenant_ids: UUID) -> IntakePolicy:
    return IntakePolicy(
        budget_scope_id=scope_id,
        tenant_ids=frozenset(tenant_ids),
        authorization_ref="synthetic-local-intake-authorization",
        retention_ref="synthetic-local-intake-retention",
    )


async def add_allowance(engine: AsyncEngine, tenant_id: UUID, person_id: UUID, seconds: int = 300):
    account = grant_minutes(
        MinuteAccount(str(tenant_id), str(person_id)),
        MinuteGrant(
            str(tenant_id),
            str(person_id),
            uuid4().hex,
            seconds,
            "synthetic-initial-allowance",
            "synthetic-fixture-owner",
            "local intake integration test",
        ),
    )
    async with AsyncSession(engine) as database, database.begin():
        database.add(
            ConversationMinuteAccount(
                tenant_id=tenant_id,
                person_id=person_id,
                snapshot=account.as_dict(),
                revision=1,
            )
        )


def make_intent(source: bytes = b"synthetic local audio") -> IntakeIntent:
    return IntakeIntent(
        source_sha256=hashlib.sha256(source).hexdigest(),
        source_bytes=len(source),
        content_type="audio/wav",
        duration_ms=1000,
        purpose="internal_analysis",
    )


async def issue(
    engine: AsyncEngine,
    state: Any,
    scope_id: UUID,
    *,
    key: str = "intake-quote",
    source: bytes = b"synthetic local audio",
    allowed_tenants: tuple[UUID, ...] | None = None,
) -> tuple[IntakeIntent, dict[str, Any]]:
    intent = make_intent(source)
    await add_allowance(engine, state.tenant_id, state.person_id)
    allowed = allowed_tenants or (state.tenant_id,)
    async with AsyncSession(engine) as database, database.begin():
        intake = ConversationIntake(
            ConversationApplication(database, clock=lambda: state.now),
            policy(scope_id, *allowed),
        )
        view = await intake.prepare(state.actor, intent, key=key)
    return intent, view


def app(database: AsyncSession, state: Any) -> ConversationApplication:
    return ConversationApplication(database, clock=lambda: state.now)


def test_quote_issuance_is_not_consent_and_requires_exact_acceptance(postgres_harness):
    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        try:
            state = await seed(engine)
            scope_id = await seed_budget(engine)
            intent, view = await issue(engine, state, scope_id)
            quote_id = UUID(view["id"])
            async with AsyncSession(engine) as database, database.begin():
                intake = ConversationIntake(app(database, state), policy(scope_id, state.tenant_id))
                assert view["recipe_revision"] == AUDIOATLAS_RECIPE
                assert view["output_kind"] == "measurements"
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(ConversationQuoteAcceptance)
                        .where(ConversationQuoteAcceptance.quote_id == quote_id)
                    )
                    == 0
                )
                with pytest.raises(ConversationDenied):
                    await intake.require_accepted(state.actor, UUID(view["recording_id"]), quote_id)
                accepted = await intake.accept(
                    state.actor,
                    quote_id,
                    QuoteAcceptance(
                        quote_fingerprint=view["quote_fingerprint"],
                        privacy_revision=view["privacy_revision"],
                        accepted=True,
                    ),
                )
                assert accepted == {"id": str(quote_id), "state": "accepted"}
                assert (
                    await intake.accept(
                        state.actor,
                        quote_id,
                        QuoteAcceptance(
                            quote_fingerprint=view["quote_fingerprint"],
                            privacy_revision=view["privacy_revision"],
                            accepted=True,
                        ),
                    )
                    == accepted
                )
                row = await database.get(ConversationQuoteAcceptance, quote_id)
                assert row is not None and row.person_id == state.person_id
                assert row.quote_fingerprint == view["quote_fingerprint"]
                assert row.privacy_revision == view["privacy_revision"]
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(ConversationQuoteAcceptance)
                        .where(ConversationQuoteAcceptance.quote_id == quote_id)
                    )
                    == 1
                )
        finally:
            await engine.dispose()

    run(exercise())


def test_quote_requires_a_synthetic_allowance_before_recording(postgres_harness):
    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        try:
            state = await seed(engine)
            scope_id = await seed_budget(engine)
            async with AsyncSession(engine) as database, database.begin():
                with pytest.raises(ConversationDenied):
                    await ConversationIntake(
                        app(database, state), policy(scope_id, state.tenant_id)
                    ).prepare(state.actor, make_intent(), key="without-allowance")
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(ConversationRecording)
                        .where(ConversationRecording.tenant_id == state.tenant_id)
                    )
                    == 0
                )
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(ConversationQuote)
                        .where(ConversationQuote.tenant_id == state.tenant_id)
                    )
                    == 0
                )
        finally:
            await engine.dispose()

    run(exercise())


def test_quote_acceptance_cannot_move_to_another_active_session(postgres_harness):
    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        try:
            state = await seed(engine)
            scope_id = await seed_budget(engine)
            _, view = await issue(engine, state, scope_id)
            quote_id = UUID(view["id"])
            acceptance = QuoteAcceptance(
                quote_fingerprint=view["quote_fingerprint"],
                privacy_revision=view["privacy_revision"],
                accepted=True,
            )
            other = replace(state, session_id=uuid4())
            async with AsyncSession(engine) as database, database.begin():
                database.add(
                    IdentitySession(
                        id=other.session_id,
                        person_id=other.person_id,
                        selected_tenant_id=other.tenant_id,
                        token_hash=other.session_id.bytes * 2,
                        expires_at=other.now + timedelta(days=1),
                    )
                )
                await database.flush()
                intake = ConversationIntake(app(database, state), policy(scope_id, state.tenant_id))
                await intake.accept(state.actor, quote_id, acceptance)
            async with AsyncSession(engine) as database, database.begin():
                intake = ConversationIntake(app(database, other), policy(scope_id, state.tenant_id))
                await intake.admit(other.actor)  # The second session is valid AC identity.
                with pytest.raises(ConversationDenied, match="current session"):
                    await intake.accept(other.actor, quote_id, acceptance)
                with pytest.raises(ConversationDenied, match="Approve this recording"):
                    await intake.require_accepted(other.actor, UUID(view["recording_id"]), quote_id)
        finally:
            await engine.dispose()

    run(exercise())


def test_intake_scope_owner_revocation_and_expiry_are_checked(postgres_harness):
    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        try:
            owner = await seed(engine)
            foreign = await seed(engine)
            scope_id = await seed_budget(engine)
            _, view = await issue(
                engine,
                owner,
                scope_id,
                allowed_tenants=(owner.tenant_id, foreign.tenant_id),
            )
            quote_id = UUID(view["id"])
            exact = QuoteAcceptance(
                quote_fingerprint=view["quote_fingerprint"],
                privacy_revision=view["privacy_revision"],
                accepted=True,
            )
            async with AsyncSession(engine) as database, database.begin():
                intake = ConversationIntake(
                    app(database, foreign), policy(scope_id, owner.tenant_id, foreign.tenant_id)
                )
                with pytest.raises(ConversationDenied):
                    await intake.accept(foreign.actor, quote_id, exact)

            async with AsyncSession(engine) as database, database.begin():
                await database.execute(
                    update(ConversationQuote)
                    .where(ConversationQuote.id == quote_id)
                    .values(revoked_at=owner.now)
                )
                with pytest.raises(ConversationDenied):
                    await ConversationIntake(
                        app(database, owner), policy(scope_id, owner.tenant_id)
                    ).accept(owner.actor, quote_id, exact)

            expired = await seed(engine)
            _, expired_view = await issue(engine, expired, scope_id, key="expired-quote")
            expired = replace(expired, now=expired.now + timedelta(minutes=31))
            expired_exact = QuoteAcceptance(
                quote_fingerprint=expired_view["quote_fingerprint"],
                privacy_revision=expired_view["privacy_revision"],
                accepted=True,
            )
            async with AsyncSession(engine) as database, database.begin():
                with pytest.raises(ConversationConflict):
                    await ConversationIntake(
                        app(database, expired), policy(scope_id, expired.tenant_id)
                    ).accept(expired.actor, UUID(expired_view["id"]), expired_exact)

            blocked = await seed(engine)
            blocked_scope = await seed_budget(engine)
            await add_allowance(engine, blocked.tenant_id, blocked.person_id)
            async with AsyncSession(engine) as database, database.begin():
                with pytest.raises(ConversationDenied):
                    await ConversationIntake(
                        app(database, blocked), policy(blocked_scope, foreign.tenant_id)
                    ).prepare(blocked.actor, make_intent(), key="blocked-workspace")
        finally:
            await engine.dispose()

    run(exercise())


def test_quote_key_replay_and_conflict_are_transactional(postgres_harness):
    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        try:
            state = await seed(engine)
            scope_id = await seed_budget(engine)
            await add_allowance(engine, state.tenant_id, state.person_id)
            intent = make_intent()
            async with AsyncSession(engine) as database, database.begin():
                intake = ConversationIntake(app(database, state), policy(scope_id, state.tenant_id))
                first = await intake.prepare(state.actor, intent, key="same-quote-key")
                replay = await intake.prepare(state.actor, intent, key="same-quote-key")
                assert replay == first
                with pytest.raises(ConversationConflict):
                    await intake.prepare(
                        state.actor,
                        intent.model_copy(update={"duration_ms": 2000}),
                        key="same-quote-key",
                    )
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(ConversationQuote)
                        .where(ConversationQuote.tenant_id == state.tenant_id)
                    )
                    == 1
                )
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(ConversationRecording)
                        .where(ConversationRecording.tenant_id == state.tenant_id)
                    )
                    == 1
                )
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(ConversationCommand)
                        .where(
                            ConversationCommand.tenant_id == state.tenant_id,
                            ConversationCommand.action == "intake_quote",
                        )
                    )
                    == 1
                )
        finally:
            await engine.dispose()

    run(exercise())


def test_approval_then_bounded_source_storage_and_local_run(postgres_harness, tmp_path: Path):
    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        source = b"RIFF synthetic local audio fixture"
        storage = PrivateLocalRecordingStorage(tmp_path / "source-storage")
        try:
            state = await seed(engine)
            scope_id = await seed_budget(engine)
            intent, view = await issue(
                engine, state, scope_id, source=source, key="approved-source"
            )
            quote_id = UUID(view["id"])
            recording_id = UUID(view["recording_id"])
            acceptance = QuoteAcceptance(
                quote_fingerprint=view["quote_fingerprint"],
                privacy_revision=view["privacy_revision"],
                accepted=True,
            )
            recipe_revision = view["recipe_revision"]
            async with AsyncSession(engine) as database, database.begin():
                intake = ConversationIntake(app(database, state), policy(scope_id, state.tenant_id))
                await intake.accept(state.actor, quote_id, acceptance)
                stored = await app(database, state).store_source(
                    state.actor,
                    recording_id,
                    chunks=(source[index : index + 7] for index in range(0, len(source), 7)),
                    storage=storage,
                )
                assert stored["state"] == "ready"
                run_view = await app(database, state).request_run(
                    state.actor,
                    RunIntent(
                        recording_id=recording_id,
                        source_revision=stored["source_revision"],
                        quote_id=quote_id,
                        recipe_revision=recipe_revision,
                    ),
                    key="approved-local-run",
                )
                assert run_view["state"] == "queued"
                assert run_view["recipe_revision"] == recipe_revision
                assert run_view["provider_calls"] == 0
                job = await database.scalar(
                    select(Job).where(
                        Job.tenant_id == state.tenant_id,
                        Job.kind == "conversation.inspect_local.v1",
                    )
                )
                assert job is not None
                assert job.payload == {
                    "run_id": run_view["id"],
                    "recording_id": str(recording_id),
                    "generation": 1,
                    "quote_id": str(quote_id),
                }
            objects = storage.list_recording(state.tenant_id, recording_id)
            assert len(objects) == 1
            assert (
                b"".join(storage.iter_bytes(objects[0], expected_sha256=intent.source_sha256))
                == source
            )
        finally:
            await engine.dispose()

    run(exercise())


async def expect_db_rejection(
    engine: AsyncEngine,
    statement_factory: Callable[[Any], Any],
) -> None:
    with pytest.raises(DBAPIError):
        async with AsyncSession(engine) as database, database.begin():
            await database.execute(statement_factory(database))


def test_quote_acceptance_and_checkpoint_rows_are_immutable_in_postgresql(postgres_harness):
    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        try:
            state = await seed(engine)
            scope_id = await seed_budget(engine)
            intent, view = await issue(engine, state, scope_id, key="immutable-quote")
            quote_id, recording_id = UUID(view["id"]), UUID(view["recording_id"])
            acceptance = QuoteAcceptance(
                quote_fingerprint=view["quote_fingerprint"],
                privacy_revision=view["privacy_revision"],
                accepted=True,
            )
            async with AsyncSession(engine) as database, database.begin():
                await ConversationIntake(
                    app(database, state), policy(scope_id, state.tenant_id)
                ).accept(state.actor, quote_id, acceptance)
                database.add(
                    ConversationCheckpoint(
                        id=uuid4(),
                        recording_id=recording_id,
                        tenant_id=state.tenant_id,
                        person_id=state.person_id,
                        cache_key="immutable-c0",
                        manifest_sha256="a" * 64,
                        payload_sha256="b" * 64,
                        stage="C0",
                        feature_blob_id=None,
                        manifest={"fixture": "immutable"},
                        payload={"source_sha256": intent.source_sha256},
                        created_at=state.now,
                    )
                )

            await expect_db_rejection(
                engine,
                lambda database: (
                    update(ConversationQuote)
                    .where(ConversationQuote.id == quote_id)
                    .values(quote={"mutated": True})
                ),
            )
            await expect_db_rejection(
                engine,
                lambda database: (
                    update(ConversationQuoteAcceptance)
                    .where(ConversationQuoteAcceptance.quote_id == quote_id)
                    .values(privacy_revision="mutated")
                ),
            )
            await expect_db_rejection(
                engine,
                lambda database: (
                    update(ConversationCheckpoint)
                    .where(
                        ConversationCheckpoint.recording_id == recording_id,
                        ConversationCheckpoint.cache_key == "immutable-c0",
                    )
                    .values(stage="C1")
                ),
            )
            async with AsyncSession(engine) as database, database.begin():
                checkpoint = await database.scalar(
                    select(ConversationCheckpoint).where(
                        ConversationCheckpoint.recording_id == recording_id,
                        ConversationCheckpoint.cache_key == "immutable-c0",
                    )
                )
                assert checkpoint is not None and checkpoint.stage == "C0"
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(ConversationQuoteAcceptance)
                        .where(ConversationQuoteAcceptance.quote_id == quote_id)
                    )
                    == 1
                )
        finally:
            await engine.dispose()

    run(exercise())
