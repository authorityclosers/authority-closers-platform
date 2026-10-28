"""Exercise the canonical issuer with a sole organisation membership."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.orm import SessionTransactionOrigin

from ac_platform.identity.application import AsyncIdentityApplication
from ac_platform.identity.services import PersonSnapshot


@pytest.mark.asyncio
@pytest.mark.parametrize("auto_select", [True, False])
async def test_canonical_session_issuer_can_leave_sole_organisation_unselected(auto_select):
    now = datetime.now(UTC)
    person = PersonSnapshot(id=uuid4(), email="synthetic@example.test", email_verified_at=now)
    organisation_id = uuid4()
    database = SimpleNamespace(
        get_transaction=lambda: SimpleNamespace(
            sync_transaction=SimpleNamespace(origin=SessionTransactionOrigin.BEGIN)
        )
    )
    identity = AsyncIdentityApplication(
        database,
        token_pepper="synthetic-pepper-long-enough-for-tests",  # noqa: S106
    )
    repository = SimpleNamespace(
        get_person_for_update=AsyncMock(return_value=person),
        find_open_deletion_request=AsyncMock(return_value=None),
        get_sole_active_tenant_id=AsyncMock(return_value=organisation_id),
        save_session=AsyncMock(),
    )
    identity._repository = repository
    options = {} if auto_select else {"auto_select_tenant": False}
    issued = await identity.issue_authenticated_session(person.id, **options)
    stored = repository.save_session.call_args.args[0]
    assert stored.selected_tenant_id == (organisation_id if auto_select else None)
    assert issued.metadata.selected_tenant_id == stored.selected_tenant_id
    assert stored.audience == "account"
    assert stored.token_hash == identity._token_hash(issued.token)
    assert repository.get_sole_active_tenant_id.await_count == int(auto_select)
