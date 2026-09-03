from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.identity.models import Person, PersonStatus
from ac_platform.tenancy.learner_provisioning import (
    AsyncLearnerProvisioningApplication,
    LearnerProvisioningError,
)
from ac_platform.tenancy.models import (
    Membership,
    MembershipRole,
    MembershipStatus,
    Tenant,
    TenantStatus,
)

NOW = datetime(2026, 9, 1, 12, tzinfo=UTC)
CONSENT_VERSION = "learner-consent-v1"


class _NestedTransaction:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_args: object) -> bool:
        return False


class _PrivilegedMembershipRaceSession:
    def __init__(self, *, person: Person, tenant: Tenant, membership: Membership) -> None:
        self._scalar_results = [person, tenant, None, membership]
        self.added: list[object] = []

    async def scalar(self, _statement: object) -> Any:
        return self._scalar_results.pop(0)

    def begin_nested(self) -> _NestedTransaction:
        return _NestedTransaction()

    def add(self, row: object) -> None:
        self.added.append(row)

    async def flush(self) -> None:
        raise IntegrityError("membership insert", {}, RuntimeError("duplicate membership"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role",
    [MembershipRole.OWNER.value, MembershipRole.ADMIN.value, MembershipRole.SUPPORT.value],
)
async def test_privileged_membership_winning_insert_race_is_preserved_but_rejected(
    role: str,
) -> None:
    person_id = uuid4()
    tenant_id = uuid4()
    person = Person(
        id=person_id,
        email=f"learner-{person_id.hex}@example.test",
        status=PersonStatus.ACTIVE.value,
        email_verified_at=NOW,
        consent_version=CONSENT_VERSION,
        consented_at=NOW,
    )
    tenant = Tenant(
        id=tenant_id,
        slug=f"public-learners-{tenant_id.hex}",
        name="Authority Closers Public Learners",
        status=TenantStatus.ACTIVE.value,
    )
    privileged_membership = Membership(
        tenant_id=tenant_id,
        person_id=person_id,
        role=role,
        status=MembershipStatus.ACTIVE.value,
    )
    session = _PrivilegedMembershipRaceSession(
        person=person,
        tenant=tenant,
        membership=privileged_membership,
    )

    with pytest.raises(LearnerProvisioningError, match="raced.*exactly learner"):
        await AsyncLearnerProvisioningApplication(cast(AsyncSession, session)).ensure(
            person_id=person_id,
            tenant_id=tenant_id,
            required_consent_version=CONSENT_VERSION,
        )

    assert privileged_membership.role == role
    assert len(session.added) == 1
    candidate = session.added[0]
    assert isinstance(candidate, Membership)
    assert candidate.role == MembershipRole.LEARNER.value
