"""DNS proof precedes registry locks and is checked against the locked version."""

from uuid import uuid4

import pytest
from sqlalchemy import select

from ac_platform.organisations.service import OrganisationDomainConflict
from ac_platform.tenancy.models import OrganisationDomainSetting
from tests.unit.organisations.test_service import create_org, state  # noqa: F401


async def test_dns_proof_runs_before_any_registry_lock(state, monkeypatch):  # noqa: F811
    org = await create_org(state)
    order = []
    for method in ("scalar", "scalars"):
        original = getattr(state.adapter, method)

        async def observe(statement, original=original):
            if statement._for_update_arg is not None:
                order.append("lock")
            return await original(statement)

        monkeypatch.setattr(state.adapter, method, observe)

    async def verify(domain, token):
        assert domain == "example.test" and token
        order.append("verify")

    await state.service.set_domains_attested(
        org.tenant_id,
        ["example.test"],
        True,
        "fictional DNS proof",
        uuid4(),
        actor_person_id=state.owner_id,
        verify_domain=verify,
    )
    assert order[0] == "verify" and "lock" in order[1:]


async def test_changed_domains_require_retry_when_proof_did_not_cover_new_domain(state):  # noqa: F811
    org = await create_org(state)
    await state.service.set_domains_attested(
        org.tenant_id, ["existing.test"], True, "fictional proof", uuid4()
    )
    checked = []

    async def verify(domain, token):
        checked.append(domain)
        # Another command removes the previously verified domain before locking.
        await state.service.set_domains_attested(
            org.tenant_id, [], False, "fictional concurrent change", uuid4()
        )

    command_id = uuid4()
    with pytest.raises(OrganisationDomainConflict, match="domains changed, retry"):
        await state.service.set_domains_attested(
            org.tenant_id,
            ["existing.test", "new.test"],
            True,
            "fictional DNS proof",
            command_id,
            actor_person_id=state.owner_id,
            verify_domain=verify,
        )
    assert checked == ["new.test"]
    assert (
        state.session.scalar(
            select(OrganisationDomainSetting).where(
                OrganisationDomainSetting.command_id == command_id
            )
        )
        is None
    )
