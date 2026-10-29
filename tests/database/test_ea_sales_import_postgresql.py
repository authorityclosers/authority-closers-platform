"""Atomic CRM history import, stable replay, dedupe and changed-source refusal."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import select

from ac_platform.audit.models import AuditEvent
from ac_platform.identity.models import Person
from ac_platform.lead_desk.models import Lead
from ac_platform.tenancy.models import Tenant
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_os_acceptance_postgresql import ROOT, world

loader = importlib.util.spec_from_file_location(
    "crm_history_test", ROOT / "scripts/data-changes/ea-sales-import.py"
)
assert loader and loader.loader
tool = importlib.util.module_from_spec(loader)
loader.loader.exec_module(tool)


def row(**extra: str) -> dict[str, str]:
    return {
        "lead_id": "fictional:1",
        "name": "Fictional Person",
        "phone_e164": "+919876073001",
        "email": "fictional@example.com",
        "owner": "Fictional Seller",
        "source_system": "neeti_crm_export",
        "status_raw": "Low Budget",
        "campaign": "Demo",
        "created_at": "2026-06-25T12:00:00+05:30",
        "last_updated": "",
        "first_contacted_at": "2026-07-01T12:00:00+05:30",
        "next_followup_at": "",
        **extra,
    }


@pytest.fixture(scope="module")
def postgres_harness() -> Any:
    yield from conversation_harness(ROOT)


def test_atomic_import_replay_and_changed_source(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            settings = here.setup.settings.model_copy(
                update={"operations_tenant_id": uuid4(), "public_learner_tenant_id": uuid4()}
            )
            monkeypatch.setattr(tool, "get_settings", lambda: settings)
            monkeypatch.setattr(tool, "COMMAND", uuid4())
            monkeypatch.setattr(tool, "NAME", "Fictional Example Organisation")
            async with here.setup.sessions() as db:
                email = await db.scalar(
                    select(Person.email).where(Person.id == here.setup.state.person_id)
                )
            assert email
            spec = tool.prepare(
                [
                    row(),
                    row(
                        lead_id="fictional:2",
                        status_raw="Converted",
                        booked_at="2026-07-10T12:00:00+05:30",
                        last_updated="2026-07-11T12:00:00+05:30",
                    ),
                ]
            )
            calls = [
                {
                    "call_id": "fictional-call",
                    "lead_id": "fictional:2",
                    "duration_sec": "42",
                    "started_at": "2026-07-12T12:00:00+05:30",
                    "agent": "Fictional Seller",
                    "direction": "",
                }
            ]

            async def execute(mode: str, data: Any = spec) -> Any:
                async with here.setup.sessions() as db:
                    try:
                        result = await tool.run(
                            db,
                            data,
                            calls,
                            owner_email=email,
                            mode=mode,
                            digest="fictional-digest",
                            now=datetime.now(UTC),
                        )
                        if mode == "apply":
                            await db.commit()
                        else:
                            await db.rollback()
                        return result
                    except BaseException:
                        await db.rollback()
                        raise

            dry = await execute("dry-run")
            assert dry["after"]["leads"] == 1 and dry["after"]["source_rows"] == 2
            async with here.setup.sessions() as db:
                assert await db.scalar(select(Tenant.id).where(Tenant.name == tool.NAME)) is None
            applied = await execute("apply")
            tenant = tool.UUID(applied["tenant_id"])
            assert applied["after"]["calls"] == 1
            assert applied["after"]["duration_seconds"] == 42
            assert applied["after"]["assigned_leads"] == 0
            assert applied["after"]["by_stage"] == {"won": 1}
            assert applied["analysis_started"] == applied["recordings_uploaded"] == 0
            async with here.setup.sessions() as db:
                lead = await db.scalar(select(Lead).where(Lead.tenant_id == tenant))
                assert lead and lead.created_at.year == datetime.now(UTC).year
                assert lead.created_at > datetime(2026, 7, 12, tzinfo=UTC)
                audit_before = len(
                    list(await db.scalars(select(AuditEvent).where(AuditEvent.tenant_id == tenant)))
                )
            replay = await execute("apply")
            assert replay["rows"] == {"done_before": 2}
            assert replay["new_calls"] == 0 and replay["after"] == applied["after"]
            async with here.setup.sessions() as db:
                assert (
                    len(
                        list(
                            await db.scalars(
                                select(AuditEvent).where(AuditEvent.tenant_id == tenant)
                            )
                        )
                    )
                    == audit_before
                )
            changed = tool.prepare([row(name="Fictional Changed")])
            with pytest.raises(ValueError, match="source changed"):
                await execute("apply", changed)
            assert (await execute("read"))["after"] == applied["after"]

    run(exercise())
