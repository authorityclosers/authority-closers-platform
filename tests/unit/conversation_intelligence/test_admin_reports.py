from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from ac_platform.conversation_intelligence import admin_reports
from ac_platform.conversation_intelligence.application import ConversationNotFound
from ac_platform.conversation_intelligence.review_service import ConversationReviewService

OPS_TENANT = UUID("f5386fc3-033d-4e75-a333-7774381cb4d5")
PUBLIC_TENANT = UUID("206ccee8-a246-433b-b6d3-78eb21592a5c")
UNRELATED_TENANT = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


class _Database:
    def __init__(self, run: object | None, *, allowed_tenants: set[UUID] | None = None) -> None:
        self.run = run
        self.allowed_tenants = allowed_tenants

    async def scalar(self, _statement: object) -> object | None:
        if (
            self.run is not None
            and self.allowed_tenants is not None
            and getattr(self.run, "tenant_id", None) not in self.allowed_tenants
        ):
            return None
        return self.run


class _Application:
    def __init__(self, database: _Database) -> None:
        self.database = database
        self.clock = lambda: datetime(2026, 9, 15, 12, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_admin_report_read_scopes_tenant_and_audits_verified_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = uuid4()
    recording_id = uuid4()
    report_id = uuid4()
    recording = SimpleNamespace(
        id=recording_id,
        tenant_id=PUBLIC_TENANT,
        source_sha256="a" * 64,
        source_revision=2,
    )
    evidence = SimpleNamespace(
        recording=recording,
        run=SimpleNamespace(id=run_id),
        draft=SimpleNamespace(id=report_id),
        retention_until=datetime(2026, 9, 22, 12, 0, tzinfo=UTC),
    )
    now = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
    audit: list[dict[str, object]] = []

    async def admit(_service: ConversationReviewService, _actor: object) -> datetime:
        return now

    async def evidence_for(
        _service: ConversationReviewService, _run_id: UUID, _now: datetime
    ) -> object:
        return evidence

    async def append_audit(
        _service: ConversationReviewService,
        _actor: object,
        **values: object,
    ) -> None:
        audit.append(values)

    class _Report:
        def model_dump(self, *, mode: str) -> dict[str, str]:
            assert mode == "json"
            return {"summary": "Bound report"}

    monkeypatch.setattr(ConversationReviewService, "_admin", admit)
    monkeypatch.setattr(ConversationReviewService, "_evidence", evidence_for)
    monkeypatch.setattr(ConversationReviewService, "_review_audit", append_audit)
    monkeypatch.setattr(
        admin_reports.ConversationReports,
        "_validated",
        staticmethod(lambda _draft, _recording: (_Report(), {})),
    )

    result = await admin_reports.AdminConversationReports(
        _Application(
            _Database(
                SimpleNamespace(id=run_id, tenant_id=PUBLIC_TENANT),
                allowed_tenants={OPS_TENANT, PUBLIC_TENANT},
            )
        ),
        OPS_TENANT,
        recording_tenant_ids=(PUBLIC_TENANT,),
    ).get(SimpleNamespace(tenant_id=OPS_TENANT), run_id)

    assert result["tenant_id"] == str(PUBLIC_TENANT)
    assert result["report"] == {"summary": "Bound report"}
    assert audit[0]["action"] == "admin_report_view"
    assert audit[0]["tenant_id"] == PUBLIC_TENANT
    assert audit[0]["resource_id"] == report_id


@pytest.mark.asyncio
async def test_admin_report_read_rejects_run_outside_configured_recording_tenants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence_called = False

    async def evidence_for(
        _service: ConversationReviewService, _run_id: UUID, _now: datetime
    ) -> object:
        nonlocal evidence_called
        evidence_called = True
        raise AssertionError("cross-tenant run must be rejected before evidence lookup")

    async def admit(_service: ConversationReviewService, _actor: object) -> datetime:
        return datetime(2026, 9, 15, 12, 0, tzinfo=UTC)

    monkeypatch.setattr(ConversationReviewService, "_admin", admit)
    monkeypatch.setattr(ConversationReviewService, "_evidence", evidence_for)

    with pytest.raises(ConversationNotFound, match="Report not found"):
        await admin_reports.AdminConversationReports(
            _Application(
                _Database(
                    SimpleNamespace(id=uuid4(), tenant_id=UNRELATED_TENANT),
                    allowed_tenants={OPS_TENANT, PUBLIC_TENANT},
                )
            ),
            OPS_TENANT,
            recording_tenant_ids=(PUBLIC_TENANT,),
        ).get(SimpleNamespace(tenant_id=OPS_TENANT), uuid4())
    assert evidence_called is False
