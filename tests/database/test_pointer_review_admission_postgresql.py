"""AUT-2010: AI pointer reviews are admitted and every paid attempt is recorded.

Disposable-loopback PostgreSQL with the real imported-report fixture (synthetic
audio and transcript). The provider is a local fake: no network, no key.
"""

from __future__ import annotations

import asyncio
import json
import re
from argparse import Namespace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain
from ac_platform.conversation_intelligence import pointer_review_admission as admission
from ac_platform.conversation_intelligence.application import ConversationApplication
from ac_platform.conversation_intelligence.models import (
    ConversationPermission,
    ConversationReportDraft,
)
from ac_platform.conversation_intelligence.pointer_review import POINTER_IDS
from ac_platform.conversation_intelligence.pointer_review_cli import (
    OPERATOR,
    _ProviderFailure,
    _review_one,
    _segments,
)
from ac_platform.conversation_intelligence.pointer_review_models import (
    ConversationPointerReview,
)
from tests.database.test_conversation_postgresql import (
    postgres_harness as _postgres_harness,
)
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_reports_postgresql import (
    ReportFixture,
    _build_fixture,
    _import_valid,
)

DIGEST = "c" * 64
FICTIONAL = {"version": "pointer-review/1", "overall": {"score": 70}, "pointers": []}


@pytest.fixture
def postgres_harness() -> Any:
    # Each case seeds its own verified control person, so each needs its own schema.
    yield from _postgres_harness.__wrapped__()  # type: ignore[attr-defined]


@pytest.fixture
def report_fixture(
    postgres_harness: Any, tmp_path_factory: pytest.TempPathFactory
) -> ReportFixture:
    return run(_build_fixture(postgres_harness, tmp_path_factory.mktemp("pointer-review")))


async def _report(sessions: Any, fixture: ReportFixture) -> dict[str, Any]:
    await _import_valid(fixture, sessions)
    async with sessions() as database:
        draft = await database.scalar(
            select(ConversationReportDraft).where(
                ConversationReportDraft.run_id == fixture.prepared.run_id
            )
        )
        assert draft is not None and draft.payload is not None
        return {
            "submission_id": uuid4(),
            "tenant_id": draft.tenant_id,
            "recording_id": draft.recording_id,
            "run_id": draft.run_id,
            "draft_id": draft.id,
            "source_sha256": draft.source_sha256,
            "transcript_revision": draft.payload["transcript_revision"],
        }


async def _claim(sessions: Any, report: dict[str, Any], **changes: Any) -> admission.Claim:
    options: dict[str, Any] = {
        "mode": "operator",
        "created_by": OPERATOR,
        "forced": False,
        "prompt_digest": DIGEST,
        "daily_cap": 50,
        "now": datetime.now(UTC),
    }
    options.update(changes)
    async with sessions() as session, session.begin():
        return await admission.claim(session, report, **options)


async def _save(sessions: Any, report: dict[str, Any], attempt: Any) -> str:
    async with sessions() as session, session.begin():
        return await admission.save(
            session,
            report,
            attempt,
            mode="operator",
            review=FICTIONAL,
            prompt_digest=DIGEST,
            usage={"promptTokenCount": 10, "candidatesTokenCount": 20},
            created_by=OPERATOR,
            now=datetime.now(UTC),
        )


async def _events(sessions: Any, report: dict[str, Any]) -> list[AuditEvent]:
    async with sessions() as session:
        return list(
            (
                await session.scalars(
                    select(AuditEvent)
                    .where(
                        AuditEvent.tenant_id == report["tenant_id"],
                        AuditEvent.action.in_((admission.STARTED, admission.FINISHED)),
                    )
                    .order_by(AuditEvent.sequence_no)
                )
            ).all()
        )


async def _reviews(sessions: Any, report: dict[str, Any]) -> int:
    async with sessions() as session:
        return int(
            await session.scalar(
                select(func.count())
                .select_from(ConversationPointerReview)
                .where(ConversationPointerReview.recording_id == report["recording_id"])
            )
        )


async def _set_revoked(sessions: Any, fixture: ReportFixture, value: datetime | None) -> None:
    async with sessions() as session, session.begin():
        await session.execute(
            update(ConversationPermission)
            .where(ConversationPermission.id == fixture.prepared.state.permission_id)
            .values(revoked_at=value)
        )


def test_attempts_are_ledgered_without_content_and_saved_once(
    postgres_harness: Any, report_fixture: ReportFixture
) -> None:
    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            report = await _report(sessions, report_fixture)
            claimed = await _claim(sessions, report)
            assert claimed.attempt is not None and claimed.refused is None
            assert await _save(sessions, report, claimed.attempt) == "saved"
            assert await _reviews(sessions, report) == 1
            # Saved once: another review needs --force, which skips nothing else.
            assert (await _claim(sessions, report)).refused == "already_reviewed"
            forced = await _claim(sessions, report, forced=True)
            assert forced.attempt is not None
            async with sessions() as session, session.begin():
                await admission.finish(
                    session,
                    report,
                    forced.attempt,
                    mode="operator",
                    outcome="timeout",
                    usage=None,
                    now=datetime.now(UTC),
                )
            # The daily cap counts paid attempts (saved, failed or uncertain).
            assert (await _claim(sessions, report, forced=True, daily_cap=2)).refused == (
                "daily_cap"
            )
            events = await _events(sessions, report)
            assert [(event.action, event.payload.get("outcome")) for event in events] == [
                (admission.STARTED, None),
                (admission.FINISHED, "saved"),
                (admission.STARTED, None),
                (admission.FINISHED, "timeout"),
            ]
            assert events[1].payload["review_id"] and events[1].payload["output_tokens"] == 20
            assert {event.actor_type for event in events} == {"operator"}
            segments = None
            async with sessions() as session:
                segments = await session.run_sync(
                    lambda sync: _segments(sync.connection(), report["draft_id"])
                )
            texts = [str(item.get("text")) for item in segments if item.get("text")]
            ledger = json.dumps([event.payload for event in events])
            assert texts and not any(text in ledger for text in texts)
            async with sessions() as session:
                assert (await verify_audit_chain(session, report["tenant_id"])).valid
        finally:
            await engine.dispose()

    run(exercise())


def test_revocation_stale_source_and_erasure_refuse_dispatch_and_late_saves(
    postgres_harness: Any, report_fixture: ReportFixture
) -> None:
    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            report = await _report(sessions, report_fixture)
            stale = {**report, "transcript_revision": "another-revision"}
            assert (await _claim(sessions, stale)).refused == "stale_source"
            assert (await _claim(sessions, {**report, "run_id": uuid4()})).refused == (
                "stale_source"
            )
            await _set_revoked(sessions, report_fixture, datetime.now(UTC))
            try:
                assert (await _claim(sessions, report)).refused == "permission_inactive"
            finally:
                await _set_revoked(sessions, report_fixture, None)
            assert await _events(sessions, report) == []
            # Consent revoked while the provider was answering: nothing is saved.
            claimed = await _claim(sessions, report)
            assert claimed.attempt is not None
            await _set_revoked(sessions, report_fixture, datetime.now(UTC))
            try:
                assert await _save(sessions, report, claimed.attempt) == (
                    "refused_permission_inactive"
                )
            finally:
                await _set_revoked(sessions, report_fixture, None)
            assert await _reviews(sessions, report) == 0
            # Erasure began while the provider was answering: nothing is saved.
            claimed = await _claim(sessions, report)
            assert claimed.attempt is not None
            async with sessions() as database, database.begin():
                await ConversationApplication(
                    database, clock=lambda: report_fixture.prepared.state.now
                ).request_deletion(
                    report_fixture.actor,
                    report_fixture.prepared.recording_id,
                    key="pointer-review-admission-delete",
                )
            assert await _save(sessions, report, claimed.attempt) == "refused_call_erased"
            assert await _reviews(sessions, report) == 0
            assert (await _claim(sessions, report, forced=True)).refused == "call_erased"
            outcomes = [
                event.payload.get("outcome")
                for event in await _events(sessions, report)
                if event.action == admission.FINISHED
            ]
            assert outcomes == ["refused_permission_inactive", "refused_call_erased"]
        finally:
            await engine.dispose()

    run(exercise())


def test_concurrent_claims_runners_and_uncertain_attempts_cannot_double_spend(
    postgres_harness: Any, report_fixture: ReportFixture
) -> None:
    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            report = await _report(sessions, report_fixture)
            now = datetime.now(UTC)
            first, second = await asyncio.gather(
                _claim(sessions, report, now=now), _claim(sessions, report, now=now)
            )
            claims = sorted([first, second], key=lambda item: item.attempt is None)
            assert claims[0].attempt is not None and claims[1].refused == "in_flight"
            # The process died without an outcome: after the in-flight window the
            # attempt is uncertain, counted as paid and as a failure.
            later = now + admission.IN_FLIGHT + timedelta(minutes=1)
            retry = await _claim(sessions, report, now=later)
            assert retry.attempt is not None
            exhausted = await _claim(
                sessions, report, now=later + admission.IN_FLIGHT + timedelta(minutes=1)
            )
            assert exhausted.refused == "attempts_exhausted"
            async with sessions() as session:
                assert await admission.attempts_today(session, "operator", OPERATOR, later) == 2
            # One runner per database.
            async with engine.connect() as one, engine.connect() as two:
                assert await admission.try_run_lock(one)
                assert not await admission.try_run_lock(two)
                await admission.release_run_lock(one)
                assert await admission.try_run_lock(two)
                await admission.release_run_lock(two)
        finally:
            await engine.dispose()

    run(exercise())


def _provider_answer(body: dict[str, Any]) -> dict[str, Any]:
    segment = re.search(r"\[([^\]\s]+)\] ", json.dumps(body))
    assert segment is not None
    pointers = [
        {
            "id": pointer_id,
            "status": "good",
            "score": 80,
            "what_happened": "You did this well.",
            "why_it_matters": "It builds trust.",
            "evidence": [segment.group(1)],
            "how_to_improve": ["Keep doing it."],
            "training_topic": "Openings",
        }
        for pointer_id in POINTER_IDS
    ]
    text = json.dumps({"score_line": "A solid call.", "pointers": pointers})
    return {
        "candidates": [{"content": {"parts": [{"text": text}]}}],
        "usageMetadata": {"promptTokenCount": 1000, "candidatesTokenCount": 2000},
    }


def test_runner_records_timeouts_and_unreadable_answers_then_stops_paying(
    postgres_harness: Any, report_fixture: ReportFixture
) -> None:
    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        calls: list[str] = []

        def timeout(body: dict[str, Any]) -> dict[str, Any]:
            calls.append("timeout")
            raise _ProviderFailure("timeout")

        def unreadable(body: dict[str, Any]) -> dict[str, Any]:
            calls.append("unreadable")
            return {
                "candidates": [{"content": {"parts": [{"text": "not json"}]}}],
                "usageMetadata": {"promptTokenCount": 1000, "candidatesTokenCount": 5},
            }

        def answer(body: dict[str, Any]) -> dict[str, Any]:
            calls.append("answer")
            return _provider_answer(body)

        try:
            report = await _report(sessions, report_fixture)
            options = Namespace(apply=True, force=False, daily_cap=50)

            async def review(provider: Any, **changes: Any) -> dict[str, Any]:
                return await _review_one(
                    sessions,
                    report,
                    Namespace(**{**vars(options), **changes}),
                    mode="operator",
                    created_by=OPERATOR,
                    call_provider=provider,
                )

            saved = await review(answer)
            assert saved["outcome"] == "saved" and saved["overall"] == 80
            assert saved["tokens"] == [1000, 2000]
            first = await review(timeout, force=True)
            assert first["outcome"] == "timeout"
            second = await review(unreadable, force=True)
            assert second["outcome"] == "parse_failed" and second["tokens"] == [1000, 5]
            third = await review(answer, force=True)
            assert third == {
                "submission": str(report["submission_id"]),
                "segments": third["segments"],
                "skipped": "attempts_exhausted",
            }
            assert calls == ["answer", "timeout", "unreadable"]
            outcomes = [
                (event.payload.get("outcome"), event.payload.get("output_tokens"))
                for event in await _events(sessions, report)
                if event.action == admission.FINISHED
            ]
            assert outcomes == [("saved", 2000), ("timeout", None), ("parse_failed", 5)]
            dry = await review(answer, apply=False)
            assert dry["dry_run"] is True and "would_refuse" not in dry
            assert calls == ["answer", "timeout", "unreadable"]
        finally:
            await engine.dispose()

    run(exercise())
