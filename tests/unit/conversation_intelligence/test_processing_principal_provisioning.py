"""Real CLI and ownership provisioning with fictional persistence/audit adapters."""

from __future__ import annotations

from argparse import Namespace
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest

import ac_platform.conversation_intelligence.processing_cli as cli
from ac_platform.audit.service import AuditRepository
from ac_platform.conversation_intelligence.acquisition_sessions import AcquisitionSessions
from ac_platform.conversation_intelligence.application import ConversationDenied
from ac_platform.conversation_intelligence.authority import ConversationAuthority
from ac_platform.conversation_intelligence.entitlements import MinuteAccount
from ac_platform.conversation_intelligence.guest_models import ConversationProcessingPrincipal
from ac_platform.conversation_intelligence.models import ConversationMinuteAccount
from ac_platform.conversation_intelligence.processing_actor import ProcessingActor
from ac_platform.identity.models import Person
from ac_platform.tenancy.models import Membership
from tests.unit.conversation_intelligence.test_acquisition_provider_policy import TENANT_ID
from tests.unit.conversation_intelligence.test_organisation_acquisition_policies import (
    CONTROL_ID,
    ORG_ID,
    ORG_PERSON_ID,
    organisation_bundle,
)


@pytest.fixture
def provisioning(monkeypatch):
    bundle = organisation_bundle()
    settings = SimpleNamespace(
        public_learner_tenant_id=TENANT_ID, database_url="unused", release_id="test"
    )
    monkeypatch.setenv("AC_ENVIRONMENT", "test")
    monkeypatch.setenv("AC_DATABASE_URL", "unused")
    monkeypatch.setattr(cli, "Settings", lambda **kwargs: settings)
    load_bundle = Mock(return_value=bundle)
    monkeypatch.setattr(cli, "load_pinned_approval", load_bundle)
    now = datetime.fromtimestamp(1100, UTC)
    monkeypatch.setattr(AcquisitionSessions, "_admit", AsyncMock(return_value=now))
    audit = AsyncMock()
    monkeypatch.setattr(AuditRepository, "append", audit)
    rows = []
    database = SimpleNamespace(committed=False, rolled_back=False)

    async def get(model, key):
        for row in rows:
            if not isinstance(row, model):
                continue
            identity = (
                (row.tenant_id, row.person_id)
                if isinstance(row, (Membership, ConversationMinuteAccount))
                else row.id
            )
            if identity == key:
                return row
        return None

    database.get = AsyncMock(side_effect=get)
    database.scalar = AsyncMock(
        side_effect=lambda statement: next(
            (row for row in rows if isinstance(row, ConversationProcessingPrincipal)), None
        )
    )
    database.add = Mock(side_effect=rows.append)
    database.flush = AsyncMock()

    @asynccontextmanager
    async def session():
        yield database

    @asynccontextmanager
    async def transaction():
        try:
            yield
        except Exception:
            database.rolled_back = True
            raise
        else:
            database.committed = True

    database.begin = transaction
    engine = SimpleNamespace(dispose=AsyncMock())
    create_engine = Mock(return_value=engine)
    monkeypatch.setattr(cli, "create_async_engine", create_engine)
    monkeypatch.setattr(cli, "async_sessionmaker", lambda *args, **kwargs: session)
    args = Namespace(
        environment="test",
        allow_production=False,
        tenant_id=ORG_ID,
        operator_reference="ref:operator/fictional",
        reason="Fictional provisioning",
    )
    return SimpleNamespace(
        bundle=bundle,
        database=database,
        rows=rows,
        audit=audit,
        args=args,
        engine=engine,
        create_engine=create_engine,
        load_bundle=load_bundle,
    )


async def test_fresh_organisation_principal_matches_same_bundle(provisioning) -> None:
    state = provisioning
    result = await cli.provision(state.args)
    assert result["processing_person_id"] == str(ORG_PERSON_ID)
    assert result["tenant_id"] == str(ORG_ID)
    person, membership, principal, ledger = state.rows
    assert isinstance(person, Person) and person.id == ORG_PERSON_ID
    assert isinstance(membership, Membership) and membership.role == "processing"
    assert isinstance(principal, ConversationProcessingPrincipal)
    assert isinstance(ledger, ConversationMinuteAccount)
    assert membership.tenant_id == principal.tenant_id == ledger.tenant_id == ORG_ID
    assert membership.person_id == principal.person_id == ledger.person_id == ORG_PERSON_ID
    assert MinuteAccount.from_dict(ledger.snapshot).available_seconds == 0
    assert state.database.committed and not state.database.rolled_back
    audit = state.audit.call_args.kwargs
    assert audit["tenant_id"] == ORG_ID
    assert audit["resource_id"] == principal.id
    assert audit["payload"]["processing_person_id"] == str(ORG_PERSON_ID)
    assert audit["reason"] == state.args.reason
    authority = ConversationAuthority(
        lambda: state.bundle, environment="test", operations_tenant_id=CONTROL_ID
    )
    actor = ProcessingActor(
        UUID(result["processing_person_id"]), UUID(result["tenant_id"]), uuid4()
    )
    authority.recipient(state.bundle, actor)
    assert (
        authority.stage_approval(state.bundle, actor, source_sha256="a" * 64, stage="C2")
        is not None
    )
    # Repeating the command resolves the same approved principal, without writes.
    state.database.add.reset_mock()
    state.audit.reset_mock()
    assert await cli.provision(state.args) == result
    state.database.add.assert_not_called()
    state.audit.assert_not_awaited()


@pytest.mark.parametrize("existing", ["mismatched_principal", "person_in_use"])
async def test_organisation_provisioning_refuses_existing_identity_without_rewrite(
    provisioning, existing
) -> None:
    state = provisioning
    if existing == "mismatched_principal":
        row = ConversationProcessingPrincipal(
            id=uuid4(),
            tenant_id=ORG_ID,
            person_id=uuid4(),
            operator_reference="ref:operator/original",
            created_at=datetime.fromtimestamp(1000, UTC),
        )
        message = "does not match the approved person"
        original = (row.id, row.tenant_id, row.person_id, row.operator_reference)
    else:
        row = Person(id=ORG_PERSON_ID, display_name="Existing fictional person", status="active")
        message = "already in use"
        original = (row.id, row.display_name, row.status)
    state.rows.append(row)
    with pytest.raises(ConversationDenied, match=message):
        await cli.provision(state.args)
    assert state.database.rolled_back and not state.database.committed
    assert state.rows == [row]
    actual = (
        (row.id, row.tenant_id, row.person_id, row.operator_reference)
        if existing == "mismatched_principal"
        else (row.id, row.display_name, row.status)
    )
    assert actual == original
    state.database.add.assert_not_called()
    state.audit.assert_not_awaited()
    state.engine.dispose.assert_awaited_once()


async def test_processing_cli_refuses_unlisted_tenant_before_database(provisioning) -> None:
    state = provisioning
    state.args.tenant_id = uuid4()
    with pytest.raises(cli.CommandError, match="approved acquisition provider policy"):
        await cli.provision(state.args)
    state.create_engine.assert_not_called()


async def test_public_bootstrap_keeps_random_non_login_principal_without_bundle(
    provisioning,
) -> None:
    state = provisioning
    state.args.tenant_id = TENANT_ID
    result = await cli.provision(state.args)
    principal = state.rows[2]
    assert UUID(result["processing_person_id"]) == principal.person_id
    assert principal.person_id != ORG_PERSON_ID
    assert principal.tenant_id == TENANT_ID
    state.load_bundle.assert_not_called()
    assert state.database.committed
    assert state.rows[1].role == "processing"
    state.audit.assert_awaited_once()
