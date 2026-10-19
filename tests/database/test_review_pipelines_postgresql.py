"""Review 2.0's pipeline editor on PostgreSQL: the control account saves a new version,
reviewers read it but cannot edit, stale edits are refused, and every save is audited.

Reuses the conversation reviews case (fictional people in the operations workspace).
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import func, select

from ac_platform.audit.models import AuditEvent
from ac_platform.conversation_intelligence.application import (
    ConversationConflict,
    ConversationDenied,
    ConversationError,
    ConversationNotFound,
)
from ac_platform.conversation_intelligence.gold_review_models import GoldReviewer
from ac_platform.conversation_intelligence.review_models import ReviewPipeline
from ac_platform.conversation_intelligence.review_verdicts import (
    PIPELINE_SAVED_ACTION,
    ReviewVerdicts,
)
from tests.database.test_conversation_reviews_postgresql import ReviewCase, run
from tests.database.test_conversation_reviews_postgresql import (
    postgres_harness as postgres_harness,
)
from tests.database.test_conversation_reviews_postgresql import (
    review_case as review_case,
)

QUESTIONS = [
    {
        "key": "correct",
        "kind": "verdict",
        "label": "Is this right?",
        "options": ["correct", "wrong", "partly"],
    },
    {
        "key": "right_type",
        "kind": "pick",
        "label": "What is it really?",
        "options": ["objection", "question", "pain", "goal"],
        "when": {"correct": "wrong"},
    },
    {
        "key": "fix",
        "kind": "correct",
        "label": "What should it say?",
        "when": {"correct": "wrong"},
    },
]


async def exercise(case: ReviewCase) -> None:
    async with case.sessions() as db, db.begin():
        db.add(
            GoldReviewer(
                person_id=case.reviewer_actor.person_id,
                designated_by=case.admin_actor.person_id,
                created_at=datetime.now(UTC),
            )
        )

    # Reviewers work in the operations workspace; the control account already does.
    reviewer = dataclasses.replace(case.reviewer_actor, tenant_id=case.operations_tenant_id)
    assert case.admin_actor.tenant_id == case.operations_tenant_id

    async def work(job: Any) -> Any:
        async with case.sessions() as db, db.begin():
            return await job(ReviewVerdicts(db, case.operations_tenant_id))

    def save(actor: Any, **values: Any) -> Any:
        body: dict[str, Any] = {
            "based_on": 1,
            "title": "Analysis: sales",
            "sample_limit": 12,
            "questions": QUESTIONS,
        }
        body.update(values)
        return lambda service: service.save_pipeline(actor, "analysis-sales", **body)

    # A reviewer reads the pipelines but cannot edit them.
    listed = await work(lambda service: service.list_pipelines(reviewer))
    assert listed["can_edit"] is False
    assert listed["limits"]["questions"] == 8
    with pytest.raises(ConversationDenied):
        await work(save(reviewer))

    # The control account edits: the default (version 1) becomes version 2.
    listed = await work(lambda service: service.list_pipelines(case.admin_actor))
    assert listed["can_edit"] is True
    saved = await work(save(case.admin_actor))
    assert (saved["version"], saved["changed"], saved["saved"]) == (2, True, True)
    assert saved["definition"]["sample"] == {"order": "newest", "limit": 12}
    assert saved["definition"]["targets"] == ["object", "fact"]  # kept, not editable yet
    assert [item["key"] for item in saved["definition"]["questions"]] == [
        "correct",
        "right_type",
        "fix",
    ]

    # The same edit again changes nothing; an edit from version 1 is now stale.
    again = await work(save(case.admin_actor, based_on=2))
    assert (again["version"], again["changed"]) == (2, False)
    with pytest.raises(ConversationConflict):
        await work(save(case.admin_actor, title="Something else"))
    with pytest.raises(ConversationNotFound):
        await work(
            lambda service: service.save_pipeline(
                case.admin_actor,
                "no-such-pipeline",
                based_on=1,
                title="X",
                sample_limit=5,
                questions=QUESTIONS,
            )
        )
    with pytest.raises(ConversationError, match="first question"):
        await work(
            save(
                case.admin_actor,
                based_on=2,
                questions=[{"key": "useful", "kind": "scale", "label": "Useful?"}],
            )
        )

    # Reviewers now work under version 2; the old version stays as history.
    listed = await work(lambda service: service.list_pipelines(reviewer))
    sales = next(item for item in listed["pipelines"] if item["key"] == "analysis-sales")
    assert sales["version"] == 2
    assert sales["definition"]["questions"][0]["options"] == ["correct", "wrong", "partly"]
    async with case.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(ReviewPipeline)) == 1
        events = (
            await db.scalars(select(AuditEvent).where(AuditEvent.action == PIPELINE_SAVED_ACTION))
        ).all()
    assert len(events) == 1
    assert events[0].payload["version"] == 2
    assert events[0].payload["questions"] == ["correct", "right_type", "fix"]


def test_control_account_saves_versions_reviewers_read_them(review_case: ReviewCase) -> None:
    run(exercise(review_case))
