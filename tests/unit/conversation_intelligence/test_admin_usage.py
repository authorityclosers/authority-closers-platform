"""Usage (AUT-1798): operations admission, bounded window, served scope only."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest

from ac_platform.conversation_intelligence import admin_usage
from ac_platform.conversation_intelligence.admin_usage import AdminUsage
from ac_platform.conversation_intelligence.application import ConversationDenied, ConversationError

OPS = UUID("f5386fc3-033d-4e75-a333-7774381cb4d5")
TEAM = UUID("206ccee8-a246-433b-b6d3-78eb21592a5c")


@pytest.mark.asyncio
async def test_usage_admits_only_operations_and_bounds_the_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = SimpleNamespace(database=None, clock=lambda: datetime(2026, 10, 11, tzinfo=UTC))
    service = AdminUsage(application, OPS, recording_tenant_ids=(TEAM, OPS))  # type: ignore[arg-type]
    assert service.tenant_ids == (TEAM,)
    with pytest.raises(ConversationDenied):
        await service.summary(SimpleNamespace(tenant_id=TEAM))  # type: ignore[arg-type]

    class _Admin:
        def __init__(self, _application: object) -> None:
            pass

        async def admit(self, _actor: object) -> None:
            return None

    monkeypatch.setattr(admin_usage, "ConversationProviderAdmin", _Admin)
    for days in (0, 91):
        with pytest.raises(ConversationError):
            await service.summary(SimpleNamespace(tenant_id=OPS), days=days)  # type: ignore[arg-type]
