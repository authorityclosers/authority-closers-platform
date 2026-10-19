"""Review 2.0's coaching pipeline on PostgreSQL: a real analysis run's saved report,
judged point by point, apart from the report's layout.

Reuses the conversation reviews case (a fictional call, run and saved report draft).
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select

from ac_platform.conversation_intelligence.application import ConversationError
from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.gold_review_models import GoldReviewer
from ac_platform.conversation_intelligence.models import ConversationReportDraft
from ac_platform.conversation_intelligence.review_verdicts import ReviewVerdicts, value_digest
from tests.database.test_conversation_reviews_postgresql import ReviewCase, run
from tests.database.test_conversation_reviews_postgresql import (
    postgres_harness as postgres_harness,
)
from tests.database.test_conversation_reviews_postgresql import (
    review_case as review_case,
)

REPORT = {
    "improvements": [{"title": "Name the next step"}],
    "overview": {
        "next_call_focus": {
            "improvement_index": 0,
            "behavior": "Ask for the date",
            "target": "Every call",
        },
        "diagnosis": {"text": "The rep waits for the buyer to lead."},
        "improvement_details": [
            {"finding_index": 0, "replacement_behavior": "Propose Tuesday at 10."}
        ],
        "practice": None,
    },
}


async def judge(case: ReviewCase) -> None:
    async with case.sessions() as db, db.begin():
        db.add(
            GoldReviewer(
                person_id=case.reviewer_actor.person_id,
                designated_by=case.admin_actor.person_id,
                created_at=datetime.now(UTC),
            )
        )
        draft = await db.scalar(
            select(ConversationReportDraft).where(
                ConversationReportDraft.run_id == case.report_run_id
            )
        )
        assert draft is not None
        # Drafts are history (never edited): a newer draft of the same run carries the
        # coaching this test judges; the reader takes the newest, unerased one.
        db.add(
            ConversationReportDraft(
                id=uuid4(),
                tenant_id=draft.tenant_id,
                person_id=draft.person_id,
                recording_id=draft.recording_id,
                run_id=draft.run_id,
                source_revision=draft.source_revision,
                source_sha256=draft.source_sha256,
                report_sha256=content_hash(REPORT),
                transcript_sha256=draft.transcript_sha256,
                profile_sha256=draft.profile_sha256,
                evidence_receipt_sha256=draft.evidence_receipt_sha256,
                payload=REPORT,
                transcript=draft.transcript,
                evidence_receipt=draft.evidence_receipt,
                created_at=datetime.now(UTC),
            )
        )
        await db.flush()
        recording_id = draft.recording_id
        actor = dataclasses.replace(case.reviewer_actor, tenant_id=case.operations_tenant_id)
        service = ReviewVerdicts(db, case.operations_tenant_id)

        found = (await service.coaching(actor, recording_id, case.report_run_id))["points"]
        assert [point["key"] for point in found] == ["focus", "diagnosis", "better:0"]
        assert found[2]["ref"] == f"{case.report_run_id}:better:0"

        saved = await service.save(
            actor,
            recording_id,
            pipeline_key="coaching",
            target_kind="coaching",
            target_ref=f"{case.report_run_id}:better:0",
            question_key="useful",
            answer={"value": 4},
            request_key="coaching-1",
        )
        assert saved["answer"] == {"value": 4}
        assert saved["ai_sha256"] == value_digest(
            "coaching.better", {"title": "Name the next step", "text": "Propose Tuesday at 10."}
        )
        for pipeline, ref, question, answer in (
            # Coaching is judged in its own pipeline only.
            ("analysis-sales", f"{case.report_run_id}:focus", "correct", {"value": "correct"}),
            # No practice point in this report.
            ("coaching", f"{case.report_run_id}:practice", "true", {"value": "true"}),
            # No saved report for an unknown run.
            ("coaching", f"{uuid4()}:focus", "true", {"value": "true"}),
        ):
            with pytest.raises(ConversationError):
                await service.save(
                    actor,
                    recording_id,
                    pipeline_key=pipeline,
                    target_kind="coaching",
                    target_ref=ref,
                    question_key=question,
                    answer=answer,
                    request_key=uuid4().hex,
                )


def test_coaching_is_judged_point_by_point_apart_from_the_report(review_case) -> None:
    run(judge(review_case))
