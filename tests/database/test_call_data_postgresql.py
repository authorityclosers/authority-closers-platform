"""Call data engine on PostgreSQL: the fast pipeline admits, extracts, fills and asks.

Disposable loopback PostgreSQL, fictional rows only. The text model is a local
fake: no network, no key.
"""

from __future__ import annotations

import hashlib
import importlib.util
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Engine, func, insert, inspect, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from ac_platform.call_data import engine as call_engine
from ac_platform.call_data.models import (
    CallDataRun,
    CallObject,
    CallObjectDecision,
)
from ac_platform.call_data.provider import Answer, ProviderFailure
from ac_platform.call_data.runner import process_call
from ac_platform.conversation_intelligence.models import (
    ConversationCheckpoint,
    ConversationRecording,
)
from ac_platform.db.models import model_metadata
from ac_platform.lead_desk.models import Lead, LeadEvent
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import application, run, seed

ROOT = Path(__file__).resolve().parents[2]
TABLES = {"call_data_settings", "call_data_runs", "call_objects", "call_object_decisions"}
SEGMENTS = [
    {
        "id": "s1",
        "speaker_id": "speaker_0",
        "start_ms": 100,
        "end_ms": 4000,
        "text": "Namaste, main Rohan, Sales Xray se baat kar raha hoon.",
    },
    {
        "id": "s2",
        "speaker_id": "speaker_1",
        "start_ms": 4100,
        "end_ms": 9000,
        "text": "Haan ji, main Amit Sharma, XYZ Digital ka founder.",
    },
    {
        "id": "s3",
        "speaker_id": "speaker_1",
        "start_ms": 9100,
        "end_ms": 15000,
        "text": "Hamari team aath logon ki hai, sales sab mere upar hai.",
    },
    {
        "id": "s4",
        "speaker_id": "speaker_1",
        "start_ms": 15100,
        "end_ms": 20000,
        "text": "Partner se baat karke Friday chaar baje bataunga.",
    },
    {
        "id": "s5",
        "speaker_id": "speaker_0",
        "start_ms": 20100,
        "end_ms": 24000,
        "text": "Main aapko Friday se pehle case study bhejta hoon.",
    },
]
ANSWER = {
    "speakers": [
        {"speaker_id": "speaker_0", "role": "salesperson"},
        {"speaker_id": "speaker_1", "role": "prospect"},
    ],
    "facts": [
        {
            "type": "person.name",
            "value": {"text": "Amit Sharma"},
            "confidence": 0.97,
            "basis": "observed",
            "segments": ["s2"],
        },
        {
            "type": "company.name",
            "value": {"text": "XYZ Digital"},
            "confidence": 0.95,
            "basis": "observed",
            "segments": ["s2"],
        },
        {
            "type": "need.primary_pain",
            "value": {"text": "All sales depend on Amit"},
            "confidence": 0.8,
            "basis": "observed",
            "segments": ["s3"],
        },
        {
            "type": "commitment.follow_up",
            "value": {
                "text": "Friday 4 PM",
                "date": "2026-10-23",
                "time": "16:00",
                "purpose": "Decision after partner talk",
            },
            "confidence": 0.9,
            "basis": "observed",
            "segments": ["s4"],
        },
        {
            "type": "commitment.seller_promise",
            "value": {"text": "Send a case study", "due": {"text": "before Friday"}},
            "confidence": 0.9,
            "basis": "observed",
            "segments": ["s5"],
        },
    ],
}


@pytest.fixture
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


class FakeModel:
    def __init__(self, answer: Any = ANSWER, failure: str | None = None) -> None:
        self.answer, self.failure, self.calls = answer, failure, 0

    def generate_json(self, **_: Any) -> Answer:
        self.calls += 1
        if self.failure:
            raise ProviderFailure(self.failure, {"promptTokenCount": 100})
        return Answer(self.answer, {"promptTokenCount": 7000, "candidatesTokenCount": 1500})


def _call(postgres_harness: Engine, *, lead_name: str | None = "Unnamed lead") -> dict[str, Any]:
    """A ready, permitted fictional call with a C2 transcript and (optionally) a lead."""

    async def seed_call() -> dict[str, Any]:
        engine = create_async_engine(postgres_harness.url)
        try:
            owner = await seed(engine)
            async with AsyncSession(engine) as database, database.begin():
                record = await application(database, owner).register(
                    owner.actor, owner.recording_intent, key=f"call-data-{uuid4().hex}"
                )
            return {"owner": owner, "recording_id": UUID(record["id"])}
        finally:
            await engine.dispose()

    seeded = run(seed_call())
    owner, recording_id = seeded["owner"], seeded["recording_id"]
    submission_id, lead_id = uuid4(), uuid4()
    payload = {
        "segments": SEGMENTS,
        "revision": "f" * 64,
        "source_sha256": owner.source_sha256,
        "duration_ms": 24000,
    }
    now = datetime.now(UTC)
    with postgres_harness.begin() as connection:
        connection.execute(
            update(ConversationRecording)
            .where(ConversationRecording.id == recording_id)
            .values(state="ready")
        )
        connection.execute(
            insert(ConversationCheckpoint).values(
                id=uuid4(),
                tenant_id=owner.tenant_id,
                person_id=owner.person_id,
                recording_id=recording_id,
                cache_key=hashlib.sha256(b"c2" + recording_id.bytes).hexdigest(),
                manifest_sha256="a" * 64,
                payload_sha256="b" * 64,
                stage="C2",
                manifest={"stage": "C2"},
                payload=payload,
                created_at=now,
            )
        )
        if lead_name is not None:
            connection.execute(
                insert(Lead).values(
                    id=lead_id,
                    tenant_id=owner.tenant_id,
                    revision=1,
                    source="manual",
                    payload={},
                    name=lead_name,
                    stage="new",
                    attempts=0,
                    calls=1,
                    repeats=0,
                    test_data=True,
                    created_at=now,
                    updated_at=now,
                )
            )
            connection.execute(
                insert(LeadEvent).values(
                    id=uuid4(),
                    tenant_id=owner.tenant_id,
                    lead_id=lead_id,
                    kind="call",
                    data={"submission_id": str(submission_id), "recording": True},
                    created_at=now,
                )
            )
    return {
        "owner": owner,
        "recording_id": recording_id,
        "submission_id": submission_id,
        "lead_id": lead_id,
    }


def _process(postgres_harness: Engine, seeded: dict[str, Any], model: Any) -> dict[str, Any]:
    sessions = sessionmaker(postgres_harness, expire_on_commit=False)
    with sessions() as session:
        calls = call_engine.candidates(
            session.connection(),
            not_before=datetime.now(UTC) - timedelta(hours=1),
            hours=48,
            limit=5,
            recording_id=seeded["recording_id"],
        )
    if not calls:
        return {"no_candidate": True}
    call = calls[0]
    # The test seeds no guest submission row; the lead link comes from the submission id.
    call.submission_id = seeded["submission_id"]
    with postgres_harness.connect() as connection:
        settings, _ = call_engine.read_settings(connection)
    return process_call(
        sessions,
        call,
        settings=settings,
        apply=True,
        trigger="operator",
        created_by="test:call-data",
        model_client=model,
        test_sources=set(),
    )


def test_fast_pipeline_saves_objects_fills_the_lead_and_asks_the_rest(
    postgres_harness: Engine,
) -> None:
    seeded = _call(postgres_harness)
    model = FakeModel()
    line = _process(postgres_harness, seeded, model)
    assert line["outcome"] == "succeeded", line
    assert line["objects"] == 5 and line["lead_written"] == 2 and model.calls == 1
    with postgres_harness.connect() as connection:
        runs = connection.execute(
            select(CallDataRun.state, CallDataRun.cost_inr, CallDataRun.counts)
            .where(CallDataRun.recording_id == seeded["recording_id"])
            .order_by(CallDataRun.created_at)
        ).all()
        assert [r.state for r in runs] == ["running", "succeeded"]
        assert runs[1].cost_inr is not None and runs[1].cost_inr > 0
        assert runs[1].counts["roles"] == {"speaker_0": "salesperson", "speaker_1": "prospect"}
        lead = connection.execute(select(Lead).where(Lead.id == seeded["lead_id"])).one()
        assert (lead.name, lead.company, lead.revision) == ("Amit Sharma", "XYZ Digital", 3)
        edits = (
            connection.execute(
                select(LeadEvent.data).where(
                    LeadEvent.lead_id == seeded["lead_id"], LeadEvent.kind == "edited"
                )
            )
            .scalars()
            .all()
        )
        assert sorted(e["changed"][0] for e in edits) == ["company", "name"]
        assert all(e["via"] == "call_data" for e in edits)
        decisions = dict(
            connection.execute(
                select(CallObject.type_key, CallObjectDecision.decision)
                .join(CallObject, CallObject.id == CallObjectDecision.object_id)
                .where(CallObjectDecision.recording_id == seeded["recording_id"])
            ).all()
        )
        assert decisions == {
            "person.name": "auto_filled",
            "company.name": "auto_filled",
            "need.primary_pain": "asked",
            "commitment.follow_up": "asked",
            "commitment.seller_promise": "asked",
        }
        evidence = connection.scalar(
            select(CallObject.evidence).where(
                CallObject.recording_id == seeded["recording_id"],
                CallObject.type_key == "person.name",
            )
        )
        assert evidence[0]["quote"] == SEGMENTS[1]["text"]
    # The same transcript is never processed twice.
    assert _process(postgres_harness, seeded, model) == {"no_candidate": True}


def test_a_persons_lead_value_is_asked_never_overwritten(postgres_harness: Engine) -> None:
    seeded = _call(postgres_harness, lead_name="Amit S.")
    line = _process(postgres_harness, seeded, FakeModel())
    assert line["outcome"] == "succeeded" and line["lead_written"] == 1  # company only
    with postgres_harness.connect() as connection:
        assert connection.scalar(select(Lead.name).where(Lead.id == seeded["lead_id"])) == "Amit S."
        question = connection.scalar(
            select(CallObjectDecision.question)
            .join(CallObject, CallObject.id == CallObjectDecision.object_id)
            .where(
                CallObjectDecision.recording_id == seeded["recording_id"],
                CallObject.type_key == "person.name",
            )
        )
        assert question == "replace"


def test_failures_count_as_attempts_and_stop_after_two(postgres_harness: Engine) -> None:
    seeded = _call(postgres_harness, lead_name=None)
    model = FakeModel(failure="provider_http_503")
    first = _process(postgres_harness, seeded, model)
    assert first["outcome"] == "failed:provider_http_503"
    # Within the in-flight window a crashed attempt is not retried; a finished
    # failure is, once more, then the transcript is given up.
    second = _process(postgres_harness, seeded, model)
    assert second["outcome"] == "failed:provider_http_503"
    third = _process(postgres_harness, seeded, model)
    assert third.get("skipped") == "attempts_exhausted" and model.calls == 2
    assert _process(postgres_harness, seeded, model) == {"no_candidate": True}
    with postgres_harness.connect() as connection:
        assert (
            connection.scalar(
                select(func.count())
                .select_from(CallObject)
                .where(CallObject.recording_id == seeded["recording_id"])
            )
            == 0
        )


def test_revoked_permission_is_refused_before_any_provider_call(postgres_harness: Engine) -> None:
    from ac_platform.conversation_intelligence.models import ConversationPermission

    seeded = _call(postgres_harness, lead_name=None)
    with postgres_harness.begin() as connection:
        connection.execute(
            update(ConversationPermission)
            .where(ConversationPermission.id == seeded["owner"].permission_id)
            .values(revoked_at=datetime.now(UTC))
        )
    model = FakeModel()
    assert _process(postgres_harness, seeded, model)["skipped"] == "permission_inactive"
    assert model.calls == 0


def test_erasure_empties_objects_and_decisions(postgres_harness: Engine) -> None:
    seeded = _call(postgres_harness)
    assert _process(postgres_harness, seeded, FakeModel())["outcome"] == "succeeded"
    with postgres_harness.begin() as connection:
        erased = call_engine.erase_for_recording(
            connection, seeded["recording_id"], datetime.now(UTC)
        )
        assert erased == 5
    with postgres_harness.connect() as connection:
        left = connection.execute(
            select(CallObject.value, CallObject.display, CallObject.evidence).where(
                CallObject.recording_id == seeded["recording_id"]
            )
        ).all()
        assert left and all(row == (None, None, None) for row in left)
        assert (
            connection.scalar(
                select(func.count())
                .select_from(CallObjectDecision)
                .where(
                    CallObjectDecision.recording_id == seeded["recording_id"],
                    CallObjectDecision.erased_at.is_(None),
                )
            )
            == 0
        )


def test_settings_switch_the_pipeline_off_and_keep_revisions(postgres_harness: Engine) -> None:
    with postgres_harness.begin() as connection:
        assert (
            call_engine.save_settings(
                connection, {"fast": {"enabled": False}}, person_id=None, now=datetime.now(UTC)
            )
            == 1
        )
        assert (
            call_engine.save_settings(
                connection, {"fast": {"daily_cap_inr": 20}}, person_id=None, now=datetime.now(UTC)
            )
            == 2
        )
    with postgres_harness.connect() as connection:
        config, revision = call_engine.read_settings(connection)
        assert revision == 2 and config["fast"]["enabled"] is True
        assert config["fast"]["daily_cap_inr"] == 20


def migration() -> Any:
    path = ROOT / "db/migrations/versions/20261019_0097_call_data.py"
    spec = importlib.util.spec_from_file_location("call_data_migration_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_is_additive_and_passes_the_schema_gate_rules() -> None:
    from scripts.ci.migration_schema_gate import check_operations
    from scripts.ops.migration_safety import classify_source

    module = migration()
    assert (module.revision, module.down_revision) == ("20261019_0097", "20261018_0096")
    path = Path(module.__file__)
    item = classify_source(path.read_text(), str(path))
    check_operations([item], set())
    assert item.verdict == "additive"


def test_empty_migration_downgrades_reupgrades_and_matches_the_models(
    postgres_harness: Engine,
) -> None:
    module = migration()
    with postgres_harness.begin() as connection:
        assert set(inspect(connection).get_table_names()) >= TABLES
        context = MigrationContext.configure(connection, opts={"target_metadata": model_metadata()})
        with Operations.context(context):
            module.downgrade()
            assert not TABLES & set(inspect(connection).get_table_names())
            module.upgrade()
        assert compare_metadata(MigrationContext.configure(connection), model_metadata()) == []


def test_constraints_hold_and_history_requires_forward_recovery(postgres_harness: Engine) -> None:
    seeded = _call(postgres_harness, lead_name=None)
    assert _process(postgres_harness, seeded, FakeModel())["outcome"] == "succeeded"
    with postgres_harness.connect() as connection:
        first = connection.execute(
            select(CallObject).where(CallObject.recording_id == seeded["recording_id"])
        ).first()
    assert first is not None
    base = {c.name: getattr(first, c.name) for c in CallObject.__table__.columns}
    for changes in (
        {"confidence": 1.5},
        {"basis": "guess"},
        {"pipeline": "person"},  # a person's object has no run
        {"value": None},  # content without erasure
        {"supersedes_id": first.supersedes_id or first.id},
    ):
        values = {**base, "id": uuid4(), **changes}
        if "supersedes_id" in changes:
            # Two successors of one object are refused.
            with postgres_harness.begin() as connection:
                connection.execute(insert(CallObject).values({**values, "id": uuid4()}))
        with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
            connection.execute(insert(CallObject).values(values))
    module = migration()
    with (
        postgres_harness.begin() as connection,
        Operations.context(MigrationContext.configure(connection)),
        pytest.raises(RuntimeError, match="forward recovery"),
    ):
        module.downgrade()
    with postgres_harness.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM call_objects")) >= 5


def test_lead_facts_questions_and_a_persons_answers(postgres_harness: Engine) -> None:
    from ac_platform.call_data import facts

    seeded = _call(postgres_harness)
    assert _process(postgres_harness, seeded, FakeModel())["outcome"] == "succeeded"
    tenant, lead = seeded["owner"].tenant_id, seeded["lead_id"]
    columns = {"name": "Amit Sharma", "company": "XYZ Digital", "city": None, "interest": None}
    with postgres_harness.connect() as connection:
        view = facts.lead_facts(connection, tenant, lead, columns)
    assert view["schema"] == "call-data-lead/1"
    assert view["pipelines"]["fast"]["state"] == "done"
    assert view["pipelines"]["deep"]["state"] == "not_started"
    assert [q["type"] for q in view["questions"]] == [
        "commitment.follow_up",
        "commitment.seller_promise",
        "need.primary_pain",
    ]
    assert {f["field"] for f in view["filled"]} == {"name", "company"}
    follow = view["questions"][0]
    assert follow["evidence"][0]["role"] == "prospect"
    assert follow["display"] == "Friday 4 PM · Decision after partner talk"
    by_type = {q["type"]: q["object_id"] for q in view["questions"]}
    now = datetime.now(UTC)
    answers = [
        ("commitment.follow_up", "accepted", None),
        ("need.primary_pain", "edited", {"text": "Every sale needs Amit"}),
        ("commitment.seller_promise", "rejected", None),
    ]
    for type_key, decision, value in answers:
        with postgres_harness.begin() as connection:
            decided = facts.plan_decision(
                connection,
                tenant_id=tenant,
                object_id=UUID(by_type[type_key]),
                person_id=seeded["owner"].person_id,
                decision=decision,
                value=value,
                command_id=uuid4(),
                now=now,
            )
            assert decided.lead_field is None  # none of these has a lead column
            facts.save_decision(connection, decided, lead_written=False)
    # A second answer to the same fact is refused.
    with pytest.raises(facts.FactsError, match="already_answered"), postgres_harness.begin() as c:
        facts.plan_decision(
            c,
            tenant_id=tenant,
            object_id=UUID(by_type["need.primary_pain"]),
            person_id=seeded["owner"].person_id,
            decision="accepted",
            value=None,
            command_id=uuid4(),
            now=now,
        )
    # An edit is checked against its type.
    with pytest.raises(facts.FactsError), postgres_harness.begin() as c:
        facts.plan_decision(
            c,
            tenant_id=tenant,
            object_id=UUID(by_type["commitment.follow_up"]),
            person_id=seeded["owner"].person_id,
            decision="edited",
            value={"text": "Friday", "time": "16:00"},
            command_id=uuid4(),
            now=now,
        )
    with postgres_harness.connect() as connection:
        after = facts.lead_facts(connection, tenant, lead, columns)
        shown = {f["type"]: f for f in after["facts"]}
        prospect = facts.prospect_facts(
            connection,
            (CallObject.tenant_id == tenant)
            & (CallObject.submission_id == seeded["submission_id"]),
            {"kind": "call", "id": str(seeded["submission_id"])},
        )
    assert after["questions"] == []
    assert shown["commitment.follow_up"]["basis"] == "confirmed"
    assert shown["need.primary_pain"]["basis"] == "edited"
    assert shown["need.primary_pain"]["display"] == "Every sale needs Amit"
    assert "commitment.seller_promise" not in shown  # rejected facts are hidden
    assert prospect["schema"] == "prospect-facts/1"
    assert {f["type"]: f["prospect_field"] for f in prospect["facts"]}["company.name"] == "business"
    assert len(prospect["facts"]) == 4


def test_calls_wait_for_budget_and_settings_keep_their_history(postgres_harness: Engine) -> None:
    seeded = _call(postgres_harness, lead_name=None)
    now = datetime.now(UTC)
    with postgres_harness.connect() as connection:
        assert call_engine.waiting_for_budget(connection, "fast", now) == 1
        assert call_engine.waiting_for_budget(connection, "deep", now) == 0  # waits for fast
    assert _process(postgres_harness, seeded, FakeModel())["outcome"] == "succeeded"
    with postgres_harness.begin() as connection:
        assert call_engine.waiting_for_budget(connection, "fast", now) == 0
        assert call_engine.waiting_for_budget(connection, "deep", now) == 1
        call_engine.save_settings(
            connection,
            {"fast": {"daily_cap_inr": 300}},
            person_id=seeded["owner"].person_id,
            now=now,
        )
        history = call_engine.settings_history(connection)
    assert history[0]["fast"]["daily_cap_inr"] == 300
    assert history[0]["by_person_id"] == str(seeded["owner"].person_id)
