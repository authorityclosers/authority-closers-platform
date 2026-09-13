from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from ac_platform.conversation_intelligence.application import (
    ConversationNotFound,
)
from ac_platform.conversation_intelligence.review_contracts import ReviewInvitationAcceptRequest
from ac_platform.conversation_intelligence.review_service import ConversationReviewService
from ac_platform.kernel.authz import ActorContext


@pytest.mark.asyncio
async def test_non_ascii_invitation_token_is_generic_not_found() -> None:
    database = Mock()
    database.scalar = AsyncMock()
    application = Mock(database=database)
    application.admit = AsyncMock(return_value=datetime.now(UTC))
    service = ConversationReviewService(
        application,
        operations_tenant_id=uuid4(),
        token_secret="review-invitation-test-secret-012345678901234567890123",  # noqa: S106 - synthetic test secret
    )
    actor = ActorContext(uuid4(), uuid4(), uuid4())

    with pytest.raises(ConversationNotFound):
        await service.accept_invitation(
            actor,
            ReviewInvitationAcceptRequest(
                schema="ac.sales-xray.review-invitation-accept/1",
                token="é" * 40,
            ),
        )

    application.admit.assert_awaited_once_with(actor)
    database.scalar.assert_not_awaited()
