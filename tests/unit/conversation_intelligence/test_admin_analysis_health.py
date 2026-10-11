"""Analysis health (AUT-1798): codes only, honest statistics, operations admission."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest

from ac_platform.conversation_intelligence.admin_analysis_health import (
    AdminAnalysisHealth,
    _percentile,
    failure_code,
)
from ac_platform.conversation_intelligence.application import ConversationDenied, ConversationError

OPS = UUID("f5386fc3-033d-4e75-a333-7774381cb4d5")
TEAM = UUID("206ccee8-a246-433b-b6d3-78eb21592a5c")


def _job(**values: object) -> SimpleNamespace:
    return SimpleNamespace(**{"failure_detail": None, "last_error": None, **values})


def test_failure_code_never_shows_free_text() -> None:
    assert failure_code(_job(failure_detail={"code": "provider_timeout"})) == "provider_timeout"
    assert failure_code(_job(last_error="conversation_local_phase_failed")) == (
        "conversation_local_phase_failed"
    )
    assert failure_code(_job(last_error="Traceback: secret prospect said X")) == "withheld"
    assert failure_code(_job(failure_detail={"code": "Has Spaces"}, last_error=None)) == (
        "not_recorded"
    )
    assert failure_code(_job()) == "not_recorded"


def test_percentile_is_bounded_and_empty_is_none() -> None:
    assert _percentile([], 0.9) is None
    assert _percentile([5.0], 0.9) == 5.0
    assert _percentile([float(value) for value in range(1, 11)], 0.9) == 9.0


@pytest.mark.asyncio
async def test_only_the_operations_workspace_and_a_bounded_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = AdminAnalysisHealth(
        SimpleNamespace(database=None, clock=lambda: datetime(2026, 10, 11, tzinfo=UTC)),  # type: ignore[arg-type]
        OPS,
        recording_tenant_ids=(TEAM, OPS),
    )
    assert service.recording_tenant_ids == (TEAM,)
    with pytest.raises(ConversationDenied):
        await service.summary(SimpleNamespace(tenant_id=TEAM))  # type: ignore[arg-type]

    async def admitted(_self: AdminAnalysisHealth, _actor: object) -> datetime:
        return datetime(2026, 10, 11, tzinfo=UTC)

    monkeypatch.setattr(AdminAnalysisHealth, "_admit", admitted)
    for days in (0, 31):
        with pytest.raises(ConversationError):
            await service.summary(SimpleNamespace(tenant_id=OPS), days=days)  # type: ignore[arg-type]
