"""Call review labels (AUT-1798): what stands, review state and value contracts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from ac_platform.conversation_intelligence.application import ConversationDenied, ConversationError
from ac_platform.conversation_intelligence.review_labels import (
    VALUES,
    GoldValue,
    LabelIntent,
    ReviewLabels,
    effective,
    review_state,
)

T0 = datetime(2026, 10, 11, 9, 0, tzinfo=UTC)
RUN = uuid4()
OPS = UUID("f5386fc3-033d-4e75-a333-7774381cb4d5")


def label(
    kind: str,
    value: dict[str, Any],
    *,
    minutes: int = 0,
    section: str | None = None,
    run: UUID | None = RUN,
    supersedes: UUID | None = None,
    actor: UUID | None = None,
) -> Any:
    return SimpleNamespace(
        id=uuid4(),
        kind=kind,
        value=value,
        section=section,
        run_id=run,
        supersedes_id=supersedes,
        actor_person_id=actor or UUID(int=1),
        created_at=T0 + timedelta(minutes=minutes),
    )


def test_superseded_labels_drop_out_and_notes_accumulate() -> None:
    first = label("verdict", {"verdict": "wrong"}, section="pillar:overview")
    second = label(
        "verdict", {"verdict": "correct"}, minutes=1, section="pillar:overview", supersedes=first.id
    )
    notes = [label("note", {"text": "a"}, minutes=2), label("note", {"text": "b"}, minutes=3)]
    current = effective([second, first, *notes])
    assert [row.id for row in current] == [second.id, notes[0].id, notes[1].id]


def test_review_state_new_needs_review_disputed_done() -> None:
    assert review_state([]) == "new"
    assert review_state([label("note", {"text": "look"})]) == "needs_review"
    wrong = label("verdict", {"verdict": "wrong"}, section="skill:qualification")
    assert review_state([wrong]) == "disputed"
    # Two reviewers disagreeing on the same section is a dispute too.
    a = label("verdict", {"verdict": "correct"}, section="pillar:facts", actor=UUID(int=1))
    b = label("verdict", {"verdict": "partly"}, section="pillar:facts", actor=UUID(int=2))
    assert review_state([a, b]) == "disputed"
    fixed = label(
        "verdict",
        {"verdict": "correct"},
        minutes=1,
        section="skill:qualification",
        supersedes=wrong.id,
    )
    assert review_state([wrong, fixed]) == "needs_review"
    done = label("status", {"state": "done"}, minutes=5, run=None)
    assert review_state([wrong, done]) == "done"
    reopened = label("status", {"state": "needs_review"}, minutes=6, run=None, supersedes=done.id)
    assert review_state([wrong, done, reopened]) == "disputed"


def test_values_are_strict_and_bounded() -> None:
    assert VALUES["verdict"].model_validate({"verdict": "partly"})
    for kind, bad in [
        ("verdict", {"verdict": "maybe"}),
        ("note", {"text": ""}),
        ("note", {"text": "x" * 4001}),
        ("data_use", {"use": "sell"}),
        ("status", {"state": "archived"}),
        ("gold", {"focus": "not_a_skill"}),
        ("gold", {"skill_states": {"qualification": "great"}}),
        ("gold", {"root_cause": "laziness"}),
        ("gold", {"surprise": 1}),
    ]:
        with pytest.raises(ValidationError):
            VALUES[kind].model_validate(bad)
    gold = GoldValue.model_validate(
        {
            "focus": "closing_decision_management",
            "root_cause": "execution",
            "skill_states": {"qualification": "needs_attention"},
        }
    )
    assert gold.model_dump(exclude_none=True)["skill_states"] == {
        "qualification": "needs_attention"
    }


def test_sections_name_a_known_part_of_the_report() -> None:
    for section in (
        "pillar:overview",
        "skill:qualification",
        "report:summary",
        "transcript",
        "coaching:focus",
    ):
        assert LabelIntent(
            kind="verdict", run_id=RUN, section=section, value={"verdict": "correct"}
        )
    for section in ("Pillar:overview", "elsewhere", "pillar:../x", "skill:" + "x" * 70):
        with pytest.raises(ValidationError):
            LabelIntent(kind="verdict", run_id=RUN, section=section, value={})


@pytest.mark.asyncio
async def test_only_operations_admins_add_and_verdicts_need_run_and_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = SimpleNamespace(database=None, clock=lambda: T0)
    service = ReviewLabels(application, OPS, recording_tenant_ids=(UUID(int=7), OPS))  # type: ignore[arg-type]
    assert service.recording_tenant_ids == (UUID(int=7),)
    intent = LabelIntent(
        kind="verdict", run_id=None, section="pillar:overview", value={"verdict": "correct"}
    )
    with pytest.raises(ConversationDenied):
        await service.add(SimpleNamespace(tenant_id=UUID(int=7)), uuid4(), intent, key="k")  # type: ignore[arg-type]

    async def admitted(_self: ReviewLabels, _actor: object) -> datetime:
        return T0

    monkeypatch.setattr(ReviewLabels, "_admit", admitted)
    actor = SimpleNamespace(tenant_id=OPS)
    with pytest.raises(ConversationError, match="names the run"):
        await service.add(actor, uuid4(), intent, key="k")  # type: ignore[arg-type]
    with pytest.raises(ConversationError, match="aren't valid"):
        await service.add(
            actor,  # type: ignore[arg-type]
            uuid4(),
            LabelIntent(kind="note", value={"text": ""}),
            key="k",
        )
    with pytest.raises(ConversationError, match="Idempotency-Key"):
        await service.add(actor, uuid4(), LabelIntent(kind="note", value={"text": "x"}), key=" ")  # type: ignore[arg-type]
