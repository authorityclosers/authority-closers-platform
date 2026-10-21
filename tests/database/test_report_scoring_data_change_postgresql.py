"""scripts/data-changes/report-scoring.py on PostgreSQL: Report settings' own version and
choice for our own company's workspace only, dry run by default, idempotent, audited with
the approval. Fictional fixture only."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from ac_platform.audit.models import AuditEvent
from ac_platform.conversation_intelligence.report_settings_admin import ReportSettingsStore
from tests.database.test_conversation_authority_postgresql import _setup
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_worker_postgresql import _postgres_harness

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "report_scoring", ROOT / "scripts/data-changes/report-scoring.py"
)
assert _spec is not None and _spec.loader is not None
script = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = script  # its dataclasses look themselves up here
_spec.loader.exec_module(script)

WORDS = "Orchestrator, 21 Oct 2026: Brain 4.0 beta in Report settings for AC's own organisation"


@pytest.fixture
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


async def company_workspace(db: Any, domain: str, *, verified: bool = True) -> UUID:
    from ac_platform.tenancy.models import Organisation, OrganisationDomainSetting, Tenant

    tenant = uuid4()
    db.add(Tenant(id=tenant, slug=f"fictional-{tenant.hex[:12]}", name="Fictional Closers"))
    await db.flush()
    db.add(
        Organisation(
            tenant_id=tenant,
            creation_command_id=uuid4(),
            domain_verification_token="t" * 43,
        )
    )
    await db.flush()
    db.add(
        OrganisationDomainSetting(
            tenant_id=tenant,
            version=1,
            verified_domains=[domain] if verified else [],
            auto_join=False,
            proof={},
            command_id=uuid4(),
        )
    )
    await db.flush()
    return tenant


def test_brain4_beta_is_chosen_for_our_own_workspace_only(
    postgres_harness: Any, tmp_path: Any
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            from ac_platform.identity.models import Person

            async with setup.sessions() as db, db.begin():
                email = (await db.get(Person, setup.actor.person_id)).email
                ours = await company_workspace(db, email.rsplit("@", 1)[1].lower())
                customer = await company_workspace(db, "customer.example.test")
            ops = setup.prepared.state.tenant_id

            async def do(scoring: str, *, apply: bool, **changes: Any) -> Any:
                command = script.Command(
                    **{
                        "environment": "test",
                        "control_email": email,
                        "scoring": scoring,
                        "approver": "Suyash Kulkarni (owner, relayed)",
                        "issue": "brain4-ac-sval",
                        "reason": WORDS,
                        "apply": apply,
                        **changes,
                    }
                )
                async with setup.sessions() as db:
                    transaction = await db.begin()
                    try:
                        result = await script.execute(db, command, operations_tenant_id=ops)
                    except BaseException:
                        await transaction.rollback()
                        raise
                    if apply and result["status"] == "applied":
                        await transaction.commit()
                    else:
                        await transaction.rollback()
                    return result

            async def scoring(tenant: UUID) -> str:
                async with setup.sessions() as db:
                    effective = await ReportSettingsStore(db).effective(tenant)
                return str(effective["settings"]["report"]["scoring"])

            dry = await do("brain4_beta", apply=False)
            assert dry["status"] == "dry_run"
            assert dry["workspace"] == {
                "tenant_id": str(ours),
                "name": "Fictional Closers",
                "kind": "company",
            }
            assert dry["before"]["scoring"] == "classic"
            assert dry["after"]["scoring"] == "brain4_beta" and dry["after"]["version_created"]
            assert await scoring(ours) == "classic"
            applied = await do("brain4_beta", apply=True)
            assert applied["status"] == "applied" and applied["after"]["source"] == "organisation"
            assert await scoring(ours) == "brain4_beta"
            assert await scoring(customer) == "classic"
            assert (await do("brain4_beta", apply=True))["status"] == "no_op"
            back = await do("classic", apply=True)
            assert back["status"] == "applied" and not back["after"]["version_created"]
            assert await scoring(ours) == "classic"

            with pytest.raises(script.Refused, match="scoring_must_be"):
                await do("graded", apply=True)
            with pytest.raises(script.Refused, match="not_our_own_company"):
                await do("brain4_beta", apply=True, tenant_id=customer)
            with pytest.raises(script.Refused, match="control_account"):
                await do("brain4_beta", apply=True, control_email="someone@example.test")

            async with setup.sessions() as db:
                events = (
                    await db.scalars(
                        select(AuditEvent)
                        .where(AuditEvent.action == script.CHOSEN)
                        .order_by(AuditEvent.sequence_no)
                    )
                ).all()
            assert len(events) == 2
            first = events[0]
            assert first.actor_person_id == setup.actor.person_id
            assert first.payload["tenant_id"] == str(ours)
            assert first.payload["approval"] == {
                "approver": "Suyash Kulkarni (owner, relayed)",
                "issue": "brain4-ac-sval",
                "data_change": script.DATA_CHANGE,
                "operator": script.OPERATOR,
            }
            assert first.payload["after"]["scoring"] == "brain4_beta"
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_the_cli_takes_only_its_own_arguments() -> None:
    with pytest.raises(SystemExit):
        script.main(["--environment", "test", "--bogus"])
    args = ["--environment", "test", "--control-email", "x@y", "--scoring", "graded"]
    args += ["--approver", "a", "--issue", "i", "--reason", "r"]
    assert script.main(args) == 2
