"""PostgreSQL proof: Sales Xray sign-in with Google, Apple and Facebook, and when it links.

A first sign-in whose provider email matches an existing account links to it only
when the provider verifies the email (Google, Apple), the account's own email is
verified, and it is not platform staff. Facebook never links; it may create a new
account. Every refusal leaves the database as it was.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from ac_platform.application.settings import Settings
from ac_platform.audit.models import AuditEvent
from ac_platform.http.auth import install_identity_http
from ac_platform.http.auth_transactions import AuthTransaction
from ac_platform.http.identity_provider import IdentityProviderEmailMissing
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.models import Person, ProviderIdentity
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.identity.provider_link_email import (
    PROVIDER_LINKED_EVENT,
    SIGN_IN_REFUSED_ACTION,
)
from ac_platform.identity.services import VerifiedProviderAssertion
from ac_platform.outbox.models import OutboxEvent
from ac_platform.tenancy.models import Membership, MembershipRole, MembershipStatus, Tenant
from tests.integration.test_password_identity_http_postgresql import _Harness, _run_async
from tests.integration.test_password_identity_http_postgresql import (
    postgres_harness as _postgres_harness,
)

SALES_ORIGIN = "https://salesxray.authorityclosers.test"
CONSENT_VERSION = "provider-sign-in-consent-v2"
LINK_ACTION = "identity.provider_linked_by_verified_email.v1"
ISSUERS = {
    "google": "https://accounts.google.com",
    "facebook": "https://www.facebook.com",
    "apple": "https://appleid.apple.com",
}


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[_Harness]:
    yield from _postgres_harness.__wrapped__()


class _Provider:
    """A provider double: protocol checks are the adapters' unit tests' job."""

    def __init__(self, name: str, *, email: str, subject: str) -> None:
        self.name = name
        self.audience = f"postgres-{name}-client"
        self.email: str | None = email
        self.email_verified = True
        self.subject = subject
        self.transactions: list[AuthTransaction] = []

    def authorization_url(self, transaction: AuthTransaction, *, redirect_uri: str) -> str:
        assert redirect_uri == f"{SALES_ORIGIN}/v1/auth/{self.name}/callback"
        self.transactions.append(transaction)
        return f"https://{self.name}.example.test/authorize?state={transaction.state}"

    async def exchange_code(
        self,
        code: str,
        transaction: AuthTransaction,
        *,
        callback_state: str,
        redirect_uri: str,
    ) -> VerifiedProviderAssertion:
        assert code == f"{self.name}-code"
        assert redirect_uri == f"{SALES_ORIGIN}/v1/auth/{self.name}/callback"
        if self.email is None:
            raise IdentityProviderEmailMissing("no email shared")
        return VerifiedProviderAssertion(
            issuer=ISSUERS[self.name],
            subject=self.subject,
            audience=self.audience,
            state=callback_state,
            nonce=transaction.nonce,
            authorization_type=transaction.authorization_type,
            email=self.email,
            email_verified=self.email_verified,
        )


def _settings(harness: _Harness, *, tenant_id: UUID) -> Settings:
    return Settings(
        environment="test",
        database_url=harness.schema_url.render_as_string(hide_password=False),
        session_token_pepper="postgres-provider-sign-in-pepper-long-enough",  # noqa: S106
        oauth_transaction_secret="postgres-provider-sign-in-transaction-secret-long",  # noqa: S106
        email_challenge_secret="postgres-provider-sign-in-email-secret-long-enough",  # noqa: S106
        learner_consent_version=CONSENT_VERSION,
        public_learner_tenant_id=tenant_id,
        operations_tenant_id=uuid4(),
        public_app_url="https://app.authorityclosers.test",
        admin_app_url="https://admin.authorityclosers.test",
        api_url="https://api.authorityclosers.test",
        sales_xray_app_url=SALES_ORIGIN,
    )


async def _sign_in(
    harness: _Harness,
    *,
    tenant_id: UUID,
    provider: _Provider,
) -> tuple[str, httpx.Response]:
    """One full Sales Xray sign-in; returns the bounded result and the final response."""

    async_engine = create_async_engine(harness.schema_url, pool_pre_ping=True)
    try:
        application = FastAPI()
        register_problem_handlers(application)
        google = provider if provider.name == "google" else None
        install_identity_http(
            application,
            settings=_settings(harness, tenant_id=tenant_id),
            sessions=async_sessionmaker(async_engine, expire_on_commit=False),
            provider=google,
            extra_providers={} if google is not None else {provider.name: provider},
        )
        transport = httpx.ASGITransport(app=application, client=("127.0.0.1", 12345))
        async with httpx.AsyncClient(transport=transport, base_url=SALES_ORIGIN) as client:
            started = await client.get(
                f"/v1/auth/{provider.name}/start",
                params={
                    "action": "authenticate",
                    "surface": "sales_xray",
                    "consent": "true",
                    "age_attested": "true",
                    "consent_version": CONSENT_VERSION,
                    "return_path": f"/auth/complete?flow={uuid4()}",
                },
                follow_redirects=False,
            )
            assert started.status_code == 303
            transaction = provider.transactions[-1]
            assert transaction.provider == provider.name
            if provider.name == "apple":
                # Apple's cross-site form_post, then the same-site GET it redirects to.
                posted = await client.post(
                    "/v1/auth/apple/callback",
                    data={"state": transaction.state, "code": "apple-code"},
                    headers={"origin": "https://appleid.apple.com"},
                    follow_redirects=False,
                )
                assert posted.status_code == 303
                finished = await client.get(posted.headers["location"], follow_redirects=False)
            else:
                finished = await client.get(
                    f"/v1/auth/{provider.name}/callback",
                    params={"state": transaction.state, "code": f"{provider.name}-code"},
                    follow_redirects=False,
                )
            assert finished.status_code == 303
            query = parse_qs(urlsplit(finished.headers["location"]).query)
            return query["auth_result"][0], finished
    finally:
        await async_engine.dispose()


def _seed(
    harness: _Harness,
    *,
    email: str | None = None,
    verified: bool = True,
    staff: bool = False,
) -> tuple[UUID, UUID | None]:
    tenant_id = uuid4()
    person_id = uuid4() if email is not None else None
    with Session(harness.engine) as database, database.begin():
        database.add(Tenant(id=tenant_id, slug=f"sx-providers-{tenant_id.hex}", name="Synthetic"))
        if person_id is not None:
            database.add(
                Person(
                    id=person_id,
                    email=email,
                    email_verified_at=datetime(2026, 9, 1, tzinfo=UTC) if verified else None,
                    consent_version="provider-sign-in-consent-v1",
                    consented_at=datetime(2026, 9, 1, tzinfo=UTC),
                )
            )
        if staff and person_id is not None:
            staff_tenant = uuid4()
            database.add(Tenant(id=staff_tenant, slug=f"sx-staff-{staff_tenant.hex}", name="Ops"))
            database.flush()
            database.add(
                Membership(
                    tenant_id=staff_tenant,
                    person_id=person_id,
                    role=MembershipRole.ADMIN.value,
                    status=MembershipStatus.ACTIVE.value,
                )
            )
    return tenant_id, person_id


def _identities(harness: _Harness, issuer: str, subject: str) -> list[ProviderIdentity]:
    with Session(harness.engine) as database:
        return list(
            database.scalars(
                select(ProviderIdentity).where(
                    ProviderIdentity.issuer == issuer, ProviderIdentity.subject == subject
                )
            )
        )


def _people_with_email(harness: _Harness, email: str) -> int:
    with Session(harness.engine) as database:
        return int(
            database.scalar(
                select(func.count())
                .select_from(Person)
                .where(func.lower(Person.email) == email.lower())
            )
            or 0
        )


def _link_notices_for(harness: _Harness, person_id: UUID) -> list[OutboxEvent]:
    with Session(harness.engine) as database:
        return list(
            database.scalars(
                select(OutboxEvent).where(
                    OutboxEvent.event_type == PROVIDER_LINKED_EVENT,
                    OutboxEvent.aggregate_id == person_id,
                )
            )
        )


def _sessions_of(harness: _Harness, person_id: UUID) -> int:
    with Session(harness.engine) as database:
        return int(
            database.scalar(
                select(func.count())
                .select_from(IdentitySession)
                .where(IdentitySession.person_id == person_id)
            )
            or 0
        )


@pytest.mark.parametrize("provider_name", ["google", "apple"])
def test_verified_email_links_a_first_provider_sign_in_to_the_existing_account(
    postgres_harness: _Harness, provider_name: str
) -> None:
    email = f"Existing.{uuid4().hex}@Example.test"
    tenant_id, person_id = _seed(postgres_harness, email=email)
    assert person_id is not None
    subject = f"{provider_name}-subject-{uuid4().hex}"
    provider = _Provider(provider_name, email=email.lower(), subject=subject)

    result, finished = _run_async(
        _sign_in(postgres_harness, tenant_id=tenant_id, provider=provider)
    )

    assert result == "success"
    assert finished.cookies.get("ac_session")
    [identity] = _identities(postgres_harness, ISSUERS[provider_name], subject)
    assert identity.person_id == person_id
    assert _people_with_email(postgres_harness, email) == 1
    assert _sessions_of(postgres_harness, person_id) == 1
    with Session(postgres_harness.engine) as database:
        person = database.get(Person, person_id)
        assert person is not None and person.consent_version == CONSENT_VERSION
        assert database.get(Membership, (tenant_id, person_id)) is not None
        [event] = database.scalars(
            select(AuditEvent).where(
                AuditEvent.tenant_id == tenant_id,
                AuditEvent.actor_person_id == person_id,
                AuditEvent.action == LINK_ACTION,
            )
        )
        # Provider, account (actor), time (occurred_at) and the client address.
        assert event.payload == {"provider": provider_name, "ip_address": "127.0.0.1"}
        assert event.actor_person_id == person_id and event.occurred_at is not None
        event_id = event.id
    # The account is told by email: one notice, carrying only the audit event id.
    [notice] = _link_notices_for(postgres_harness, person_id)
    assert notice.payload == {"audit_event_id": str(event_id)}

    # The next sign-in uses the link itself and adds nothing.
    again, _ = _run_async(_sign_in(postgres_harness, tenant_id=tenant_id, provider=provider))
    assert again == "success"
    assert len(_identities(postgres_harness, ISSUERS[provider_name], subject)) == 1
    assert _sessions_of(postgres_harness, person_id) == 2
    assert len(_link_notices_for(postgres_harness, person_id)) == 1


@pytest.mark.parametrize(
    ("provider_name", "verified", "staff"),
    [
        ("facebook", True, False),
        ("google", False, False),
        ("apple", True, True),
        ("google", True, True),
    ],
    ids=["facebook-never-links", "unverified-account", "apple-staff", "google-staff"],
)
def test_an_email_that_may_not_be_linked_is_refused_and_changes_nothing(
    postgres_harness: _Harness, provider_name: str, verified: bool, staff: bool
) -> None:
    email = f"kept-{uuid4().hex}@example.test"
    tenant_id, person_id = _seed(postgres_harness, email=email, verified=verified, staff=staff)
    assert person_id is not None
    subject = f"{provider_name}-subject-{uuid4().hex}"
    provider = _Provider(provider_name, email=email, subject=subject)

    result, finished = _run_async(
        _sign_in(postgres_harness, tenant_id=tenant_id, provider=provider)
    )

    assert result == "account_exists"
    assert "ac_session" not in finished.cookies
    assert _identities(postgres_harness, ISSUERS[provider_name], subject) == []
    assert _people_with_email(postgres_harness, email) == 1
    assert _sessions_of(postgres_harness, person_id) == 0
    assert _link_notices_for(postgres_harness, person_id) == []
    with Session(postgres_harness.engine) as database:
        person = database.get(Person, person_id)
        assert person is not None and person.consent_version == "provider-sign-in-consent-v1"
        assert database.get(Membership, (tenant_id, person_id)) is None
        # The refusal itself is recorded apart from the rolled-back sign-in.
        [refusal] = database.scalars(
            select(AuditEvent).where(
                AuditEvent.action == SIGN_IN_REFUSED_ACTION,
                AuditEvent.resource_id == str(person_id),
            )
        )
        expected_reason = (
            "provider_never_links"
            if provider_name == "facebook"
            else "account_email_unverified"
            if not verified
            else "platform_staff"
        )
        assert refusal.payload == {
            "provider": provider_name,
            "reason": expected_reason,
            "ip_address": "127.0.0.1",
        }
        assert refusal.actor_person_id is None and refusal.actor_type == "system"


@pytest.mark.parametrize(
    ("provider_name", "email"),
    [
        ("facebook", "new-facebook-{}@example.test"),
        ("apple", "{}@privaterelay.appleid.com"),
    ],
)
def test_a_new_email_creates_one_account_and_the_next_sign_in_reuses_it(
    postgres_harness: _Harness, provider_name: str, email: str
) -> None:
    tenant_id, _ = _seed(postgres_harness)
    address = email.format(uuid4().hex)
    subject = f"{provider_name}-subject-{uuid4().hex}"
    provider = _Provider(provider_name, email=address, subject=subject)

    first, _ = _run_async(_sign_in(postgres_harness, tenant_id=tenant_id, provider=provider))
    second, _ = _run_async(_sign_in(postgres_harness, tenant_id=tenant_id, provider=provider))

    assert (first, second) == ("success", "success")
    [identity] = _identities(postgres_harness, ISSUERS[provider_name], subject)
    assert _people_with_email(postgres_harness, address) == 1
    with Session(postgres_harness.engine) as database:
        person = database.get(Person, identity.person_id)
        assert person is not None and person.email == address
        assert person.email_verified_at is not None
        assert database.get(Membership, (tenant_id, identity.person_id)) is not None
        assert (
            database.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.actor_person_id == identity.person_id,
                    AuditEvent.action == LINK_ACTION,
                )
            )
            == 0
        )
    assert _sessions_of(postgres_harness, identity.person_id) == 2


def test_a_provider_that_shares_no_email_writes_nothing(postgres_harness: _Harness) -> None:
    tenant_id, _ = _seed(postgres_harness)
    subject = f"facebook-subject-{uuid4().hex}"
    provider = _Provider("facebook", email="unused@example.test", subject=subject)
    provider.email = None

    result, finished = _run_async(
        _sign_in(postgres_harness, tenant_id=tenant_id, provider=provider)
    )

    assert result == "no_email"
    assert "ac_session" not in finished.cookies
    assert _identities(postgres_harness, ISSUERS["facebook"], subject) == []


@pytest.mark.parametrize("provider_name", ["google", "apple"])
def test_a_provider_email_that_is_not_verified_never_links(
    postgres_harness: _Harness, provider_name: str
) -> None:
    email = f"unverified-at-provider-{uuid4().hex}@example.test"
    tenant_id, person_id = _seed(postgres_harness, email=email)
    assert person_id is not None
    subject = f"{provider_name}-subject-{uuid4().hex}"
    provider = _Provider(provider_name, email=email, subject=subject)
    provider.email_verified = False

    result, finished = _run_async(
        _sign_in(postgres_harness, tenant_id=tenant_id, provider=provider)
    )

    assert result == "failed"
    assert "ac_session" not in finished.cookies
    assert _identities(postgres_harness, ISSUERS[provider_name], subject) == []
    assert _sessions_of(postgres_harness, person_id) == 0
    assert _link_notices_for(postgres_harness, person_id) == []
    with Session(postgres_harness.engine) as database:
        person = database.get(Person, person_id)
        assert person is not None and person.consent_version == "provider-sign-in-consent-v1"
        assert database.get(Membership, (tenant_id, person_id)) is None
