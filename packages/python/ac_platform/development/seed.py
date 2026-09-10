"""Populate an isolated localhost sandbox through real identity/catalog commands.

No production people, tokens or database copies are used. This executable has
no HTTP route. It refuses remote/database-default targets before connecting.
Local test identities are clearly distinct from Dipak and live administrators.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4, uuid5

from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.application.asyncio_runtime import run_async
from ac_platform.application.settings import Settings
from ac_platform.audit.service import AuditRepository
from ac_platform.authorization.application import CapabilityApplication
from ac_platform.authorization.models import CapabilityRevocation
from ac_platform.authorization.policy import CapabilityScope
from ac_platform.catalog.models import ActivityKind, Program, ProgramVersion
from ac_platform.catalog.services import AsyncCatalogApplication
from ac_platform.enrollment.models import Enrollment, EnrollmentEligibilityFact, Entitlement
from ac_platform.enrollment.services import (
    AsyncEnrollmentApplication,
    ManualEnrollmentGrantCommand,
    SqlAlchemyEnrollmentRepository,
)
from ac_platform.identity.application import AsyncIdentityApplication
from ac_platform.identity.models import EmailChallenge, EmailChallengeKind, Person
from ac_platform.identity.password_auth import (
    PasswordIdentityService,
    decrypt_challenge_token,
    validate_password,
)
from ac_platform.kernel.authz import ActorContext
from ac_platform.media.staging_fixture_import import StagingFixtureImportApplication
from ac_platform.media.staging_fixture_manifest import (
    MANIFEST_SHA256,
    load_verified_staging_fixture_pack,
)
from ac_platform.seed.application import StagingSeedApplication
from ac_platform.seed.contract import CONTROLLED_FOUNDATION_SEED_PATH, load_seed
from ac_platform.seed.technical_media_fixture_v2 import (
    technical_media_identity,
    technical_media_seed,
)
from ac_platform.tenancy.models import Membership, Tenant

_NAMESPACE = UUID("c188a5b6-ce2b-43c4-9a37-f08d21aa588e")
OPERATIONS_TENANT = uuid5(_NAMESPACE, "operations")
ACADEMY_TENANT = uuid5(_NAMESPACE, "academy")
CONSENT_VERSION = "disposable-local-test-v1"
STUDIO_PROGRAM = uuid5(_NAMESPACE, "synthetic-studio-program-v1")
STUDIO_VERSION = uuid5(_NAMESPACE, "synthetic-studio-version-v1")
STUDIO_SOURCE = "local:synthetic-studio-draft-v1"
FIXTURE_REASON = "Synthetic localhost fixture only; not evidence about a real learner."
ACCOUNTS = {
    "learner": "learner@ac.localhost",
    "coach": "coach@ac.localhost",
    "admin": "admin@ac.localhost",
}


def require_local_target(settings: Settings, *, acknowledged: bool) -> None:
    """A local environment label alone cannot authorize writes to a remote DB."""
    url = make_url(settings.database_url)
    if (
        not acknowledged
        or settings.environment != "local"
        or url.drivername != "postgresql+psycopg"
        or url.host != "127.0.0.1"
        or url.port != 55432
        or url.database != "ac_local_sandbox"
        or url.username != "ac_runtime"
        or url.query
        or not settings.external_side_effects_hold
        or settings.email_provider != "fake"
        or settings.media_provider_enabled
        or settings.google_oauth_configured
        or any(name.upper().startswith("PG") for name in os.environ)
    ):
        raise ValueError("Only the isolated loopback:55432 local sandbox is allowed.")


@dataclass(frozen=True)
class LocalSeedResult:
    operations_tenant_id: UUID
    academy_tenant_id: UUID
    account_emails: tuple[str, ...]
    foundation_program_id: UUID
    technical_program_id: UUID
    studio_program_id: UUID


async def seed_accounts(database: AsyncSession, *, password: str, secret: str) -> dict[str, UUID]:
    """Disposable fixture setup only; never repair or replace an existing account."""
    validate_password(password)
    people = tuple(await database.scalars(select(Person)))
    if any(person.email not in ACCOUNTS.values() for person in people):
        raise ValueError("Sandbox contains non-fixture accounts; refusing fixture setup.")
    for tenant_id, slug, name in (
        (OPERATIONS_TENANT, "local-operations", "Local Platform Operations"),
        (ACADEMY_TENANT, "local-closers-academy", "Closers Academy · Local sandbox"),
    ):
        tenant = await database.get(Tenant, tenant_id)
        if tenant is None:
            database.add(Tenant(id=tenant_id, slug=slug, name=name))
        elif tenant.slug != slug or tenant.name != name or tenant.status != "active":
            raise ValueError("Local tenant changed; refusing to overwrite it.")
    await database.flush()
    identity = PasswordIdentityService(database, token_secret=secret)
    ids: dict[str, UUID] = {}
    for kind, email in ACCOUNTS.items():
        existing = next((person for person in people if person.email == email), None)
        if existing is None:
            registration = await identity.register(
                email=email,
                first_name=f"Local {kind.title()}",
                whatsapp_number="+15550100000",  # fictional local-only test data
                password=password,
                consent_version=CONSENT_VERSION,
            )
            if registration.challenge is None:
                raise ValueError("Fixture registration changed concurrently; retry setup.")
            challenge = await database.get(EmailChallenge, registration.challenge.challenge_id)
            if challenge is None:
                raise ValueError("Local verification challenge unavailable.")
            # Exercise the same one-use verification command, without sending
            # mail or claiming that a real person's mailbox has been verified.
            token = decrypt_challenge_token(
                secret,
                challenge.encrypted_token,
                kind=EmailChallengeKind.VERIFICATION,
                person_id=challenge.person_id,
            )
            person = await identity.consume_verification(token)
        else:
            person = await identity.authenticate(email=email, password=password)
            if person.consent_version != CONSENT_VERSION:
                raise ValueError("Existing account is not this local test fixture.")
        ids[kind] = person.id
        memberships = [(ACADEMY_TENANT, "admin" if kind == "admin" else "learner")]
        if kind == "admin":
            memberships.append((OPERATIONS_TENANT, "owner"))
        for tenant_id, role in memberships:
            member = await database.get(Membership, (tenant_id, person.id))
            if member is None:
                database.add(Membership(tenant_id=tenant_id, person_id=person.id, role=role))
            elif member.role != role or member.status != "active" or member.ended_at is not None:
                raise ValueError("Local assignment changed; refusing to overwrite it.")
        await database.flush()
    return ids


async def _film_eligibility(
    database: AsyncSession, *, actor: ActorContext, person_id: UUID, version: ProgramVersion
) -> None:
    """Explicit fictional inputs, never a general-purpose eligibility command."""
    fact_id = uuid5(version.id, f"local-film-eligibility:{person_id}")
    expected = {
        "id": fact_id,
        "tenant_id": ACADEMY_TENANT,
        "person_id": person_id,
        "program_version_id": version.id,
        "program_id": version.program_id,
        "program_scope": version.scope,
        "program_tenant_id": version.tenant_id,
        "program_owner_key": version.owner_key,
        "age_gate_passed": True,
        "eligibility_passed": True,
        "prerequisites_satisfied": True,
        "policy_version": CONSENT_VERSION,
        "evidence": {
            "synthetic": True,
            "purpose": "isolated-public-film-playback-test",
            "notice": FIXTURE_REASON,
            "source_ref": version.content_source_ref,
        },
        "valid_until": None,
    }
    fact = await database.scalar(
        select(EnrollmentEligibilityFact).where(
            EnrollmentEligibilityFact.tenant_id == ACADEMY_TENANT,
            EnrollmentEligibilityFact.person_id == person_id,
            EnrollmentEligibilityFact.program_version_id == version.id,
        )
    )
    if fact is not None:
        if any(getattr(fact, field) != value for field, value in expected.items()):
            raise ValueError("Synthetic eligibility changed; refusing to replace it.")
        return
    database.add(EnrollmentEligibilityFact(**expected))
    await database.flush()
    await AuditRepository(database).append_for_actor(
        actor,
        action="local.synthetic_eligibility_created",
        resource_type="enrollment_eligibility_fact",
        resource_id=fact_id,
        payload={"synthetic": True, "program_version_id": str(version.id)},
        reason=FIXTURE_REASON,
    )


async def _studio_draft(database: AsyncSession, *, actor: ActorContext) -> None:
    program = await database.get(Program, STUDIO_PROGRAM)
    if program is not None:
        version = await database.get(ProgramVersion, STUDIO_VERSION)
        if (
            program.scope != "tenant"
            or program.tenant_id != ACADEMY_TENANT
            or version is None
            or version.program_id != program.id
            or version.tenant_id != ACADEMY_TENANT
            or version.content_source_ref != STUDIO_SOURCE
        ):
            raise ValueError("Synthetic Studio course ownership changed; refusing replacement.")
        # Keep every subsequent UI content/title edit and publication intact.
        return
    catalog = AsyncCatalogApplication(database)
    await catalog.create_program(
        actor=actor,
        tenant_id=ACADEMY_TENANT,
        slug="local-studio-practice",
        title="Local Studio practice · Synthetic draft",
        program_id=STUDIO_PROGRAM,
    )
    await catalog.create_version(
        STUDIO_PROGRAM,
        actor=actor,
        tenant_id=ACADEMY_TENANT,
        version_id=STUDIO_VERSION,
        content_source_ref=STUDIO_SOURCE,
    )
    module = await catalog.add_module(
        STUDIO_VERSION,
        actor=actor,
        tenant_id=ACADEMY_TENANT,
        title="Draft workspace",
        module_id=uuid5(_NAMESPACE, "synthetic-studio-module-v1"),
    )
    await catalog.add_activity(
        module.id,
        actor=actor,
        tenant_id=ACADEMY_TENANT,
        kind=ActivityKind.REFLECTION,
        title="Synthetic draft reflection",
        prompt="Local editor test content only. Replace this text while testing Studio.",
        activity_id=uuid5(_NAMESPACE, "synthetic-studio-activity-v1"),
    )
    await AuditRepository(database).append_for_actor(
        actor,
        action="local.synthetic_studio_draft_created",
        resource_type="program",
        resource_id=STUDIO_PROGRAM,
        payload={"synthetic": True, "published": False},
        reason=FIXTURE_REASON,
    )


async def seed_local_access(
    database: AsyncSession, *, settings: Settings, ids: dict[str, UUID], password: str
) -> None:
    """Audited fixture commands inside the caller's disposable-local transaction.

    No caller-selected course, person, tenant, permission or source is accepted.
    The only policy booleans belong to fictional accounts and the pinned films.
    Public self-attestation, official progress and publication policy are unchanged.
    """
    require_local_target(settings, acknowledged=True)
    people = tuple(await database.scalars(select(Person)))
    if (
        set(ids) != set(ACCOUNTS)
        or len(people) != len(ACCOUNTS)
        or any(
            not any(
                person.id == ids[kind]
                and person.email == email
                and person.consent_version == CONSENT_VERSION
                for kind, email in ACCOUNTS.items()
            )
            for person in people
        )
    ):
        raise ValueError("Only the exact synthetic local accounts may receive fixture access.")
    program_id, version_id, _, _ = technical_media_identity(settings.release_id)
    seed = technical_media_seed(settings.release_id)
    version = await database.get(ProgramVersion, version_id)
    if (
        version is None
        or version.program_id != program_id
        or version.scope != "global"
        or version.tenant_id is not None
        or version.status != "published"
        or version.content_digest != seed.content_digest
        or version.content_source_ref != seed.source_ref
        or version.content_seed_kind != "technical-validation"
    ):
        raise ValueError("The exact published synthetic film catalog is required.")

    async with database.begin_nested():
        capabilities = CapabilityApplication(database, operations_tenant_id=OPERATIONS_TENANT)
        # Governance fence precedes identity/person locks; replay cannot reopen
        # bootstrap or reactivate a revoked local manager.
        await capabilities.bootstrap_first_manager(
            person_id=ids["admin"],
            command_id=uuid5(_NAMESPACE, "synthetic-first-manager-v1"),
            reason=FIXTURE_REASON,
        )
        person = await PasswordIdentityService(
            database, token_secret=settings.email_challenge_secret.get_secret_value()
        ).authenticate(email=ACCOUNTS["admin"], password=password)
        if person.id != ids["admin"]:
            raise ValueError("Synthetic admin identity changed.")
        identity = AsyncIdentityApplication(
            database,
            token_pepper=settings.session_token_pepper.get_secret_value(),
            session_ttl=timedelta(minutes=5),
        )
        issued = await identity.issue_authenticated_session(
            person.id, user_agent="AC disposable-local fixture setup", ip_address="127.0.0.1"
        )
        resolved = await identity.select_tenant(issued.token, ACADEMY_TENANT)
        if resolved.membership_role != "admin":
            raise ValueError("Synthetic academy administrator assignment changed.")
        # Only the two permissions needed by this command, after canonical role
        # resolution. No platform grant is mapped into tenant catalog authority.
        actor = replace(
            resolved.actor, permissions=frozenset({"enrollment_grant", "catalog_write"})
        )
        await _studio_draft(database, actor=actor)
        for permission in ("catalog_read", "catalog_write", "catalog_publish"):
            grant = await capabilities.grant(
                actor,
                command_id=uuid5(_NAMESPACE, f"synthetic-coach:{ids['coach']}:{permission}"),
                subject_person_id=ids["coach"],
                permission=permission,
                scope=CapabilityScope("program", ACADEMY_TENANT, STUDIO_PROGRAM),
                reason=FIXTURE_REASON,
            )
            if await database.scalar(
                select(CapabilityRevocation.id).where(CapabilityRevocation.grant_id == grant.id)
            ):
                raise ValueError("Synthetic coach assignment was revoked; refusing reactivation.")
        for kind in ("learner", "coach"):
            await _film_eligibility(database, actor=actor, person_id=ids[kind], version=version)
            policy = await SqlAlchemyEnrollmentRepository(database).load_manual_grant_policy(
                actor_person_id=actor.person_id,
                subject_person_id=ids[kind],
                tenant_id=ACADEMY_TENANT,
                program_version_id=version.id,
                now=datetime.now(UTC),
            )
            result = await AsyncEnrollmentApplication(database).grant_manual(
                ManualEnrollmentGrantCommand(
                    actor_person_id=actor.person_id,
                    subject_person_id=ids[kind],
                    tenant_id=ACADEMY_TENANT,
                    program_version_id=version.id,
                    idempotency_key=f"local-film-v1:{version.id}:{ids[kind]}",
                    reason=FIXTURE_REASON,
                    policy=policy,
                ),
                actor=actor,
            )
            enrollment = await database.get(Enrollment, result.enrollment_id)
            entitlement = await database.get(Entitlement, result.entitlement_id)
            if (
                enrollment is None
                or enrollment.status != "active"
                or entitlement is None
                or entitlement.status != "active"
            ):
                raise ValueError("Synthetic film access was revoked; refusing reactivation.")
            if result.created:
                await AuditRepository(database).append_for_actor(
                    actor,
                    action="local.synthetic_film_enrollment_created",
                    resource_type="enrollment",
                    resource_id=result.enrollment_id,
                    payload={"synthetic": True, "provenance_id": str(result.provenance_id)},
                    reason=FIXTURE_REASON,
                )
        # The setup session is never returned or printed and cannot be reused
        # in a browser. Failed setup rolls back this entire savepoint instead.
        await identity.revoke_self(issued.token, issued.metadata.id, reason="Local setup complete")


async def initialize(
    settings: Settings, *, password: str, acknowledged: bool, film_root: Path
) -> LocalSeedResult:
    require_local_target(settings, acknowledged=acknowledged)
    validate_password(password)
    # The local sandbox uses the existing isolated-test catalog command seam,
    # not a weakened staging CLI or a fabricated deployment release marker.
    foundation = load_seed(
        CONTROLLED_FOUNDATION_SEED_PATH,
        environment="test",
        expected_release_id=settings.release_id,
    )
    technical = technical_media_seed(settings.release_id)
    # Verify the fixed public-film inventory before any database connection.
    pack = load_verified_staging_fixture_pack(
        environment="test",
        release_id=settings.release_id,
        tenant_id=ACADEMY_TENANT,
        root=film_root,
        expected_manifest_sha256=MANIFEST_SHA256,
    )
    engine = create_async_engine(settings.database_url, hide_parameters=True)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as database:
            async with database.begin():
                ids = await seed_accounts(
                    database,
                    password=password,
                    secret=settings.email_challenge_secret.get_secret_value(),
                )
            catalog = StagingSeedApplication(
                database, environment="test", expected_release_id=settings.release_id
            )
            actor = ActorContext(ids["admin"], uuid4(), None)
            course = await catalog.apply(foundation, actor=actor)
            films = await catalog.apply_technical_validation(technical, actor=actor)
            await StagingFixtureImportApplication(
                database, environment="test", release_id=settings.release_id, pack=pack
            ).apply(
                actor_person_id=ids["admin"], expected_catalog_version_id=films.program_version_id
            )
            async with database.begin():
                await seed_local_access(database, settings=settings, ids=ids, password=password)
    finally:
        await engine.dispose()
    return LocalSeedResult(
        OPERATIONS_TENANT,
        ACADEMY_TENANT,
        tuple(ACCOUNTS.values()),
        course.program_id,
        films.program_id,
        STUDIO_PROGRAM,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acknowledge-disposable-local", action="store_true")
    args = parser.parse_args()
    # No password CLI argument: credentials must not appear in process lists.
    password = os.environ.get("AC_LOCAL_TEST_PASSWORD", "")
    result = run_async(
        initialize(
            Settings(_env_file=None),
            password=password,
            acknowledged=args.acknowledge_disposable_local,
            film_root=Path(os.environ.get("AC_LOCAL_FILM_ROOT", "")),
        )
    )
    print(json.dumps(asdict(result), default=str, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
