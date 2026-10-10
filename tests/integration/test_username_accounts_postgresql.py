"""Fresh schema and canonical HTTP/session proof for admin-issued username credentials."""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain_sync
from ac_platform.http.auth import install_identity_http
from ac_platform.http.organisation import install_organisation_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.application import AsyncIdentityApplication
from ac_platform.identity.email_login import EmailLoginCodeService
from ac_platform.identity.models import PasswordCredential, Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.identity.password_auth import (
    InvalidPasswordCredentials,
    PasswordIdentityService,
    verify_password,
)
from ac_platform.identity.sales_xray_profile import (
    get_sales_xray_profile,
    update_sales_xray_profile,
)
from ac_platform.identity.services import AuthorizationDenied
from ac_platform.identity.username_accounts import normalize_username
from ac_platform.kernel.errors import ResourceConflict
from ac_platform.organisations.service import OrganisationService
from ac_platform.tenancy.models import Membership, Tenant
from tests.integration.test_password_identity_http_postgresql import (  # noqa: F401
    _email_code_settings,
)
from tests.integration.test_password_identity_http_postgresql import (
    postgres_harness as _postgres_harness,
)


@pytest.fixture(scope="module")
def postgres_harness():
    yield from _postgres_harness.__wrapped__()


ORIGIN = "https://salesxray.authorityclosers.test"
CONSENT = "username-fixture-v1"
PERSONAL_PASSWORD = "fictional-own-password-42"  # noqa: S105


@asynccontextmanager
async def account(harness, *, email=None):
    engine = create_async_engine(harness.schema_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    ops, public, owner, operator = (uuid4() for _ in range(4))
    settings = _email_code_settings(
        harness.schema_url,
        public_tenant_id=public,
        operations_tenant_id=ops,
        consent_version=CONSENT,
    )
    username = "rep." + uuid4().hex
    creation_key = uuid4()
    try:
        async with sessions() as db, db.begin():
            db.add_all(
                [
                    Tenant(id=ops, name="Synthetic operations", slug="ops-" + uuid4().hex),
                    Tenant(id=public, name="Synthetic Personal", slug="personal-" + uuid4().hex),
                    Person(
                        id=owner,
                        email=uuid4().hex + "@owner.test",
                        email_verified_at=datetime.now(UTC),
                    ),
                    Person(
                        id=operator,
                        email=uuid4().hex + "@operator.test",
                        email_verified_at=datetime.now(UTC),
                    ),
                ]
            )
            await db.flush()
            service = OrganisationService(
                db, operations_tenant_id=ops, public_learner_tenant_id=public
            )
            org = await service.create(
                "Synthetic organisation",
                owner,
                uuid4(),
                operator_reference="Fictional organisation setup",
                actor_person_id=owner,
            )
            result = await service.create_username_member(
                org.tenant_id,
                username,
                "Synthetic Rep",
                email,
                creation_key,
                actor_person_id=operator,
                operator_reference="AUT-1694 fictional account",
            )
        app = FastAPI()
        register_problem_handlers(app)
        actor = install_identity_http(app, settings=settings, sessions=sessions)
        install_organisation_http(app, settings=settings, require_actor=actor)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=ORIGIN
        ) as client:
            yield client, sessions, settings, org.tenant_id, result, operator, creation_key
    finally:
        await engine.dispose()


def test_username_normalization_is_bounded():
    assert normalize_username(" Vijay.Rajpurohit ") == "vijay.rajpurohit"
    for invalid in ("ab", "a" * 61, "a@b.test", "a/b", "a\nb", ".abc", "abc.", "अमित"):
        with pytest.raises(ValueError):
            normalize_username(invalid)


@pytest.mark.parametrize("with_email", [False, True])
def test_creation_first_change_login_and_org_profile_without_mailbox_fabrication(
    postgres_harness, with_email
):
    async def run():
        email = uuid4().hex + "@optional.test" if with_email else None
        async with account(postgres_harness, email=email) as (
            client,
            sessions,
            settings,
            tenant,
            created,
            operator,
            key,
        ):
            person_id = UUID(created["person_id"])
            identifiers = [created["username"].upper()] + ([email.upper()] if email else [])
            for identifier in identifiers:
                response = await client.post(
                    "/v1/auth/password/login",
                    headers={"Origin": ORIGIN},
                    json={"email": identifier, "password": created["temporary_password"]},
                )
                assert response.status_code == 200
                assert response.json() == {"authenticated": False, "password_change_required": True}
                assert not client.cookies.get("ac_session")
            async with sessions() as db, db.begin():
                identity = AsyncIdentityApplication(
                    db, token_pepper=settings.session_token_pepper.get_secret_value()
                )
                with pytest.raises(AuthorizationDenied):
                    await identity.issue_authenticated_session(person_id)
                password = PasswordIdentityService(
                    db, token_secret=settings.email_challenge_secret.get_secret_value()
                )
                if email:
                    assert await password.begin_verification(email=email) is None
                    assert await password.begin_reset(email=email) is None
                    codes = EmailLoginCodeService(
                        db,
                        challenge_secret=settings.email_challenge_secret.get_secret_value(),
                        audit_tenant_id=settings.operations_tenant_id,
                    )
                    assert (
                        await codes.begin(
                            email=email,
                            consent_accepted=True,
                            submitted_consent_version=CONSENT,
                            required_consent_version=CONSENT,
                            age_attested=True,
                        )
                        is None
                    )
            body = {
                "email": identifiers[0],
                "password": created["temporary_password"],
                "new_password": PERSONAL_PASSWORD,
                "consent": True,
                "age_attested": True,
                "consent_version": CONSENT,
            }
            for mutation in (
                {"consent": False},
                {"age_attested": False},
                {"consent_version": "outdated"},
                {"new_password": created["temporary_password"]},
            ):
                refused = await client.post(
                    "/v1/auth/password/first-change",
                    headers={"Origin": ORIGIN},
                    json={**body, **mutation},
                )
                assert refused.status_code in {400, 422}
                assert created["temporary_password"] not in refused.text
                assert PERSONAL_PASSWORD not in refused.text
            refused_origin = await client.post(
                "/v1/auth/password/first-change",
                headers={"Origin": "https://foreign.test"},
                json=body,
            )
            assert refused_origin.status_code == 403
            changed = await client.post(
                "/v1/auth/password/first-change", headers={"Origin": ORIGIN}, json=body
            )
            assert changed.status_code == 200 and changed.json()["authenticated"] is True
            assert client.cookies.get("ac_session")
            me = await client.get("/v1/me")
            assert me.status_code == 200
            assert me.json()["username"] == created["username"]
            assert me.json()["email"] == email and me.json()["email_verified_at"] is None
            assert me.json()["selected_tenant_id"] == str(tenant)
            assert (await client.get("/v1/organisation/invites")).json() == {"invites": []}
            members = await client.get("/v1/organisation/members")
            assert members.status_code == 200
            assert any(row["person_id"] == str(person_id) for row in members.json()["members"])
            replay = await client.post(
                "/v1/auth/password/first-change", headers={"Origin": ORIGIN}, json=body
            )
            assert replay.status_code == 401
            client.cookies.clear()
            for identifier in identifiers:
                login = await client.post(
                    "/v1/auth/password/login",
                    headers={"Origin": ORIGIN},
                    json={"email": identifier, "password": PERSONAL_PASSWORD},
                )
                assert login.status_code == 200 and login.json()["authenticated"] is True
                assert (await client.get("/v1/me")).json()["selected_tenant_id"] == str(tenant)
            async with sessions() as db, db.begin():
                service = OrganisationService(
                    db,
                    operations_tenant_id=settings.operations_tenant_id,
                    public_learner_tenant_id=settings.public_learner_tenant_id,
                )
                replay_create = await service.create_username_member(
                    tenant,
                    created["username"],
                    "Synthetic Rep",
                    email,
                    key,
                    actor_person_id=operator,
                    operator_reference="AUT-1694 fictional account",
                )
                assert replay_create["temporary_password"] is None
                assert (
                    replay_create["password_change_required"] is False
                    and replay_create["expires_at"] is None
                )
                with pytest.raises(ResourceConflict):
                    await service.reissue_username_password(
                        tenant,
                        person_id,
                        uuid4(),
                        actor_person_id=operator,
                        operator_reference="Fictional reissue",
                    )
                profile = await get_sales_xray_profile(db, person_id=person_id)
                assert profile.email == email and profile.name == "Synthetic Rep"
                profile = await update_sales_xray_profile(
                    db,
                    person_id=person_id,
                    session_id=None,
                    tenant_id=tenant,
                    full_name="Synthetic Rep",
                    phone_number_e164="+919876543210",
                    expected_revision=0,
                )
                assert profile.profile_complete
                person = await db.get(Person, person_id)
                assert person.username_verified_at is not None and person.email_verified_at is None
                assert person.consent_version == CONSENT and not person.password_change_required
                credential = await db.scalar(
                    select(PasswordCredential).where(PasswordCredential.person_id == person_id)
                )
                assert verify_password(PERSONAL_PASSWORD, credential.password_hash)
                assert not verify_password(created["temporary_password"], credential.password_hash)
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(Membership)
                        .where(
                            Membership.person_id == person_id,
                            Membership.tenant_id == settings.public_learner_tenant_id,
                        )
                    )
                    == 0
                )
            with Session(postgres_harness.engine) as db:
                assert verify_audit_chain_sync(db, tenant_id=tenant).valid
                for event in db.scalars(
                    select(AuditEvent).where(AuditEvent.resource_id == str(person_id))
                ):
                    assert created["temporary_password"] not in str(event.payload)
                    assert PERSONAL_PASSWORD not in str(event.payload)

    asyncio.run(run())


def test_expired_temporary_password_reissue_and_concurrent_consumption(postgres_harness):
    async def run():
        async with account(postgres_harness) as (
            client,
            sessions,
            settings,
            tenant,
            created,
            operator,
            _key,
        ):
            person_id = UUID(created["person_id"])
            async with sessions() as db, db.begin():
                person = await db.get(Person, person_id)
                person.temporary_password_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            body = {"email": created["username"], "password": created["temporary_password"]}
            assert (
                await client.post("/v1/auth/password/login", headers={"Origin": ORIGIN}, json=body)
            ).status_code == 401
            async with sessions() as db, db.begin():
                service = OrganisationService(
                    db,
                    operations_tenant_id=settings.operations_tenant_id,
                    public_learner_tenant_id=settings.public_learner_tenant_id,
                )
                reissued = await service.reissue_username_password(
                    tenant,
                    person_id,
                    uuid4(),
                    actor_person_id=operator,
                    operator_reference="Fictional lost initial delivery",
                )
            assert (
                await client.post("/v1/auth/password/login", headers={"Origin": ORIGIN}, json=body)
            ).status_code == 401
            body = {
                **body,
                "password": reissued["temporary_password"],
                "new_password": PERSONAL_PASSWORD,
                "consent": True,
                "age_attested": True,
                "consent_version": CONSENT,
            }
            replies = await asyncio.gather(
                *(
                    client.post(
                        "/v1/auth/password/first-change", headers={"Origin": ORIGIN}, json=body
                    )
                    for _ in range(2)
                )
            )
            assert sorted(reply.status_code for reply in replies) == [200, 401]
            async with sessions() as db:
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(IdentitySession)
                        .where(IdentitySession.person_id == person_id)
                    )
                    == 1
                )

    asyncio.run(run())


def test_reissue_revokes_an_existing_session_and_blocks_direct_session_admission(postgres_harness):
    async def run():
        async with account(postgres_harness) as (
            _client,
            sessions,
            settings,
            tenant,
            created,
            operator,
            _key,
        ):
            person_id = UUID(created["person_id"])
            async with sessions() as db, db.begin():
                # An independently seeded legacy session cannot bypass the forced-change gate.
                db.add(
                    IdentitySession(
                        id=uuid4(),
                        person_id=person_id,
                        token_hash=b"x" * 32,
                        created_at=datetime.now(UTC),
                        expires_at=datetime.now(UTC) + timedelta(days=1),
                    )
                )
            async with sessions() as db, db.begin():
                service = OrganisationService(
                    db,
                    operations_tenant_id=settings.operations_tenant_id,
                    public_learner_tenant_id=settings.public_learner_tenant_id,
                )
                await service.reissue_username_password(
                    tenant,
                    person_id,
                    uuid4(),
                    actor_person_id=operator,
                    operator_reference="Fictional initial password reissue",
                )
                session = await db.scalar(
                    select(IdentitySession).where(IdentitySession.person_id == person_id)
                )
                assert session.revoked_at is not None
                person = await db.get(Person, person_id)
                person.status = "suspended"
            async with sessions() as db, db.begin():
                with pytest.raises(InvalidPasswordCredentials):
                    await PasswordIdentityService(
                        db, token_secret=settings.email_challenge_secret.get_secret_value()
                    ).authenticate(
                        email=created["username"], password=created["temporary_password"]
                    )

    asyncio.run(run())
