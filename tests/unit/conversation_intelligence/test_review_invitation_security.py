from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from ac_platform.conversation_intelligence.application import (
    ConversationNotFound,
)
from ac_platform.conversation_intelligence.review_contracts import ReviewInvitationAcceptRequest
from ac_platform.conversation_intelligence.review_service import ConversationReviewService
from ac_platform.identity.models import Person, Session
from ac_platform.kernel.authz import ActorContext


@pytest.mark.asyncio
async def test_non_ascii_invitation_token_is_generic_not_found() -> None:
    now = datetime(2026, 9, 14, tzinfo=UTC)
    actor = ActorContext(uuid4(), uuid4(), uuid4())
    database = Mock()
    database.scalar = AsyncMock(
        side_effect=[
            Session(
                id=actor.session_id,
                person_id=actor.person_id,
                audience="reviewer",
                selected_tenant_id=None,
                revoked_at=None,
                expires_at=now + timedelta(hours=1),
            ),
            Person(id=actor.person_id, status="active", email_verified_at=now),
        ]
    )
    application = Mock(database=database, clock=Mock(return_value=now))
    application.admit = AsyncMock()
    service = ConversationReviewService(
        application,
        operations_tenant_id=uuid4(),
        token_secret="review-invitation-test-secret-012345678901234567890123",  # noqa: S106 - synthetic test secret
    )

    with pytest.raises(ConversationNotFound):
        await service.accept_invitation(
            actor,
            ReviewInvitationAcceptRequest(
                schema="ac.sales-xray.review-invitation-accept/1",
                token="é" * 40,
            ),
        )

    # Validate the real reviewer admission path before rejecting malformed input.
    # Only the session/person queries run; no invitation token reaches a lookup.
    application.admit.assert_not_awaited()
    assert database.scalar.await_count == 2
    assert [
        call.args[0].column_descriptions[0]["entity"] for call in database.scalar.await_args_list
    ] == [Session, Person]
