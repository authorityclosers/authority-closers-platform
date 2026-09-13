"""Actual PostgreSQL proof for the separate operations feedback read.

The fixture uses synthetic source/provider data. Existing internal review
services seed historical feedback; the retired learner HTTP routes stay closed.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest

from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationDenied,
    ConversationNotFound,
)
from ac_platform.conversation_intelligence.review_contracts import ReviewAssignment
from ac_platform.conversation_intelligence.review_service import ConversationReviewService
from tests.database.test_conversation_postgresql import postgres_harness as postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_reviews_postgresql import (
    ReviewCase,
    _create_assignment,
    _feedback_request,
    _service,
)
from tests.database.test_conversation_reviews_postgresql import review_case as review_case


def test_admin_reads_historical_feedback_without_reviewer_impersonation(
    review_case: ReviewCase,
) -> None:
    async def exercise() -> None:
        assignment = ReviewAssignment.model_validate(
            await _create_assignment(review_case, key="admin-detail-assignment")
        )
        async with review_case.sessions() as database, database.begin():
            service = _service(database, review_case)
            saved = await service.submit(
                review_case.reviewer_actor,
                assignment.id,
                _feedback_request(review_case, assignment, key="admin-detail-feedback"),
            )
        async with review_case.sessions() as database, database.begin():
            details = await _service(database, review_case).admin_details(
                review_case.admin_actor, assignment.id
            )
            assert details["assignment"]["id"] == str(assignment.id)
            assert details["feedback_count"] == 1
            assert details["feedback"][0]["payload"] == saved
            assert "report" not in details and "transcript" not in details
            assert "audio_source_url" not in details
        for actor in (review_case.reviewer_actor, review_case.foreign_actor):
            async with review_case.sessions() as database, database.begin():
                with pytest.raises(ConversationDenied):
                    await _service(database, review_case).admin_details(actor, assignment.id)
        async with review_case.sessions() as database, database.begin():
            with pytest.raises(ConversationNotFound):
                await _service(database, review_case).admin_details(
                    review_case.admin_actor, uuid4()
                )
        async with review_case.sessions() as database, database.begin():
            service = _service(database, review_case)
            await service.revoke(review_case.admin_actor, assignment.id, "admin-detail-revoke")
            details = await service.admin_details(review_case.admin_actor, assignment.id)
            assert details["lifecycle"]["state"] == "revoked"
            assert details["lifecycle"]["revocation"] is not None
            assert details["feedback"][0]["payload"] == saved
        # The real source retains bytes until its cleanup worker runs. A clock
        # beyond the three-hour retention deadline must still hide its content.
        async with review_case.sessions() as database, database.begin():
            service = ConversationReviewService(
                ConversationApplication(
                    database, clock=lambda: review_case.prepared.state.now + timedelta(hours=4)
                ),
                operations_tenant_id=review_case.operations_tenant_id,
            )
            details = await service.admin_details(review_case.admin_actor, assignment.id)
            assert details["feedback"][0]["state"] == "unavailable"
            assert details["feedback"][0]["unavailable_reason"] == "retention_expired"
            assert details["feedback"][0]["payload"] is None
            assert details["feedback"][0]["id"] == saved["id"]
            assert details["available_feedback_count"] == 0

    run(exercise())
