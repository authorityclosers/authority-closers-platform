"""The data change that readies a test or sandbox workspace for an API call upload, on
PostgreSQL (orchestrator, 15 Nov 2026: Luna on staging, one of Dipak's gold calls through
``sx upload``, never in a customer's workspace). Fictional people and workspaces only."""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy import select, update

from ac_platform.audit.models import AuditEvent
from ac_platform.conversation_intelligence import key_upload
from ac_platform.identity.models import Person
from ac_platform.integrations import keys
from ac_platform.tenancy.models import Tenant
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_submission_http_postgresql import _setup
from tests.database.test_lead_desk_postgresql import _organisation

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "api_upload_proof_setup", ROOT / "scripts/data-changes/api-upload-proof-setup.py"
)
assert _spec is not None and _spec.loader is not None
script = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = script  # its dataclasses look themselves up here
_spec.loader.exec_module(script)

POLICY = "c" * 64
APPROVAL = [
    "--approver",
    "Suyash Kulkarni (owner), decided by the orchestrator on his delegation",
    "--issue",
    "orch:luna-staging-gold-call-20261115",
    "--reason",
    "one gold call through the API on staging",
]


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def _command(setup: Any, email: str, action: str, *extra: str) -> Any:
    args = script._parser().parse_args(
        [
            "--environment",
            "test",
            "--tenant",
            str(setup.state.tenant_id),
            "--maker-email",
            email,
            "--upload-policy-sha256",
            POLICY,
            *APPROVAL,
            *extra,
            action,
        ]
    )
    return script.command_from(args)


async def _run(setup: Any, command: Any) -> dict[str, Any]:
    async with setup.sessions() as db, db.begin():
        return cast(
            dict[str, Any],
            await script.execute(db, command, billing_enabled=False, now=datetime.now(UTC)),
        )


def test_a_test_workspace_gets_its_terms_and_a_key_once(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)  # the signed-in person is an admin here
            async with setup.sessions() as db, db.begin():
                await db.execute(
                    update(Tenant)
                    .where(Tenant.id == setup.state.tenant_id)
                    .values(name="TEST · API upload proof")
                )
                email = await db.scalar(
                    select(Person.email).where(Person.id == setup.state.person_id)
                )
            assert email

            status = await _run(setup, _command(setup, email, "status"))
            assert (status["status"], status["terms"]) == ("read_only", "ask")
            assert status["api_keys_allowed"] and status["recordings_write_allowed"]
            assert any(member["role"] == "admin" for member in status["members"])

            on = await _run(setup, _command(setup, email, "terms", "--apply"))
            assert (on["status"], on["terms_after"]) == ("applied", "on")
            again = await _run(setup, _command(setup, email, "terms", "--apply"))
            assert again["status"] == "already_on"
            async with setup.sessions() as db:
                found = await key_upload.terms(db, setup.state.tenant_id, POLICY, "test")
                recorded = list(
                    await db.scalars(
                        select(AuditEvent).where(
                            AuditEvent.action == "conversation.api_upload_terms_data_change"
                        )
                    )
                )
            assert found.state == "on"
            (note,) = recorded
            assert note.payload["approver"].startswith("Suyash Kulkarni (owner)")
            assert note.payload["terms_event_id"] == str(found.event_id)

            minted = await _run(setup, _command(setup, email, "mint-key", "--apply"))
            key = minted.pop("_key")
            assert key.startswith("sxk_test_") and minted["status"] == "applied"
            async with setup.sessions() as db:
                context = await db.run_sync(
                    lambda sync: keys.authenticate(
                        sync.connection(), key, environment="test", now=datetime.now(UTC)
                    )
                )
                made = await db.scalar(
                    select(AuditEvent).where(
                        AuditEvent.action == "integration.api_key_created",
                        AuditEvent.resource_id == minted["key_id"],
                    )
                )
            assert context is not None and context.scopes == frozenset({"recordings:write"})
            assert made is not None and made.payload["issue"] == APPROVAL[3]
            assert key not in str(made.payload)
            # Release PR #623 review: run again, it makes no second key and shows none.
            twice = await _run(setup, _command(setup, email, "mint-key", "--apply"))
            assert (twice["status"], twice["key_id"]) == ("already_minted", minted["key_id"])
            assert "_key" not in twice
            async with setup.sessions() as db:
                made_twice = list(
                    await db.scalars(
                        select(AuditEvent).where(
                            AuditEvent.action == "integration.api_key_created",
                            AuditEvent.tenant_id == setup.state.tenant_id,
                        )
                    )
                )
            assert len(made_twice) == 1
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_a_customer_workspace_or_a_member_is_refused(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            async with setup.sessions() as db, db.begin():
                await db.execute(
                    update(Tenant)
                    .where(Tenant.id == setup.state.tenant_id)
                    .values(name="Acme Realty")
                )
                email = await db.scalar(
                    select(Person.email).where(Person.id == setup.state.person_id)
                )
            assert email
            with pytest.raises(script.Refused, match="not_a_test_sandbox_or_fictional"):
                await _run(setup, _command(setup, email, "status"))
            async with setup.sessions() as db, db.begin():
                await db.execute(
                    update(Tenant)
                    .where(Tenant.id == setup.state.tenant_id)
                    .values(name="AC Sandbox")
                )
            member = await seed(setup.engine, tenant_id=setup.state.tenant_id, role="member")
            async with setup.sessions() as db:
                member_email = await db.scalar(
                    select(Person.email).where(Person.id == member.person_id)
                )
            assert member_email
            with pytest.raises(script.Refused, match="owner_or_admin"):
                await _run(setup, _command(setup, member_email, "mint-key", "--apply"))
            # A change without its approval never runs.
            args = script._parser().parse_args(
                [
                    "--environment",
                    "test",
                    "--tenant",
                    str(setup.state.tenant_id),
                    "--maker-email",
                    email,
                    "terms",
                ]
            )
            with pytest.raises(script.Refused, match="approver_and_issue"):
                script.command_from(args)
        finally:
            await setup.engine.dispose()

    run(exercise())
