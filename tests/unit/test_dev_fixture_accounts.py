"""Development fixture accounts: target guard, secrets handling and idempotence."""

from __future__ import annotations

import json
import os
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from ac_platform.application.settings import Settings
from ac_platform.authorization.models import CapabilityGrant
from ac_platform.development import sales_xray_fixture_accounts as fixture
from ac_platform.development.sales_xray_fixture_accounts import (
    ACCOUNTS,
    FIXTURE_PHONE,
    PASSWORD_VARIABLES,
    fixture_passwords,
    require_development_target,
    seed_fixture_accounts,
)
from ac_platform.identity.models import EmailChallenge, Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.identity.password_auth import PasswordIdentityService
from ac_platform.outbox.models import OutboxEvent
from ac_platform.tenancy.models import Membership, Tenant
from tests.unit.test_local_platform_seed import empty_database  # noqa: F401 - fixture

DEV_URL = "postgresql+psycopg://ac_runtime:unused@172.27.0.2:5432/ac_platform"
SECRET = "test-fixture-email-key-at-least-32-bytes"  # noqa: S105 - isolated test input
CONSENT = "sales-xray-consent-test-v1"
PASSWORDS = {kind: f"fictional-{kind}-password-only" for kind in ACCOUNTS}
PUBLIC_TENANT = uuid4()


def dev_settings(**updates):
    # CI runs with its own AC_* environment; this exercises the dev boundary only.
    return Settings(_env_file=None, environment="local").model_copy(
        update={"environment": "development", "database_url": DEV_URL, **updates}
    )


@pytest.fixture(autouse=True)
def no_libpq_overrides(monkeypatch):
    for name in [name for name in os.environ if name.upper().startswith("PG")]:
        monkeypatch.delenv(name)


def test_exact_development_target_requires_acknowledgement():
    require_development_target(dev_settings(), acknowledged=True)
    with pytest.raises(ValueError):
        require_development_target(dev_settings(), acknowledged=False)


@pytest.mark.parametrize(
    "updates",
    [
        {"environment": "local"},
        {"environment": "test"},
        {"environment": "staging"},
        {"environment": "production"},
        # Staging/production compose endpoints use the same database name.
        {"database_url": "postgresql+psycopg://ac_runtime@postgres:5432/ac_platform"},
        {"database_url": "postgresql+psycopg://ac_runtime@db.staging.internal/ac_platform"},
        {"database_url": "postgresql+psycopg://ac_runtime@127.0.0.1:55432/ac_platform"},
        {"database_url": "postgresql+psycopg://ac_runtime@127.0.0.1:55432/ac_local_sandbox"},
        {"database_url": "postgresql+psycopg://ac_runtime@172.27.0.2:5433/ac_platform"},
        {"database_url": "postgresql+psycopg://ac_runtime@172.27.0.2:5432/ac_staging"},
        {"database_url": "postgresql+asyncpg://ac_runtime@172.27.0.2:5432/ac_platform"},
        {"database_url": "postgresql+psycopg://ac_runtime@172.27.0.2:5432/ac_platform?host=prod"},
    ],
)
def test_staging_and_production_like_targets_are_refused(updates):
    with pytest.raises(ValueError, match="Only the development database"):
        require_development_target(dev_settings(**updates), acknowledged=True)


@pytest.mark.parametrize("name", ["PGHOST", "PGHOSTADDR", "PGSERVICE", "PGOPTIONS"])
def test_libpq_overrides_cannot_redirect_the_target(monkeypatch, name):
    monkeypatch.setenv(name, "untrusted-override")
    with pytest.raises(ValueError):
        require_development_target(dev_settings(), acknowledged=True)


def test_passwords_come_only_from_named_variables_and_are_never_echoed():
    environ = {PASSWORD_VARIABLES[kind]: value for kind, value in PASSWORDS.items()}
    assert fixture_passwords(environ) == PASSWORDS
    weak = {**environ, PASSWORD_VARIABLES["admin"]: "tiny"}
    with pytest.raises(ValueError, match="AC_DEV_FIXTURE_PASSWORD_ADMIN") as refused:
        fixture_passwords(weak)
    assert "tiny" not in str(refused.value)
    missing = {k: v for k, v in environ.items() if not k.endswith("_MEMBER")}
    with pytest.raises(ValueError, match="AC_DEV_FIXTURE_PASSWORD_MEMBER"):
        fixture_passwords(missing)


def test_cli_has_no_caller_chosen_accounts_or_passwords(monkeypatch, capsys):
    with pytest.raises(SystemExit):
        fixture.main(["--acknowledge-development-fixtures", "--email", "x@example.test"])
    monkeypatch.setattr(fixture, "Settings", lambda **_: dev_settings(environment="staging"))
    with pytest.raises(ValueError, match="Only the development database"):
        fixture.main(["--acknowledge-development-fixtures"])
    assert capsys.readouterr().out == ""


def test_cli_prints_only_emails_and_person_ids(monkeypatch, capsys):
    person_id = uuid4()

    async def initialize(settings, *, environ, acknowledged):
        assert acknowledged
        return dict.fromkeys(ACCOUNTS.values(), person_id)

    monkeypatch.setattr(fixture, "initialize", initialize)
    for kind, value in PASSWORDS.items():
        monkeypatch.setenv(PASSWORD_VARIABLES[kind], value)
    assert fixture.main(["--acknowledge-development-fixtures"]) == 0
    printed = capsys.readouterr().out
    assert json.loads(printed) == {
        "accounts": [{"email": email, "person_id": str(person_id)} for email in ACCOUNTS.values()]
    }
    assert not any(value in printed for value in PASSWORDS.values())


async def seed(state, passwords=PASSWORDS):
    return await seed_fixture_accounts(
        state.adapter,
        passwords=passwords,
        secret=SECRET,
        public_tenant_id=PUBLIC_TENANT,
        consent_version=CONSENT,
    )


@pytest.fixture
def dev_database(empty_database):  # noqa: F811 - pytest fixture reuse
    empty_database.db.add(Tenant(id=PUBLIC_TENANT, slug="public", name="Public learners"))
    staff = Person(id=uuid4(), email="staff@authorityclosers.com", first_name="Staff")
    empty_database.db.add(staff)
    empty_database.db.flush()
    empty_database.staff = staff
    return empty_database


async def test_accounts_get_exactly_personal_learner_access_and_no_email(dev_database):
    state = dev_database
    ids = await seed(state)
    assert set(ids) == set(ACCOUNTS.values())
    identity = PasswordIdentityService(state.adapter, token_secret=SECRET)
    for kind, email in ACCOUNTS.items():
        person = await identity.authenticate(email=email, password=PASSWORDS[kind])
        assert person.id == ids[email]
        assert person.consent_version == CONSENT and person.consented_at is not None
        assert person.whatsapp_number == FIXTURE_PHONE
        memberships = state.db.scalars(select(Membership).where(Membership.person_id == person.id))
        assert [(m.tenant_id, m.role, m.status) for m in memberships] == [
            (PUBLIC_TENANT, "learner", "active")
        ]
    assert state.db.scalar(select(func.count()).select_from(CapabilityGrant)) == 0
    assert state.db.scalar(select(func.count()).select_from(IdentitySession)) == 0
    assert state.db.scalar(select(func.count()).select_from(OutboxEvent)) == 0
    assert all(row.consumed_at for row in state.db.scalars(select(EmailChallenge)))


async def test_second_run_is_a_no_op_and_never_touches_other_people(dev_database):
    state = dev_database
    ids = await seed(state)
    staff_before = (state.staff.email, state.staff.first_name, state.staff.revision)
    challenges = state.db.scalar(select(func.count()).select_from(EmailChallenge))
    assert await seed(state) == ids
    assert state.db.scalar(select(func.count()).select_from(Person)) == 4
    assert state.db.scalar(select(func.count()).select_from(EmailChallenge)) == challenges
    assert state.db.scalar(select(func.count()).select_from(Membership)) == 3
    assert (state.staff.email, state.staff.first_name, state.staff.revision) == staff_before


async def test_wrong_password_for_existing_account_refuses(dev_database):
    await seed(dev_database)
    with pytest.raises(ValueError, match="sx-admin@example.test exists"):
        await seed(dev_database, {**PASSWORDS, "admin": "a-different-fictional-password"})


async def test_changed_existing_account_is_not_repaired(dev_database):
    ids = await seed(dev_database)
    membership = dev_database.db.get(Membership, (PUBLIC_TENANT, ids["sx-member@example.test"]))
    dev_database.db.delete(membership)
    dev_database.db.flush()
    with pytest.raises(ValueError, match="no longer matches"):
        await seed(dev_database)
    assert dev_database.db.scalar(select(func.count()).select_from(Membership)) == 2
