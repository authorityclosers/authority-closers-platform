from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as DbSession

from ac_platform.db.base import Base
from ac_platform.tenancy.repositories import SqlAlchemyTenantStore
from ac_platform.tenancy.services import (
    MembershipSnapshot,
    TenantConcurrencyError,
    TenantContextService,
    TenantSnapshot,
)


def test_sqlalchemy_tenant_store_preserves_composite_membership_scope_and_revision() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    person_id = uuid4()
    tenant_id = uuid4()
    try:
        with DbSession(engine) as session:
            store = SqlAlchemyTenantStore(session)
            tenant = TenantSnapshot(id=tenant_id, slug="ac", name="Authority Closers")
            membership = MembershipSnapshot(
                tenant_id=tenant_id,
                person_id=person_id,
                role="learner",
            )
            # The membership FK is part of the durable boundary, so seed the
            # referenced person through the model registry's identity table.
            from ac_platform.identity.models import Person

            session.add(Person(id=person_id))
            store.save_tenant(tenant)
            store.save_membership(membership)
            session.commit()

            assert store.get_tenant(tenant_id) == tenant
            assert store.get_membership(tenant_id, person_id) == membership
            assert TenantContextService(store).select(person_id, tenant_id).tenant_id == tenant_id
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_sqlalchemy_tenant_store_rejects_stale_tenant_revision() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    tenant_id = uuid4()
    try:
        with DbSession(engine) as session:
            store = SqlAlchemyTenantStore(session)
            tenant = TenantSnapshot(id=tenant_id, slug="ac", name="Before")
            store.save_tenant(tenant)
            session.commit()
            stale = store.get_tenant(tenant_id)
            assert stale is not None
            store.save_tenant(replace(stale, name="After", revision=stale.revision + 1))
            session.commit()

            with pytest.raises(TenantConcurrencyError):
                store.save_tenant(replace(stale, name="Lost", revision=stale.revision + 1))
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
