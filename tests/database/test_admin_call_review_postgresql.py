"""The Admin call review console reads (AUT-1798), on PostgreSQL.

Runs on the offline review fixture (fictional audio and transcript): the queue
finds the analysed call with its filters and counts, the call lists its runs,
the review bundle carries report and transcript and is audited, and only the
operations control account is admitted.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from ac_platform.audit.models import AuditEvent
from ac_platform.conversation_intelligence.admin_call_review import AdminCallReview
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationDenied,
    ConversationError,
    ConversationNotFound,
)
from tests.database.test_conversation_reviews_postgresql import ReviewCase, run
from tests.database.test_conversation_reviews_postgresql import (
    postgres_harness as postgres_harness,
)
from tests.database.test_conversation_reviews_postgresql import (
    review_case as review_case,
)


def _service(database, case: ReviewCase) -> AdminCallReview:
    return AdminCallReview(
        ConversationApplication(database, clock=lambda: case.prepared.state.now),
        case.operations_tenant_id,
        recording_tenant_ids=(case.prepared.state.tenant_id, case.operations_tenant_id),
    )


def test_queue_call_and_bundle_show_one_analysed_call(review_case: ReviewCase) -> None:
    case = review_case
    recording_id = str(case.prepared.recording_id)

    async def exercise() -> None:
        async with case.sessions() as database, database.begin():
            service = _service(database, case)
            queue = await service.queue(case.admin_actor)
            item = next(row for row in queue["items"] if row["recording_id"] == recording_id)
            assert item["status"] == "ready"
            assert item["report_run_id"] == str(case.report_run_id)
            assert item["organisation"]["id"] == str(case.prepared.state.tenant_id)
            assert item["runs"] >= 1
            assert queue["counts"]["ready"] >= 1
            assert queue["window"] == {"size": 500, "truncated": False}
            organisations = {entry["value"] for entry in queue["facets"]["organisations"]}
            assert str(case.prepared.state.tenant_id) in organisations
            # The operations workspace is never part of the review scope.
            assert str(case.operations_tenant_id) not in organisations

            failed = await service.queue(case.admin_actor, status="failed")
            assert recording_id not in {row["recording_id"] for row in failed["items"]}
            elsewhere = await service.queue(case.admin_actor, organisation=uuid4())
            assert elsewhere["items"] == [] and elsewhere["total"] == 0
            today = case.prepared.state.now.date()
            dated = await service.queue(
                case.admin_actor, since=today - timedelta(days=1), until=today + timedelta(days=1)
            )
            assert recording_id in {row["recording_id"] for row in dated["items"]}
            later = await service.queue(case.admin_actor, since=today + timedelta(days=2))
            assert recording_id not in {row["recording_id"] for row in later["items"]}
            page = await service.queue(case.admin_actor, limit=1)
            assert len(page["items"]) == 1

            call = await service.call(case.admin_actor, case.prepared.recording_id)
            assert call["recording_id"] == recording_id
            assert call["status"] == "ready"
            reported = [entry for entry in call["runs"] if entry["report_id"]]
            assert [entry["id"] for entry in reported] == [str(case.report_run_id)]
            # The analysed call has no dead-lettered step to retry.
            assert call["failed_jobs"] == []

            bundle = await service.bundle(case.admin_actor, case.report_run_id)
            assert bundle["run_id"] == str(case.report_run_id)
            assert bundle["recording_id"] == recording_id
            assert bundle["transcript"]["segments"]
            assert any(
                segment["id"] == case.span_id for segment in bundle["transcript"]["segments"]
            )
            assert isinstance(bundle["report"], dict) and bundle["report"]
            assert bundle["audio_source_url"].endswith(f"/runs/{case.report_run_id}/source")
            assert set(bundle) >= {"story", "waveform", "metrics"}
            if bundle["metrics"] is not None:
                assert bundle["metrics"]["speakers"]

            source = await service.playback(case.admin_actor, case.report_run_id)
            assert source["id"] == recording_id and source["source_bytes"] > 0

        async with case.sessions() as database:
            audits = (
                await database.scalars(
                    select(AuditEvent).where(
                        AuditEvent.action == "conversation.admin_call_review_view"
                    )
                )
            ).all()
            assert any(event.actor_person_id == case.admin_actor.person_id for event in audits)

    run(exercise())


def test_only_the_operations_control_account_is_admitted(review_case: ReviewCase) -> None:
    case = review_case

    async def exercise() -> None:
        for actor in (case.source_actor, case.foreign_actor):
            async with case.sessions() as database, database.begin():
                service = _service(database, case)
                with pytest.raises(ConversationDenied):
                    await service.queue(actor)
                with pytest.raises(ConversationDenied):
                    await service.bundle(actor, case.report_run_id)
        async with case.sessions() as database, database.begin():
            service = _service(database, case)
            with pytest.raises(ConversationNotFound):
                await service.call(case.admin_actor, uuid4())
            with pytest.raises(ConversationNotFound):
                await service.bundle(case.admin_actor, UUID(int=1))
            with pytest.raises(ConversationError):
                await service.queue(case.admin_actor, status="nonsense")
            with pytest.raises(ConversationError):
                await service.queue(case.admin_actor, cursor="not-a-cursor")

    run(exercise())


def test_analysis_health_counts_the_fixture_analysis(review_case: ReviewCase) -> None:
    from ac_platform.conversation_intelligence.admin_analysis_health import AdminAnalysisHealth

    case = review_case

    async def exercise() -> None:
        async with case.sessions() as database, database.begin():
            health = await AdminAnalysisHealth(
                ConversationApplication(database, clock=lambda: case.prepared.state.now),
                case.operations_tenant_id,
                recording_tenant_ids=(case.prepared.state.tenant_id, case.operations_tenant_id),
            ).summary(case.admin_actor, days=30)
            assert health["jobs"]["total"] >= 1
            assert set(health["jobs"]["by_status"]) == {
                "queued",
                "leased",
                "retry_wait",
                "held",
                "succeeded",
                "dead_letter",
            }
            # A rolling 30-day window touches 31 calendar dates (the first in part).
            assert len(health["daily"]) == 31
            assert health["durations"]["runs"]["count"] >= 1
            assert health["cost"]["basis"] == "admin_pricing_estimate_not_settlement"
            for item in health["failed"]:
                assert " " not in item["code"]
            # Versions come only from steps linked to a processing plan; the fixture
            # analyses through direct quotes, so only the invariants are checked here.
            assert isinstance(health["versions"], list)
            for row in health["versions"]:
                assert row["completed"] + row["running"] + row["held"] <= row["analyses"]

    run(exercise())
