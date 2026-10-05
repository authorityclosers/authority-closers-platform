"""Isolated fictional PostgreSQL proof; no production account or settings are read."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from ac_platform.application.settings import Settings
from ac_platform.audit.models import AuditChainHead, AuditEvent
from ac_platform.audit.service import AuditRepository, verify_audit_chain_sync
from ac_platform.identity.models import EmailChallenge, PasswordCredential, Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.tenancy.learner_provisioning import (
    AsyncLearnerProvisioningApplication,
    LearnerProvisioningError,
)
from ac_platform.tenancy.models import Membership, Tenant
from tests.integration.test_media_delivery_renewal_postgresql import postgres_harness  # noqa: F401
from tests.unit.identity.test_smoke_verification_data_change import arguments, tool


@pytest.fixture
def state(postgres_harness, monkeypatch):  # noqa: F811
    person, other, operations, public = (uuid4() for _ in range(4))
    email = f"fictional-{person}+ac-qa-production@authorityclosers.com"
    now = datetime.now(UTC)
    with Session(postgres_harness.engine) as db, db.begin():
        db.add_all(
            [
                Tenant(id=key, slug=f"fictional-{key}", name="Fictional")
                for key in (operations, public)
            ]
        )
        db.add_all(
            [
                Person(
                    id=person,
                    email=email,
                    first_name="Rowan Fixture",
                    display_name="Rowan Fixture",
                    consent_version="fictional-v1",
                    consented_at=now,
                ),
                Person(id=other, email=f"other-{other}@example.test"),
            ]
        )
        db.flush()
        db.add(PasswordCredential(person_id=person, password_hash=uuid4().hex))
        db.add(
            EmailChallenge(
                person_id=person,
                kind="email_verification",
                token_hash=uuid4().bytes + uuid4().bytes,
                encrypted_token=uuid4().hex,
                issued_at=now,
                expires_at=now + timedelta(days=1),
            )
        )
        db.add(
            IdentitySession(
                person_id=person,
                token_hash=uuid4().bytes + uuid4().bytes,
                created_at=now,
                expires_at=now + timedelta(days=1),
            )
        )
    settings = Settings(
        _env_file=None,
        environment="test",
        operations_tenant_id=operations,
        public_learner_tenant_id=public,
        learner_consent_version="fictional-v1",
    ).model_copy(
        update={
            "environment": "production",
            "release_id": "1" * 40,
            "database_url": postgres_harness.schema_url.render_as_string(hide_password=False),
        }
    )
    monkeypatch.setattr(tool, "_settings", lambda _: settings)
    monkeypatch.setattr(tool, "_email_from_stdin", lambda: email)
    return SimpleNamespace(
        person=person,
        other=other,
        operations=operations,
        public=public,
        email=email,
        settings=settings,
        harness=postgres_harness,
    )


def snapshot(state):
    with state.harness.engine.connect() as connection:
        return {
            model.__tablename__: [tuple(row) for row in connection.execute(select(model.__table__))]
            for model in (
                Person,
                PasswordCredential,
                EmailChallenge,
                IdentitySession,
                Membership,
                Tenant,
                AuditEvent,
                AuditChainHead,
            )
        }


def record_prior_consent(state, version):
    if version is not None:
        with Session(state.harness.engine) as db, db.begin():
            db.get(Person, state.person).consent_version = version


@pytest.mark.asyncio
@pytest.mark.parametrize("named_version", [None, tool.APPROVED_PRIOR_CONSENT_VERSION])
async def test_default_preview_is_read_only_with_no_writes(
    state, capsys, monkeypatch, named_version
):
    record_prior_consent(state, named_version)
    before = snapshot(state)
    original = tool._change

    async def checked(session, *args):
        from sqlalchemy import text

        assert await session.scalar(text("SHOW transaction_read_only")) == "on"
        return await original(session, *args)

    monkeypatch.setattr(tool, "_change", checked)
    assert await tool._run(arguments(state.person, consent_version=named_version)) == 0
    output = capsys.readouterr().out
    report = json.loads(output)
    assert report["mode"] == "dry_run"
    assert report["before"] == {
        "email_verified": False,
        "revision": 0,
        "learner_membership": "absent",
    }
    assert report["after"] == {
        "email_verified": True,
        "revision": 1,
        "learner_membership": "planned",
    }
    assert report["audit_tenant_id"] == str(state.operations)
    assert report["consent"] == {
        "recorded_version": named_version or "fictional-v1",
        "configured_version": "fictional-v1",
        "named_prior_version": named_version,
    }
    assert state.email not in output
    assert snapshot(state) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("existing_membership", [False, True])
@pytest.mark.parametrize("named_version", [None, tool.APPROVED_PRIOR_CONSENT_VERSION])
async def test_first_apply_audits_once_and_replay_preserves_timestamp(
    state, capsys, existing_membership, named_version
):
    record_prior_consent(state, named_version)
    if existing_membership:
        with Session(state.harness.engine) as db, db.begin():
            db.add(Membership(person_id=state.person, tenant_id=state.public, role="learner"))
    before = snapshot(state)
    with Session(state.harness.engine) as db:
        person = db.get(Person, state.person)
        recorded_consent = (person.consent_version, person.consented_at)
    args = arguments(state.person, apply=True, consent_version=named_version)
    assert await tool._run(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "applied"
    applied = snapshot(state)
    for table in ("password_credentials", "email_challenges", "sessions", "tenants"):
        assert applied[table] == before[table]
    if existing_membership:
        assert applied["memberships"] == before["memberships"]
    with Session(state.harness.engine) as db:
        membership = db.scalars(
            select(Membership).where(Membership.person_id == state.person)
        ).one()
        assert (membership.person_id, membership.tenant_id, membership.role, membership.status) == (
            state.person,
            state.public,
            "learner",
            "active",
        )
        person = db.get(Person, state.person)
        assert (person.consent_version, person.consented_at) == recorded_consent
        timestamp = person.email_verified_at
        assert timestamp is not None and person.revision == 1
        assert db.get(Person, state.other).email_verified_at is None
        audit = db.scalar(select(AuditEvent).where(AuditEvent.request_id == str(args.command_id)))
        assert audit.actor_type == "operator" and audit.actor_person_id is None
        expected_intent = {
            "person_id": str(state.person),
            "email_verified": True,
            "learner_tenant_id": str(state.public),
            "required_consent_version": named_version or "fictional-v1",
            **report["attribution"],
        }
        if named_version is not None:
            expected_intent.update(
                named_prior_consent_version=named_version,
                configured_consent_version="fictional-v1",
            )
        assert audit.payload["intent"] == expected_intent
        assert (
            audit.payload["consent"]
            == report["consent"]
            == {
                "recorded_version": named_version or "fictional-v1",
                "configured_version": "fictional-v1",
                "named_prior_version": named_version,
            }
        )
        assert audit.payload["before"] == {
            "email_verified": False,
            "revision": 0,
            "email_verified_at": None,
            "learner_membership": "present" if existing_membership else "absent",
        }
        assert audit.payload["after"]["learner_membership"] == "present"
        assert report["after"]["learner_membership"] == "present"
        assert datetime.fromisoformat(audit.payload["after"]["email_verified_at"]) == timestamp
        assert tool.OWNER in json.dumps(audit.payload) and "AUT-398" in audit.reason
        assert verify_audit_chain_sync(db, state.operations).valid
    assert await tool._run(args) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "replayed"
    assert snapshot(state) == applied
    assert await tool._run(arguments(state.person, apply=True, consent_version=named_version)) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "already_verified"
    assert snapshot(state) == applied


@pytest.mark.asyncio
async def test_verified_fixture_missing_membership_preserves_timestamp(state, capsys):
    timestamp = datetime.now(UTC) - timedelta(days=1)
    with Session(state.harness.engine) as db, db.begin():
        db.get(Person, state.person).email_verified_at = timestamp
    args = arguments(state.person, apply=True)
    assert await tool._run(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "applied"
    assert report["before"]["learner_membership"] == "absent"
    assert report["after"]["learner_membership"] == "present"
    with Session(state.harness.engine) as db:
        person = db.get(Person, state.person)
        assert person.email_verified_at == timestamp and person.revision == 0
        membership = db.scalars(
            select(Membership).where(Membership.person_id == state.person)
        ).one()
        assert membership.tenant_id == state.public and membership.person_id == state.person
        audit = db.scalars(
            select(AuditEvent).where(AuditEvent.request_id == str(args.command_id))
        ).one()
        assert audit.payload["before"]["email_verified_at"] == timestamp.isoformat()
        assert audit.payload["after"]["email_verified_at"] == timestamp.isoformat()
    applied = snapshot(state)
    assert await tool._run(args) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "replayed"
    assert snapshot(state) == applied


@pytest.mark.asyncio
@pytest.mark.parametrize("apply", [False, True])
@pytest.mark.parametrize(
    "recorded_version,named_version",
    [
        ("fictional-v1", None),
        (tool.APPROVED_PRIOR_CONSENT_VERSION, None),
        ("fictional-other-prior", tool.APPROVED_PRIOR_CONSENT_VERSION),
        ("fictional-v1", tool.APPROVED_PRIOR_CONSENT_VERSION),
        ("fictional-v2", tool.APPROVED_PRIOR_CONSENT_VERSION),
        (tool.APPROVED_PRIOR_CONSENT_VERSION, "fictional-other-prior"),
    ],
)
async def test_consent_version_mismatch_refused_without_writes(
    state, capsys, apply, recorded_version, named_version
):
    record_prior_consent(state, recorded_version)
    state.settings.learner_consent_version = "fictional-v2"
    args = arguments(state.person, apply=apply)
    args.recorded_consent_version = named_version
    before = snapshot(state)
    with pytest.raises(tool.SmokeVerificationError, match="exact configured or explicitly named"):
        await tool._run(args)
    assert snapshot(state) == before
    assert capsys.readouterr().out == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("named_version", [None, tool.APPROVED_PRIOR_CONSENT_VERSION])
async def test_provisioning_failure_rolls_back_verification_and_membership(
    state, monkeypatch, capsys, named_version
):
    record_prior_consent(state, named_version)
    before = snapshot(state)
    original = AsyncLearnerProvisioningApplication.ensure

    async def fail(self, **kwargs):
        await original(self, **kwargs)
        raise LearnerProvisioningError("fictional-private-provisioning-marker")

    monkeypatch.setattr(AsyncLearnerProvisioningApplication, "ensure", fail)
    with pytest.raises(LearnerProvisioningError):
        await tool._run(arguments(state.person, apply=True, consent_version=named_version))
    assert snapshot(state) == before
    assert capsys.readouterr().out == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("named_version", [None, tool.APPROVED_PRIOR_CONSENT_VERSION])
async def test_audit_failure_rolls_back_verification_and_chain(
    state, monkeypatch, capsys, named_version
):
    record_prior_consent(state, named_version)
    before = snapshot(state)
    original = AuditRepository.append

    async def fail(self, **kwargs):
        await original(self, **kwargs)
        raise tool.SmokeVerificationError("fictional failure after audit append")

    monkeypatch.setattr(AuditRepository, "append", fail)
    with pytest.raises(tool.SmokeVerificationError):
        await tool._run(arguments(state.person, apply=True, consent_version=named_version))
    assert snapshot(state) == before
    assert capsys.readouterr().out == ""


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid",
    [
        "pin",
        "absent",
        "inactive",
        "name",
        "consent",
        "credential",
        "privileged",
        "wrong_tenant",
        "inactive_tenant",
    ],
)
async def test_unexpected_targets_fail_closed_without_writes(state, monkeypatch, invalid, capsys):
    args = arguments(state.person, apply=True)
    with Session(state.harness.engine) as db, db.begin():
        person = db.get(Person, state.person)
        if invalid == "pin":
            args.person_id = state.other
        elif invalid == "absent":
            monkeypatch.setattr(
                tool, "_email_from_stdin", lambda: "absent+ac-qa-production@authorityclosers.com"
            )
        elif invalid == "inactive":
            person.status = "suspended"
        elif invalid == "name":
            person.display_name = "Unexpected Fixture"
        elif invalid == "consent":
            person.consented_at = None
        elif invalid == "credential":
            db.delete(
                db.scalar(
                    select(PasswordCredential).where(PasswordCredential.person_id == state.person)
                )
            )
        elif invalid in ("privileged", "wrong_tenant"):
            db.add(
                Membership(
                    person_id=state.person,
                    tenant_id=state.public if invalid == "privileged" else state.operations,
                    role="admin" if invalid == "privileged" else "learner",
                )
            )
        else:
            db.get(Tenant, state.operations).status = "suspended"
    before = snapshot(state)
    with pytest.raises(tool.SmokeVerificationError):
        await tool._run(args)
    assert snapshot(state) == before
    assert capsys.readouterr().out == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["operator_reference", "run_reference", "person_id"])
async def test_command_conflicts_fail_closed(state, field, capsys):
    args = arguments(state.person, apply=True)
    await tool._run(args)
    capsys.readouterr()
    setattr(args, field, uuid4())
    before = snapshot(state)
    with pytest.raises(tool.SmokeVerificationError):
        await tool._run(args)
    assert snapshot(state) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("named_version", [None, tool.APPROVED_PRIOR_CONSENT_VERSION])
async def test_concurrent_apply_serializes_one_update_and_one_audit(state, capsys, named_version):
    record_prior_consent(state, named_version)
    args = arguments(state.person, apply=True, consent_version=named_version)
    await asyncio.wait_for(asyncio.gather(tool._run(args), tool._run(args)), timeout=15)
    reports = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert sorted(row["status"] for row in reports) == ["applied", "replayed"]
    with Session(state.harness.engine) as db:
        assert (
            len(
                list(
                    db.scalars(
                        select(AuditEvent).where(AuditEvent.resource_id == str(state.person))
                    )
                )
            )
            == 1
        )
        assert db.get(Person, state.person).revision == 1
        membership = db.scalars(
            select(Membership).where(Membership.person_id == state.person)
        ).one()
        assert (membership.person_id, membership.tenant_id, membership.role, membership.status) == (
            state.person,
            state.public,
            "learner",
            "active",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", ["configured_version", "named_version"])
async def test_named_prior_command_conflicts_preserve_audit_history(state, capsys, changed):
    record_prior_consent(state, tool.APPROVED_PRIOR_CONSENT_VERSION)
    args = arguments(state.person, apply=True, consent_version=tool.APPROVED_PRIOR_CONSENT_VERSION)
    await tool._run(args)
    capsys.readouterr()
    if changed == "configured_version":
        state.settings.learner_consent_version = "fictional-v2"
    else:
        state.settings.learner_consent_version = tool.APPROVED_PRIOR_CONSENT_VERSION
        args.recorded_consent_version = None
    before = snapshot(state)
    with pytest.raises(tool.SmokeVerificationError, match="conflicting intent"):
        await tool._run(args)
    assert snapshot(state) == before
    assert capsys.readouterr().out == ""
