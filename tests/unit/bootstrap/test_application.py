from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.bootstrap import BootstrapApplication, BootstrapError
from ac_platform.bootstrap import application as bootstrap_module
from ac_platform.identity.application import AsyncIdentityApplication
from ac_platform.identity.services import PersonSnapshot, StoredSession
from ac_platform.tenancy.models import TenantStatus
from ac_platform.tenancy.services import MembershipSnapshot, TenantSnapshot

NOW = datetime(2026, 8, 30, 12, tzinfo=UTC)
PERSON_ID = uuid4()
TENANT_ID = uuid4()
OPERATIONS_TENANT_ID = uuid4()


class TransactionalSession:
    def get_transaction(self) -> Any:
        from sqlalchemy.orm import SessionTransactionOrigin

        return SimpleNamespace(
            sync_transaction=SimpleNamespace(origin=SessionTransactionOrigin.BEGIN)
        )


@dataclass
class FakeIdentityRepository:
    people: tuple[PersonSnapshot, ...]
    has_provider: bool = True
    sessions_updated: int = 0

    def __init__(self, _session: object) -> None:
        self.people = ()
        self.has_provider = True
        self.sessions_updated = 0

    async def find_people_by_exact_email_for_update(self, email: str) -> tuple[PersonSnapshot, ...]:
        return tuple(person for person in self.people if person.email == email)

    async def has_provider_identity(self, person_id: UUID) -> bool:
        return self.has_provider and person_id == PERSON_ID

    async def select_tenant_for_active_sessions(
        self, person_id: UUID, tenant_id: UUID, *, now: datetime
    ) -> int:
        assert person_id == PERSON_ID
        assert now == NOW
        return self.sessions_updated


class FakeTenantRepository:
    tenant: TenantSnapshot | None = None
    operations_tenant: TenantSnapshot | None = None
    membership: MembershipSnapshot | None = None

    def __init__(self, _session: object) -> None:
        self.tenant = None
        self.operations_tenant = None
        self.membership = None

    async def get_tenant(self, tenant_id: UUID) -> TenantSnapshot | None:
        for tenant in (self.tenant, self.operations_tenant):
            if tenant is not None and tenant.id == tenant_id:
                return tenant
        return None

    async def get_tenant_by_slug_for_update(self, slug: str) -> TenantSnapshot | None:
        if self.tenant is not None and self.tenant.slug == slug:
            return self.tenant
        return None

    async def save_tenant(self, tenant: TenantSnapshot) -> None:
        self.tenant = tenant

    async def get_membership_for_update(
        self, tenant_id: UUID, person_id: UUID
    ) -> MembershipSnapshot | None:
        if self.membership is not None and (
            self.membership.tenant_id == tenant_id and self.membership.person_id == person_id
        ):
            return self.membership
        return None

    async def save_membership(self, membership: MembershipSnapshot) -> None:
        self.membership = membership


def _person(*, email_verified_at: datetime | None = NOW) -> PersonSnapshot:
    return PersonSnapshot(
        id=PERSON_ID,
        email="admin@authorityclosers.com",
        email_verified_at=email_verified_at,
    )


@pytest.fixture()
def repositories(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[FakeIdentityRepository, FakeTenantRepository]:
    identity = FakeIdentityRepository(object())
    tenancy = FakeTenantRepository(object())
    monkeypatch.setattr(bootstrap_module, "AsyncSqlAlchemyIdentityRepository", lambda _: identity)
    monkeypatch.setattr(bootstrap_module, "AsyncSqlAlchemyTenantRepository", lambda _: tenancy)
    return identity, tenancy


@pytest.mark.asyncio
async def test_bootstrap_requires_existing_verified_oauth_person(
    repositories: tuple[FakeIdentityRepository, FakeTenantRepository],
) -> None:
    identity, _ = repositories
    identity.people = (_person(email_verified_at=None),)

    with pytest.raises(BootstrapError, match="not verified"):
        await BootstrapApplication(cast(AsyncSession, TransactionalSession())).bootstrap_owner(
            email=" admin@AUTHORITYCLOSERS.COM ",
            tenant_slug="authority-closers",
            tenant_name="Authority Closers",
            now=NOW,
        )

    identity.people = (_person(),)
    identity.has_provider = False
    with pytest.raises(BootstrapError, match="no existing OAuth"):
        await BootstrapApplication(cast(AsyncSession, TransactionalSession())).bootstrap_owner(
            email="admin@authorityclosers.com",
            tenant_slug="authority-closers",
            tenant_name="Authority Closers",
            now=NOW,
        )


@pytest.mark.asyncio
async def test_bootstrap_requires_caller_owned_transaction() -> None:
    class UntransactionalSession:
        def get_transaction(self) -> None:
            return None

    with pytest.raises(BootstrapError, match="caller-owned"):
        await BootstrapApplication(cast(AsyncSession, UntransactionalSession())).bootstrap_owner(
            email="admin@authorityclosers.com",
            tenant_slug="authority-closers",
            tenant_name="Authority Closers",
            now=NOW,
        )


@pytest.mark.asyncio
async def test_bootstrap_creates_owner_and_is_idempotent(
    repositories: tuple[FakeIdentityRepository, FakeTenantRepository],
) -> None:
    identity, tenancy = repositories
    identity.people = (_person(),)
    identity.sessions_updated = 3
    application = BootstrapApplication(cast(AsyncSession, TransactionalSession()))

    first = await application.bootstrap_owner(
        email="admin@authorityclosers.com",
        tenant_slug="authority-closers",
        tenant_name="Authority Closers",
        now=NOW,
    )
    second = await application.bootstrap_owner(
        email="admin@authorityclosers.com",
        tenant_slug="authority-closers",
        tenant_name="Authority Closers",
        now=NOW,
    )

    assert first.tenant_created is True
    assert first.membership_created is True
    assert first.sessions_updated == 3
    assert second.tenant_created is False
    assert second.membership_created is False
    assert second.tenant_id == first.tenant_id
    assert tenancy.membership is not None
    assert tenancy.membership.role == "owner"


@pytest.mark.asyncio
async def test_public_learner_tenant_bootstrap_is_idempotent_and_creates_no_membership(
    repositories: tuple[FakeIdentityRepository, FakeTenantRepository],
) -> None:
    _, tenancy = repositories
    tenancy.operations_tenant = TenantSnapshot(
        id=OPERATIONS_TENANT_ID,
        slug="authority-closers-operations",
        name="Authority Closers Operations",
        status=TenantStatus.ACTIVE.value,
    )
    application = BootstrapApplication(cast(AsyncSession, TransactionalSession()))

    first = await application.bootstrap_public_learner_tenant(
        tenant_slug="authority-closers-public-learners",
        tenant_name="Authority Closers Public Learners",
        operations_tenant_id=OPERATIONS_TENANT_ID,
    )
    second = await application.bootstrap_public_learner_tenant(
        tenant_slug="authority-closers-public-learners",
        tenant_name="Authority Closers Public Learners",
        operations_tenant_id=OPERATIONS_TENANT_ID,
    )

    assert first.tenant_created is True
    assert second.tenant_created is False
    assert second.tenant_id == first.tenant_id
    assert tenancy.tenant is not None
    assert tenancy.operations_tenant.status == TenantStatus.ACTIVE.value
    assert tenancy.tenant.status == TenantStatus.ACTIVE.value
    assert tenancy.membership is None


@pytest.mark.asyncio
async def test_public_learner_tenant_bootstrap_rejects_omitted_operations_id(
    repositories: tuple[FakeIdentityRepository, FakeTenantRepository],
) -> None:
    _, tenancy = repositories
    tenancy.tenant = TenantSnapshot(
        id=OPERATIONS_TENANT_ID,
        slug="authority-closers-public-learners",
        name="Authority Closers Public Learners",
    )

    with pytest.raises(BootstrapError, match="required to prove"):
        await BootstrapApplication(
            cast(AsyncSession, TransactionalSession())
        ).bootstrap_public_learner_tenant(
            tenant_slug="authority-closers-public-learners",
            tenant_name="Authority Closers Public Learners",
        )

    assert tenancy.tenant.id == OPERATIONS_TENANT_ID
    assert tenancy.membership is None


@pytest.mark.asyncio
async def test_public_learner_tenant_bootstrap_rejects_unknown_operations_id(
    repositories: tuple[FakeIdentityRepository, FakeTenantRepository],
) -> None:
    with pytest.raises(BootstrapError, match="isolation cannot be proven"):
        await BootstrapApplication(
            cast(AsyncSession, TransactionalSession())
        ).bootstrap_public_learner_tenant(
            tenant_slug="authority-closers-public-learners",
            tenant_name="Authority Closers Public Learners",
            operations_tenant_id=OPERATIONS_TENANT_ID,
        )


@pytest.mark.asyncio
async def test_public_learner_tenant_bootstrap_rejects_suspended_operations_tenant(
    repositories: tuple[FakeIdentityRepository, FakeTenantRepository],
) -> None:
    _, tenancy = repositories
    tenancy.operations_tenant = TenantSnapshot(
        id=OPERATIONS_TENANT_ID,
        slug="authority-closers-operations",
        name="Authority Closers Operations",
        status=TenantStatus.SUSPENDED.value,
    )

    with pytest.raises(BootstrapError, match="operations control tenant is not active"):
        await BootstrapApplication(
            cast(AsyncSession, TransactionalSession())
        ).bootstrap_public_learner_tenant(
            tenant_slug="authority-closers-public-learners",
            tenant_name="Authority Closers Public Learners",
            operations_tenant_id=OPERATIONS_TENANT_ID,
        )

    assert tenancy.operations_tenant.status == TenantStatus.SUSPENDED.value
    assert tenancy.tenant is None
    assert tenancy.membership is None


@pytest.mark.asyncio
async def test_public_learner_tenant_bootstrap_rejects_operations_tenant_collision(
    repositories: tuple[FakeIdentityRepository, FakeTenantRepository],
) -> None:
    _, tenancy = repositories
    tenancy.tenant = TenantSnapshot(
        id=TENANT_ID,
        slug="authority-closers-public-learners",
        name="Authority Closers Public Learners",
    )

    with pytest.raises(BootstrapError, match="different from the operations"):
        await BootstrapApplication(
            cast(AsyncSession, TransactionalSession())
        ).bootstrap_public_learner_tenant(
            tenant_slug="authority-closers-public-learners",
            tenant_name="Authority Closers Public Learners",
            operations_tenant_id=TENANT_ID,
        )


@pytest.mark.asyncio
async def test_bootstrap_fails_closed_on_tenant_name_or_membership_conflict(
    repositories: tuple[FakeIdentityRepository, FakeTenantRepository],
) -> None:
    identity, tenancy = repositories
    identity.people = (_person(),)
    tenancy.tenant = TenantSnapshot(id=TENANT_ID, slug="authority-closers", name="Other")

    with pytest.raises(BootstrapError, match="different name"):
        await BootstrapApplication(cast(AsyncSession, TransactionalSession())).bootstrap_owner(
            email="admin@authorityclosers.com",
            tenant_slug="authority-closers",
            tenant_name="Authority Closers",
            now=NOW,
        )

    tenancy.tenant = TenantSnapshot(
        id=TENANT_ID, slug="authority-closers", name="Authority Closers"
    )
    tenancy.membership = MembershipSnapshot(
        tenant_id=TENANT_ID,
        person_id=PERSON_ID,
        role="admin",
    )
    with pytest.raises(BootstrapError, match="not an active owner"):
        await BootstrapApplication(cast(AsyncSession, TransactionalSession())).bootstrap_owner(
            email="admin@authorityclosers.com",
            tenant_slug="authority-closers",
            tenant_name="Authority Closers",
            now=NOW,
        )


@pytest.mark.asyncio
async def test_new_production_session_uses_sole_active_tenant() -> None:
    tenant_id = uuid4()

    class Repository:
        def __init__(self) -> None:
            self.session: StoredSession | None = None

        async def get_sole_active_tenant_id(self, person_id: UUID) -> UUID:
            assert person_id == PERSON_ID
            return tenant_id

        async def save_session(self, session: StoredSession) -> None:
            self.session = session

    repository = Repository()
    application = cast(Any, object.__new__(AsyncIdentityApplication))
    application._repository = repository
    application._session_ttl = timedelta(days=30)
    application._token_length_bytes = 32
    application._token_pepper = b"p" * 32
    issued = await application._issue_session(
        _person(),
        current_time=NOW,
        user_agent=None,
        ip_address=None,
    )

    assert issued.metadata.selected_tenant_id == tenant_id
    assert repository.session is not None
    assert repository.session.selected_tenant_id == tenant_id


@pytest.mark.asyncio
async def test_new_production_session_stays_unscoped_without_sole_active_tenant() -> None:
    class Repository:
        def __init__(self) -> None:
            self.session: StoredSession | None = None

        async def get_sole_active_tenant_id(self, person_id: UUID) -> None:
            assert person_id == PERSON_ID
            return None

        async def save_session(self, session: StoredSession) -> None:
            self.session = session

    repository = Repository()
    application = cast(Any, object.__new__(AsyncIdentityApplication))
    application._repository = repository
    application._session_ttl = timedelta(days=30)
    application._token_length_bytes = 32
    application._token_pepper = b"p" * 32
    issued = await application._issue_session(
        _person(),
        current_time=NOW,
        user_agent=None,
        ip_address=None,
    )

    assert issued.metadata.selected_tenant_id is None
    assert repository.session is not None
    assert repository.session.selected_tenant_id is None
