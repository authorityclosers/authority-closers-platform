"""The dev-only WhatsApp test-number connect (scripts/data-changes), with Meta faked.

Development only; a dry run writes nothing; --apply keeps the number for the
organisation with its token sealed, subscribes the account, brings the templates in and
writes one audit event; only an owner or admin of that organisation can be named.
"""

import importlib.util
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy import select

from ac_platform.audit.models import AuditEvent
from ac_platform.identity.models import Person
from ac_platform.lead_desk.models import LeadWhatsAppNumber, LeadWhatsAppTemplate
from ac_platform.lead_desk.whatsapp import cloud
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import _setup
from tests.database.test_lead_desk_postgresql import _organisation
from tests.database.test_lead_desk_whatsapp_postgresql import (
    NUMBER_ID,
    PENDING,
    WABA_ID,
    WELCOME,
    FakeCloud,
)
from tests.unit.lead_desk_whatsapp.test_whatsapp_cloud import ENV as WHATSAPP_ENV

ROOT = Path(__file__).resolve().parents[2]
TOKEN = "fake-business-token"  # noqa: S105 - the fake's own token


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def script() -> Any:
    path = ROOT / "scripts/data-changes/lead-desk-whatsapp-dev-connect.py"
    spec = importlib.util.spec_from_file_location("lead_desk_whatsapp_dev_connect", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dev_connect_keeps_the_test_number_on_dev_only(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value in WHATSAPP_ENV.items():
        monkeypatch.setenv(name, value)
    FakeCloud.sent, FakeCloud.templates_at_meta = [], [WELCOME, PENDING]
    tool = script()
    cfg = cloud.config()
    assert cfg is not None

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            tenant = setup.state.tenant_id
            async with setup.sessions() as db:
                me = await db.get(Person, setup.state.person_id)
                assert me is not None and me.email
                email = me.email

            def ask(**changes: Any) -> dict[str, Any]:
                return {
                    "environment": "development",
                    "org": tenant,
                    "by": email,
                    "waba_id": WABA_ID,
                    "phone_number_id": NUMBER_ID,
                    "approver": "Owner (fictional test)",
                    "issue": "dev WhatsApp test number",
                    "register": False,
                    "apply": False,
                    "token": TOKEN,
                    "api": FakeCloud(cfg),
                    **changes,
                }

            for refused in (
                {"environment": "staging"},
                {"environment": "production"},
                {"token": None},
                {"waba_id": "not-an-id"},
                {"by": "nobody@fictional.example"},
            ):
                async with setup.sessions() as db, db.begin():
                    with pytest.raises(SystemExit):
                        await tool.change(db, **ask(**refused))

            async with setup.sessions() as db, db.begin():
                dry = await tool.change(db, **ask())
            assert dry["applied"] is False and dry["number"] == "+91 80000 00000"
            assert TOKEN not in str(dry)
            async with setup.sessions() as db:
                assert await db.scalar(select(LeadWhatsAppNumber)) is None  # nothing written

            async with setup.sessions() as db, db.begin():
                done = await tool.change(db, **ask(apply=True))
            assert done["applied"] is True and TOKEN not in str(done)
            assert [row["number"] for row in done["after"]] == ["+91 80000 00000"]
            assert done["templates"] >= 1
            async with setup.sessions() as db:
                row = await db.scalar(select(LeadWhatsAppNumber))
                assert row is not None and row.tenant_id == tenant and row.status == "active"
                assert row.pin is None  # Meta's test number comes registered
                assert wa_token(cfg, row) == TOKEN
                assert await db.scalar(
                    select(LeadWhatsAppTemplate.name).where(
                        LeadWhatsAppTemplate.tenant_id == tenant
                    )
                )
                event = await db.scalar(select(AuditEvent).where(AuditEvent.action == tool.ACTION))
                assert event is not None and event.payload["issue"] == "dev WhatsApp test number"
                assert TOKEN not in str(event.payload)
        finally:
            await setup.engine.dispose()

    run(exercise())


def wa_token(cfg: cloud.WhatsAppConfig, row: LeadWhatsAppNumber) -> str:
    from ac_platform.lead_desk.whatsapp import inbox

    return inbox.token(cfg, row)
