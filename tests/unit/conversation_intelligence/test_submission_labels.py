from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from ac_platform.conversation_intelligence.application import (
    ConversationConflict,
    ConversationDenied,
    ConversationError,
)
from ac_platform.conversation_intelligence.guest_ownership import SubmissionScope
from ac_platform.conversation_intelligence.submission_label_models import (
    ConversationSubmissionLabelRevision,
)
from ac_platform.conversation_intelligence.submission_labels import (
    MAX_DISPLAY_NAME_LENGTH,
    MAX_LABEL_REVISION,
    erase_submission_labels_for_person,
    erase_submission_labels_for_recording,
    format_revision_etag,
    normalize_display_name,
    parse_revision_etag,
    read_submission_label,
    update_submission_label,
)
from ac_platform.kernel.authz import ActorContext


def test_normalize_display_name_trims_limits_and_accepts_unicode() -> None:
    assert normalize_display_name("  Discovery with Asha  ") == "Discovery with Asha"
    assert normalize_display_name("😀" * MAX_DISPLAY_NAME_LENGTH) == "😀" * 120
    assert normalize_display_name("Family 👨‍👩‍👧‍👦") == "Family 👨‍👩‍👧‍👦"
    assert normalize_display_name("मराठी — العربية") == "मराठी — العربية"
    assert normalize_display_name("Cafe\u0301") == "Cafe\u0301"
    assert normalize_display_name(None) is None


@pytest.mark.parametrize(
    "value",
    [
        "",
        "  \t\n ",
        "call\u0000name",
        "call\nname",
        "\ud800",
        "x" * 121,
        "\u200b",
        "\u200d\ufeff",
        "\u0301",
        " \u200b\u0301 ",
        *[
            "Call" + chr(point) + "name"
            for point in (*range(0x202A, 0x202F), *range(0x2066, 0x206A))
        ],
        3,
        [],
        {},
    ],
)
def test_normalize_display_name_rejects_ambiguous_or_invalid_values(value: object) -> None:
    with pytest.raises(ConversationError):
        normalize_display_name(value)


def test_revision_etag_is_strong_single_and_non_negative() -> None:
    assert format_revision_etag(0) == '"call-label-0"'
    assert parse_revision_etag('"call-label-23"') == 23
    assert parse_revision_etag(format_revision_etag(MAX_LABEL_REVISION)) == MAX_LABEL_REVISION
    for value in (
        None,
        "*",
        'W/"call-label-2"',
        '"call-label-02"',
        '"call-label-9999999999"',
        '"other-2"',
    ):
        with pytest.raises(ConversationError):
            parse_revision_etag(value)


@pytest.mark.asyncio
async def test_direct_update_rejects_revision_outside_sql_integer_range() -> None:
    scope = _scope()
    ownership = _ownership(scope, scalar_values=[])
    with pytest.raises(ConversationError):
        await update_submission_label(
            ownership,  # type: ignore[arg-type]
            scope.submission_id,
            actor=_actor(tenant_id=scope.tenant_id),
            expected_revision=MAX_LABEL_REVISION + 1,
            display_name="Call",
        )
    ownership.database.scalar.assert_not_awaited()


def _actor(*, tenant_id=None) -> ActorContext:
    return ActorContext(
        person_id=uuid4(),
        session_id=uuid4(),
        tenant_id=tenant_id or uuid4(),
    )


def _scope(*, claimed_account: bool = True) -> SubmissionScope:
    return SubmissionScope(
        tenant_id=uuid4(),
        submission_id=uuid4(),
        recording_id=uuid4(),
        processing_person_id=uuid4(),
        processing_lease_id=uuid4(),
        usage_id=uuid4(),
        source_sha256="a" * 64,
        claimed_account=claimed_account,
    )


class _Audit:
    rows: list[dict[str, object]] = []

    def __init__(self, _database) -> None:
        pass

    async def append(self, **kwargs):
        self.rows.append(kwargs)


def _ownership(scope: SubmissionScope, *, scalar_values: list[object]):
    database = SimpleNamespace(
        scalar=AsyncMock(side_effect=scalar_values),
        add=MagicMock(),
        flush=AsyncMock(),
        execute=AsyncMock(return_value=SimpleNamespace(rowcount=2)),
    )
    ownership = SimpleNamespace(
        tenant_id=scope.tenant_id,
        database=database,
        require_submission_owner=AsyncMock(return_value=scope),
    )
    return ownership


@pytest.mark.asyncio
async def test_update_appends_revision_and_audits_ids_without_label_text(monkeypatch) -> None:
    scope = _scope()
    actor = _actor(tenant_id=scope.tenant_id)
    recording = SimpleNamespace(id=scope.recording_id)
    ownership = _ownership(scope, scalar_values=[recording, None])
    _Audit.rows = []
    monkeypatch.setattr(
        "ac_platform.conversation_intelligence.submission_labels.AuditRepository", _Audit
    )

    result = await update_submission_label(
        ownership,  # type: ignore[arg-type]
        scope.submission_id,
        actor=actor,
        expected_revision=0,
        display_name="  Discovery with Asha  ",
        request_id="test-request-1",
        now=datetime(2026, 9, 25, tzinfo=UTC),
    )

    assert result.display_name == "Discovery with Asha"
    assert result.revision == 1
    assert ownership.require_submission_owner.await_count == 2
    ownership.database.add.assert_called_once()
    added = ownership.database.add.call_args.args[0]
    assert isinstance(added, ConversationSubmissionLabelRevision)
    assert added.tenant_id == scope.tenant_id
    assert added.submission_id == scope.submission_id
    assert added.actor_person_id == actor.person_id
    assert added.revision == 1
    assert added.display_name == "Discovery with Asha"
    assert ownership.database.flush.await_count == 1
    assert len(_Audit.rows) == 1
    audit = _Audit.rows[0]
    assert audit["actor_person_id"] == actor.person_id
    assert audit["resource_id"] == scope.submission_id
    assert audit["payload"] == {"old_revision": 0, "new_revision": 1}
    assert "Discovery with Asha" not in repr(audit)


@pytest.mark.asyncio
async def test_stale_retry_of_already_applied_value_does_not_duplicate_audit(monkeypatch) -> None:
    scope = _scope()
    actor = _actor(tenant_id=scope.tenant_id)
    recording = SimpleNamespace(id=scope.recording_id)
    latest = SimpleNamespace(display_name="Same name", revision=4)
    ownership = _ownership(scope, scalar_values=[recording, latest])
    _Audit.rows = []
    monkeypatch.setattr(
        "ac_platform.conversation_intelligence.submission_labels.AuditRepository", _Audit
    )

    result = await update_submission_label(
        ownership,  # type: ignore[arg-type]
        scope.submission_id,
        actor=actor,
        expected_revision=3,
        display_name="Same name",
    )

    assert result.display_name == "Same name"
    assert result.revision == 4
    ownership.database.add.assert_not_called()
    ownership.database.flush.assert_not_awaited()
    assert _Audit.rows == []


@pytest.mark.asyncio
async def test_stale_competing_value_conflicts_without_write_or_audit(monkeypatch) -> None:
    scope = _scope()
    actor = _actor(tenant_id=scope.tenant_id)
    current = SimpleNamespace(display_name="Other", revision=2)
    ownership = _ownership(
        scope,
        scalar_values=[SimpleNamespace(id=scope.recording_id), current],
    )
    _Audit.rows = []
    monkeypatch.setattr(
        "ac_platform.conversation_intelligence.submission_labels.AuditRepository", _Audit
    )

    with pytest.raises(ConversationConflict):
        await update_submission_label(
            ownership,  # type: ignore[arg-type]
            scope.submission_id,
            actor=actor,
            expected_revision=1,
            display_name="Mine",
        )

    ownership.database.add.assert_not_called()
    ownership.database.flush.assert_not_awaited()
    assert _Audit.rows == []


@pytest.mark.asyncio
async def test_null_clear_appends_a_revision_without_audit_content(monkeypatch) -> None:
    scope = _scope()
    actor = _actor(tenant_id=scope.tenant_id)
    latest = SimpleNamespace(display_name="Old call name", revision=2)
    ownership = _ownership(
        scope,
        scalar_values=[SimpleNamespace(id=scope.recording_id), latest],
    )
    _Audit.rows = []
    monkeypatch.setattr(
        "ac_platform.conversation_intelligence.submission_labels.AuditRepository", _Audit
    )

    result = await update_submission_label(
        ownership,  # type: ignore[arg-type]
        scope.submission_id,
        actor=actor,
        expected_revision=2,
        display_name=None,
    )

    assert result.display_name is None
    assert result.revision == 3
    added = ownership.database.add.call_args.args[0]
    assert added.display_name is None
    assert added.revision == 3
    assert _Audit.rows[0]["payload"] == {"old_revision": 2, "new_revision": 3}
    assert "Old call name" not in repr(_Audit.rows[0])


@pytest.mark.asyncio
async def test_ownerless_and_guest_updates_are_denied_before_mutation() -> None:
    scope = _scope()
    ownership = _ownership(scope, scalar_values=[])
    with pytest.raises(ConversationDenied):
        await update_submission_label(
            ownership,  # type: ignore[arg-type]
            scope.submission_id,
            actor=None,
            expected_revision=0,
            display_name="Call",
        )
    assert ownership.database.scalar.await_count == 0

    guest_scope = _scope(claimed_account=False)
    guest_owner = _ownership(
        guest_scope, scalar_values=[SimpleNamespace(id=guest_scope.recording_id)]
    )
    guest_actor = _actor(tenant_id=guest_scope.tenant_id)
    with pytest.raises(ConversationDenied):
        await update_submission_label(
            guest_owner,  # type: ignore[arg-type]
            guest_scope.submission_id,
            actor=guest_actor,
            expected_revision=0,
            display_name="Call",
        )
    guest_owner.database.add.assert_not_called()


@pytest.mark.asyncio
async def test_read_uses_the_retained_owner_gate() -> None:
    scope = _scope()
    row = SimpleNamespace(display_name="Retained call", revision=3)
    ownership = _ownership(scope, scalar_values=[row])
    actor = _actor(tenant_id=scope.tenant_id)

    result = await read_submission_label(
        ownership,  # type: ignore[arg-type]
        scope.submission_id,
        actor=actor,
    )

    assert result.display_name == "Retained call"
    assert result.revision == 3
    ownership.require_submission_owner.assert_awaited_once_with(
        scope.submission_id,
        token=None,
        actor=actor,
        shared_identity_locks=False,
        allow_organisation_read=False,
    )


@pytest.mark.asyncio
async def test_erasure_helpers_scope_to_recording_and_account() -> None:
    scope = _scope()
    owner = _ownership(scope, scalar_values=[])

    erased_recording = await erase_submission_labels_for_recording(
        owner.database, tenant_id=scope.tenant_id, recording_id=scope.recording_id
    )
    erased_person = await erase_submission_labels_for_person(owner.database, person_id=uuid4())

    assert erased_recording == 2
    assert erased_person == 2
    assert owner.database.execute.await_count == 2
