"""Fictional local PostgreSQL proof for preview, apply, replay and atomic refusal."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from ac_platform.application.settings import Settings
from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain_sync
from ac_platform.identity.models import Person
from ac_platform.organisations.service import OrganisationCommandError, OrganisationService
from ac_platform.tenancy.models import Membership, Organisation, OrganisationInvite, Tenant
from tests.integration.test_media_delivery_renewal_postgresql import postgres_harness  # noqa: F401
from tests.unit.organisations.test_membership_data_change import arguments, tool


@pytest.fixture
def state(postgres_harness, monkeypatch):  # noqa: F811
    owner, worker, second, unverified, inactive, tenant, operations, public = (
        uuid4() for _ in range(8)
    )
    now = datetime.now(UTC)
    people = {
        key: f"{name}-{key}@example.test"
        for name, key in [
            ("owner", owner),
            ("worker", worker),
            ("second", second),
            ("unverified", unverified),
            ("inactive", inactive),
        ]
    }
    with Session(postgres_harness.engine) as db, db.begin():
        db.add_all(
            [
                Tenant(id=key, slug=f"fictional-{key}", name="Fictional Team")
                for key in (tenant, operations, public)
            ]
        )
        db.add_all(
            [
                Person(
                    id=key,
                    email=email,
                    email_verified_at=None if key == unverified else now,
                    status="suspended" if key == inactive else "active",
                )
                for key, email in people.items()
            ]
        )
        db.flush()
        # Registry rows for protected tenants test the wrapper's explicit guard.
        db.add_all(
            [
                Organisation(
                    tenant_id=key,
                    created_by_person_id=owner,
                    creation_command_id=uuid4(),
                    domain_verification_token="fictional-fixture-" + uuid4().hex,
                )
                for key in (tenant, operations, public)
            ]
        )
        db.add(Membership(tenant_id=tenant, person_id=owner, role="owner"))
    settings = Settings(
        _env_file=None,
        environment="test",
        operations_tenant_id=operations,
        public_learner_tenant_id=public,
    ).model_copy(
        update={
            "environment": "staging",
            "release_id": "1" * 40,
            "database_url": postgres_harness.schema_url.render_as_string(hide_password=False),
        }
    )
    monkeypatch.setattr(tool, "_settings", lambda _args: settings)
    return SimpleNamespace(
        owner=owner,
        worker=worker,
        second=second,
        unverified=unverified,
        inactive=inactive,
        tenant=tenant,
        operations=operations,
        public=public,
        people=people,
        settings=settings,
        harness=postgres_harness,
    )


def counts(state):
    with Session(state.harness.engine) as db:
        return tuple(
            db.scalar(
                select(func.count()).select_from(model).where(model.tenant_id == state.tenant)
            )
            for model in (Membership, AuditEvent, OrganisationInvite)
        )


@pytest.mark.asyncio
async def test_default_preview_skips_missing_and_ineligible_without_any_writes(state, capsys):
    before = counts(state)
    args = arguments(
        state.tenant,
        [
            state.people[state.worker],
            "missing@example.test",
            state.unverified,
            state.inactive,
            uuid4(),
        ],
    )
    assert await tool._run(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert [row["status"] for row in report["targets"]] == [
        "eligible",
        "skipped_missing_person",
        "skipped_unverified_person",
        "skipped_inactive_person",
        "skipped_missing_person",
    ]
    assert report["targets"][0]["before"] is None
    assert report["targets"][0]["after"] == {"role": "admin", "status": "active"}
    assert report["mode"] == "dry_run"
    assert counts(state) == before
    assert state.people[state.worker] not in json.dumps(report)


@pytest.mark.asyncio
async def test_apply_has_attributable_audit_and_replay_preserves_history(state, capsys):
    args = arguments(state.tenant, [state.people[state.worker], state.second], apply=True)
    assert await tool._run(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert [row["status"] for row in report["targets"]] == ["applied", "applied"]
    assert counts(state) == (3, 2, 2)
    with Session(state.harness.engine) as db:
        original = list(db.scalars(select(AuditEvent).where(AuditEvent.tenant_id == state.tenant)))
        hashes = [(row.id, row.event_hash) for row in original]
        assert verify_audit_chain_sync(db, state.tenant).valid
        for audit in original:
            assert json.loads(audit.reason) == report["attribution"]
            assert audit.actor_type == "operator"
            assert audit.payload["intent"]["operator_reference"] == "root-operator"
            assert audit.request_id in [str(key) for key in args.command_id]
            assert audit.payload["before"] is None
            assert audit.payload["after"] == {"role": "admin", "status": "active"}
        assert db.get(Membership, (state.tenant, state.owner)).role == "owner"
    assert await tool._run(args) == 0
    assert [row["status"] for row in json.loads(capsys.readouterr().out)["targets"]] == [
        "replayed"
    ] * 2
    assert counts(state) == (3, 2, 2)
    with Session(state.harness.engine) as db:
        assert [
            (row.id, row.event_hash)
            for row in db.scalars(select(AuditEvent).where(AuditEvent.tenant_id == state.tenant))
        ] == hashes
    fresh = arguments(state.tenant, [state.worker, state.second], apply=True)
    assert await tool._run(fresh) == 0
    assert [row["status"] for row in json.loads(capsys.readouterr().out)["targets"]] == [
        "already_correct"
    ] * 2
    assert counts(state) == (3, 2, 2)


@pytest.mark.asyncio
async def test_batch_service_error_rolls_back_memberships_invites_and_audit(
    state, monkeypatch, capsys
):
    original = OrganisationService.add_member
    calls = 0

    async def failing(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        result = await original(self, *args, **kwargs)
        if calls == 2:
            raise OrganisationCommandError("fictional batch failure after audit")
        return result

    monkeypatch.setattr(OrganisationService, "add_member", failing)
    before = counts(state)
    with pytest.raises(OrganisationCommandError, match="batch failure"):
        await tool._run(arguments(state.tenant, [state.worker, state.second], apply=True))
    assert calls == 2
    assert counts(state) == before
    assert capsys.readouterr().out == ""
    with Session(state.harness.engine) as db:
        assert verify_audit_chain_sync(db, state.tenant).valid


@pytest.mark.asyncio
async def test_apply_rechecks_person_after_preview(state, capsys):
    args = arguments(state.tenant, [state.worker])
    await tool._run(args)
    assert json.loads(capsys.readouterr().out)["targets"][0]["status"] == "eligible"
    with Session(state.harness.engine) as db, db.begin():
        db.get(Person, state.worker).email_verified_at = None
    args.apply = True
    before = counts(state)
    await tool._run(args)
    assert (
        json.loads(capsys.readouterr().out)["targets"][0]["status"] == "skipped_unverified_person"
    )
    assert counts(state) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("protected", ["operations", "public", "owner"])
@pytest.mark.parametrize("apply", [False, True])
async def test_protected_targets_refused(state, protected, apply, capsys):
    tenant = state.tenant if protected == "owner" else getattr(state, protected)
    targets = [state.owner] if protected == "owner" else [state.worker]
    before = counts(state)
    with pytest.raises(OrganisationCommandError, match="refused"):
        await tool._run(arguments(tenant, targets, apply=apply))
    assert counts(state) == before
    assert capsys.readouterr().out == ""


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field", ["role", "approver", "issue_reference", "operator_reference", "run_reference"]
)
async def test_command_reuse_cannot_change_intent_or_attribution(state, field, capsys):
    args = arguments(state.tenant, [state.worker], apply=True)
    await tool._run(args)
    capsys.readouterr()
    setattr(
        args,
        field,
        "member" if field == "role" else uuid4() if field == "run_reference" else "changed",
    )
    before = counts(state)
    with pytest.raises(OrganisationCommandError, match="different intent or attribution"):
        await tool._run(args)
    assert counts(state) == before


@pytest.mark.asyncio
async def test_duplicate_person_resolved_by_email_and_id_rolls_back(state):
    before = counts(state)
    with pytest.raises(OrganisationCommandError, match="same person"):
        await tool._run(
            arguments(state.tenant, [state.worker, state.people[state.worker]], apply=True)
        )
    assert counts(state) == before


@pytest.mark.asyncio
async def test_reactivation_records_before_after_and_skips_ineligible_targets(
    state, capsys, monkeypatch
):
    with Session(state.harness.engine) as db, db.begin():
        db.add(
            Membership(
                tenant_id=state.tenant,
                person_id=state.worker,
                role="member",
                status="inactive",
                ended_at=datetime.now(UTC),
            )
        )
    monkeypatch.setenv("AC_FICTIONAL_CONTAINMENT_MARKER", "fictional-env-value-never-printed")
    args = arguments(
        state.tenant, [state.worker, "absent@example.test", state.unverified], apply=True
    )
    await tool._run(args)
    output = capsys.readouterr().out
    assert "fictional-env-value-never-printed" not in output
    assert state.settings.database_url not in output
    report = json.loads(output)
    assert [row["status"] for row in report["targets"]] == [
        "applied",
        "skipped_missing_person",
        "skipped_unverified_person",
    ]
    with Session(state.harness.engine) as db:
        member = db.get(Membership, (state.tenant, state.worker))
        assert (member.role, member.status, member.ended_at, member.revision) == (
            "admin",
            "active",
            None,
            1,
        )
        audit = db.scalar(
            select(AuditEvent).where(AuditEvent.request_id == str(args.command_id[0]))
        )
        assert audit.payload["before"] == {"role": "member", "status": "inactive"}
        assert audit.payload["after"] == {"role": "admin", "status": "active"}
    assert counts(state) == (2, 1, 1)


@pytest.mark.asyncio
async def test_concurrent_apply_serializes_and_never_duplicates_effect(state):
    engine = create_async_engine(state.settings.database_url, hide_parameters=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    args = arguments(state.tenant, [state.worker], apply=True)

    async def apply():
        async with sessions() as db, db.begin():
            return await tool._batch(db, state.settings, args)

    try:
        results = await asyncio.wait_for(asyncio.gather(apply(), apply()), timeout=15)
        assert sorted(row["targets"][0]["status"] for row in results) == ["applied", "replayed"]
        assert counts(state) == (2, 1, 1)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["unregistered", "suspended", "no_owner", "two_owners"])
async def test_invalid_organisation_state_is_refused(state, invalid):
    with Session(state.harness.engine) as db, db.begin():
        if invalid == "unregistered":
            tenant_id = uuid4()
            db.add(Tenant(id=tenant_id, slug=f"unregistered-{tenant_id}", name="Fictional"))
        elif invalid == "suspended":
            db.get(Tenant, state.tenant).status = "suspended"
        elif invalid == "no_owner":
            db.get(Membership, (state.tenant, state.owner)).role = "member"
        else:
            db.add(Membership(tenant_id=state.tenant, person_id=state.second, role="owner"))
    before = counts(state)
    with pytest.raises(OrganisationCommandError):
        await tool._run(
            arguments(
                tenant_id if invalid == "unregistered" else state.tenant, [state.worker], apply=True
            )
        )
    assert counts(state) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["duplicate_target", "duplicate_command", "missing_command"])
async def test_invalid_batch_shape_is_refused_without_writes(state, invalid):
    args = arguments(state.tenant, [state.worker, state.second], apply=True)
    if invalid == "duplicate_target":
        args.target[1] = args.target[0]
    elif invalid == "duplicate_command":
        args.command_id[1] = args.command_id[0]
    else:
        args.command_id.pop()
    before = counts(state)
    with pytest.raises(OrganisationCommandError, match="unique"):
        await tool._run(args)
    assert counts(state) == before
