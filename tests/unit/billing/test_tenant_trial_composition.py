"""Checkout projections retain Personal trials and never derive an Organisation trial."""

from uuid import uuid4

import pytest
from sqlalchemy import select

from ac_platform.billing.catalogue import StaticCatalogue
from ac_platform.billing.checkout import CheckoutService
from ac_platform.billing.commands import Caller
from ac_platform.billing.trial import TrialPolicy, trial_enabled_for_tenant
from ac_platform.payments.registry import PaymentProviderRegistry
from ac_platform.tenancy.models import Membership, Organisation
from tests.unit.billing.test_ledger import T0
from tests.unit.billing.test_ledger import state as state  # noqa: F401


@pytest.mark.parametrize("personal", [True, False])
@pytest.mark.parametrize("version,trial_seconds", [("v1", 3600), ("v2", 6000)])
async def test_checkout_projection_keeps_grants_and_tenant_trial(
    state, monkeypatch, personal, version, trial_seconds
):
    service = CheckoutService(
        catalogue=StaticCatalogue(),
        providers=PaymentProviderRegistry(),
        public_learner_tenant_id=state.tenant if personal else uuid4(),
        operations_tenant_id=state.operations,
        return_url_base="https://salesxray.example.test",
        trial_policy=TrialPolicy(version),
        clock=lambda: T0,
    )
    if not personal:
        state.db.add(
            Organisation(
                tenant_id=state.tenant,
                creation_command_id=uuid4(),
                domain_verification_token="x" * 43,
            )
        )
        state.db.scalar(
            select(Membership).where(Membership.tenant_id == state.tenant)
        ).role = "owner"
        state.db.flush()
    composed = []
    original = service.ledger

    async def get(model, identifier):
        return state.db.get(model, identifier)

    monkeypatch.setattr(state.async_db, "get", get, raising=False)

    def capture(database, *, tenant_id):
        ledger = original(database, tenant_id=tenant_id)
        composed.append(ledger)
        return ledger

    monkeypatch.setattr(service, "ledger", capture)
    await service.resolve_account(
        state.async_db,
        Caller(state.person, state.session, None if personal else state.tenant, "owner"),
        "personal" if personal else "organisation",
        write=True,
    )
    ledger = composed[0]
    assert ledger.trial_enabled is personal
    account = await ledger.personal_account(
        tenant_id=state.tenant, person_id=state.person, create=True
    )
    state.rows.append(
        await ledger.write_lot(
            account=account,
            kind="grant",
            seconds=600,
            valid_from=T0,
            source_ref="fictional:tenant-trial-grant",
            actor_type="system",
        )
    )
    projected = await ledger.project_person(tenant_id=state.tenant, person_id=state.person, now=T0)
    assert projected.available_seconds == 600 + (trial_seconds if personal else 0)
    assert (projected.trial is not None) is personal
    with pytest.raises(TypeError, match="tenant_id"):
        service.ledger(state.async_db)
    assert service.ledger(state.async_db, tenant_id=state.operations).trial_enabled is False


def test_missing_public_identity_never_derives_a_trial():
    assert trial_enabled_for_tenant(uuid4(), None) is False
    assert trial_enabled_for_tenant(None, None) is False
