from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session as DbSession

from ac_platform.db.base import Base
from ac_platform.identity.application import (
    AsyncIdentityApplication,
    ProductionTransactionRequiredError,
    _drain_account_deletion_hook,
)
from ac_platform.identity.factories import create_production_identity_services
from ac_platform.identity.repositories import (
    AsyncSqlAlchemyIdentityRepository,
    SqlAlchemyIdentityStore,
)
from ac_platform.identity.services import (
    DeletionService,
    IdentityLinkService,
    InMemoryIdentityStore,
    PersonSnapshot,
    ProviderAuthorizationType,
    ProviderIdentityRaceError,
    ProviderIdentitySnapshot,
    SessionRevisionConflictError,
    SessionService,
    StoredSession,
    TenantScopeDeniedError,
    VerifiedProviderAssertion,
)
from ac_platform.telemetry.retention import (
    TelemetryAccountDeletionAction,
    TelemetryAccountDeletionResult,
)
from ac_platform.tenancy.models import Membership, Tenant
from ac_platform.tenancy.services import (
    InMemoryTenantStore,
    MembershipSnapshot,
    TenantContextService,
    TenantSnapshot,
)

NOW = datetime(2026, 8, 30, 12, tzinfo=UTC)
EMAIL = "learner@authorityclosers.com"
PEPPER = b"p" * 32


def _verified_person(person_id: UUID) -> PersonSnapshot:
    return PersonSnapshot(
        id=person_id,
        email=EMAIL,
        email_verified_at=NOW,
    )


def test_scoped_session_authentication_fails_closed_without_a_trusted_context_port() -> None:
    person_id = uuid4()
    tenant_id = uuid4()
    identity_store = InMemoryIdentityStore([_verified_person(person_id)])
    tenancy_store = InMemoryTenantStore(
        tenants=[TenantSnapshot(id=tenant_id, slug="ac", name="Authority Closers")],
        memberships=[MembershipSnapshot(tenant_id=tenant_id, person_id=person_id, role="learner")],
    )
    trusted = TenantContextService(tenancy_store)
    issued = SessionService(identity_store, token_pepper=PEPPER, tenant_context=trusted).issue(
        person_id,
        selected_tenant_id=tenant_id,
        now=NOW,
    )

    with pytest.raises(TenantScopeDeniedError, match="trusted tenant-context"):
        SessionService(identity_store, token_pepper=PEPPER).authenticate(
            issued.token, now=NOW + timedelta(seconds=1)
        )


def test_scoped_session_authentication_revalidates_live_membership() -> None:
    person_id = uuid4()
    tenant_id = uuid4()
    membership = MembershipSnapshot(tenant_id=tenant_id, person_id=person_id, role="learner")
    identity_store = InMemoryIdentityStore([_verified_person(person_id)])
    tenancy_store = InMemoryTenantStore(
        tenants=[TenantSnapshot(id=tenant_id, slug="ac", name="Authority Closers")],
        memberships=[membership],
    )
    trusted = TenantContextService(tenancy_store)
    sessions = SessionService(identity_store, token_pepper=PEPPER, tenant_context=trusted)
    issued = sessions.issue(person_id, selected_tenant_id=tenant_id, now=NOW)

    tenancy_store.replace_membership(
        replace(membership, status="inactive", ended_at=NOW),
    )

    with pytest.raises(TenantScopeDeniedError, match="tenant-context"):
        sessions.authenticate(issued.token, now=NOW + timedelta(seconds=1))


def test_scoped_session_authentication_revalidates_live_tenant_status() -> None:
    person_id = uuid4()
    tenant_id = uuid4()
    identity_store = InMemoryIdentityStore([_verified_person(person_id)])
    tenancy_store = InMemoryTenantStore(
        tenants=[TenantSnapshot(id=tenant_id, slug="ac", name="Authority Closers")],
        memberships=[MembershipSnapshot(tenant_id=tenant_id, person_id=person_id, role="learner")],
    )
    trusted = TenantContextService(tenancy_store)
    sessions = SessionService(identity_store, token_pepper=PEPPER, tenant_context=trusted)
    issued = sessions.issue(person_id, selected_tenant_id=tenant_id, now=NOW)

    tenancy_store.tenants[tenant_id] = replace(
        tenancy_store.tenants[tenant_id],
        status="suspended",
    )

    with pytest.raises(TenantScopeDeniedError, match="tenant-context"):
        sessions.authenticate(issued.token, now=NOW + timedelta(seconds=1))


def test_stale_session_snapshot_cannot_replace_a_concurrent_revocation() -> None:
    person_id = uuid4()
    store = InMemoryIdentityStore([_verified_person(person_id)])
    session_service = SessionService(store, token_pepper=PEPPER)
    issued = session_service.issue(person_id, now=NOW)
    stale = store.get_session(issued.metadata.id)
    assert stale is not None

    revoked = replace(stale, revoked_at=NOW, revision=stale.revision + 1)
    store.save_session(revoked)

    with pytest.raises(SessionRevisionConflictError):
        store.save_session(
            replace(
                stale,
                last_seen_at=NOW + timedelta(seconds=1),
                revision=stale.revision + 1,
            )
        )
    assert store.get_session(issued.metadata.id) == revoked


class _CanonicalReloadRaceStore(InMemoryIdentityStore):
    def __init__(self, canonical: ProviderIdentitySnapshot) -> None:
        super().__init__([_verified_person(canonical.person_id)])
        self._canonical = canonical
        self._raced = False

    def save_provider_identity(self, identity: ProviderIdentitySnapshot) -> None:
        if not self._raced:
            self._raced = True
            self.provider_identities[self._canonical.id] = self._canonical
            raise ProviderIdentityRaceError("simulated unique-key race")
        super().save_provider_identity(identity)


def test_provider_link_returns_the_deterministic_canonical_row_after_a_unique_race() -> None:
    person_id = uuid4()
    canonical = ProviderIdentitySnapshot(
        id=uuid4(),
        person_id=person_id,
        issuer="https://issuer.example",
        subject="subject-1",
        created_at=NOW,
    )
    store = _CanonicalReloadRaceStore(canonical)

    actor = SessionService(store, token_pepper=PEPPER).issue(person_id, now=NOW).metadata
    service = IdentityLinkService(store)
    transaction = service.begin_provider_authorization(
        actor, audience="authority-closers-web", now=NOW
    )
    linked = service.link_verified_provider_identity(
        actor,
        transaction_id=transaction.transaction_id,
        assertion=VerifiedProviderAssertion(
            issuer=canonical.issuer,
            subject=canonical.subject,
            audience="authority-closers-web",
            state=transaction.state,
            nonce=transaction.nonce,
            authorization_type=ProviderAuthorizationType.LINK,
            email=EMAIL,
            email_verified=True,
        ),
        pkce_verifier=transaction.pkce_verifier,
        now=NOW,
    )

    assert linked == canonical


async def test_production_factory_is_async_only_and_requires_caller_transaction() -> None:
    session = AsyncSession()
    try:
        services = create_production_identity_services(
            session,
            token_pepper=b"p" * 32,
        )
        assert isinstance(services.application, AsyncIdentityApplication)
        assert isinstance(services.repository, AsyncSqlAlchemyIdentityRepository)
        with pytest.raises(ProductionTransactionRequiredError):
            await services.application.resolve_actor("x" * 43)
    finally:
        await session.close()


def test_sqlalchemy_identity_store_round_trips_hashed_session_metadata() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        person_id = uuid4()
        now = NOW
        with DbSession(engine) as session:
            store = SqlAlchemyIdentityStore(session)
            store.save_person(_verified_person(person_id))
            stored = StoredSession(
                id=uuid4(),
                person_id=person_id,
                token_hash=b"h" * 32,
                created_at=now,
                expires_at=now + timedelta(hours=1),
            )
            store.save_session(stored)
            session.commit()

            loaded = store.find_session_by_token_hash(b"h" * 32)
            assert loaded == stored
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_identity_and_tenancy_model_modules_are_directly_importable() -> None:
    root = Path(__file__).resolve().parents[3]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(root / "packages" / "python")
    for module_name, symbol in (
        ("ac_platform.identity.models", "Person"),
        ("ac_platform.tenancy.models", "Tenant"),
    ):
        result = subprocess.run(  # noqa: S603 - module and symbol are fixed above
            [sys.executable, "-c", f"from {module_name} import {symbol}"],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr


class _DeletionOperator:
    def require_permission(self, permission: str) -> None:
        assert permission == "identity_deletion_process"


class _PrivacyBatchHook:
    def __init__(self, results: list[TelemetryAccountDeletionResult]) -> None:
        self.results = results
        self.calls = 0

    async def apply(self, _session: AsyncSession, **_kwargs: object) -> object:
        self.calls += 1
        return self.results.pop(0)


async def test_account_deletion_drains_available_privacy_batches() -> None:
    hook = _PrivacyBatchHook(
        [
            TelemetryAccountDeletionResult(
                policy_id="learner-telemetry-v1",
                action=TelemetryAccountDeletionAction.PURGE,
                purged=1,
                has_more=True,
            ),
            TelemetryAccountDeletionResult(
                policy_id="learner-telemetry-v1",
                action=TelemetryAccountDeletionAction.PURGE,
                purged=1,
                has_more=True,
            ),
            TelemetryAccountDeletionResult(
                policy_id="learner-telemetry-v1",
                action=TelemetryAccountDeletionAction.PURGE,
                purged=1,
            ),
        ]
    )

    complete = await _drain_account_deletion_hook(
        hook,
        cast(AsyncSession, object()),
        deletion_request_id=uuid4(),
        person_id=uuid4(),
        tenant_id=uuid4(),
        now=NOW,
    )

    assert complete is True
    assert hook.calls == 3
    assert hook.results == []


async def test_account_deletion_keeps_processing_when_privacy_batch_is_locked() -> None:
    hook = _PrivacyBatchHook(
        [
            TelemetryAccountDeletionResult(
                policy_id="learner-telemetry-v1",
                action=TelemetryAccountDeletionAction.PURGE,
                purged=1,
                has_more=True,
            ),
            TelemetryAccountDeletionResult(
                policy_id="learner-telemetry-v1",
                action=TelemetryAccountDeletionAction.PURGE,
                already_anonymized=1,
                has_more=True,
            ),
        ]
    )

    complete = await _drain_account_deletion_hook(
        hook,
        cast(AsyncSession, object()),
        deletion_request_id=uuid4(),
        person_id=uuid4(),
        tenant_id=uuid4(),
        now=NOW,
    )

    assert complete is False
    assert hook.calls == 2
    assert len(hook.results) == 0


def test_sqlalchemy_deletion_ends_all_memberships_in_same_transaction() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        person_id = uuid4()
        tenant_id = uuid4()
        with DbSession(engine) as session:
            store = SqlAlchemyIdentityStore(session)
            store.save_person(_verified_person(person_id))
            session.add(Tenant(id=tenant_id, slug="ac", name="Authority Closers"))
            session.add(Membership(tenant_id=tenant_id, person_id=person_id, role="learner"))
            session.flush()

            deletion = DeletionService(store)
            request = deletion.request(person_id, person_id, now=NOW)
            processing = deletion.begin_processing(_DeletionOperator(), request.id)
            deletion.complete(_DeletionOperator(), processing.id, now=NOW + timedelta(minutes=1))

            membership = session.get(Membership, (tenant_id, person_id))
            assert membership is not None
            assert membership.ended_at is not None
            assert membership.status == "inactive"
            assert membership.ended_at.replace(tzinfo=UTC) == NOW + timedelta(minutes=1)
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
