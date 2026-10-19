"""Review 2.0 on PostgreSQL: moments (segment labels) judged in psychology terms.

A moment's verdict is bound to its reading and its place in the call (the engine's
span-aware digest). Disposable loopback PostgreSQL, fictional rows only.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import Engine, insert, select

from ac_platform.call_data.models import CallObject
from ac_platform.call_data.values import value_digest as engine_digest
from ac_platform.conversation_intelligence.application import ConversationError
from tests.database.conversation_harness import conversation_harness
from tests.database.test_call_data_postgresql import ROOT
from tests.database.test_review_verdicts_postgresql import (
    _designate,
    _save,
    _seeded_call,
    _with_service,
)

READING = {
    "intent": "pricing",
    "act": "question",
    "sentiment": "neutral",
    "tone": "curious",
    "topics": ["price"],
}
EVIDENCE = [{"segment_id": "s2", "start_ms": 4100, "end_ms": 9000, "speaker": "speaker_1"}]


@pytest.fixture
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def _moment(postgres_harness: Engine, seeded: dict[str, Any]) -> Any:
    """One deep-pipeline moment beside the call's fast objects (fictional reading)."""
    with postgres_harness.begin() as connection:
        source = (
            connection.execute(
                select(CallObject.__table__).where(CallObject.id == seeded["target"].id)
            )
            .mappings()
            .one()
        )
        moment_id = uuid4()
        connection.execute(
            insert(CallObject).values(
                {
                    **dict(source),
                    "id": moment_id,
                    "type_key": "conversation.segment",
                    "category": "conversation",
                    "value": READING,
                    "display": "Pricing question",
                    "evidence": EVIDENCE,
                    "pipeline": "deep",
                    "supersedes_id": None,
                    "created_at": datetime.now(UTC),
                }
            )
        )
    return moment_id


def test_moments_are_judged_in_psychology_terms_bound_to_their_place(
    postgres_harness: Engine,
) -> None:
    seeded = _seeded_call(postgres_harness)
    owner, url = seeded["owner"], postgres_harness.url
    moment = _moment(postgres_harness, seeded)
    _designate(postgres_harness, owner.person_id)
    psychology = {"pipeline_key": "analysis-psychology", "target_kind": "segment"}

    first = _with_service(
        url,
        owner.tenant_id,
        _save(seeded, **psychology, target_ref=str(moment), answer={"value": "wrong"}),
    )
    assert first["pipeline"] == {"key": "analysis-psychology", "version": 1}
    assert first["ai_sha256"] == engine_digest(
        "conversation.segment", READING, [4100, 9000, "speaker_1"]
    )
    intent = _with_service(
        url,
        owner.tenant_id,
        _save(
            seeded,
            **psychology,
            target_ref=str(moment),
            question_key="intent",
            answer={"value": "objection"},
        ),
    )
    assert intent["answer"] == {"value": "objection"}

    refused = (
        # A word outside the engine's own intents.
        {
            **psychology,
            "target_ref": str(moment),
            "question_key": "intent",
            "answer": {"value": "anger"},
        },
        # A moment is not an object, and an object is not a moment.
        {"pipeline_key": "analysis-sales", "target_kind": "object", "target_ref": str(moment)},
        {**psychology, "target_ref": str(seeded["target"].id)},
        # The sales pipeline does not judge moments.
        {"pipeline_key": "analysis-sales", "target_kind": "segment", "target_ref": str(moment)},
    )
    for overrides in refused:
        with pytest.raises(ConversationError):
            _with_service(url, owner.tenant_id, _save(seeded, **overrides))
