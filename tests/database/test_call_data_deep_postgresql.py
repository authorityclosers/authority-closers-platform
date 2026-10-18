"""Deep pipeline on PostgreSQL: after the fast read, a whole-call read supersedes, keeps a
person's answers, retracts weak facts, labels every segment and measures the voice.

Disposable loopback PostgreSQL, fictional rows only; a local fake model, no network.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import sessionmaker

from ac_platform.call_data import engine as call_engine
from ac_platform.call_data import facts
from ac_platform.call_data.deep_runner import process_deep_call
from ac_platform.call_data.models import CallDataRun, CallObject
from ac_platform.call_data.provider import Answer
from tests.database.conversation_harness import conversation_harness
from tests.database.test_call_data_postgresql import ANSWER, ROOT, FakeModel, _call, _process


@pytest.fixture
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


DEEP_FACTS = {
    "speakers": ANSWER["speakers"],
    "facts": [
        # Same name as the fast read: superseded (no person answered it).
        {
            "type": "person.name",
            "value": {"text": "Amit Sharma"},
            "confidence": 0.98,
            "basis": "observed",
            "segments": ["s2"],
        },
        # A better pain than the fast read's: supersedes; its question moves on.
        {
            "type": "need.primary_pain",
            "value": {"text": "Every sale needs Amit himself"},
            "confidence": 0.92,
            "basis": "observed",
            "segments": ["s3"],
        },
        # New in the deep read.
        {
            "type": "company.team_size",
            "value": {"text": "8 people", "lower": "8", "unit": "people"},
            "confidence": 0.95,
            "basis": "observed",
            "segments": ["s3"],
        },
    ],
}


class DeepModel:
    """Facts for the whole-call read, labels for each segment chunk."""

    def __init__(self) -> None:
        self.calls = 0

    def generate_json(self, **kwargs: Any) -> Answer:
        self.calls += 1
        usage = {"promptTokenCount": 3000, "candidatesTokenCount": 900}
        if "labels" in kwargs["schema"]["properties"]:
            labels = [
                {
                    "segment": f"s{n}",
                    "intent": "discovery",
                    "act": "statement",
                    "sentiment": "neutral",
                    "tone": "neutral",
                    "topics": ["team"],
                }
                for n in range(1, 6)
            ]
            return Answer({"labels": labels}, usage)
        return Answer(DEEP_FACTS, usage)


def _deep(postgres_harness: Engine, seeded: dict[str, Any], model: Any) -> dict[str, Any]:
    sessions = sessionmaker(postgres_harness, expire_on_commit=False)
    with sessions() as session, session.begin():
        call_engine.save_settings(
            session.connection(),
            {"deep": {"enabled": True}},
            person_id=None,
            now=datetime.now(UTC),
        )
    with sessions() as session:
        connection = session.connection()
        calls = call_engine.candidates(
            connection,
            not_before=datetime.now(UTC) - timedelta(hours=1),
            hours=48,
            limit=5,
            pipeline="deep",
            recording_id=seeded["recording_id"],
        )
        settings, _ = call_engine.read_settings(connection)
    if not calls:
        return {"no_candidate": True}
    calls[0].submission_id = seeded["submission_id"]
    return process_deep_call(
        sessions,
        calls[0],
        settings=settings,
        apply=True,
        trigger="operator",
        created_by="test:call-data-deep",
        model_client=model,
        test_sources=set(),
        storage_root=None,
    )


def test_deep_waits_for_fast_then_supersedes_labels_and_measures(postgres_harness: Engine) -> None:
    seeded = _call(postgres_harness, lead_name="Amit S.")
    # No fast read yet: the deep pipeline does not pick the call.
    assert _deep(postgres_harness, seeded, DeepModel()) == {"no_candidate": True}
    weak = {
        **ANSWER,
        "facts": [
            *ANSWER["facts"],
            {
                "type": "need.goal",
                "value": {"text": "Grow somehow"},
                "confidence": 0.5,
                "basis": "observed",
                "segments": ["s3"],
            },
        ],
    }
    assert _process(postgres_harness, seeded, FakeModel(weak))["outcome"] == "succeeded"
    tenant, lead = seeded["owner"].tenant_id, seeded["lead_id"]
    with postgres_harness.begin() as connection:
        # The seller already answered the follow-up: the deep read must not touch it.
        follow = connection.scalar(
            select(CallObject.id).where(
                CallObject.recording_id == seeded["recording_id"],
                CallObject.type_key == "commitment.follow_up",
            )
        )
        decided = facts.plan_decision(
            connection,
            tenant_id=tenant,
            object_id=follow,
            person_id=seeded["owner"].person_id,
            decision="accepted",
            value=None,
            command_id=uuid4(),
            now=datetime.now(UTC),
        )
        facts.save_decision(connection, decided, lead_written=False)

    model = DeepModel()
    line = _deep(postgres_harness, seeded, model)
    assert line["outcome"] == "succeeded", line
    assert model.calls == 2  # one whole-call read, one label chunk
    assert line["superseded"] == 2 and line["retracted"] == 1
    with postgres_harness.connect() as connection:
        run = connection.execute(
            select(CallDataRun.counts, CallDataRun.pipeline_version, CallDataRun.cost_inr).where(
                CallDataRun.recording_id == seeded["recording_id"],
                CallDataRun.pipeline == "deep",
                CallDataRun.state == "succeeded",
            )
        ).one()
        assert run.pipeline_version == "deep/1" and run.cost_inr > 0
        assert run.counts["segments_labelled"] == 5 and run.counts["audio"] == "timings"
        kinds = {
            row.type_key
            for row in connection.execute(
                select(CallObject.type_key).where(
                    CallObject.recording_id == seeded["recording_id"],
                    CallObject.pipeline == "deep",
                    CallObject.retracted.is_(False),
                )
            )
        }
        assert {
            "conversation.segment",
            "audio.features",
            "conversation.talk_ratio",
            "company.team_size",
            "need.primary_pain",
        } <= kinds
        view = facts.lead_facts(
            connection,
            tenant,
            lead,
            {"name": "Amit S.", "company": None, "city": None, "interest": None},
        )
    shown = {f["type"]: f for f in view["facts"]}
    assert shown["need.primary_pain"]["display"] == "Every sale needs Amit himself"
    assert shown["need.primary_pain"]["source"]["pipeline"] == "deep"
    assert shown["commitment.follow_up"]["basis"] == "confirmed"  # the person's word stayed
    assert "need.goal" not in shown  # weak fast fact retracted
    assert "conversation.segment" not in shown and "audio.features" not in shown
    assert view["pipelines"]["deep"]["state"] == "done"
    # The pain question now asks about the deep value; the name is still a replace.
    asked = {q["type"]: q for q in view["questions"]}
    assert asked["need.primary_pain"]["display"] == "Every sale needs Amit himself"
    assert asked["person.name"]["question"] == "replace"
    # Admin sees everything: facts, every segment label in time order, the voice.
    with postgres_harness.connect() as connection:
        everything = facts.call_objects(connection, seeded["recording_id"])
    assert everything["schema"] == "call-data-objects/1"
    assert [s["segment_id"] for s in everything["segments"]] == ["s1", "s2", "s3", "s4", "s5"]
    assert everything["segments"][1]["speaker"] == "prospect"
    assert everything["segments"][0]["intent"] == "discovery"
    assert everything["voice"]["source"] == "transcript timings only"
    assert set(everything["voice"]["speakers"]) == {"salesperson", "prospect"}
    pain = next(f for f in everything["facts"] if f["type"] == "need.primary_pain")
    assert pain["superseded_a_fast_fact"] is True
    # The dense Admin call detail: attempts, history, edges.
    from ac_platform.call_data.detail import detail

    with postgres_harness.connect() as connection:
        dense = detail(connection, seeded["recording_id"])
    assert dense is not None and dense["schema"] == "call-data-detail/1"
    assert [(r["pipeline"], r["state"]) for r in dense["runs"]] == [
        ("fast", "succeeded"),
        ("deep", "succeeded"),
    ]
    assert dense["runs"][1]["tokens_in"] == 6000 and dense["runs"][1]["cost_inr"] > 0
    history = list(dense["objects"])
    assert any(o["retracted"] for o in history)
    assert any(not o["current"] and not o["retracted"] for o in history)  # superseded
    follow_up = next(o for o in history if o["type"] == "commitment.follow_up")
    assert [d["decision"] for d in follow_up["decisions"]] == ["asked", "accepted"]
    edges = {(e["from"], e["to"]): e for e in dense["edges"]}
    assert edges[("better_transcript", "deep")]["branch"] == "deep"
    assert edges[("fast", "objects")]["status"] == "done"
    assert len(dense["segments"]) == 5 and dense["voice"] is not None
    # Read once: the same transcript is not read again.
    assert _deep(postgres_harness, seeded, DeepModel()) == {"no_candidate": True}
    assert isinstance(UUID(str(follow)), UUID)
