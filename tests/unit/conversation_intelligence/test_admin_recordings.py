from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from ac_platform.conversation_intelligence.admin_recordings import (
    _cost_view,
    _cursor,
    _decode_cursor,
    _owner_view,
    _safe_duration,
    _status,
)
from ac_platform.conversation_intelligence.application import ConversationError


def test_cursor_round_trip_is_opaque_and_stable() -> None:
    created = datetime(2026, 9, 14, 12, 30, tzinfo=UTC)
    recording_id = UUID("11111111-1111-4111-8111-111111111111")
    token = _cursor(created, recording_id)

    assert token != f"{created.isoformat()}|{recording_id}"
    assert _decode_cursor(token) == (created, recording_id)


@pytest.mark.parametrize("token", ["!", "not-a-cursor", "@@@@"])
def test_cursor_rejects_untrusted_values(token: str) -> None:
    with pytest.raises(ConversationError, match="cursor is invalid"):
        _decode_cursor(token)


def test_owner_view_does_not_expose_guest_visitor_identity() -> None:
    recording = SimpleNamespace(person_id=uuid4())
    guest = SimpleNamespace()
    usage = SimpleNamespace(person_id=None, visitor_id=uuid4())

    view = _owner_view(recording, guest, usage, None, {})

    assert view == {
        "kind": "guest",
        "label": "Guest upload",
        "person_id": None,
        "display_name": None,
        "email": None,
        "claimed": False,
    }
    assert "visitor_id" not in view


def test_status_prioritizes_verified_report_and_preserves_failed_run() -> None:
    recording = SimpleNamespace(state="ready")
    run = SimpleNamespace(state="failed")
    plan = SimpleNamespace(state="held")

    assert _status(recording, run, plan, has_report=True) == "completed"
    assert _status(recording, run, plan, has_report=False) == "held"
    assert _status(recording, run, None, has_report=False) == "failed"


def test_cost_view_never_invents_actual_cost_without_settlement() -> None:
    view = _cost_view(None, None, None)

    assert view["reservation_paise"] is None
    assert view["estimate_paise"] is None
    assert view["actual_paise"] is None
    assert view["actual_state"] == "not_settled"


def test_duration_only_accepts_bounded_native_measurement() -> None:
    assert _safe_duration({"media_duration_ms": 12_345}) == 12_345
    assert _safe_duration({"media_duration_ms": 0}) is None
    assert _safe_duration({"media_duration_ms": "12345"}) is None
    assert _safe_duration({"duration_ms": 12_345}) is None
