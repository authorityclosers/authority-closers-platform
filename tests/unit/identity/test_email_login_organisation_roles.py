from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from ac_platform.db.models import model_metadata
from ac_platform.identity.email_login import (
    EmailLoginCodeService,
    decrypt_email_login_code,
)
from ac_platform.identity.models import EmailLoginCode, Person, PersonStatus
from ac_platform.tenancy.models import (
    Membership,
    MembershipRole,
    Organisation,
    Tenant,
)

_NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
_SECRET = b"email-login-organisation-role-test-secret-32-bytes"


class _NestedTransaction:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._transaction: Any = None

    async def __aenter__(self) -> None:
        self._transaction = self._session.begin_nested()
        self._transaction.__enter__()
        return None

    async def __aexit__(self, *args: object) -> bool:
        return bool(self._transaction.__exit__(*args))


class _AsyncSessionAdapter:
    def __init__(self, session: Session) -> None:
        self.session = session

    async def scalar(self, statement: Any) -> Any:
        value = self.session.scalar(statement)
        if isinstance(value, EmailLoginCode):
            # SQLite drops timezone metadata from DateTime values on reload.
            for field in ("issued_at", "expires_at", "send_window_started_at"):
                timestamp = getattr(value, field)
                if timestamp.tzinfo is None:
                    setattr(value, field, timestamp.replace(tzinfo=UTC))
        return value

    def add(self, row: Any) -> None:
        self.session.add(row)

    async def flush(self) -> None:
        self.session.flush()

    def begin_nested(self) -> _NestedTransaction:
        return _NestedTransaction(self.session)


@pytest.fixture
def state() -> Iterator[Any]:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection: Any, _record: Any) -> None:
        connection.execute("PRAGMA foreign_keys=ON")

    model_metadata().create_all(engine)
    with Session(engine, expire_on_commit=False) as session, session.begin():
        operations_id, organisation_id, person_id = uuid4(), uuid4(), uuid4()
        session.add_all(
            [
                Tenant(id=operations_id, slug="ops-login-test", name="Operations"),
                Tenant(id=organisation_id, slug="org-login-test", name="Organisation"),
                Person(
                    id=person_id,
                    email="org-admin@example.test",
                    email_verified_at=_NOW,
                    status=PersonStatus.ACTIVE.value,
                ),
            ]
        )
        session.flush()
        session.add(
            Organisation(
                tenant_id=organisation_id,
                creation_command_id=uuid4(),
                domain_verification_token="d" * 43,
            )
        )
        session.flush()
        yield SimpleNamespace(
            session=session,
            adapter=cast(Any, _AsyncSessionAdapter(session)),
            operations_id=operations_id,
            organisation_id=organisation_id,
            person_id=person_id,
        )
    engine.dispose()


@pytest.mark.parametrize("role", [MembershipRole.ADMIN.value, MembershipRole.OWNER.value])
@pytest.mark.asyncio
async def test_organisation_admin_and_owner_can_start_email_code_sign_in(
    state: SimpleNamespace, role: str
) -> None:
    state.session.add(
        Membership(
            tenant_id=state.organisation_id,
            person_id=state.person_id,
            role=role,
        )
    )
    await state.adapter.flush()
    service = EmailLoginCodeService(state.adapter, challenge_secret=_SECRET)

    issued = await service.begin(
        email="org-admin@example.test",
        consent_accepted=False,
        submitted_consent_version=None,
        required_consent_version=None,
        now=_NOW,
    )

    assert issued is not None
    row = state.session.get(EmailLoginCode, issued.challenge_id)
    assert row is not None
    code = decrypt_email_login_code(_SECRET, row, generation_id=issued.generation_id)
    verified = await service.verify(
        email="org-admin@example.test",
        code=code,
        required_consent_version=None,
        now=_NOW + timedelta(seconds=1),
    )
    assert verified.person is not None
    assert verified.person.id == state.person_id


@pytest.mark.asyncio
async def test_operations_admin_membership_still_blocks_email_code_sign_in(
    state: SimpleNamespace,
) -> None:
    state.session.add_all(
        [
            Membership(
                tenant_id=state.organisation_id,
                person_id=state.person_id,
                role=MembershipRole.ADMIN.value,
            ),
            Membership(
                tenant_id=state.operations_id,
                person_id=state.person_id,
                role=MembershipRole.ADMIN.value,
            ),
        ]
    )
    await state.adapter.flush()
    service = EmailLoginCodeService(state.adapter, challenge_secret=_SECRET)

    issued = await service.begin(
        email="org-admin@example.test",
        consent_accepted=False,
        submitted_consent_version=None,
        required_consent_version=None,
        now=_NOW,
    )

    assert issued is None
    assert state.session.query(EmailLoginCode).count() == 0
