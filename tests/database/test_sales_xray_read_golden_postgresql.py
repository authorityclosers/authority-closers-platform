"""Golden Sales Xray read responses and SQL statement budgets (performance safety net).

One fictional workspace exercises the reads behind the Calls list, call progress,
Report, transcript, speaker map and coaching pages: a durable C2-C6 report with a
call name, confirmed speakers, a recorded outcome and a saved AI pointer review; a
private legacy draft with a sensitive mark; held, active and quoted plans; local-only
and queued uploads; a claimed and an unclaimed guest call; an organisation member's
call read by the owner (the rep has their own display name); and enough calls for a
second list page.

Every response must equal the checked-in golden JSON exactly (status code, key sets,
values and list order). Only per-run identifiers (UUIDs) and wall-clock timestamps are
replaced, by stable placeholders numbered in order of first appearance, so equal
identifiers stay equal. In Coaching's ``call_label`` only, the run's own display date
("Sales call · 17 Oct 2026") becomes ``<date>``; any other date stays literal, so a
wrong day fails. Every read must also stay within its statement budget.
Set ``AC_UPDATE_FIXTURES=1`` to rewrite the golden file after an intentional change.
``AC_READ_PROBE_OUT`` (and optional ``AC_READ_PROBE_REPEAT``) write per-read statement
counts and wall times for before/after measurements. No provider or network call is made.
"""

from __future__ import annotations

import json
import os
import re
import statistics
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import event, select, update

from ac_platform.conversation_intelligence.broker_router import FixedProviderRouter, ProviderRoute
from ac_platform.conversation_intelligence.guest_models import ConversationGuestSubmission
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.conversation_intelligence.inference_worker import ConversationInferenceWorker
from ac_platform.conversation_intelligence.models import (
    ConversationCommand,
    ConversationProcessingPlan,
    ConversationRecording,
    ConversationReportDraft,
)
from ac_platform.conversation_intelligence.pointer_review import parse_review, payload_sha256
from ac_platform.conversation_intelligence.pointer_review_models import ConversationPointerReview
from ac_platform.conversation_intelligence.processing_plan import ProcessingPlanScheduler
from ac_platform.conversation_intelligence.prospect_call_outcome import (
    DealValue,
    HumanOutcome,
    HumanOutcomeCommand,
)
from ac_platform.conversation_intelligence.prospect_call_outcome_store import CallOutcomeStore
from ac_platform.conversation_intelligence.prospect_store import ProspectStore
from ac_platform.conversation_intelligence.sensitive_segments_store import SensitiveSegmentsStore
from ac_platform.identity.models import Person
from ac_platform.tenancy.models import Organisation
from tests.database.test_coaching_postgresql import draft_for, install
from tests.database.test_conversation_account_library_postgresql import (
    _seed_retained_guest_submission,
    _session,
)
from tests.database.test_conversation_library_reports_first_postgresql import _pause_analysis
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_processing_plan_postgresql import _make_due
from tests.database.test_conversation_reporting_pipeline_postgresql import ReportingBroker
from tests.database.test_conversation_submission_http_postgresql import (
    ORIGIN,
    PREFIX,
    _headers,
    _setup,
    _sign_in,
)
from tests.database.test_conversation_worker_postgresql import (
    OfflineConversationWorker,
    _reconcile,
    _wav_one_second_48k,
)
from tests.database.test_prospect_store_postgresql import direct_call
from tests.unit.conversation_intelligence.test_pointer_review import answer

GOLDEN = Path(__file__).resolve().parents[1] / "fixtures" / "sales_xray_read_golden.json"
COACHING = "/v1/me/coaching"
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})?")
# Coaching names undated calls by their UTC creation date ("Sales call · 17 Oct 2026").
# Only that field, and only a date this run's clock produced, becomes ``<date>``.
_DATE = re.compile(r"\b\d{1,2} (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{4}\b")

# Upper bounds on SQL statements per HTTP read, including session admission.
# Lower a bound when a read gets cheaper; never raise one to hide a regression.
BUDGETS: dict[str, int] = {
    "list.owners.page1": 14,
    "list.owners.page2": 15,
    "list.newest.page1": 14,
    "list.reports_first.page1": 14,
    "list.summary": 13,
    "progress.analysed": 76,
    "progress.local_only": 54,
    "progress.queued": 54,
    "progress.legacy": 54,
    "progress.held": 65,
    "progress.active": 53,
    "progress.quoted": 53,
    "progress.claimed": 95,
    "progress.rep": 60,
    "report.analysed": 268,
    "report.legacy": 168,
    "report.rep": 182,
    "report.local_only": 34,
    "transcript.analysed": 61,
    "transcript.legacy": 36,
    "transcript.local_only": 34,
    "speaker_map.analysed": 106,
    "speaker_map.legacy": 57,
    "coaching.home": 117,
    "coaching.team": 158,
    "rep.list.page1": 14,
    "rep.progress.rep": 54,
    "rep.report.rep": 168,
    "rep.report.analysed": 17,
    "guest.progress.unclaimed": 47,
    "guest.report.unclaimed": 28,
    "guest.transcript.unclaimed": 28,
    "guest.report.analysed": 4,
}


@pytest.fixture
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


class _Normaliser:
    """Replace per-run identifiers and clock values with first-appearance placeholders."""

    def __init__(self, named: dict[str, str], dates: frozenset[str] = frozenset()) -> None:
        self.names = dict(named)
        self.dates = dates
        self.counts = {"uuid": 0, "time": 0}

    def _token(self, kind: str, value: str) -> str:
        if value not in self.names:
            self.counts[kind] += 1
            self.names[value] = f"<{kind}-{self.counts[kind]}>"
        return self.names[value]

    def text(self, value: str) -> str:
        value = _UUID.sub(lambda match: self._token("uuid", match.group(0)), value)
        return _TIME.sub(lambda match: self._token("time", match.group(0)), value)

    def __call__(self, value: Any, key: str | None = None) -> Any:
        if isinstance(value, dict):
            # Sorted traversal keeps placeholder numbering independent of key order.
            return {self.text(name): self(value[name], name) for name in sorted(value)}
        if isinstance(value, list):
            return [self(item) for item in value]
        if isinstance(value, str):
            text = self.text(value)
            if key == "call_label":
                text = _DATE.sub(
                    lambda match: "<date>" if match.group(0) in self.dates else match.group(0),
                    text,
                )
            return text
        return value


def _display_dates(start: datetime, end: datetime) -> frozenset[str]:
    """Every UTC calendar day this run's clock covered, as Coaching writes it."""
    day, last, found = start.astimezone(UTC).date(), end.astimezone(UTC).date(), set()
    while day <= last:
        found.add(f"{day.day} {day:%b %Y}")
        day += timedelta(days=1)
    return frozenset(found)


def _tick(setup: Any) -> None:
    """Distinct created_at values make every list order deterministic."""
    setup.clock[0] += timedelta(seconds=1)


async def _upload(setup: Any, client: httpx.AsyncClient) -> UUID:
    _tick(setup)
    data, submission = _wav_one_second_48k(), uuid4()
    response = await client.put(
        f"{PREFIX}/submissions/{submission}/source",
        content=data,
        headers=await _headers(client, data),
    )
    assert response.status_code == 202, response.text
    return submission


async def _call(setup: Any) -> UUID:
    _tick(setup)
    return await direct_call(setup)


async def _recording_for(setup: Any, submission: UUID) -> ConversationRecording:
    async with setup.sessions() as db:
        link = await db.scalar(
            select(ConversationGuestSubmission).where(
                ConversationGuestSubmission.submission_id == submission
            )
        )
        assert link is not None
        recording = await db.get(ConversationRecording, link.recording_id)
        assert recording is not None
        return recording


async def _plan(setup: Any, submission: UUID, state: str) -> None:
    """A plan row in one exact state (active plans cite an accepted command)."""
    async with setup.sessions() as db, db.begin():
        link = await db.scalar(
            select(ConversationGuestSubmission).where(
                ConversationGuestSubmission.submission_id == submission
            )
        )
        assert link is not None
        recording = await db.get(ConversationRecording, link.recording_id)
        assert recording is not None
        command = await db.scalar(
            select(ConversationCommand.id).where(
                ConversationCommand.tenant_id == recording.tenant_id,
                ConversationCommand.person_id == recording.person_id,
            )
        )
        db.add(
            ConversationProcessingPlan(
                id=uuid4(),
                tenant_id=recording.tenant_id,
                person_id=recording.person_id,
                recording_id=recording.id,
                processing_lease_id=link.processing_lease_id,
                generation=recording.generation,
                plan_sha256="a" * 64,
                manifest={},
                acceptance_command_id=command if state == "active" else None,
                state=state,
                progress={},
                next_check_at=setup.clock[0],
                created_at=setup.clock[0],
                expires_at=setup.clock[0] + timedelta(hours=1),
            )
        )


async def _durable_report(setup: Any, client: httpx.AsyncClient) -> UUID:
    """Upload, measure and analyse one call through the real C1-C6 workers."""
    submission = await _upload(setup, client)
    path = f"{PREFIX}/submissions/{submission}"
    await _reconcile(setup.sessions, setup.state)
    local = OfflineConversationWorker(
        setup.sessions,
        storage=setup.runtime.storage,
        scratch=setup.runtime.scratch,
        environment="test",
    )
    assert await local.run_once()
    quote = await client.post(
        path + "/plan/quote", headers={"Origin": ORIGIN, "Idempotency-Key": "golden-plan"}
    )
    assert quote.status_code == 201, quote.text
    plan = quote.json()
    broker = ReportingBroker(_wav_one_second_48k())
    router = FixedProviderRouter(
        {
            provider: ProviderRoute(provider, f"ref:credential:{provider}", broker)
            for provider in ("elevenlabs", "gemini")
        },
        authority=setup.authority,
    )
    worker = ConversationInferenceWorker(
        setup.sessions, setup.runtime.storage, router, authority=setup.authority
    )
    accepted = await client.post(
        path + "/plan",
        json={
            "plan_id": plan["id"],
            "plan_fingerprint": plan["plan_fingerprint"],
            "privacy_revision": plan["privacy_revision"],
            "accepted": True,
        },
        headers={"Origin": ORIGIN, "Idempotency-Key": "golden-accept"},
    )
    assert accepted.status_code == 202, accepted.text
    scheduler = ProcessingPlanScheduler(setup.sessions, setup.authority)
    for _ in range(8):
        await worker.run_once()
        await _make_due(setup, UUID(plan["id"]))
        await scheduler.step()
    assert broker.routes == ["elevenlabs", "gemini", "gemini"]
    report = await client.get(path + "/report")
    assert report.status_code == 200, report.text
    return submission


async def _enrich(setup: Any, client: httpx.AsyncClient, submission: UUID) -> None:
    """Owner name, confirmed speakers, a recorded outcome and an AI pointer review."""
    path = f"{PREFIX}/submissions/{submission}"
    renamed = await client.patch(
        path + "/label",
        json={"display_name": "Golden discovery call"},
        headers={"Origin": ORIGIN, "If-Match": '"call-label-0"'},
    )
    assert renamed.status_code == 200, renamed.text
    current = (await client.get(path + "/speaker-map")).json()
    speakers = [
        {
            "speaker_id": row["speaker_id"],
            "role": "other"
            if row["speaker_id"] == "unattributed"
            else ("you" if index == 0 else "prospect"),
        }
        for index, row in enumerate(current["speakers"])
    ]
    confirmed = await client.put(
        path + "/speaker-map",
        json={"transcript_revision": current["transcript_revision"], "speakers": speakers},
        headers={"Origin": ORIGIN, "If-Match": '"call-label-0"'},
    )
    assert confirmed.status_code == 200, confirmed.text
    async with setup.sessions() as db, db.begin():
        await CallOutcomeStore(ProspectStore(GuestOwnership(setup.factory(db)))).save(
            setup.state.actor,
            submission,
            HumanOutcomeCommand(
                value=HumanOutcome("won", deal_value=DealValue("125000", "INR")),
                expected_revision=0,
                expected_membership_id=None,
                expected_prospect_stage_revision=None,
            ),
        )
    envelope = (await client.get(path + "/report")).json()
    transcript = (await client.get(path + "/transcript")).json()
    payload = parse_review(answer(), transcript["segments"])
    async with setup.sessions() as db, db.begin():
        draft = await db.scalar(
            select(ConversationReportDraft).where(
                ConversationReportDraft.run_id == UUID(envelope["run_id"])
            )
        )
        assert draft is not None
        db.add(
            ConversationPointerReview(
                id=uuid4(),
                tenant_id=draft.tenant_id,
                recording_id=draft.recording_id,
                run_id=draft.run_id,
                report_draft_id=draft.id,
                source_sha256=envelope["source_sha256"],
                transcript_revision=envelope["transcript_revision"],
                version="pointer-review/1",
                model_id="fictional-offline",
                prompt_sha256="a" * 64,
                payload=payload,
                payload_sha256=payload_sha256(payload),
                created_by="fictional-golden",
                created_at=setup.clock[0],
            )
        )


class _Reader:
    """Record status, JSON, SQL statement count and wall time for each read."""

    def __init__(self, setup: Any, repeat: int) -> None:
        self.setup, self.repeat = setup, repeat
        self.responses: dict[str, dict[str, Any]] = {}
        self.statements: dict[str, int] = {}
        self.seconds: dict[str, list[float]] = {}

    async def __call__(self, name: str, client: httpx.AsyncClient, path: str) -> Any:
        assert name not in self.responses, name
        captured: list[str] = []

        def capture(_conn: Any, _cursor: Any, statement: str, *_: Any) -> None:
            captured.append(statement)

        engine = self.setup.engine.sync_engine
        timings = []
        response = None
        for attempt in range(self.repeat):
            if attempt == 0:
                event.listen(engine, "before_cursor_execute", capture)
            started = time.perf_counter()
            try:
                current = await client.get(path)
            finally:
                timings.append(time.perf_counter() - started)
                if attempt == 0:
                    event.remove(engine, "before_cursor_execute", capture)
            if response is None:
                response = current
            else:
                assert current.status_code == response.status_code, name
        assert response is not None
        self.statements[name] = len(captured)
        self.seconds[name] = timings
        self.responses[name] = {"status": response.status_code, "body": response.json()}
        return response.json()


def test_sales_xray_reads_match_golden_json_within_statement_budgets(
    postgres_harness: Any, tmp_path: Path
) -> None:
    repeat = max(1, int(os.getenv("AC_READ_PROBE_REPEAT", "1")))

    async def exercise() -> tuple[dict[str, Any], _Reader]:
        setup = await _setup(postgres_harness, tmp_path, gemini=True)
        install(setup, organisation=True)
        reader = _Reader(setup, repeat)
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as owner:
                _sign_in(setup, owner)
                analysed = await _durable_report(setup, owner)
                local_only = await _upload(setup, owner)
                local = OfflineConversationWorker(
                    setup.sessions,
                    storage=setup.runtime.storage,
                    scratch=setup.runtime.scratch,
                    environment="test",
                )
                while await local.run_once():
                    pass
                queued = await _upload(setup, owner)
                legacy = await _call(setup)
                _, legacy_revision = await draft_for(
                    setup, legacy, line="Golden legacy line: the buyer asks about price."
                )
                held = await _call(setup)
                await _pause_analysis(setup, str(held))
                active = await _call(setup)
                await _plan(setup, active, "active")
                quoted = await _call(setup)
                await _plan(setup, quoted, "quoted")
                _tick(setup)
                claimed = (await _seed_retained_guest_submission(setup))["submission_id"]
                async with setup.sessions() as db, db.begin():
                    await setup.factory(db).claim(setup.guest.token, setup.state.actor)
                _tick(setup)
                stranger_setup = SimpleNamespace(**vars(setup))
                stranger_setup.guest = setup.stranger
                unclaimed = (await _seed_retained_guest_submission(stranger_setup))["submission_id"]
                # The person (already the workspace owner) runs an organisation
                # with one member rep, so organisation reads are exercised too.
                async with setup.sessions() as db, db.begin():
                    db.add(
                        Organisation(
                            tenant_id=setup.state.tenant_id,
                            created_by_person_id=setup.state.person_id,
                            creation_command_id=uuid4(),
                            domain_verification_token=uuid4().hex + uuid4().hex,
                        )
                    )
                rep = await seed(setup.engine, tenant_id=setup.state.tenant_id, role="member")
                rep_token = await _session(setup, rep)
                # A distinct name, so an owner_name mix-up cannot pass unnoticed.
                async with setup.sessions() as db, db.begin():
                    await db.execute(
                        update(Person)
                        .where(Person.id == rep.person_id)
                        .values(display_name="Golden Member Rep")
                    )
                _tick(setup)
                rep_call = await direct_call(setup, rep.actor)
                await draft_for(setup, rep_call, line="Golden rep line: the buyer asks about ROI.")
                fillers = [await _call(setup) for _ in range(12)]
                await _enrich(setup, owner, analysed)
                legacy_recording = await _recording_for(setup, legacy)
                async with setup.sessions() as db, db.begin():
                    await SensitiveSegmentsStore(db).mark(
                        setup.state.actor,
                        recording_id=legacy_recording.id,
                        transcript_revision=legacy_revision,
                        segments=[("s1", "SENSITIVE_FINANCIAL")],
                        reason_ref="AUT-golden-reads",
                        idempotency_key="golden-legacy-mark",
                    )

                calls = {
                    "analysed": analysed,
                    "local_only": local_only,
                    "queued": queued,
                    "legacy": legacy,
                    "held": held,
                    "active": active,
                    "quoted": quoted,
                    "claimed": claimed,
                    "rep": rep_call,
                }
                base = PREFIX + "/submissions"
                page = await reader("list.owners.page1", owner, base + "?include_owners=true")
                assert len(page["submissions"]) == 20 and page["next_cursor"] is not None
                await reader(
                    "list.owners.page2",
                    owner,
                    base + f"?include_owners=true&before={page['next_cursor']}",
                )
                await reader("list.newest.page1", owner, base)
                await reader("list.reports_first.page1", owner, base + "?order=reports_first")
                await reader("list.summary", owner, base + "/summary")
                for name, submission in calls.items():
                    await reader(f"progress.{name}", owner, f"{base}/{submission}")
                for name in ("analysed", "legacy", "rep", "local_only"):
                    await reader(f"report.{name}", owner, f"{base}/{calls[name]}/report")
                for name in ("analysed", "legacy", "local_only"):
                    await reader(f"transcript.{name}", owner, f"{base}/{calls[name]}/transcript")
                for name in ("analysed", "legacy"):
                    await reader(f"speaker_map.{name}", owner, f"{base}/{calls[name]}/speaker-map")
                await reader("coaching.home", owner, COACHING)
                await reader("coaching.team", owner, COACHING + "/team")

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as member:
                member.cookies.set(setup.settings.session_cookie_name, rep_token)
                await reader("rep.list.page1", member, base)
                await reader("rep.progress.rep", member, f"{base}/{rep_call}")
                await reader("rep.report.rep", member, f"{base}/{rep_call}/report")
                await reader("rep.report.analysed", member, f"{base}/{analysed}/report")

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as guest:
                guest.cookies.set("ac_xray_guest", setup.stranger.token)
                await reader("guest.progress.unclaimed", guest, f"{base}/{unclaimed}")
                await reader("guest.report.unclaimed", guest, f"{base}/{unclaimed}/report")
                await reader("guest.transcript.unclaimed", guest, f"{base}/{unclaimed}/transcript")
                await reader("guest.report.analysed", guest, f"{base}/{analysed}/report")

            named = {
                str(setup.state.tenant_id): "<tenant>",
                str(setup.state.person_id): "<owner>",
                str(setup.state.session_id): "<owner-session>",
                str(rep.person_id): "<rep>",
                str(rep.session_id): "<rep-session>",
                str(unclaimed): "<submission:unclaimed>",
                **{str(value): f"<submission:{key}>" for key, value in calls.items()},
                **{str(value): f"<submission:filler-{n}>" for n, value in enumerate(fillers)},
            }
            normalise = _Normaliser(named, _display_dates(setup.state.now, setup.clock[0]))
            return (
                {name: normalise(reader.responses[name]) for name in reader.responses},
                reader,
            )
        finally:
            await setup.engine.dispose()

    actual, reader = run(exercise())
    output = os.getenv("AC_READ_PROBE_OUT")
    if output:
        Path(output).write_text(
            json.dumps(
                {
                    name: {
                        "status": reader.responses[name]["status"],
                        "statements": reader.statements[name],
                        "seconds_median": round(statistics.median(timings), 5),
                        "seconds_min": round(min(timings), 5),
                        "bytes": len(json.dumps(reader.responses[name]["body"])),
                    }
                    for name, timings in reader.seconds.items()
                },
                indent=1,
            )
            + "\n"
        )
    if os.getenv("AC_UPDATE_FIXTURES") == "1":
        GOLDEN.write_text(json.dumps(actual, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
    expected = json.loads(GOLDEN.read_text())
    assert sorted(actual) == sorted(expected)
    for name in expected:
        assert actual[name] == expected[name], f"{name} differs from the golden read"
    over = {
        name: (count, BUDGETS.get(name))
        for name, count in reader.statements.items()
        if count > BUDGETS.get(name, -1)
    }
    assert not over, f"reads above their statement budget: {over}"


def test_normaliser_keeps_identity_equalities_and_key_order_independence() -> None:
    first, second = str(uuid4()), str(uuid4())
    stamp = datetime(2026, 10, 17, 1, 2, 3, 456789, tzinfo=UTC).isoformat()
    normalise = _Normaliser(
        {first: "<known>"},
        _display_dates(
            datetime(2026, 10, 17, 23, tzinfo=UTC), datetime(2026, 10, 18, 1, tzinfo=UTC)
        ),
    )
    value = normalise(
        {
            "b": [second, first, f"x:{second}"],
            "a": {"at": stamp, "again": stamp, "n": 1},
            "c": [
                {"call_label": "Sales call · 17 Oct 2026"},
                {"call_label": "Sales call · 18 Oct 2026"},
                {"call_label": "Sales call · 16 Oct 2026"},
                {"summary": "Follow up on 17 Oct 2026"},
            ],
        }
    )
    assert value == {
        "a": {"again": "<time-1>", "at": "<time-1>", "n": 1},
        "b": ["<uuid-1>", "<known>", "x:<uuid-1>"],
        # Only the run's own days, and only in call_label, become <date>.
        "c": [
            {"call_label": "Sales call · <date>"},
            {"call_label": "Sales call · <date>"},
            {"call_label": "Sales call · 16 Oct 2026"},
            {"summary": "Follow up on 17 Oct 2026"},
        ],
    }
