"""Fictional plan snapshots freeze owner choices, including no-role fallback."""

from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from ac_platform.conversation_intelligence import processing_plan, reports
from ac_platform.conversation_intelligence.checkpoints import canonical
from ac_platform.conversation_intelligence.processing_plan import ConversationProcessingPlans
from ac_platform.conversation_intelligence.sensitive_segments import EMPTY_PLAN, WithheldPlan
from tests.unit.conversation_intelligence.test_processing_plan import saved_plan
from tests.unit.conversation_intelligence.test_speaker_map_service import TRANSCRIPT


@pytest.fixture
def case(monkeypatch):
    owner = uuid4()
    database = SimpleNamespace(
        get=AsyncMock(return_value=SimpleNamespace(display_name="Zoya", first_name="Wrong")),
        scalar=AsyncMock(return_value=None),
    )
    app = SimpleNamespace(database=database, clock=lambda: datetime.now(UTC))
    service = ConversationProcessingPlans(app, Mock())
    recording = SimpleNamespace(
        id=uuid4(), tenant_id=uuid4(), person_id=uuid4(), source_sha256="f" * 64
    )
    customer = AsyncMock(return_value=owner)
    monkeypatch.setattr(processing_plan, "_customer_person_id", customer)
    monkeypatch.setattr(processing_plan, "withheld_plan_for", AsyncMock(return_value=EMPTY_PLAN))
    monkeypatch.setattr(reports, "SPEAKER_ROLE_PROMPT_REVISIONS", frozenset({"coaching-v3"}))
    return service, recording, database, customer, owner


@pytest.mark.asyncio
@pytest.mark.parametrize("revision", [f"coaching-v{n}" for n in range(1, 7)])
async def test_undeclared_plan_never_reads_or_changes_roles(case, monkeypatch, revision):
    monkeypatch.setattr(reports, "SPEAKER_ROLE_PROMPT_REVISIONS", frozenset())
    service, recording, database, customer, _ = case
    row = saved_plan()
    assert await service._speaker_roles_for_c5(row, recording, TRANSCRIPT, revision) is None
    assert row.speaker_roles is None and row.progress == {}
    customer.assert_not_awaited()
    database.get.assert_not_awaited()
    database.scalar.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["predicted", "confirmed", "stale", "unclaimed", "withheld"])
async def test_owner_snapshot_is_names_free_and_replayed_without_live_reads(
    case, monkeypatch, caplog, source
):
    service, recording, database, customer, owner = case
    row = saved_plan()
    if source in {"confirmed", "stale"}:
        database.scalar.return_value = SimpleNamespace(
            revision=2,
            transcript_revision="old" if source == "stale" else TRANSCRIPT["revision"],
            speakers=[
                {"speaker_id": "speaker_0", "role": "prospect", "display_name": "Private name"},
                {"speaker_id": "speaker_1", "role": "you", "display_name": None},
            ],
        )
    if source == "unclaimed":
        customer.return_value = None
    if source == "withheld":
        monkeypatch.setattr(
            processing_plan,
            "withheld_plan_for",
            AsyncMock(return_value=WithheldPlan(frozenset({"s0"}), frozenset())),
        )
    before = deepcopy(TRANSCRIPT)
    roles = await service._speaker_roles_for_c5(row, recording, TRANSCRIPT, "coaching-v3")
    assert roles == row.speaker_roles and row.progress["speaker_roles_frozen"] is True
    assert roles["transcript_revision"] == TRANSCRIPT["revision"]
    assert all(set(s) == {"speaker_id", "role", "is_account_holder"} for s in roles["speakers"])
    holders = [s["speaker_id"] for s in roles["speakers"] if s["is_account_holder"]]
    assert holders == (
        ["speaker_1"]
        if source == "confirmed"
        else ["speaker_0"]
        if source in {"predicted", "stale"}
        else []
    )
    assert roles["origin"] == (
        "user_confirmed_roles"
        if source == "confirmed"
        else "text_predicted_roles"
        if source in {"predicted", "stale", "unclaimed"}
        else "unverified_provider_labels"
    )
    assert "Zoya" not in canonical(roles).decode() and "Private name" not in caplog.text
    assert caplog.messages == (["speaker_roles_source_invalid"] if source == "stale" else [])
    if source != "unclaimed":
        database.get.assert_awaited_once_with(processing_plan.Person, owner)
    else:
        database.get.assert_not_awaited()
        database.scalar.assert_not_awaited()
    reads = customer.await_count, database.scalar.await_count
    database.scalar.return_value = None
    replay = await service._speaker_roles_for_c5(row, recording, TRANSCRIPT, "coaching-v3")
    assert replay == roles and (customer.await_count, database.scalar.await_count) == reads
    replay["speakers"].clear()
    assert row.speaker_roles == roles and before == TRANSCRIPT


@pytest.mark.asyncio
async def test_invalid_snapshot_freezes_null_but_new_plan_resolves_current_map(
    case, monkeypatch, caplog
):
    service, recording, _, customer, _ = case
    original = processing_plan.resolve_speaker_map
    monkeypatch.setattr(
        processing_plan, "resolve_speaker_map", Mock(side_effect=ValueError("private"))
    )
    row = saved_plan()
    assert await service._speaker_roles_for_c5(row, recording, TRANSCRIPT, "coaching-v3") is None
    assert row.speaker_roles is None and caplog.messages == ["speaker_roles_snapshot_invalid"]
    monkeypatch.setattr(processing_plan, "resolve_speaker_map", original)
    assert await service._speaker_roles_for_c5(row, recording, TRANSCRIPT, "coaching-v3") is None
    customer.assert_awaited_once()
    assert await service._speaker_roles_for_c5(saved_plan(), recording, TRANSCRIPT, "coaching-v3")
    assert customer.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("hold", [None, "C5"])
async def test_advance_carries_frozen_roles_and_marker_across_polls(case, monkeypatch, hold):
    service, recording, _, customer, _ = case
    row = saved_plan()
    row.state = "active"
    value = processing_plan.manifest_for(row).model_copy(
        update={"coaching_prompt_revision": "coaching-v3"}
    )
    monkeypatch.setattr(processing_plan, "require_plan_consent", AsyncMock(return_value=value))
    pipeline = SimpleNamespace(
        plan=AsyncMock(
            return_value=SimpleNamespace(
                prepared=SimpleNamespace(chunk_count=1), transcript=TRANSCRIPT
            )
        )
    )
    monkeypatch.setattr(processing_plan, "ReportingPipeline", lambda _: pipeline)
    service.app._recording = AsyncMock(return_value=recording)
    requests = []

    async def enqueue(_actor, _row, _value, request):
        if request is not None and request.stage == "C5":
            requests.append(request.model_dump(mode="json"))
        return SimpleNamespace(
            state="queued" if request is not None and request.stage == "C5" else "completed",
            checkpoint_id=uuid4(),
            stage="C2" if request is None else request.stage,
        )

    service._enqueue = enqueue
    service._account_profile_hold_stage = AsyncMock(return_value=hold)
    await service.advance(Mock(), row)
    await service.advance(Mock(), row)
    assert requests[0]["speaker_roles"] == requests[1]["speaker_roles"] == row.speaker_roles
    assert row.progress["speaker_roles_frozen"] is True
    assert row.progress["current_stage"] == "C5"
    customer.assert_awaited_once()
