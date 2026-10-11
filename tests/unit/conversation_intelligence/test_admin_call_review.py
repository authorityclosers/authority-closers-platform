"""Queue logic for the Admin call review console (AUT-1798), without a database."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from ac_platform.conversation_intelligence import admin_call_review as module
from ac_platform.conversation_intelligence.admin_call_review import (
    AdminCallReview,
    _cursor,
    _offset,
    _plan_facts,
    _status,
)
from ac_platform.conversation_intelligence.application import (
    ConversationDenied,
    ConversationError,
)

OPS = UUID("f5386fc3-033d-4e75-a333-7774381cb4d5")
TEAM_A = UUID("206ccee8-a246-433b-b6d3-78eb21592a5c")
TEAM_B = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


def _plan(state: str = "completed", **manifest: Any) -> Any:
    return SimpleNamespace(
        id=uuid4(),
        state=state,
        created_at=NOW,
        manifest={
            "report_language": "hi-Deva+en",
            "duration_ms": 240_000,
            "coaching_prompt_revision": "coaching-v5",
            "stages": [
                {"stage": "C2", "provider_id": "deepgram", "model_id": "nova-3"},
                {"stage": "C4", "provider_id": "gemini", "model_id": "flash"},
                {"stage": "C5", "provider_id": "gemini", "model_id": "pro"},
            ],
            **manifest,
        },
    )


def _run(state: str, minutes_ago: int = 0) -> Any:
    return SimpleNamespace(
        id=uuid4(),
        state=state,
        generation=1,
        recipe_revision="r1",
        created_at=NOW - timedelta(minutes=minutes_ago),
        completed_at=None,
    )


def test_plan_facts_reads_language_provider_and_prompt_with_defaults() -> None:
    facts = _plan_facts(_plan())
    assert facts["language"] == "hi-Deva+en"
    assert (facts["provider"], facts["model"]) == ("gemini", "pro")
    assert facts["transcription_provider"] == "deepgram"
    assert facts["prompt_revision"] == "coaching-v5"
    assert facts["duration_ms"] == 240_000
    empty = _plan_facts(None)
    assert empty["language"] is None and empty["provider"] is None and empty["plan_id"] is None
    legacy = _plan_facts(SimpleNamespace(id=uuid4(), state="completed", manifest={"stages": "x"}))
    assert legacy["language"] == "en" and legacy["provider"] is None


def test_status_is_honest_about_work_in_flight_failure_and_reports() -> None:
    assert _status(_run("running"), None, False) == "analysing"
    assert _status(_run("completed"), _plan("active"), True) == "analysing"
    assert _status(_run("completed"), None, True) == "ready"
    assert _status(_run("failed"), None, False) == "failed"
    assert _status(_run("failed"), None, True) == "ready"
    assert _status(None, _plan("expired"), False) == "failed"
    assert _status(None, None, False) == "uploaded"


def test_cursor_round_trips_and_rejects_anything_else() -> None:
    assert _offset(None) == 0
    assert _offset(_cursor(50)) == 50
    for bad in ("nonsense", _cursor(10_000), "bzotMQ"):
        with pytest.raises(ConversationError):
            _offset(bad)


def _queue_service(monkeypatch: pytest.MonkeyPatch, recordings: list[Any]) -> AdminCallReview:
    async def admit(_self: AdminCallReview, _actor: Any) -> datetime:
        return NOW

    class _Scalars:
        def all(self) -> list[Any]:
            return recordings

    class _Database:
        async def scalars(self, _statement: Any) -> _Scalars:
            return _Scalars()

    reps = {
        recording.id: {
            "kind": "learner",
            "label": recording.rep_label,
            "person_id": str(recording.person_id),
            "display_name": recording.rep_label,
            "email": None,
            "claimed": True,
        }
        for recording in recordings
    }

    async def owners(_self: AdminCallReview, rows: Any) -> dict[UUID, dict]:
        return {row.id: reps[row.id] for row in rows}

    async def organisations(_self: AdminCallReview, ids: Any) -> dict[UUID, str]:
        return {TEAM_A: "Team A", TEAM_B: "Team B"}

    async def runs(_self: AdminCallReview, ids: Any) -> dict[UUID, list[Any]]:
        return {row.id: row.runs for row in recordings}

    async def plans(_self: AdminCallReview, ids: Any) -> dict[UUID, list[Any]]:
        return {row.id: row.plans for row in recordings}

    async def reports(_self: AdminCallReview, ids: Any) -> dict[UUID, dict[UUID, UUID]]:
        return {
            row.id: {run.id: uuid4() for run in row.runs if run.state == "completed"}
            for row in recordings
        }

    for name, value in {
        "_admit": admit,
        "_owners": owners,
        "_organisations": organisations,
        "_runs": runs,
        "_plans": plans,
        "_reports": reports,
    }.items():
        monkeypatch.setattr(AdminCallReview, name, value)
    monkeypatch.setattr(
        module, "recording_is_canary", lambda: module.ConversationRecording.id.is_(None)
    )
    application = SimpleNamespace(database=_Database(), clock=lambda: NOW)
    return AdminCallReview(application, OPS, recording_tenant_ids=(TEAM_A, TEAM_B, OPS))  # type: ignore[arg-type]


def _recording(tenant: UUID, rep: str, runs: list[Any], plans: list[Any]) -> Any:
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant,
        person_id=uuid4(),
        rep_label=rep,
        created_at=NOW,
        runs=runs,
        plans=plans,
    )


@pytest.mark.asyncio
async def test_queue_filters_counts_facets_and_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    ready = _recording(TEAM_A, "Asha", [_run("completed")], [_plan()])
    failed = _recording(TEAM_A, "Asha", [_run("failed")], [_plan(report_language="en")])
    busy = _recording(TEAM_B, "Bharat", [_run("running")], [_plan("active")])
    marathi = _recording(
        TEAM_B,
        "Chitra",
        [_run("completed")],
        [
            _plan(
                report_language="mr-Deva+en",
                coaching_prompt_revision="coaching-v6",
                stages=[{"stage": "C5", "provider_id": "openai", "model_id": "x"}],
            )
        ],
    )
    service = _queue_service(monkeypatch, [ready, failed, busy, marathi])
    actor = SimpleNamespace(tenant_id=OPS)

    everything = await service.queue(actor)
    assert everything["total"] == 4
    assert everything["counts"] == {"ready": 2, "analysing": 1, "failed": 1, "uploaded": 0}
    assert [entry["label"] for entry in everything["facets"]["organisations"]] == [
        "Team A",
        "Team B",
    ]
    assert {entry["value"] for entry in everything["facets"]["providers"]} == {"gemini", "openai"}
    first = everything["items"][0]
    assert first["organisation"] == {"id": str(TEAM_A), "name": "Team A"}
    assert first["report_run_id"] == str(ready.runs[0].id)

    only_ready = await service.queue(actor, status="ready")
    assert {item["recording_id"] for item in only_ready["items"]} == {
        str(ready.id),
        str(marathi.id),
    }
    assert only_ready["counts"]["failed"] == 1  # tabs keep their counts while one is selected
    marathi_only = await service.queue(actor, language="mr-Deva+en")
    assert [item["recording_id"] for item in marathi_only["items"]] == [str(marathi.id)]
    openai = await service.queue(actor, provider="openai")
    assert [item["recording_id"] for item in openai["items"]] == [str(marathi.id)]
    assert [(entry["value"], entry["count"]) for entry in everything["facets"]["prompts"]] == [
        ("coaching-v5", 3),
        ("coaching-v6", 1),
    ]
    # A call counts for every prompt it was analysed with, not only its latest.
    rerun = _recording(
        TEAM_A,
        "Asha",
        [_run("completed")],
        [_plan(coaching_prompt_revision="coaching-v7"), _plan()],
    )
    with_rerun = _queue_service(monkeypatch, [ready, failed, busy, marathi, rerun])
    v5 = await with_rerun.queue(actor, prompt="coaching-v5")
    assert str(rerun.id) in {item["recording_id"] for item in v5["items"]}
    assert {entry["value"]: entry["count"] for entry in v5["facets"]["prompts"]} == {
        "coaching-v5": 4,
        "coaching-v6": 1,
        "coaching-v7": 1,
    }
    newest_prompt = await service.queue(actor, prompt="coaching-v6")
    assert [item["recording_id"] for item in newest_prompt["items"]] == [str(marathi.id)]
    assert (await service.queue(actor, prompt="coaching-v1"))["items"] == []
    asha = await service.queue(actor, rep=ready.person_id)
    assert [item["recording_id"] for item in asha["items"]] == [str(ready.id)]

    page = await service.queue(actor, limit=3)
    assert len(page["items"]) == 3 and page["next_cursor"] is not None
    rest = await service.queue(actor, limit=3, cursor=page["next_cursor"])
    assert len(rest["items"]) == 1 and rest["next_cursor"] is None


@pytest.mark.asyncio
async def test_queue_refuses_unknown_filters_and_other_workspaces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _queue_service(monkeypatch, [])
    actor = SimpleNamespace(tenant_id=OPS)
    with pytest.raises(ConversationError):
        await service.queue(actor, status="maybe")
    with pytest.raises(ConversationError):
        await service.queue(actor, language="fr")
    with pytest.raises(ConversationError):
        await service.queue(actor, limit=500)
    with pytest.raises(ConversationError):
        await service.queue(actor, since=NOW.date(), until=NOW.date() - timedelta(days=1))
    monkeypatch.undo()
    real = AdminCallReview(
        SimpleNamespace(database=None, clock=lambda: NOW),  # type: ignore[arg-type]
        OPS,
        recording_tenant_ids=(TEAM_A,),
    )
    with pytest.raises(ConversationDenied):
        await real.queue(SimpleNamespace(tenant_id=TEAM_A))


def test_operations_workspace_is_never_in_review_scope() -> None:
    service = AdminCallReview(
        SimpleNamespace(database=None, clock=lambda: NOW),  # type: ignore[arg-type]
        OPS,
        recording_tenant_ids=(TEAM_A, OPS, TEAM_A),
    )
    assert service.recording_tenant_ids == (TEAM_A,)
