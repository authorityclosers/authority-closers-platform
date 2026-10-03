"""Create three fictional Sales Xray password accounts on the development DB.

Development only: it refuses every environment and database except the dev DB
endpoint below. The three addresses are fixed; passwords come only from the
environment and are never printed. New accounts go through the app's own
password registration, one-use verification and public-learner provisioning,
with no email sent. An existing fixture account is authenticated with its
password and left unchanged. No other person is read or written.
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.application.asyncio_runtime import run_async
from ac_platform.application.settings import Settings
from ac_platform.development.seed import verify_registration_without_mail
from ac_platform.identity.models import Person
from ac_platform.identity.password_auth import (
    PasswordAuthError,
    PasswordIdentityService,
    validate_password,
)
from ac_platform.tenancy.learner_provisioning import AsyncLearnerProvisioningApplication
from ac_platform.tenancy.models import Membership, MembershipRole, MembershipStatus

# The dev Postgres container on its Docker bridge (AUT-119). If the container
# is recreated with another address, update this and the README together.
DEVELOPMENT_DATABASE = ("172.27.0.2", 5432, "ac_platform")
FIXTURE_PHONE = "+14155550100"  # fictional 555-01xx number
ACCOUNTS = {
    "owner": "sx-owner@example.test",
    "admin": "sx-admin@example.test",
    "member": "sx-member@example.test",
}
PASSWORD_VARIABLES = {kind: f"AC_DEV_FIXTURE_PASSWORD_{kind.upper()}" for kind in ACCOUNTS}


def require_development_target(settings: Settings, *, acknowledged: bool) -> None:
    """Refuse before connecting unless this is exactly the dev database."""
    url = make_url(settings.database_url)
    if (
        not acknowledged
        or settings.environment != "development"
        or url.drivername != "postgresql+psycopg"
        or (url.host, url.port or 5432, url.database) != DEVELOPMENT_DATABASE
        or url.query
        or any(name.upper().startswith("PG") for name in os.environ)
    ):
        host, port, database = DEVELOPMENT_DATABASE
        raise ValueError(f"Only the development database {host}:{port}/{database} is allowed.")


def fixture_passwords(environ: Mapping[str, str]) -> dict[str, str]:
    passwords: dict[str, str] = {}
    for kind, variable in PASSWORD_VARIABLES.items():
        try:
            passwords[kind] = validate_password(environ.get(variable, ""))
        except PasswordAuthError:
            # Name the variable only; the value never reaches output.
            raise ValueError(f"{variable} is missing or fails the password policy.") from None
    return passwords


async def seed_fixture_accounts(
    database: AsyncSession,
    *,
    passwords: Mapping[str, str],
    secret: str,
    public_tenant_id: UUID,
    consent_version: str,
) -> dict[str, UUID]:
    """Run inside one transaction: any refusal leaves the database unchanged."""
    identity = PasswordIdentityService(database, token_secret=secret)
    ids: dict[str, UUID] = {}
    for kind, email in ACCOUNTS.items():
        password = passwords[kind]
        existing = await database.scalar(select(Person.id).where(func.lower(Person.email) == email))
        if existing is None:
            # The same steps as POST /v1/auth/password/register and /verify,
            # without enqueueing the verification email.
            registration = await identity.register(
                email=email,
                first_name=f"SX {kind.title()}",
                whatsapp_number=FIXTURE_PHONE,
                password=password,
                consent_version=consent_version,
            )
            person = await verify_registration_without_mail(
                database, identity, registration, secret=secret
            )
            await AsyncLearnerProvisioningApplication(database).ensure(
                person_id=person.id,
                tenant_id=public_tenant_id,
                required_consent_version=consent_version,
            )
        else:
            try:
                person = await identity.authenticate(email=email, password=password)
            except PasswordAuthError:
                raise ValueError(
                    f"{email} exists but does not accept its fixture password; refusing."
                ) from None
            membership = await database.get(Membership, (public_tenant_id, person.id))
            if (
                person.consent_version != consent_version
                or membership is None
                or membership.role != MembershipRole.LEARNER.value
                or membership.status != MembershipStatus.ACTIVE.value
            ):
                raise ValueError(f"{email} no longer matches the fixture; refusing to change it.")
        ids[email] = person.id
    return ids


async def initialize(
    settings: Settings, *, environ: Mapping[str, str], acknowledged: bool
) -> dict[str, UUID]:
    require_development_target(settings, acknowledged=acknowledged)
    passwords = fixture_passwords(environ)
    consent_version = (settings.learner_consent_version or "").strip()
    if settings.public_learner_tenant_id is None or not consent_version:
        raise ValueError("The public learner tenant and consent version must be configured.")
    engine = create_async_engine(settings.database_url, hide_parameters=True)
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as database, database.begin():
            return await seed_fixture_accounts(
                database,
                passwords=passwords,
                secret=settings.email_challenge_secret.get_secret_value(),
                public_tenant_id=settings.public_learner_tenant_id,
                consent_version=consent_version,
            )
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acknowledge-development-fixtures", action="store_true")
    args = parser.parse_args(argv)
    # No password CLI arguments: credentials must not appear in process lists.
    ids = run_async(
        initialize(
            Settings(_env_file=None),
            environ=os.environ,
            acknowledged=args.acknowledge_development_fixtures,
        )
    )
    accounts = [{"email": email, "person_id": str(person_id)} for email, person_id in ids.items()]
    print(json.dumps({"accounts": accounts}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
