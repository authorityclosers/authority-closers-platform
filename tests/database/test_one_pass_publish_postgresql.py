"""Publishing one-pass results (analysis pipeline ``one_pass``) on PostgreSQL.

One strict read of today's saved transcript becomes the call's deep call data at once
and, when the call's report is saved, its pointer review; today's deep pipeline and
pointer review wait only while one pass works on the call, and take it when one pass
does not finish. Disposable loopback PostgreSQL with the real imported-report fixture
(synthetic audio and transcript); the model is a local fake: no network, no key.
"""

from __future__ import annotations

import hashlib
from argparse import Namespace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import insert, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

from ac_platform.ai_spend import ledger, policy
from ac_platform.ai_spend.models import AiSpendSettings
from ac_platform.call_data import engine as call_engine
from ac_platform.call_data.models import CallDataRun
from ac_platform.conversation_intelligence.models import (
    ConversationCheckpoint,
    ConversationReportDraft,
)
from ac_platform.conversation_intelligence.pointer_review_models import (
    ConversationPointerReview,
)
from ac_platform.one_pass import publish
from ac_platform.one_pass import settings as choices
from ac_platform.one_pass.gemini import OnePassFailure, Reply
from ac_platform.one_pass.models import OnePassRun
from ac_platform.one_pass.pricing import Usage
from ac_platform.one_pass.runner import run_pass
from tests.database.test_conversation_postgresql import (
    postgres_harness as _postgres_harness,
)
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_reports_postgresql import (
    ReportFixture,
    _build_fixture,
)
from tests.database.test_pointer_review_admission_postgresql import _report
from tests.unit.one_pass.test_one_pass import _answer, _review

EXTRA = [
    "Main Amit Sharma, XYZ Digital ka founder hoon.",
    "Team aath logon ki hai, revenue chaar lakh mahina.",
    "Partner se baat karke Friday chaar baje bataunga.",
    "Main Friday se pehle case study bhejta hoon.",
]


@pytest.fixture
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()  # type: ignore[attr-defined]


@pytest.fixture
def report_fixture(
    postgres_harness: Any, tmp_path_factory: pytest.TempPathFactory
) -> ReportFixture:
    return run(_build_fixture(postgres_harness, tmp_path_factory.mktemp("one-pass-publish")))


class FakeGemini:
    """The facts request's answer: today's call data and a full pointer review."""

    name = "fake"

    def __init__(self, fail: str | None = None) -> None:
        self.fail = fail
        self.requests: list[Any] = []

    def generate(self, *, model: str, request: Any, tier: str) -> Reply:
        self.requests.append((model, tier, request))
        if self.fail:
            raise OnePassFailure(self.fail, Usage(prompt=9_000, output=100))
        review = _review()
        review.pop("prospect")
        # Evidence the saved report's own transcript has (its s1): the review is parsed
        # again against it when published.
        review["prospect_profile"] = {
            "name": {"value": "Amit Sharma", "evidence": ["s1"]},
            "insights": [{"kind": "team", "text": "A team of eight.", "evidence": ["s1"]}],
        }
        data = {"call_data": _answer()["call_data"], "review": review}
        return Reply(data, Usage(prompt=12_000, output=7_000), tier, 1, 900, "STOP", "e" * 64)


def _seed(postgres_harness: Any, fixture: ReportFixture) -> dict[str, Any]:
    """The fixture's saved report, a newer C2 transcript of the same revision (the
    report's s1 and four more fictional rows) and the fast pipeline's finished run."""

    async def report() -> dict[str, Any]:
        engine = create_async_engine(postgres_harness.url)
        try:
            return await _report(async_sessionmaker(engine, expire_on_commit=False), fixture)
        finally:
            await engine.dispose()

    seeded = run(report())
    now = datetime.now(UTC)
    with postgres_harness.begin() as connection:
        draft = connection.execute(
            select(ConversationReportDraft.transcript, ConversationReportDraft.person_id).where(
                ConversationReportDraft.id == seeded["draft_id"]
            )
        ).one()
        first = draft.transcript["normalized"]["segments"][0]
        segments = [first] + [
            {
                "id": f"s{index}",
                "speaker_id": "speaker_1" if index % 2 else "speaker_0",
                "start_ms": index * 5_000,
                "end_ms": index * 5_000 + 4_000,
                "text": line,
            }
            for index, line in enumerate(EXTRA, 2)
        ]
        checkpoint = uuid4()
        connection.execute(
            insert(ConversationCheckpoint).values(
                id=checkpoint,
                tenant_id=seeded["tenant_id"],
                person_id=draft.person_id,
                recording_id=seeded["recording_id"],
                cache_key=hashlib.sha256(b"one-pass" + checkpoint.bytes).hexdigest(),
                manifest_sha256="a" * 64,
                payload_sha256="b" * 64,
                stage="C2",
                manifest={"stage": "C2"},
                payload={
                    "segments": segments,
                    "revision": seeded["transcript_revision"],
                    "source_sha256": seeded["source_sha256"],
                    "duration_ms": 30_000,
                },
                created_at=now,
            )
        )
        call = call_engine.Call(
            tenant_id=seeded["tenant_id"],
            recording_id=seeded["recording_id"],
            principal_id=draft.person_id,
            checkpoint_id=checkpoint,
            transcript_revision=seeded["transcript_revision"],
            source_sha256=seeded["source_sha256"],
            duration_ms=30_000,
            created_at=now,
        )
        call_engine.skip_run(
            connection,
            call,
            reason="test",
            pipeline="fast",
            trigger="auto",
            created_by="test",
            now=now,
        )
    return seeded


def _settings(sessions: Any, *, mode: str = "one_pass", cap: int = 200) -> None:
    now = datetime.now(UTC)
    with sessions() as session, session.begin():
        connection = session.connection()
        choices.save(
            connection,
            "development",
            {"mode": mode},
            person_id=None,
            reason="Owner: So at least get this on prod now",
            now=now,
        )
        config = policy.with_cap(policy.defaults("development"), "one_pass", cap)
        config["background_enabled"] = True
        revision = connection.scalar(
            text("SELECT coalesce(max(revision), 0) FROM ai_spend_settings")
        )
        connection.execute(
            insert(AiSpendSettings).values(
                id=uuid4(),
                revision=int(revision) + 1,
                config=policy.validate("development", config),
                reason="test",
                created_by_person_id=None,
                created_at=now,
            )
        )


def _sessions(postgres_harness: Any) -> tuple[Any, Any]:
    return postgres_harness, sessionmaker(postgres_harness, expire_on_commit=False)


def _pass(sessions: Any, transport: Any) -> list[dict[str, Any]]:
    arguments = Namespace(
        recording=None,
        recent_hours=2,
        limit=5,
        not_before=datetime.now(UTC) - timedelta(hours=1),
        force=False,
        apply=True,
    )
    return run_pass(
        sessions,
        arguments,
        transport,
        created_by=publish.AUTOMATIC,
        environment="development",
    )


def test_one_read_becomes_the_deep_call_data_and_the_pointer_review(
    postgres_harness: Any, report_fixture: ReportFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(call_engine, "test_source_shas", lambda _connection: set())
    seeded = _seed(postgres_harness, report_fixture)
    sync, sessions = _sessions(postgres_harness)
    _settings(sessions)
    model = FakeGemini()
    lines = _pass(sessions, model)
    read = next(line for line in lines if line.get("pipeline") == "one_pass")
    assert read["outcome"] == "succeeded", lines
    published = {
        "recording": str(seeded["recording_id"]),
        "review": "one_pass",
        "outcome": "published",
    }
    assert published in lines
    # One strict request, the standard tier, never a schema sent as text.
    [(model_id, tier, request)] = model.requests
    assert model_id == choices.ANALYSIS_MODEL and tier == "standard"
    assert not request.schema_fallback and request.schema["required"] == [
        "call_data",
        "review",
    ]
    with sync.connect() as connection:
        runs = connection.execute(
            select(OnePassRun.__table__)
            .where(OnePassRun.recording_id == seeded["recording_id"])
            .order_by(OnePassRun.created_at)
        ).all()
        assert [r.state for r in runs] == ["running", "succeeded"]
        done = runs[1]
        assert done.mode == "one_pass" and done.transcription_model is None
        assert done.transcription_cost_inr is None and done.analysis_cost_inr > 0
        assert done.checks["deep_run"] == "saved"
        assert done.checks["pointer_review"] == "ok"
        # The deep call data run: today's store, no tokens or rupees of its own.
        deep = connection.execute(
            select(CallDataRun.__table__).where(
                CallDataRun.recording_id == seeded["recording_id"],
                CallDataRun.pipeline == "deep",
                CallDataRun.state == "succeeded",
            )
        ).one()
        assert deep.created_by == publish.AUTOMATIC and deep.cost_inr == 0
        assert deep.input_tokens is None and deep.counts["one_pass_run"] == str(runs[0].id)
        objects = connection.execute(
            text("SELECT type_key FROM call_objects WHERE recording_id = :r AND pipeline = 'deep'"),
            {"r": seeded["recording_id"]},
        ).scalars()
        assert {"person.name", "company.name"} <= set(objects)
        # The pointer review, saved against the report through its own admission.
        review = connection.execute(
            select(ConversationPointerReview.__table__).where(
                ConversationPointerReview.recording_id == seeded["recording_id"]
            )
        ).one()
        assert review.created_by == publish.AUTOMATIC
        assert review.report_draft_id == seeded["draft_id"]
        assert review.input_tokens is None and len(review.payload["pointers"]) == 27
        profile = review.payload["prospect_profile"]
        # Parsed again against the report's own transcript: a name only when said there.
        assert profile["name"]["value"] is None
        assert profile["insights"][0]["text"] == "A team of eight."
        # Spend: counted once, as one pass.
        rows = ledger.read(connection, datetime.now(UTC) - timedelta(hours=1))
        spent = {r.feature: r.inr for r in rows}
        assert spent["one_pass"] == done.analysis_cost_inr
        assert not spent.get("call_data_deep") and not spent.get("pointer_review")
        # Today's deep pipeline has nothing left to do.
        assert not publish.Handoff().waits(
            connection,
            seeded["recording_id"],
            seeded["transcript_revision"],
            kind="deep",
            now=datetime.now(UTC),
        )
    # Read once, published once.
    assert _pass(sessions, model) == []
    assert len(model.requests) == 1


def test_todays_pipeline_waits_only_while_one_pass_works_and_takes_a_failure(
    postgres_harness: Any, report_fixture: ReportFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(call_engine, "test_source_shas", lambda _connection: set())
    seeded = _seed(postgres_harness, report_fixture)
    sync, sessions = _sessions(postgres_harness)
    recording, revision = seeded["recording_id"], seeded["transcript_revision"]
    with sync.connect() as connection:
        # Classic: no handoff at all.
        assert publish.handoff(connection, "development") is None
    _settings(sessions)
    now = datetime.now(UTC)
    with sync.connect() as connection:
        handoff = publish.handoff(connection, "development")
        assert handoff is not None
        # Not started yet, transcript fresh: both wait (at most 15 minutes).
        for kind in ("deep", "review"):
            assert handoff.waits(connection, recording, revision, kind=kind, now=now)
        later = now + publish.HANDOFF_START + timedelta(seconds=1)
        assert not handoff.waits(connection, recording, revision, kind="deep", now=later)
    lines = _pass(sessions, FakeGemini(fail="provider_http_503"))
    assert lines[0]["outcome"] == "failed:provider_http_503"
    with sync.connect() as connection:
        failed = connection.execute(
            select(OnePassRun.__table__).where(
                OnePassRun.recording_id == recording, OnePassRun.state == "failed"
            )
        ).one()
        # The billed failure is counted; nothing was saved for people.
        assert failed.analysis_cost_inr > 0 and failed.outputs is None
        for kind in ("deep", "review"):
            assert not handoff.waits(
                connection, recording, revision, kind=kind, now=datetime.now(UTC)
            )
        assert (
            connection.scalar(
                select(text("count(*)"))
                .select_from(CallDataRun)
                .where(CallDataRun.recording_id == recording, CallDataRun.pipeline == "deep")
            )
            == 0
        )
    # One attempt here: today's deep pipeline and pointer review take the call.
    assert _pass(sessions, FakeGemini()) == []
