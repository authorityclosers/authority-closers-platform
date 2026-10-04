"""Fictional relational evidence for AUT-828, including the CLI transaction boundary."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, Never, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from ac_platform.application.settings import Settings
from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import AuditRepository, verify_audit_chain_sync
from ac_platform.authorization import operator_data_change as tool
from ac_platform.authorization.application import CapabilityApplication
from ac_platform.authorization.models import CapabilityGrant
from ac_platform.authorization.policy import CapabilityDenied
from ac_platform.db.models import model_metadata
from ac_platform.identity.models import PasswordCredential, Person, ProviderIdentity
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.kernel.authz import ActorContext
from ac_platform.tenancy.models import Membership, Tenant
from tests.unit.authorization.test_capability_cli import Database


@pytest.fixture
def state(monkeypatch: pytest.MonkeyPatch) -> Iterator[SimpleNamespace]:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def foreign_keys(connection: Any, _record: Any) -> None:
        connection.execute("PRAGMA foreign_keys=ON")

    model_metadata().create_all(engine)
    owner = UUID("11111111-1111-4111-8111-111111111111")
    operations = UUID("22222222-2222-4222-8222-222222222222")
    manager, academy, session_id = uuid4(), uuid4(), uuid4()
    now = datetime.now(UTC)
    with Session(engine) as db, db.begin():
        db.add_all(
            [
                Tenant(id=operations, slug="fictional-operations", name="Fictional operations"),
                Tenant(id=academy, slug="fictional-academy", name="Fictional academy"),
                Person(id=owner, email="owner@example.test", email_verified_at=now),
                Person(id=manager, email="manager@example.test", email_verified_at=now),
            ]
        )
        db.flush()
        db.add_all(
            [
                ProviderIdentity(
                    person_id=owner,
                    issuer="https://provider.example.test",
                    subject="fictional-owner",
                ),
                ProviderIdentity(
                    person_id=manager,
                    issuer="https://provider.example.test",
                    subject="fictional-manager",
                ),
                Membership(tenant_id=operations, person_id=manager, role="owner"),
                Membership(tenant_id=academy, person_id=owner, role="learner"),
                PasswordCredential(person_id=owner, password_hash="fictional-verifier"),  # noqa: S106 - fictional verifier
            ]
        )
        db.flush()
        db.add(
            IdentitySession(
                id=session_id,
                person_id=owner,
                token_hash=b"x" * 32,
                created_at=now,
                expires_at=now + timedelta(hours=1),
                selected_tenant_id=academy,
            )
        )
    settings = Settings(_env_file=None, environment="test", operations_tenant_id=operations)

    async def dispose() -> None:
        pass

    # Keep the real _run transaction/rollback path, replacing only its DB driver.
    monkeypatch.setattr(
        tool, "create_async_engine", lambda *_a, **_kw: SimpleNamespace(dispose=dispose)
    )
    monkeypatch.setattr(
        tool, "async_sessionmaker", lambda *_a, **_kw: lambda: Database(Session(engine))
    )
    monkeypatch.setattr(tool, "Settings", lambda **_kw: settings)
    yield SimpleNamespace(
        engine=engine,
        owner=owner,
        manager=manager,
        operations=operations,
        academy=academy,
        session_id=session_id,
        settings=settings,
    )
    engine.dispose()


def command(**overrides: Any) -> tool.Command:
    values: dict[str, Any] = dict(
        action="add-operations-owner",
        environment="test",
        allow_production=False,
        email="owner@example.test",
        command_id=UUID("33333333-3333-4333-8333-333333333333"),
        approver="fictional-approver",
        issue="AUT-828",
        reason="Approved fictional fixture",
        apply=False,
    )
    values.update(overrides)
    return tool.Command(**values)


def snapshot(state: SimpleNamespace) -> dict[str, list[tuple[Any, ...]]]:
    with state.engine.connect() as connection:
        return {
            table.name: list(connection.execute(select(table)).tuples())
            for table in model_metadata().sorted_tables
        }


async def prepare_grant(state: SimpleNamespace) -> None:
    await tool._run(state.settings, command(apply=True))
    with Session(state.engine) as db, db.begin():
        app = CapabilityApplication(
            cast(AsyncSession, Database(db)), operations_tenant_id=state.operations
        )
        await app.bootstrap_first_manager(
            person_id=state.manager, command_id=uuid4(), reason="Fictional first manager"
        )


def grant_command(**overrides: Any) -> tool.Command:
    return command(
        **{
            "action": "grant-platform-capability",
            "permission": "platform_release_manage",
            "command_id": UUID("44444444-4444-4444-8444-444444444444"),
            **overrides,
        }
    )


async def test_owner_dry_run_apply_replay_and_no_side_effects(state: SimpleNamespace) -> None:
    before = snapshot(state)
    preview = await tool._run(state.settings, command())
    assert snapshot(state) == before
    assert preview["status"] == "dry_run"
    assert preview["before"] is None
    assert preview["after"] == {"role": "owner", "status": "active"}
    assert preview["capability_history_exists"] is False
    applied = await tool._run(state.settings, command(apply=True))
    assert applied == {**preview, "status": "applied"}
    after = snapshot(state)
    assert {name for name in before if before[name] != after[name]} == {
        "memberships",
        "audit_events",
        "audit_chain_heads",
    }
    with Session(state.engine) as db:
        member = db.get(Membership, (state.operations, state.owner))
        assert member is not None and member.role == "owner" and member.status == "active"
        audit = db.get(AuditEvent, command().command_id)
        assert audit is not None
        assert audit.actor_type == "operator_data_change"
        assert audit.actor_person_id is None and audit.session_id is None
        assert audit.payload == {
            "approver": "fictional-approver",
            "issue": "AUT-828",
            "environment": "test",
            "command_id": str(command().command_id),
            "subject_person_id": str(state.owner),
            "tenant_id": str(state.operations),
            "role": "owner",
        }
        assert verify_audit_chain_sync(db, state.operations).valid
    replay = await tool._run(state.settings, command(apply=True))
    assert replay["no_op"] is True and snapshot(state) == after
    await tool._run(state.settings, replace(command(apply=True), command_id=uuid4()))
    assert snapshot(state) == after
    print("owner dry-run:", json.dumps(preview, sort_keys=True))
    print("owner apply:", json.dumps(applied, sort_keys=True))


@pytest.mark.parametrize(
    "field,value", [("approver", "other"), ("issue", "AUT-529"), ("reason", "Another intent")]
)
async def test_owner_conflicting_replay_zero_writes(
    state: SimpleNamespace, field: str, value: str
) -> None:
    await tool._run(state.settings, command(apply=True))
    before = snapshot(state)
    with pytest.raises(tool.DataChangeRefused, match="intent"):
        await tool._run(state.settings, replace(command(apply=True), **{field: value}))
    assert snapshot(state) == before


@pytest.mark.parametrize(
    "mode",
    [
        "missing_tenant",
        "inactive_tenant",
        "missing_person",
        "unverified",
        "suspended",
        "no_provider",
        "two_matches",
        "non_owner",
        "inactive_owner",
    ],
)
@pytest.mark.parametrize("apply", [False, True])
async def test_invalid_owner_refused_without_writes(
    state: SimpleNamespace, mode: str, apply: bool
) -> None:
    with Session(state.engine) as db, db.begin():
        if mode == "missing_tenant":
            state.settings = state.settings.model_copy(update={"operations_tenant_id": uuid4()})
        elif mode == "inactive_tenant":
            db.get(Tenant, state.operations).status = "suspended"
        elif mode == "missing_person":
            db.get(Person, state.owner).email = "other@example.test"
        elif mode == "unverified":
            db.get(Person, state.owner).email_verified_at = None
        elif mode == "suspended":
            db.get(Person, state.owner).status = "suspended"
        elif mode == "no_provider":
            db.delete(
                db.scalar(select(ProviderIdentity).where(ProviderIdentity.person_id == state.owner))
            )
        elif mode == "two_matches":
            # The production index prevents duplicates; also prove fail-closed resolution
            # against historical/corrupt ambiguity without weakening production models.
            db.execute(text("DROP INDEX uq_persons_email_ci"))
            db.add(Person(email="OWNER@example.test", email_verified_at=datetime.now(UTC)))
        else:
            db.add(
                Membership(
                    tenant_id=state.operations,
                    person_id=state.owner,
                    role="member" if mode == "non_owner" else "owner",
                    status="active" if mode == "non_owner" else "inactive",
                    ended_at=None if mode == "non_owner" else datetime.now(UTC),
                )
            )
    before = snapshot(state)
    with pytest.raises((tool.DataChangeRefused, CapabilityDenied)):
        await tool._run(state.settings, command(apply=apply))
    assert snapshot(state) == before


async def test_grant_preview_apply_replay_and_existing_no_op(state: SimpleNamespace) -> None:
    await prepare_grant(state)
    before = snapshot(state)
    preview = await tool._run(state.settings, grant_command())
    assert preview["status"] == "dry_run" and preview["before"] == []
    assert preview["after"] == ["platform_release_manage"]
    assert preview["active_platform_permissions"] == []
    assert snapshot(state) == before
    result = await tool._run(state.settings, grant_command(apply=True))
    assert result["status"] == "applied"
    assert result["active_platform_permissions"] == ["platform_release_manage"]
    after = snapshot(state)
    assert {name for name in before if before[name] != after[name]} == {
        "capability_grants",
        "audit_events",
        "audit_chain_heads",
    }
    with Session(state.engine) as db:
        row = db.get(CapabilityGrant, grant_command().command_id)
        assert row is not None and row.granted_by_person_id == state.owner
        audit = db.get(AuditEvent, row.audit_event_id)
        assert audit is not None and audit.actor_type == "operator_data_change"
        assert audit.actor_person_id is None and audit.session_id is None
        assert audit.payload == {
            "approver": "fictional-approver",
            "issue": "AUT-828",
            "environment": "test",
            "command_id": str(grant_command().command_id),
            "subject_person_id": str(state.owner),
            "permission": "platform_release_manage",
            "scope_kind": "platform",
            "tenant_id": None,
            "program_id": None,
        }
        assert verify_audit_chain_sync(db, state.operations).valid
    replay = await tool._run(state.settings, grant_command(apply=True))
    assert replay["status"] == "no_op" and snapshot(state) == after
    fresh = replace(grant_command(apply=True), command_id=uuid4())
    assert (await tool._run(state.settings, fresh))["grant_id"] == result["grant_id"]
    assert snapshot(state) == after
    assert (await tool._run(state.settings, command()))["capability_history_exists"] is True


@pytest.mark.parametrize(
    "field,value",
    [
        ("approver", "other"),
        ("issue", "AUT-529"),
        ("reason", "Another intent"),
        ("email", "manager@example.test"),
    ],
)
async def test_grant_conflicting_replay_zero_writes(
    state: SimpleNamespace, field: str, value: str
) -> None:
    await prepare_grant(state)
    await tool._run(state.settings, grant_command(apply=True))
    before = snapshot(state)
    with pytest.raises(tool.DataChangeRefused, match="intent|attribution"):
        await tool._run(state.settings, replace(grant_command(apply=True), **{field: value}))
    assert snapshot(state) == before


@pytest.mark.parametrize(
    "mode",
    ["no_owner", "non_owner", "no_manager", "revoked_manager", "access_manage", "other_permission"],
)
async def test_grant_refusals_zero_writes(state: SimpleNamespace, mode: str) -> None:
    if mode == "no_owner":
        pass
    elif mode == "no_manager":
        await tool._run(state.settings, command(apply=True))
    else:
        await prepare_grant(state)
        with Session(state.engine) as db, db.begin():
            if mode == "non_owner":
                db.get(Membership, (state.operations, state.owner)).role = "member"
            elif mode == "revoked_manager":
                app = CapabilityApplication(
                    cast(AsyncSession, Database(db)), operations_tenant_id=state.operations
                )
                session = db.get(IdentitySession, state.session_id)
                session.selected_tenant_id = None
                session.person_id = state.manager
                db.flush()
                grant = db.scalar(select(CapabilityGrant))
                await app.revoke(
                    ActorContext(state.manager, state.session_id, None),
                    command_id=uuid4(),
                    grant_id=grant.id,
                    reason="Fictional retirement",
                )
    cmd = grant_command(apply=True)
    if mode in {"access_manage", "other_permission"}:
        cmd = replace(
            cmd, permission="platform_access_manage" if mode == "access_manage" else "catalog_read"
        )
    before = snapshot(state)
    with pytest.raises(tool.DataChangeRefused):
        await tool._run(state.settings, cmd)
    assert snapshot(state) == before


async def test_revoked_replay_does_not_reactivate_and_fresh_id_appends(
    state: SimpleNamespace,
) -> None:
    await prepare_grant(state)
    await tool._run(state.settings, grant_command(apply=True))
    with Session(state.engine) as db, db.begin():
        session = db.get(IdentitySession, state.session_id)
        session.selected_tenant_id = None
        session.person_id = state.manager
        db.flush()
        app = CapabilityApplication(
            cast(AsyncSession, Database(db)), operations_tenant_id=state.operations
        )
        await app.revoke(
            ActorContext(state.manager, state.session_id, None),
            command_id=uuid4(),
            grant_id=grant_command().command_id,
            reason="Fictional release retirement",
        )
    before = snapshot(state)
    replay = await tool._run(state.settings, grant_command(apply=True))
    assert replay["status"] == "no_op" and replay["active_platform_permissions"] == []
    assert snapshot(state) == before
    fresh = replace(grant_command(apply=True), command_id=uuid4())
    assert (await tool._run(state.settings, fresh))["status"] == "applied"
    assert len(snapshot(state)["capability_grants"]) == len(before["capability_grants"]) + 1
    assert snapshot(state)["capability_revocations"] == before["capability_revocations"]


@pytest.mark.parametrize("factory", [command, grant_command])
@pytest.mark.parametrize("mode", ["environment_mismatch", "production_guard"])
async def test_environment_guards_before_connection(
    state: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, factory: Any, mode: str
) -> None:
    def no_connection(*args: Any, **kwargs: Any) -> Never:
        pytest.fail("guard must refuse before opening a database connection")

    monkeypatch.setattr(tool, "create_async_engine", no_connection)
    cmd = factory(environment="production", apply=True)
    settings = (
        state.settings
        if mode == "environment_mismatch"
        else state.settings.model_copy(update={"environment": "production"})
    )
    before = snapshot(state)
    with pytest.raises(tool.DataChangeRefused):
        await tool._run(settings, cmd)
    assert snapshot(state) == before


@pytest.mark.parametrize("factory", [command, grant_command])
async def test_failure_after_audit_rolls_back_all_writes(
    state: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, factory: Any
) -> None:
    if factory is grant_command:
        await prepare_grant(state)
    original = AuditRepository.append

    async def fail_after_append(*args: Any, **kwargs: Any) -> None:
        await original(*args, **kwargs)
        raise RuntimeError("fictional failure after audit")

    monkeypatch.setattr(AuditRepository, "append", fail_after_append)
    before = snapshot(state)
    with pytest.raises(RuntimeError, match="fictional failure"):
        await tool._run(state.settings, factory(apply=True))
    assert snapshot(state) == before


@pytest.mark.parametrize("source,target", [(command, grant_command), (grant_command, command)])
async def test_command_id_cross_mode_conflicts(
    state: SimpleNamespace, source: Any, target: Any
) -> None:
    await prepare_grant(state)
    if source is grant_command:
        await tool._run(state.settings, grant_command(apply=True))
    before = snapshot(state)
    cmd = replace(target(apply=True), command_id=source().command_id)
    with pytest.raises(tool.DataChangeRefused):
        await tool._run(state.settings, cmd)
    assert snapshot(state) == before


def test_cli_outputs_and_error_containment(
    state: SimpleNamespace, capsys: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    args = [
        "add-operations-owner",
        "--environment",
        "test",
        "--email",
        "owner@example.test",
        "--command-id",
        str(command().command_id),
        "--approver",
        "fictional-approver",
        "--issue",
        "AUT-828",
        "--reason",
        "Approved fictional fixture",
    ]
    assert tool.main(args) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "dry_run"
    assert tool.main([*args, "--apply"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "applied"
    assert tool.main([*args, "--token", "fictional-value-never-printed"]) == 2
    output = capsys.readouterr()
    assert not output.out and "fictional-value-never-printed" not in output.err

    async def failing(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("fictional-driver-secret-never-printed other@example.test")

    monkeypatch.setattr(tool, "_run", failing)
    assert tool.main(args) == 2
    output = capsys.readouterr()
    assert not output.out and "other@example.test" not in output.err
    assert "fictional-driver-secret-never-printed" not in output.err
