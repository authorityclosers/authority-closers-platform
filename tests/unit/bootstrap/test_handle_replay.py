"""Owner bootstrap preserves identity after a handle change, without repair."""

from dataclasses import replace
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.bootstrap import BootstrapApplication, BootstrapError
from ac_platform.tenancy.services import MembershipSnapshot, TenantSnapshot
from tests.unit.bootstrap.test_application import (
    NOW,
    PERSON_ID,
    TENANT_ID,
    TransactionalSession,
    _person,
    repositories,  # noqa: F401
)


async def test_renamed_owner_replay_fails_closed_for_old_handle(repositories):  # noqa: F811
    identity, tenancy = repositories
    identity.people = (replace(_person(), email="owner@example.test"),)
    app = BootstrapApplication(cast(AsyncSession, TransactionalSession()))
    args = {"email": "owner@example.test", "tenant_name": "Fictional Team", "now": NOW}
    first = await app.bootstrap_owner(tenant_slug="fictional-original", **args)
    assert first.tenant_created and first.membership_created
    tenancy.tenant = replace(tenancy.tenant, slug="fictional-renamed")
    before = tenancy.tenant, tenancy.membership
    with pytest.raises(
        BootstrapError,
        match="person already owns a tenant; replay with its current handle "
        "or use the organisation API",
    ):
        await app.bootstrap_owner(tenant_slug="fictional-original", **args)
    assert (tenancy.tenant, tenancy.membership) == before
    replay = await app.bootstrap_owner(tenant_slug="fictional-renamed", **args)
    assert replay.tenant_id == first.tenant_id
    assert not replay.tenant_created and not replay.membership_created


@pytest.mark.parametrize(
    "role,status,ended_at", [("member", "active", None), ("owner", "inactive", NOW)]
)
async def test_non_owner_or_inactive_membership_does_not_block_first_bootstrap(
    repositories,  # noqa: F811
    role,
    status,
    ended_at,
):  # noqa: F811
    identity, tenancy = repositories
    identity.people = (replace(_person(), email="owner@example.test"),)
    tenancy.tenant = TenantSnapshot(TENANT_ID, "fictional-existing", "Existing")
    tenancy.membership = MembershipSnapshot(TENANT_ID, PERSON_ID, role, status, ended_at)
    result = await BootstrapApplication(cast(AsyncSession, TransactionalSession())).bootstrap_owner(
        email="owner@example.test",
        tenant_slug="fictional-first",
        tenant_name="Fictional First",
        now=NOW,
    )
    assert result.tenant_id != TENANT_ID and result.tenant_created and result.membership_created
