"""Who Sales X-Ray records usage analytics for (owner, 24 Oct 2026, option B)."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from ac_platform.audit.models import AuditEvent
from ac_platform.conversation_intelligence.synthetic_import_models import (
    ConversationSandboxOrganisation,
)
from ac_platform.db.models import model_metadata
from ac_platform.identity.models import Person
from ac_platform.kernel.authz import ActorContext
from ac_platform.telemetry.ingest import TelemetryConsentStatus
from ac_platform.telemetry.sales_xray import NOTICE_EFFECTIVE_AT, NOTICE_VERSION
from ac_platform.telemetry.sales_xray_consent import (
    PERSON_ACTION,
    RESOURCE_TYPE,
    WORKSPACE_ACTION,
    read_standing,
    sales_xray_consent,
)
from ac_platform.tenancy.models import Membership, Tenant


class _Database:
    def __init__(self, session: Session) -> None:
        self.session = session

    async def run_sync(self, operation):  # type: ignore[no-untyped-def]
        return operation(self.session)


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    model_metadata().create_all(engine)
    made = Session(engine)
    try:
        yield made
    finally:
        made.close()
        engine.dispose()


def _workspace(session: Session, person_id: UUID) -> UUID:
    tenant_id = uuid4()
    session.add(Tenant(id=tenant_id, slug=f"w-{tenant_id.hex}", name="Workspace"))
    session.flush()
    session.add(
        Membership(tenant_id=tenant_id, person_id=person_id, role="member", status="active")
    )
    session.flush()
    return tenant_id


def _choice(
    session: Session, tenant_id: UUID, resource_id: str, enabled: bool, at: datetime
) -> None:
    sequence = session.query(AuditEvent).filter(AuditEvent.tenant_id == tenant_id).count() + 1
    session.add(
        AuditEvent(
            id=uuid4(),
            tenant_id=tenant_id,
            sequence_no=sequence,
            actor_person_id=None,
            actor_type="system",
            action=WORKSPACE_ACTION if resource_id == "workspace" else PERSON_ACTION,
            resource_type=RESOURCE_TYPE,
            resource_id=resource_id,
            payload={"enabled": enabled, "notice_version": NOTICE_VERSION},
            occurred_at=at,
            recorded_at=at,
            previous_hash="0" * 64,
            event_hash=f"{sequence:064x}",
        )
    )
    session.flush()


def test_on_by_default_off_for_a_person_everywhere_and_back_on_from_then(
    session: Session,
) -> None:
    person_id = uuid4()
    session.add(Person(id=person_id, email=f"p-{person_id.hex}@example.test"))
    session.flush()
    first, second = _workspace(session, person_id), _workspace(session, person_id)
    standing = read_standing(session, tenant_id=first, person_id=person_id)
    assert standing.collecting
    assert standing.since == NOTICE_EFFECTIVE_AT

    now = datetime.now(UTC)
    # Turned off in one workspace: off in every workspace they belong to.
    _choice(session, first, str(person_id), False, now - timedelta(hours=2))
    assert not read_standing(session, tenant_id=second, person_id=person_id).collecting
    # Back on (in the other workspace): recording restarts from then.
    _choice(session, second, str(person_id), True, now - timedelta(hours=1))
    standing = read_standing(session, tenant_id=first, person_id=person_id)
    assert standing.collecting
    assert standing.since == now - timedelta(hours=1)

    # A workspace switched off covers only that workspace.
    _choice(session, first, "workspace", False, now)
    assert not read_standing(session, tenant_id=first, person_id=person_id).collecting
    assert read_standing(session, tenant_id=second, person_id=person_id).collecting


def test_the_resolver_grants_denies_and_skips_sandboxes(session: Session) -> None:
    person_id = uuid4()
    session.add(Person(id=person_id, email=f"p-{person_id.hex}@example.test"))
    session.flush()
    tenant_id = _workspace(session, person_id)
    actor = ActorContext(person_id=person_id, session_id=uuid4(), tenant_id=tenant_id)
    database = _Database(session)

    granted = asyncio.run(sales_xray_consent(database, actor))
    assert granted is not None
    assert granted.status is TelemetryConsentStatus.GRANTED
    assert granted.policy_version == NOTICE_VERSION
    assert (granted.tenant_id, granted.person_id, granted.session_id) == (
        tenant_id,
        person_id,
        actor.session_id,
    )

    _choice(session, tenant_id, "workspace", False, datetime.now(UTC))
    denied = asyncio.run(sales_xray_consent(database, actor))
    assert denied is not None
    assert denied.status is TelemetryConsentStatus.DENIED

    session.add(
        ConversationSandboxOrganisation(
            tenant_id=tenant_id,
            approved_by_person_id=person_id,
            approval_reference="test",
            created_at=datetime.now(UTC),
        )
    )
    session.flush()
    assert asyncio.run(sales_xray_consent(database, actor)) is None
    no_workspace = ActorContext(person_id=person_id, session_id=uuid4(), tenant_id=None)
    assert asyncio.run(sales_xray_consent(database, no_workspace)) is None
