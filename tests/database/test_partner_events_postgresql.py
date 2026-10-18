"""Partner webhooks end to end on disposable loopback PostgreSQL (fictional data only).

The real imported-report fixture (synthetic audio and transcript) gives a
saved report; a fictional guest submission, uploader and lead are added. The
quote-facts provider is a local fake and every HTTP call goes to an
``httpx.MockTransport``: no network, no key, no real endpoint. The owner's
alert command is replaced by a recorder.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import hmac
import json
import re
import time
from argparse import Namespace
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain
from ac_platform.conversation_intelligence.acquisition_models import ConversationAcquisitionUsage
from ac_platform.conversation_intelligence.application import ConversationApplication
from ac_platform.conversation_intelligence.guest_models import (
    ConversationGuestSubmission,
    ConversationProcessingLease,
    ConversationProcessingPrincipal,
)
from ac_platform.conversation_intelligence.models import (
    ConversationPermission,
    ConversationReportDraft,
)
from ac_platform.identity.models import Person
from ac_platform.lead_desk.models import Lead, LeadEvent
from ac_platform.partner_events import cli, delivery, endpoints, pipeline
from ac_platform.partner_events import extraction as ledger
from ac_platform.partner_events.delivery import (
    claim_next,
    deliver_one,
    drop,
    erase_partner_rows_for_recording,
    erasure_sweep,
    retry_delay,
)
from ac_platform.partner_events.models import (
    PartnerQuoteFacts,
    PartnerWebhookAttempt,
    PartnerWebhookEndpoint,
    PartnerWebhookEvent,
)
from ac_platform.partner_events.payload import body_sha256, summary_text
from ac_platform.partner_events.pipeline import ProviderFailure
from tests.database.test_conversation_postgresql import (
    postgres_harness as _postgres_harness,
)
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_reports_postgresql import (
    ReportFixture,
    _build_fixture,
    _import_valid,
)

SECRET_REF = "AC_PARTNER_WEBHOOK_SECRET__FICTIONAL"  # noqa: S105 - a variable name
NEXT_SECRET_REF = "AC_PARTNER_WEBHOOK_SECRET__FICTIONAL_NEXT"  # noqa: S105 - a name, never set
SECRET = "whsec-fictional-test-secret"  # noqa: S105 - fictional test value
URL = "https://hooks.example.test/sx"
PROFILE = "wiselife-quote-v1"


@pytest.fixture
def postgres_harness() -> Any:
    # Each case seeds its own verified control person, so each needs its own schema.
    yield from _postgres_harness.__wrapped__()  # type: ignore[attr-defined]


@pytest.fixture
def report_fixture(
    postgres_harness: Any, tmp_path_factory: pytest.TempPathFactory
) -> ReportFixture:
    fixture: ReportFixture = run(
        _build_fixture(postgres_harness, tmp_path_factory.mktemp("partner-events"))
    )
    return fixture


@pytest.fixture(autouse=True)
def webhook_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(SECRET_REF, SECRET)


@pytest.fixture(autouse=True)
def owner_alerts(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Never the host's real alert command: alerts are recorded here instead."""
    sent: list[str] = []

    def record(text: str) -> str:
        sent.append(text)
        return "sent"

    monkeypatch.setattr(delivery, "notify_owner", record)
    return sent


class Clock:
    def __init__(self) -> None:
        self.now = datetime.now(UTC)

    def __call__(self) -> datetime:
        return self.now


class Receiver:
    """A fictional partner endpoint: records requests, answers with the next queued status."""

    def __init__(self, *statuses: int) -> None:
        self.statuses = list(statuses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.statuses.pop(0) if self.statuses else 200)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self), follow_redirects=False)


def answer(body: dict[str, Any]) -> dict[str, Any]:
    """A fictional provider: cites the first transcript segment with its last word."""
    user = body["contents"][0]["parts"][0]["text"]
    found = re.search(r"^\[([^\]\s]+)\] \S+ \d\d:\d\d: (.*)$", user, re.MULTILINE)
    assert found is not None
    segment, words = found.group(1), found.group(2).split()
    facts = [
        {
            "type": "product_mention",
            "status": "stated",
            "value": {"stated_as": words[-1]},
            "evidence": [segment],
        },
        # Not said in the call: dropped by validation.
        {
            "type": "mentioned_price",
            "status": "stated",
            "value": {"applies_to": "system", "stated_as": "3.70 lakh"},
            "evidence": [segment],
        },
    ]
    return {
        "candidates": [{"content": {"parts": [{"text": json.dumps({"facts": facts})}]}}],
        "usageMetadata": {"promptTokenCount": 900, "candidatesTokenCount": 120},
    }


async def _draft(sessions: Any, fixture: ReportFixture) -> ConversationReportDraft:
    await _import_valid(fixture, sessions)
    async with sessions() as session:
        draft: ConversationReportDraft | None = await session.scalar(
            select(ConversationReportDraft)
            .where(ConversationReportDraft.run_id == fixture.prepared.run_id)
            .order_by(ConversationReportDraft.created_at.desc())
        )
        assert draft is not None and draft.payload is not None
        return draft


async def _submission(sessions: Any, fixture: ReportFixture, draft: Any) -> UUID:
    """A fictional guest submission for the fixture's call, uploaded by its member."""
    state = fixture.prepared.state
    now = datetime.now(UTC)
    submission_id, usage_id = uuid4(), uuid4()
    async with sessions() as session, session.begin():
        session.add(
            ConversationAcquisitionUsage(
                id=usage_id,
                tenant_id=state.tenant_id,
                visitor_id=None,
                person_id=state.person_id,
                submission_id=submission_id,
                source_sha256=draft.source_sha256,
                duration_evidence_sha256="d" * 64,
                reserved_seconds=60,
                policy_revision="fictional-policy",
                created_at=now,
            )
        )
        principal = await session.scalar(
            select(ConversationProcessingPrincipal).where(
                ConversationProcessingPrincipal.tenant_id == state.tenant_id
            )
        )
        if principal is None:
            principal = ConversationProcessingPrincipal(
                id=uuid4(),
                tenant_id=state.tenant_id,
                person_id=state.person_id,
                operator_reference="fictional",
                created_at=now,
                revoked_at=None,
            )
            session.add(principal)
        await session.flush()
        lease_id = uuid4()
        session.add(
            ConversationProcessingLease(
                id=lease_id,
                principal_id=principal.id,
                tenant_id=state.tenant_id,
                person_id=principal.person_id,
                usage_id=usage_id,
                created_at=now,
                expires_at=now + timedelta(hours=1),
                revoked_at=None,
            )
        )
        await session.flush()
        session.add(
            ConversationGuestSubmission(
                tenant_id=state.tenant_id,
                submission_id=submission_id,
                person_id=draft.person_id,
                recording_id=draft.recording_id,
                processing_lease_id=lease_id,
                usage_id=usage_id,
                source_sha256=draft.source_sha256,
                capture_source="web_upload",
                created_at=now - timedelta(minutes=3),
            )
        )
    return submission_id


async def _lead(sessions: Any, tenant_id: UUID, submission_id: UUID) -> UUID:
    now = datetime.now(UTC)
    lead_id = uuid4()
    async with sessions() as session, session.begin():
        session.add(
            Lead(
                id=lead_id,
                tenant_id=tenant_id,
                revision=1,
                source="manual",
                payload={"name": "Customer A"},
                name="Customer A",
                phone="+910000000000",
                city="Pune",
                stage="follow_up",
                attempts=1,
                calls=1,
                repeats=0,
                last_submission_id=None,
                test_data=True,
                created_at=now,
                updated_at=now,
            )
        )
        await session.flush()
        session.add(
            LeadEvent(
                id=uuid4(),
                tenant_id=tenant_id,
                lead_id=lead_id,
                kind="call",
                data={"submission_id": str(submission_id), "simulated": False},
                created_at=now,
            )
        )
    return lead_id


async def _register(
    sessions: Any, tenant_id: UUID, since: datetime, *, facts_profile: str | None = PROFILE
) -> UUID:
    async with sessions() as session, session.begin():
        result = await endpoints.register(
            session,
            tenant_id=tenant_id,
            url=URL,
            secret_ref=SECRET_REF,
            secret_ref_next=None,
            events=["analysis.completed"],
            facts_profile=facts_profile,
            reason="fictional partner test",
            operator_reference="fictional operator",
            supersede=False,
            apply=True,
            environment="development",
            now=since,
        )
    return UUID(result["after"]["endpoint_id"])


async def _copy_draft(
    sessions: Any, draft: Any, created_at: datetime, payload: dict[str, Any] | None = None
) -> UUID:
    """A re-analysis of the same call: a newer report draft with the same transcript."""
    draft_id = uuid4()
    async with sessions() as session, session.begin():
        session.add(
            ConversationReportDraft(
                id=draft_id,
                tenant_id=draft.tenant_id,
                person_id=draft.person_id,
                recording_id=draft.recording_id,
                run_id=draft.run_id,
                source_revision=draft.source_revision,
                source_sha256=draft.source_sha256,
                report_sha256=hashlib.sha256(draft_id.bytes).hexdigest(),
                transcript_sha256=draft.transcript_sha256,
                profile_sha256=draft.profile_sha256,
                evidence_receipt_sha256=draft.evidence_receipt_sha256,
                payload=copy.deepcopy(payload if payload is not None else draft.payload),
                transcript=copy.deepcopy(draft.transcript),
                evidence_receipt=copy.deepcopy(draft.evidence_receipt),
                created_at=created_at,
                erased_at=None,
            )
        )
    return draft_id


async def _process(
    sessions: Any, clock: Clock, provider: Callable[[dict[str, Any]], dict[str, Any]]
) -> list[dict[str, Any]]:
    """One extract + enqueue pass over every candidate, as the runner does."""
    lines = []
    async with sessions() as session:
        found = await pipeline.candidates(session, now=clock(), recent_hours=72, limit=10)
    for candidate in found:
        extraction, line = await pipeline.extract(
            sessions, candidate, apply=True, daily_cap=50, call_provider=provider, clock=clock
        )
        if extraction is not None:
            line.update(
                await pipeline.enqueue(
                    sessions,
                    candidate,
                    extraction,
                    app_url="https://salesxray.example.test",
                    clock=clock,
                )
            )
        lines.append(line)
    return lines


async def _events(sessions: Any) -> list[PartnerWebhookEvent]:
    async with sessions() as session:
        return list(
            (
                await session.scalars(
                    select(PartnerWebhookEvent).order_by(PartnerWebhookEvent.created_at)
                )
            ).all()
        )


def _verify(request: httpx.Request) -> None:
    stamp, *signatures = request.headers["X-SX-Signature"].split(",")
    expected = hmac.new(
        SECRET.encode(), stamp.removeprefix("t=").encode() + b"." + request.content, "sha256"
    ).hexdigest()
    assert signatures == [f"v1={expected}"]


def test_finished_report_becomes_one_signed_event_with_validated_quote_facts(
    postgres_harness: Any, report_fixture: ReportFixture
) -> None:
    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        clock = Clock()
        try:
            draft = await _draft(sessions, report_fixture)
            submission_id = await _submission(sessions, report_fixture, draft)
            lead_id = await _lead(sessions, draft.tenant_id, submission_id)
            async with sessions() as session:
                assert (
                    await pipeline.candidates(session, now=clock(), recent_hours=72, limit=10) == []
                )  # no endpoint yet
            endpoint_id = await _register(
                sessions, draft.tenant_id, draft.created_at - timedelta(minutes=1)
            )
            calls: list[str] = []

            def provider(body: dict[str, Any]) -> dict[str, Any]:
                calls.append("answer")
                return answer(body)

            (line,) = await _process(sessions, clock, provider)
            assert line["facts_outcome"] == "saved" and line["facts_dropped"] == 1
            assert line["revision"] == 1 and line["extraction"] == "complete"
            assert line["tokens"] == [900, 120] and line["est_paise"] >= 0
            # Idempotent: the report is no longer a candidate, and the facts are reused.
            assert await _process(sessions, clock, provider) == []
            assert calls == ["answer"]
            (event,) = await _events(sessions)
            payload = event.payload
            assert payload is not None
            assert event.endpoint_id == endpoint_id and event.status == "pending"
            assert event.payload_sha256 == body_sha256(payload)
            assert payload["schema"] == "sx.analysis_completed.v1"
            assert payload["event_id"] == str(event.id)
            assert payload["analysis_id"] == f"sub_{submission_id.hex}"
            assert payload["analysis_url"] == (
                f"https://salesxray.example.test/analysis/calls/{submission_id}"
            )
            assert payload["analysis_revision"] == 1 and payload["supersedes_event_id"] is None
            assert payload["call"]["duration_sec"] == 1
            assert payload["call"]["report_language"] == "en"
            async with sessions() as session:
                person = await session.get(Person, report_fixture.prepared.state.person_id)
                assert person is not None
            assert payload["salesperson"] == {
                "ref": f"per_{person.id.hex}",
                "name": person.display_name,
                "email": person.email,
            }
            assert payload["lead"] == {
                "ref": f"lead_{lead_id.hex}",
                "phone_e164": "+910000000000",
                "name": "Customer A",
                "city": "Pune",
            }
            assert draft.payload is not None
            assert payload["summary"] == summary_text(draft.payload["summary"])
            assert payload["outcome"] == {"kind": None}
            assert payload["extraction"]["status"] == "complete"
            product = [fact for fact in payload["facts"] if fact["type"] == "product_mention"]
            assert len(product) == 1 and product[0]["source"]["segment_id"]
            assert not any(fact["type"] == "mentioned_price" for fact in payload["facts"])
            assert {fact["type"] for fact in payload["facts"] if fact["status"] == "unknown"} == {
                "system_size",
                "battery_type",
                "warranty",
                "site",
                "delivery_basis",
            }

            receiver = Receiver(202)
            async with receiver.client() as client:
                delivered = await deliver_one(
                    sessions, client, environment="development", clock=clock
                )
                assert (
                    await deliver_one(sessions, client, environment="development", clock=clock)
                    is None
                )
            assert delivered is not None and delivered["status"] == "delivered"
            (request,) = receiver.requests
            assert str(request.url) == URL
            assert request.headers["X-SX-Event-Id"] == str(event.id)
            assert request.headers["X-SX-Event-Type"] == "analysis.completed"
            assert hashlib.sha256(request.content).hexdigest() == event.payload_sha256
            assert json.loads(request.content) == payload
            _verify(request)
            async with sessions() as session:
                stored = await session.get(PartnerWebhookEvent, event.id)
                assert stored is not None and stored.status == "delivered"
                assert stored.attempts == 1 and stored.last_http_status == 202
                attempts = (await session.scalars(select(PartnerWebhookAttempt))).all()
                assert [(item.attempt, item.http_status, item.error_code) for item in attempts] == [
                    (1, 202, None)
                ]
                facts_row = await session.scalar(select(PartnerQuoteFacts))
                assert facts_row is not None and facts_row.status == "complete"
                assert facts_row.attempt == 1 and facts_row.input_tokens == 900
                # The paid-attempt ledger carries ids, digests and counts, never words.
                ledger_events = (
                    await session.scalars(
                        select(AuditEvent)
                        .where(AuditEvent.action.in_((ledger.STARTED, ledger.FINISHED)))
                        .order_by(AuditEvent.sequence_no)
                    )
                ).all()
                assert [item.payload.get("outcome") for item in ledger_events] == [None, "saved"]
                text = json.dumps([item.payload for item in ledger_events])
                assert "buyer" not in text.lower() and "hello" not in text.lower()
                assert (await verify_audit_chain(session, draft.tenant_id)).valid
        finally:
            await engine.dispose()

    run(exercise())


def test_retries_dead_letter_replay_admission_drop_and_no_double_send(
    postgres_harness: Any, report_fixture: ReportFixture, owner_alerts: list[str]
) -> None:
    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        clock = Clock()
        try:
            draft = await _draft(sessions, report_fixture)
            submission_id = await _submission(sessions, report_fixture, draft)
            endpoint_id = await _register(
                sessions, draft.tenant_id, draft.created_at - timedelta(minutes=1)
            )
            # Five frozen events for five reports of the same call.
            drafts = [draft.id]
            for minutes in (5, 4, 3, 2):
                drafts.append(
                    await _copy_draft(
                        sessions, draft, draft.created_at - timedelta(minutes=minutes)
                    )
                )
            async with sessions() as session, session.begin():
                for number, draft_id in enumerate(drafts, 1):
                    payload = {"schema": "sx.analysis_completed.v1", "fictional": number}
                    session.add(
                        PartnerWebhookEvent(
                            id=uuid4(),
                            endpoint_id=endpoint_id,
                            tenant_id=draft.tenant_id,
                            recording_id=draft.recording_id,
                            report_draft_id=draft_id,
                            submission_id=submission_id,
                            event_type="analysis.completed",
                            analysis_revision=number,
                            supersedes_event_id=None,
                            payload=payload,
                            payload_sha256=body_sha256(payload),
                            status="pending",
                            attempts=0,
                            replayed_attempts=0,
                            next_attempt_at=clock() - timedelta(seconds=1),
                            created_at=clock(),
                        )
                    )
            # A claimed event is leased: a second runner skips it.
            async with sessions() as first, first.begin():
                held = await claim_next(first, clock())
                assert held is not None
                async with sessions() as second, second.begin():
                    other = await claim_next(second, clock())
                    assert other is not None and other.event_id != held.event_id
            async with sessions() as session, session.begin():
                await session.execute(
                    update(PartnerWebhookEvent).values(leased_until=None)
                )  # release both leases for the runners below

            # Two runners at once: every event is sent exactly once.
            receiver = Receiver()

            async def runner() -> None:
                async with receiver.client() as client:
                    for _ in range(10):
                        if not await deliver_one(
                            sessions, client, environment="development", clock=clock
                        ):
                            return
                        await asyncio.sleep(0)

            await asyncio.gather(runner(), runner())
            sent = [request.headers["X-SX-Event-Id"] for request in receiver.requests]
            assert len(sent) == 5 and len(set(sent)) == 5
            events = await _events(sessions)
            assert {event.status for event in events} == {"delivered"}

            # A failing endpoint: retried with backoff, then dead-lettered, then replayed.
            target = events[0]
            async with sessions() as session, session.begin():
                await session.execute(
                    update(PartnerWebhookEvent)
                    .where(PartnerWebhookEvent.id == target.id)
                    .values(status="pending", delivered_at=None, next_attempt_at=clock())
                )
            failing = Receiver(500, 500, 500)
            async with failing.client() as client:
                line = await deliver_one(sessions, client, environment="development", clock=clock)
                assert line is not None and line["status"] == "pending"
                async with sessions() as session:
                    stored = await session.get(PartnerWebhookEvent, target.id)
                    assert stored is not None
                    assert stored.attempts == 2 and stored.last_http_status == 500
                    assert stored.last_error_code == "http_status"
                    assert stored.next_attempt_at == clock() + retry_delay(2)
                # Not due yet: nothing is sent.
                assert (
                    await deliver_one(sessions, client, environment="development", clock=clock)
                    is None
                )
                async with sessions() as session, session.begin():
                    await session.execute(
                        update(PartnerWebhookEvent)
                        .where(PartnerWebhookEvent.id == target.id)
                        .values(attempts=24, next_attempt_at=clock())
                    )
                assert owner_alerts == []
                line = await deliver_one(sessions, client, environment="development", clock=clock)
                assert line is not None and line["status"] == "dead_letter"
                # Review 18 Oct, item 6: the owner is alerted, with ids and a count only.
                assert line["alert"] == "dead_letter" and line["notified"] == "sent"
                (alert,) = owner_alerts
                assert alert == (
                    "Sales X-Ray partner webhook dead letter (development): endpoint "
                    f"{str(endpoint_id)[:8]}, event {str(target.id)[:8]}, 25 attempts. "
                    "Replay it with the partner_events CLI once the endpoint answers."
                )
                async with sessions() as session, session.begin():
                    with pytest.raises(endpoints.EndpointError):
                        await endpoints.replay(
                            session,
                            event_id=events[1].id,
                            reason="fictional",
                            operator_reference="fictional operator",
                            apply=True,
                            now=clock(),
                        )
                async with sessions() as session, session.begin():
                    dry = await endpoints.replay(
                        session,
                        event_id=target.id,
                        reason="partner asked for a resend",
                        operator_reference="fictional operator",
                        apply=False,
                        now=clock(),
                    )
                    assert dry["before"] == {"status": "dead_letter", "attempts": 25}
                async with sessions() as session:
                    stored = await session.get(PartnerWebhookEvent, target.id)
                    assert stored is not None and stored.status == "dead_letter"
                async with sessions() as session, session.begin():
                    replayed = await endpoints.replay(
                        session,
                        event_id=target.id,
                        reason="partner asked for a resend",
                        operator_reference="fictional operator",
                        apply=True,
                        now=clock(),
                    )
                    assert replayed["applied"] is True
                line = await deliver_one(sessions, client, environment="development", clock=clock)
                assert line is not None and line["status"] == "pending" and line["attempt"] == 26
                async with sessions() as session:
                    stored = await session.get(PartnerWebhookEvent, target.id)
                    assert stored is not None and stored.replayed_attempts == 25
                    assert stored.next_attempt_at == clock() + retry_delay(1)
                    attempts = await session.scalar(
                        select(func.count())
                        .select_from(PartnerWebhookAttempt)
                        .where(PartnerWebhookAttempt.event_id == target.id)
                    )
                    assert attempts == 4  # the first delivery and three failures (others skipped)

            # Consent revoked before a retry: the event is dropped and emptied, never sent.
            async with sessions() as session, session.begin():
                await session.execute(
                    update(ConversationPermission)
                    .where(ConversationPermission.id == report_fixture.prepared.state.permission_id)
                    .values(revoked_at=clock())
                )
                await session.execute(
                    update(PartnerWebhookEvent)
                    .where(PartnerWebhookEvent.id == target.id)
                    .values(next_attempt_at=clock())
                )
            blocked = Receiver()
            async with blocked.client() as client:
                line = await deliver_one(sessions, client, environment="development", clock=clock)
            assert line is not None and line["dropped"] == "permission_inactive"
            assert blocked.requests == []
            async with sessions() as session:
                stored = await session.get(PartnerWebhookEvent, target.id)
                assert stored is not None and stored.status == "dropped"
                assert stored.payload is None and stored.erased_at is not None
        finally:
            await engine.dispose()

    run(exercise())


def test_failed_extraction_revision_chain_and_erasure(
    postgres_harness: Any, report_fixture: ReportFixture
) -> None:
    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        clock = Clock()
        try:
            draft = await _draft(sessions, report_fixture)
            await _submission(sessions, report_fixture, draft)
            await _register(sessions, draft.tenant_id, draft.created_at - timedelta(minutes=1))

            def timeout(body: dict[str, Any]) -> dict[str, Any]:
                raise ProviderFailure("timeout")

            # First failure waits for a second attempt; the second sends extraction "failed".
            (first,) = await _process(sessions, clock, timeout)
            assert first == {"facts_attempt": 1, "facts_outcome": "timeout"}
            (second,) = await _process(sessions, clock, timeout)
            assert second["facts_attempt"] == 2 and second["extraction"] == "failed"
            (event_a,) = await _events(sessions)
            assert event_a.payload is not None
            assert event_a.payload["extraction"]["status"] == "failed"
            assert event_a.payload["facts"] == []
            async with sessions() as session:
                rows = (
                    await session.scalars(
                        select(PartnerQuoteFacts).order_by(PartnerQuoteFacts.attempt)
                    )
                ).all()
                assert [(row.attempt, row.status, row.error_code) for row in rows] == [
                    (1, "failed", "timeout"),
                    (2, "failed", "timeout"),
                ]
            receiver = Receiver()
            async with receiver.client() as client:
                await deliver_one(sessions, client, environment="development", clock=clock)

            # A re-analysis: revision 2 supersedes the first event.
            clock.now = clock.now + timedelta(minutes=1)
            await _copy_draft(sessions, draft, clock.now - timedelta(seconds=5))
            (line,) = await _process(sessions, clock, answer)
            assert line["revision"] == 2 and line["extraction"] == "complete"
            events = await _events(sessions)
            assert len(events) == 2
            event_b = events[1]
            assert event_b.payload is not None
            assert event_b.analysis_revision == 2
            assert event_b.supersedes_event_id == event_a.id
            assert event_b.payload["supersedes_event_id"] == str(event_a.id)
            assert event_b.payload["analysis_id"] == event_a.payload["analysis_id"]

            # The call is erased before event B is sent: it is dropped, never sent, and
            # every payload and quote facts row of the call is emptied.
            async with sessions() as session, session.begin():
                await ConversationApplication(
                    session, clock=lambda: report_fixture.prepared.state.now
                ).request_deletion(
                    report_fixture.actor,
                    report_fixture.prepared.recording_id,
                    key="partner-events-erasure",
                )
            async with receiver.client() as client:
                sent = await deliver_one(sessions, client, environment="development", clock=clock)
            assert sent is not None and sent["dropped"] == "call_erased"
            assert len(receiver.requests) == 1
            async with sessions() as session, session.begin():
                swept = await erasure_sweep(session, clock())
                assert swept["events_erased"] == 1  # the delivered event A
            async with sessions() as session, session.begin():
                assert await erasure_sweep(session, clock()) == {
                    "facts_erased": 0,
                    "events_erased": 0,
                }
            async with sessions() as session:
                for event in (await session.scalars(select(PartnerWebhookEvent))).all():
                    assert event.payload is None and event.erased_at is not None
                statuses = {
                    event.id: event.status
                    for event in (await session.scalars(select(PartnerWebhookEvent))).all()
                }
                assert statuses == {event_a.id: "delivered", event_b.id: "dropped"}
                for row in (await session.scalars(select(PartnerQuoteFacts))).all():
                    assert row.payload is None and row.erased_at is not None
            # Nothing of an erased call is a candidate again.
            assert await _process(sessions, clock, answer) == []
        finally:
            await engine.dispose()

    run(exercise())


def test_cli_dry_runs_change_nothing_and_apply_runs_one_pass(
    postgres_harness: Any,
    report_fixture: ReportFixture,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    url_file = tmp_path / "database-url"
    url = postgres_harness.url
    url_file.write_text(url if isinstance(url, str) else url.render_as_string(hide_password=False))
    service = tmp_path / "service.json"
    service.write_text(json.dumps({"environment": "development", "providers": []}))

    def arguments(*command: str) -> Namespace:
        return cli._arguments(
            [
                "--service-config",
                str(service),
                "--database-url-file",
                str(url_file),
                "--app-url",
                "https://salesxray.example.test",
                *command,
            ]
        )

    def output() -> list[dict[str, Any]]:
        return [json.loads(line) for line in capsys.readouterr().out.splitlines()]

    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            draft = await _draft(sessions, report_fixture)
            await _submission(sessions, report_fixture, draft)
            tenant = str(draft.tenant_id)
            # With no active endpoint an applied run needs no secret: it stops before Infisical.
            assert await cli._preflight_async(arguments("run", "--apply")) is False
            assert output() == [{"endpoints": 0}]
            register = (
                "register-endpoint",
                "--tenant",
                tenant,
                "--url",
                "http://127.0.0.1:8787/hook?token=fictional",
                "--secret-ref",
                SECRET_REF,
                "--events",
                "analysis.completed",
                "--facts-profile",
                PROFILE,
                "--reason",
                "fictional partner test",
                "--operator-reference",
                "fictional operator",
            )
            assert await cli._inner_async(arguments(*register)) == 0
            (dry,) = output()
            assert dry["apply"] is False and dry["before"] is None
            assert dry["after"]["url"] == "http://127.0.0.1:8787/…"
            async with sessions() as session:
                assert (
                    await session.scalar(select(func.count()).select_from(PartnerWebhookEndpoint))
                    == 0
                )
            assert await cli._inner_async(arguments(*register, "--apply")) == 0
            (applied,) = output()
            endpoint_id = applied["after"]["endpoint_id"]
            # A second active endpoint needs --supersede.
            assert await cli._inner_async(arguments(*register, "--apply")) == 2
            assert output() == [{"error": "active_endpoint_exists_use_supersede"}]
            async with sessions() as session, session.begin():
                await session.execute(
                    update(PartnerWebhookEndpoint).values(
                        events_since=draft.created_at - timedelta(minutes=1)
                    )
                )
            assert await cli._inner_async(arguments("list")) == 0
            (listed,) = output()
            assert listed["endpoints"][0]["url"] == "http://127.0.0.1:8787/…"
            assert "token" not in json.dumps(listed)

            # A dry run pays nothing and writes nothing.
            calls: list[str] = []

            def provider(body: dict[str, Any]) -> dict[str, Any]:
                calls.append("answer")
                return answer(body)

            assert await cli._inner_async(arguments("run"), call_provider=provider) == 0
            lines = output()
            assert lines[0]["facts"] == "would_extract"
            assert lines[-1] == {"due_events": 0, "apply": False}
            assert calls == []
            async with sessions() as session:
                assert await session.scalar(select(func.count()).select_from(AuditEvent).where(
                    AuditEvent.action == ledger.STARTED
                )) == 0  # fmt: skip
            assert (
                await cli._inner_async(arguments("test-event", "--endpoint-id", endpoint_id)) == 0
            )
            (test_dry,) = output()
            assert test_dry["apply"] is False and test_dry["endpoint"] == "http://127.0.0.1:8787/…"

            # Our own test sources (the canary fixture) are filtered in the query: never
            # read, never sent, and no row is written for them.
            original = pipeline.test_sources

            async def everything_is_a_test(session: Any) -> set[str]:
                return {draft.source_sha256}

            pipeline.test_sources = everything_is_a_test
            try:
                status = await cli._inner_async(
                    arguments("run", "--apply", "--seconds", "1"), call_provider=provider
                )
            finally:
                pipeline.test_sources = original
            assert status == 0 and calls == []
            assert output() == []
            assert await _events(sessions) == []

            # One applied pass: quote facts, enqueue, signed delivery to the local receiver.
            receiver = Receiver(200)
            async with receiver.client() as client:
                status = await cli._inner_async(
                    arguments("run", "--apply", "--seconds", "1"),
                    call_provider=provider,
                    client=client,
                )
            assert status == 0 and calls == ["answer"]
            totals = output()[-1]["totals"]
            assert totals["enqueued"] == 1 and totals["delivered"] == 1
            (request,) = receiver.requests
            assert str(request.url) == "http://127.0.0.1:8787/hook?token=fictional"
            _verify(request)

            # A signed fictional test event, recorded in the audit chain.
            receiver = Receiver(204)
            async with receiver.client() as client:
                status = await cli._inner_async(
                    arguments("test-event", "--endpoint-id", endpoint_id, "--apply"),
                    client=client,
                )
            assert status == 0
            (sent,) = output()
            assert sent["http_status"] == 204
            (request,) = receiver.requests
            assert json.loads(request.content)["schema"] == "sx.test.v1"
            assert request.headers["X-SX-Event-Type"] == "test"
            _verify(request)

            # Disabling drops nothing already delivered and is audited.
            assert (
                await cli._inner_async(
                    arguments(
                        "disable-endpoint",
                        "--endpoint-id",
                        endpoint_id,
                        "--reason",
                        "pilot paused",
                        "--operator-reference",
                        "fictional operator",
                        "--apply",
                    )
                )
                == 0
            )
            (disabled,) = output()
            assert disabled["after"]["status"] == "disabled"
            assert disabled["undelivered_events_to_drop"] == 0
            async with sessions() as session:
                actions = (
                    await session.scalars(
                        select(AuditEvent.action)
                        .where(AuditEvent.action.like("partner_events.%"))
                        .order_by(AuditEvent.sequence_no)
                    )
                ).all()
            assert actions == [
                "partner_events.endpoint_registered",
                ledger.STARTED,
                ledger.FINISHED,
                "partner_events.test_event_sent",
                "partner_events.endpoint_disabled",
            ]
            assert SECRET not in capsys.readouterr().out
        finally:
            await engine.dispose()

    run(exercise())


async def _runner_pass(
    sessions: Any,
    clock: Clock,
    provider: Callable[[dict[str, Any]], dict[str, Any]],
    *,
    receiver: Receiver | None = None,
) -> dict[str, int]:
    """One real runner pass (``cli._one_pass``): pages, final rows, age-out, delivery, sweep."""
    totals = dict.fromkeys(
        ("enqueued", "final", "aged_out", "attempts", "delivered", "dropped", "dead_letters",
         "errors", "waiting"),
        0,
    )  # fmt: skip
    arguments = Namespace(apply=True, limit=10, recent_hours=72, daily_cap=50)
    async with (receiver or Receiver()).client() as client:
        await cli._one_pass(
            sessions,
            arguments,
            environment="development",
            app_url="https://salesxray.example.test",
            client=client,
            call_provider=provider,
            clock=clock,
            deadline=time.monotonic() + 60,
            totals=totals,
            cache={},
        )
    return totals


def test_reports_never_sent_get_a_final_row_and_an_aged_out_report_alerts(
    postgres_harness: Any,
    report_fixture: ReportFixture,
    owner_alerts: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review 18 Oct, item 5: no report blocks newer ones or ages out silently."""

    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        clock = Clock()
        try:
            draft = await _draft(sessions, report_fixture)
            await _submission(sessions, report_fixture, draft)
            endpoint_id = await _register(
                sessions, draft.tenant_id, draft.created_at - timedelta(minutes=1)
            )
            calls: list[str] = []

            def provider(body: dict[str, Any]) -> dict[str, Any]:
                calls.append("answer")
                return answer(body)

            # Our own test sources are filtered in the query: no row, never a candidate.
            original = pipeline.test_sources

            async def everything_is_a_test(session: Any) -> set[str]:
                return {draft.source_sha256}

            monkeypatch.setattr(pipeline, "test_sources", everything_is_a_test)
            totals = await _runner_pass(sessions, clock, provider)
            monkeypatch.setattr(pipeline, "test_sources", original)
            assert totals["enqueued"] == totals["final"] == totals["waiting"] == 0
            assert calls == [] and await _events(sessions) == []
            async with sessions() as session:
                assert (
                    await pipeline.candidates(
                        session,
                        now=clock(),
                        recent_hours=72,
                        limit=10,
                        tests={draft.source_sha256},
                    )
                    == []
                )

            # A newer report without a transcript revision: a final row; it is never read.
            assert draft.payload is not None
            no_revision = copy.deepcopy(draft.payload)
            no_revision.pop("transcript_revision", None)
            clock.now += timedelta(seconds=10)
            second = await _copy_draft(
                sessions, draft, clock.now - timedelta(seconds=5), payload=no_revision
            )
            totals = await _runner_pass(sessions, clock, provider)
            assert totals["final"] == 1 and calls == []
            (row,) = await _events(sessions)
            assert (row.report_draft_id, row.endpoint_id, row.status) == (
                second,
                endpoint_id,
                "dropped",
            )
            assert row.last_error_code == "transcript_revision_missing"
            assert row.payload is None and row.erased_at is not None and row.attempts == 0
            assert row.payload_sha256 == hashlib.sha256(b"").hexdigest()
            assert row.analysis_revision >= 2 and row.supersedes_event_id is None

            # Consent revoked before the event is built: a final row; nothing is paid or sent.
            clock.now += timedelta(seconds=10)
            third = await _copy_draft(sessions, draft, clock.now - timedelta(seconds=5))
            async with sessions() as session, session.begin():
                await session.execute(
                    update(ConversationPermission)
                    .where(ConversationPermission.id == report_fixture.prepared.state.permission_id)
                    .values(revoked_at=clock())
                )
            receiver = Receiver()
            totals = await _runner_pass(sessions, clock, provider, receiver=receiver)
            assert totals["final"] == 1 and calls == [] and receiver.requests == []
            events = await _events(sessions)
            assert [(event.report_draft_id, event.last_error_code) for event in events] == [
                (second, "transcript_revision_missing"),
                (third, "permission_inactive"),
            ]
            # Final rows are final: the next pass finds nothing to do or wait for.
            totals = await _runner_pass(sessions, clock, provider)
            assert totals["final"] == totals["waiting"] == totals["errors"] == 0
            assert len(await _events(sessions)) == 2

            # A report still without an event after the recent window: recorded, owner alerted.
            clock.now += timedelta(seconds=10)
            fourth = await _copy_draft(sessions, draft, clock.now - timedelta(seconds=5))
            clock.now += timedelta(hours=73)
            assert owner_alerts == []
            totals = await _runner_pass(sessions, clock, provider)
            assert totals["aged_out"] == 1 and totals["final"] == 0 and calls == []
            last = (await _events(sessions))[-1]
            assert (last.report_draft_id, last.status, last.last_error_code) == (
                fourth,
                "dropped",
                "aged_out",
            )
            assert last.payload is None
            (alert,) = owner_alerts
            assert alert.startswith(
                "Sales X-Ray partner webhooks (development): 1 report(s) aged out after 72 h"
            )
            assert f"(endpoint {str(endpoint_id)[:8]})" in alert
            totals = await _runner_pass(sessions, clock, provider)
            assert totals["aged_out"] == 0 and len(owner_alerts) == 1
            async with sessions() as session:
                (listed,) = await endpoints.list_endpoints(session)
            assert listed["events"] == {
                "pending": 0,
                "delivered": 0,
                "dead_letter": 0,
                "dropped": 3,
            }
        finally:
            await engine.dispose()

    run(exercise())


def test_supersedes_follows_the_endpoint_chain_and_payloads_are_emptied(
    postgres_harness: Any, report_fixture: ReportFixture
) -> None:
    """Review 18 Oct, items 1, 7, 9, 12 and 13."""

    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        clock = Clock()
        try:
            draft = await _draft(sessions, report_fixture)
            assert draft.payload is not None
            await _submission(sessions, report_fixture, draft)
            first_endpoint = await _register(
                sessions, draft.tenant_id, draft.created_at - timedelta(minutes=1)
            )
            await _process(sessions, clock, answer)
            (event_a,) = await _events(sessions)
            receiver = Receiver()
            async with receiver.client() as client:
                line = await deliver_one(sessions, client, environment="development", clock=clock)
            assert line is not None and line["status"] == "delivered"

            # A secret rotation supersedes the endpoint; the next secret is not set yet.
            async with sessions() as session, session.begin():
                rotated = await endpoints.register(
                    session,
                    tenant_id=draft.tenant_id,
                    url=URL,
                    secret_ref=SECRET_REF,
                    secret_ref_next=NEXT_SECRET_REF,
                    events=["analysis.completed"],
                    facts_profile=PROFILE,
                    reason="fictional rotation",
                    operator_reference="fictional operator",
                    supersede=True,
                    apply=True,
                    environment="development",
                    now=clock(),
                )
            second_endpoint = UUID(rotated["after"]["endpoint_id"])

            # A re-analysis whose summary names prices: it supersedes A, prices are masked.
            priced = copy.deepcopy(draft.payload)
            priced["summary"] = (
                "Customer wants 5 kW; budget teen lakh sattar hazaar, packing 500, "
                "₹3,40,000 quoted, सवा दो लाख तक."
            )
            clock.now += timedelta(minutes=1)
            await _copy_draft(sessions, draft, clock.now - timedelta(seconds=5), payload=priced)
            (line,) = await _process(sessions, clock, answer)
            event_b = (await _events(sessions))[-1]
            assert event_b.payload is not None
            assert event_b.endpoint_id == second_endpoint
            assert event_b.supersedes_event_id == event_a.id
            assert event_b.payload["summary"] == (
                "Customer wants 5 kW; budget [amount], packing [amount], [amount] quoted, "
                "[amount] तक."
            )
            # Item 9: the missing next secret no longer blocks delivery; the current one signs.
            receiver = Receiver()
            async with receiver.client() as client:
                line = await deliver_one(sessions, client, environment="development", clock=clock)
            assert line is not None and line["status"] == "delivered"
            assert line["rotation"] == "next_not_set"
            (request,) = receiver.requests
            _verify(request)

            # An event dropped unsent is never what a newer event supersedes.
            clock.now += timedelta(minutes=1)
            await _copy_draft(sessions, draft, clock.now - timedelta(seconds=5))
            await _process(sessions, clock, answer)
            event_c = (await _events(sessions))[-1]
            async with sessions() as session, session.begin():
                await drop(session, event_c.id, "call_erased", clock())
            clock.now += timedelta(minutes=1)
            await _copy_draft(sessions, draft, clock.now - timedelta(seconds=5))
            await _process(sessions, clock, answer)
            event_d = (await _events(sessions))[-1]
            assert event_d.supersedes_event_id == event_b.id

            # Item 13: disabling drops and empties the undelivered events.
            async with sessions() as session, session.begin():
                disabled = await endpoints.disable(
                    session,
                    endpoint_id=second_endpoint,
                    reason="pilot paused",
                    operator_reference="fictional operator",
                    apply=True,
                    now=clock(),
                )
            assert disabled["undelivered_events_to_drop"] == 1
            async with sessions() as session:
                stored = await session.get(PartnerWebhookEvent, event_d.id)
                assert stored is not None and stored.status == "dropped"
                assert stored.payload is None and stored.erased_at is not None
                assert stored.last_error_code == "endpoint_disabled"

            # A new endpoint (not a supersede) starts its own chain.
            third_endpoint = await _register(sessions, draft.tenant_id, clock())
            assert third_endpoint != first_endpoint
            clock.now += timedelta(minutes=1)
            await _copy_draft(sessions, draft, clock.now - timedelta(seconds=5))
            await _process(sessions, clock, answer)
            event_e = (await _events(sessions))[-1]
            assert event_e.endpoint_id == third_endpoint
            assert event_e.supersedes_event_id is None

            # Item 7: the canonical erasure hook empties every partner row of the call at once.
            async with sessions() as session, session.begin():
                erased = await erase_partner_rows_for_recording(
                    session,
                    tenant_id=draft.tenant_id,
                    recording_id=draft.recording_id,
                    now=clock(),
                )
            assert erased == {"facts_erased": 5, "events_erased": 3}  # A, B delivered; E pending
            async with sessions() as session, session.begin():
                again = await erase_partner_rows_for_recording(
                    session,
                    tenant_id=draft.tenant_id,
                    recording_id=draft.recording_id,
                    now=clock(),
                )
            assert again == {"facts_erased": 0, "events_erased": 0}
            async with sessions() as session:
                rows = (await session.scalars(select(PartnerWebhookEvent))).all()
                assert all(row.payload is None and row.erased_at is not None for row in rows)
                statuses = {row.id: (row.status, row.last_error_code) for row in rows}
                assert statuses[event_a.id][0] == statuses[event_b.id][0] == "delivered"
                assert statuses[event_e.id] == ("dropped", "call_erased")
                for facts in (await session.scalars(select(PartnerQuoteFacts))).all():
                    assert facts.payload is None and facts.erased_at is not None
        finally:
            await engine.dispose()

    run(exercise())
