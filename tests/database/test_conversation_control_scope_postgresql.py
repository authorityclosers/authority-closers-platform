"""PostgreSQL proof that provider control stays in OPS while calls stay public.

The fixtures use synthetic zero-cost provider references and the existing
disposable conversation harness.  No provider credentials or network calls are
used; the broker is the deterministic reporting test double.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update

from ac_platform.conversation_intelligence.activation_contract import HostedApprovalBundle
from ac_platform.conversation_intelligence.application import ConversationDenied
from ac_platform.conversation_intelligence.authority import ConversationAuthority
from ac_platform.conversation_intelligence.contracts import QuoteAcceptance
from ac_platform.conversation_intelligence.inference import ConversationInference
from ac_platform.conversation_intelligence.inference_worker import ConversationInferenceWorker
from ac_platform.conversation_intelligence.models import (
    ConversationProviderConfiguration,
    ConversationRun,
)
from ac_platform.conversation_intelligence.provider_admin import (
    CONTROL_ACCOUNT,
    ConversationProviderAdmin,
)
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.kernel.authz import ActorContext
from ac_platform.tenancy.models import Membership, Tenant
from tests.database.test_conversation_authority_postgresql import (
    AuthorityFixture,
    _application,
    _bundle,
    _registry_config,
    _setup,
)
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_reporting_pipeline_postgresql import completed_checkpoint
from tests.database.test_conversation_worker_postgresql import _postgres_harness


@pytest.fixture
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


@dataclass(frozen=True, slots=True)
class ControlScope:
    setup: AuthorityFixture
    operations_tenant_id: UUID
    operations_session_id: UUID
    public_actor: ActorContext
    authority: ConversationAuthority
    bundle_box: dict[str, HostedApprovalBundle]
    config_view: dict[str, Any]


async def _control_scope(setup: AuthorityFixture) -> ControlScope:
    state = setup.prepared.state
    operations_tenant_id = uuid4()
    operations_session_id = uuid4()
    public_actor = ActorContext(state.person_id, state.session_id, state.tenant_id)
    operations_actor = ActorContext(
        state.person_id,
        operations_session_id,
        operations_tenant_id,
        frozenset({"admin_surface"}),
    )

    async with setup.sessions() as database, database.begin():
        public_membership = await database.get(Membership, (state.tenant_id, state.person_id))
        assert public_membership is not None
        public_membership.role = "learner"
        database.add(
            Tenant(
                id=operations_tenant_id,
                slug=f"ops-{operations_tenant_id.hex}",
                name="Disposable Sales Xray operations tenant",
                status="active",
            )
        )
        await database.flush()
        database.add(
            Membership(
                tenant_id=operations_tenant_id,
                person_id=state.person_id,
                role="owner",
                status="active",
            )
        )
        await database.flush()
        database.add(
            IdentitySession(
                id=operations_session_id,
                person_id=state.person_id,
                token_hash=operations_session_id.bytes * 2,
                created_at=state.now,
                expires_at=state.now + timedelta(days=1),
                selected_tenant_id=operations_tenant_id,
            )
        )
        await database.flush()
        config_view = await ConversationProviderAdmin(_application(setup, database)).save(
            operations_actor,
            _registry_config("ops-hosted-control-config-v1").as_dict(),
            expected_revision=0,
            key=f"ops-provider-config-{uuid4().hex}",
        )

    bundle = _bundle(
        state,
        state.source_sha256,
        config_view["configuration_sha256"],
        now_epoch=int(state.now.timestamp()),
    ).model_copy(update={"provider_control_tenant_id": operations_tenant_id})
    bundle_box = {"bundle": bundle}
    authority = ConversationAuthority(
        lambda: bundle_box["bundle"],
        environment="test",
        operations_tenant_id=operations_tenant_id,
    )
    async with setup.sessions() as database, database.begin():
        await authority.claim_allowance(_application(setup, database), public_actor)

    return ControlScope(
        setup,
        operations_tenant_id,
        operations_session_id,
        public_actor,
        authority,
        bundle_box,
        config_view,
    )


async def _issue_public(
    scope: ControlScope,
    *,
    key: str,
    authority: ConversationAuthority | None = None,
) -> dict[str, Any]:
    async with scope.setup.sessions() as database, database.begin():
        return await (authority or scope.authority).issue(
            _application(scope.setup, database),
            scope.public_actor,
            scope.setup.prepared.recording_id,
            key=key,
        )


async def _start_public(scope: ControlScope, quote: dict[str, Any], *, key: str) -> dict[str, Any]:
    async with scope.setup.sessions() as database, database.begin():
        service = ConversationInference(
            _application(scope.setup, database), authority=scope.authority
        )
        await service.accept(
            scope.public_actor,
            scope.setup.prepared.recording_id,
            UUID(quote["id"]),
            QuoteAcceptance(
                quote_fingerprint=quote["quote_fingerprint"],
                privacy_revision=quote["privacy_revision"],
                accepted=True,
            ),
        )
        return await service.request_transcription(
            scope.public_actor,
            scope.setup.prepared.recording_id,
            UUID(quote["id"]),
            key=key,
        )


def test_ops_control_can_issue_and_settle_public_c2_without_public_admin_access(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            scope = await _control_scope(setup)
            assert scope.authority.operations_tenant_id == scope.operations_tenant_id
            assert scope.public_actor.permissions == frozenset()
            assert scope.config_view["revision"] == 1
            assert (
                scope.config_view["configuration_sha256"]
                != setup.config_view["configuration_sha256"]
            )

            async with setup.sessions() as database:
                ops_config = await database.scalar(
                    select(ConversationProviderConfiguration).where(
                        ConversationProviderConfiguration.tenant_id == scope.operations_tenant_id
                    )
                )
                public_config = await database.scalar(
                    select(ConversationProviderConfiguration).where(
                        ConversationProviderConfiguration.tenant_id
                        == setup.prepared.state.tenant_id
                    )
                )
                ops_membership = await database.get(
                    Membership,
                    (scope.operations_tenant_id, setup.prepared.state.person_id),
                )
                public_membership = await database.get(
                    Membership,
                    (setup.prepared.state.tenant_id, setup.prepared.state.person_id),
                )
                assert (
                    ops_config is not None
                    and ops_config.person_id == setup.prepared.state.person_id
                )
                assert public_config is not None
                assert ops_config.configuration_sha256 == scope.config_view["configuration_sha256"]
                assert (
                    public_config.configuration_sha256 == setup.config_view["configuration_sha256"]
                )
                assert ops_membership is not None and ops_membership.role == "owner"
                assert public_membership is not None and public_membership.role == "learner"

            quote = await _issue_public(scope, key="ops-public-c2-quote")
            assert quote["stage"] == "C2"
            assert quote["provider"] == "elevenlabs"
            assert quote["input_sha256"] == setup.prepared.state.source_sha256

            run_view = await _start_public(scope, quote, key="ops-public-c2-run")
            worker = ConversationInferenceWorker(
                setup.sessions,
                setup.prepared.storage,
                setup.broker,
                authority=scope.authority,
            )
            assert await worker.run_once()
            assert await completed_checkpoint(setup.sessions, run_view)
            async with setup.sessions() as database:
                settled = await database.get(ConversationRun, UUID(run_view["id"]))
                assert settled is not None
                assert settled.tenant_id == setup.prepared.state.tenant_id
            assert setup.broker.calls == 1
        finally:
            await setup.engine.dispose()

    run(exercise())


@pytest.mark.parametrize("failure", ["configured_operations_tenant", "bundle_control_tenant"])
def test_control_scope_rejects_wrong_configured_or_bundle_tenant(
    postgres_harness: Any, tmp_path: Path, failure: str
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            scope = await _control_scope(setup)
            if failure == "configured_operations_tenant":
                authority = ConversationAuthority(
                    lambda: scope.bundle_box["bundle"],
                    environment="test",
                    operations_tenant_id=uuid4(),
                )
            else:
                wrong_bundle_box = {
                    "bundle": scope.bundle_box["bundle"].model_copy(
                        update={"provider_control_tenant_id": uuid4()}
                    )
                }
                authority = ConversationAuthority(
                    lambda: wrong_bundle_box["bundle"],
                    environment="test",
                    operations_tenant_id=scope.operations_tenant_id,
                )
            with pytest.raises(ConversationDenied):
                await _issue_public(
                    scope,
                    key=f"wrong-control-scope-{failure}",
                    authority=authority,
                )
            assert setup.broker.calls == 0
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_control_scope_rechecks_revoked_membership_changed_email_and_suspended_tenant(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def expect_denied(scope: ControlScope, key: str) -> None:
        with pytest.raises(ConversationDenied, match="control"):
            await _issue_public(scope, key=key)

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            scope = await _control_scope(setup)
            state = setup.prepared.state

            async with setup.sessions() as database, database.begin():
                await database.execute(
                    update(Membership)
                    .where(
                        Membership.tenant_id == scope.operations_tenant_id,
                        Membership.person_id == state.person_id,
                    )
                    .values(role="learner")
                )
            await expect_denied(scope, "control-role-change")

            async with setup.sessions() as database, database.begin():
                await database.execute(
                    update(Membership)
                    .where(
                        Membership.tenant_id == scope.operations_tenant_id,
                        Membership.person_id == state.person_id,
                    )
                    .values(role="owner", status="inactive", ended_at=state.now)
                )
            await expect_denied(scope, "control-membership-revoked")

            async with setup.sessions() as database, database.begin():
                await database.execute(
                    update(Membership)
                    .where(
                        Membership.tenant_id == scope.operations_tenant_id,
                        Membership.person_id == state.person_id,
                    )
                    .values(status="active", ended_at=None)
                )
                await database.execute(
                    update(Person)
                    .where(Person.id == state.person_id)
                    .values(email="changed-control@example.test")
                )
            await expect_denied(scope, "control-email-change")

            async with setup.sessions() as database, database.begin():
                await database.execute(
                    update(Person).where(Person.id == state.person_id).values(email=CONTROL_ACCOUNT)
                )
                await database.execute(
                    update(Tenant)
                    .where(Tenant.id == scope.operations_tenant_id)
                    .values(status="suspended")
                )
            await expect_denied(scope, "control-tenant-suspension")
            assert setup.broker.calls == 0
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_control_scope_does_not_grant_processing_to_a_nonrecipient(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            scope = await _control_scope(setup)
            scope.bundle_box["bundle"] = scope.bundle_box["bundle"].model_copy(
                update={"allowances": ()}
            )
            with pytest.raises(ConversationDenied, match="allowance"):
                await _issue_public(scope, key="control-nonrecipient")
            assert setup.broker.calls == 0
        finally:
            await setup.engine.dispose()

    run(exercise())
