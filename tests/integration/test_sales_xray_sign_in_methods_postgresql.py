"""PostgreSQL proof: Settings -> Security -> Sign-in methods lists the ways in and removes
a provider only after a fresh sign-in, never the last way in, with an audit event and an
email notice."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from ac_platform.audit.models import AuditEvent
from ac_platform.http.auth import install_identity_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.http.routes import RouteContext
from ac_platform.http.routes.sign_in_methods import install as install_sign_in_methods
from ac_platform.identity.application import (
    AsyncIdentityApplication,
    has_platform_staff_membership,
)
from ac_platform.identity.email_login import EmailLoginCodeService
from ac_platform.identity.models import PasswordCredential, Person, ProviderIdentity
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.identity.provider_link_email import (
    PROVIDER_REMOVED_ACTION,
    PROVIDER_REMOVED_EVENT,
)
from ac_platform.outbox.models import OutboxEvent
from ac_platform.tenancy.models import (
    Membership,
    MembershipRole,
    MembershipStatus,
    Organisation,
    Tenant,
)
from tests.integration.test_password_identity_http_postgresql import _Harness, _run_async
from tests.integration.test_password_identity_http_postgresql import (
    postgres_harness as _postgres_harness,
)
from tests.integration.test_sales_xray_provider_sign_in_postgresql import (
    SALES_ORIGIN,
    _settings,
)

GOOGLE = "https://accounts.google.com"


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[_Harness]:
    yield from _postgres_harness.__wrapped__()


def _seed(
    harness: _Harness,
    *,
    password: bool,
    providers: tuple[str, ...],
    staff: bool = False,
    role: str = MembershipRole.ADMIN.value,
    organisation: bool = False,
) -> tuple[UUID, UUID]:
    tenant_id, person_id = uuid4(), uuid4()
    verified = datetime(2026, 9, 1, tzinfo=UTC)
    with Session(harness.engine) as database, database.begin():
        database.add(Tenant(id=tenant_id, slug=f"sx-methods-{tenant_id.hex}", name="Synthetic"))
        database.add(
            Person(
                id=person_id,
                email=f"methods-{person_id.hex}@example.test",
                email_verified_at=verified,
                consent_version="v1",
                consented_at=verified,
            )
        )
        database.flush()
        if password:
            database.add(PasswordCredential(person_id=person_id, password_hash="x" * 60))
        for issuer in providers:
            database.add(
                ProviderIdentity(
                    person_id=person_id,
                    issuer=issuer,
                    subject=f"{issuer}-{person_id.hex}",
                    last_authenticated_at=datetime(2026, 10, 18, 9, tzinfo=UTC),
                )
            )
        if staff:
            staff_tenant = uuid4()
            database.add(Tenant(id=staff_tenant, slug=f"sx-ops-{staff_tenant.hex}", name="Ops"))
            database.flush()
            if organisation:
                # A customer organisation: its admins are not platform staff.
                database.add(
                    Organisation(
                        tenant_id=staff_tenant,
                        created_by_person_id=person_id,
                        creation_command_id=uuid4(),
                        domain_verification_token=uuid4().hex * 2,
                    )
                )
            database.add(
                Membership(
                    tenant_id=staff_tenant,
                    person_id=person_id,
                    role=role,
                    status=MembershipStatus.ACTIVE.value,
                )
            )
    return tenant_id, person_id


async def _call(
    harness: _Harness,
    *,
    tenant_id: UUID,
    person_id: UUID,
    age: timedelta,
    method: str,
    path: str,
    origin: str = SALES_ORIGIN,
) -> httpx.Response:
    engine = create_async_engine(harness.schema_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    settings = _settings(harness, tenant_id=tenant_id)
    try:
        async with sessions() as database, database.begin():
            issued = await AsyncIdentityApplication(
                database, token_pepper=settings.session_token_pepper.get_secret_value()
            ).issue_authenticated_session(person_id, user_agent="test", ip_address=None)
            if age:
                await database.execute(
                    update(IdentitySession)
                    .where(IdentitySession.id == issued.metadata.id)
                    .values(created_at=datetime.now(UTC) - age)
                )
        application = FastAPI()
        register_problem_handlers(application)
        require_actor = install_identity_http(application, settings=settings, sessions=sessions)
        install_sign_in_methods(
            application,
            RouteContext(settings=settings, require_actor=require_actor, sessions=sessions),
        )
        transport = httpx.ASGITransport(app=application, client=("127.0.0.1", 12345))
        async with httpx.AsyncClient(
            transport=transport,
            base_url=SALES_ORIGIN,
            cookies={settings.session_cookie_name: issued.token},
        ) as client:
            return await client.request(method, path, headers={"origin": origin})
    finally:
        await engine.dispose()


def _google_rows(harness: _Harness, person_id: UUID) -> int:
    with Session(harness.engine) as database:
        return int(
            database.scalar(
                select(func.count())
                .select_from(ProviderIdentity)
                .where(ProviderIdentity.person_id == person_id, ProviderIdentity.issuer == GOOGLE)
            )
            or 0
        )


def _removals(harness: _Harness, person_id: UUID) -> tuple[list[AuditEvent], list[OutboxEvent]]:
    with Session(harness.engine) as database:
        events = list(
            database.scalars(
                select(AuditEvent).where(
                    AuditEvent.actor_person_id == person_id,
                    AuditEvent.action == PROVIDER_REMOVED_ACTION,
                )
            )
        )
        notices = list(
            database.scalars(
                select(OutboxEvent).where(
                    OutboxEvent.event_type == PROVIDER_REMOVED_EVENT,
                    OutboxEvent.aggregate_id == person_id,
                )
            )
        )
        return events, notices


def test_lists_each_way_in_with_when_it_was_added_and_last_used(
    postgres_harness: _Harness,
) -> None:
    tenant_id, person_id = _seed(postgres_harness, password=True, providers=(GOOGLE,))
    response = _run_async(
        _call(
            postgres_harness,
            tenant_id=tenant_id,
            person_id=person_id,
            age=timedelta(0),
            method="GET",
            path="/v1/me/sign-in-methods",
        )
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    body = response.json()
    assert [method["kind"] for method in body["methods"]] == ["email_code", "password", "google"]
    google = body["methods"][2]
    assert google["removable"] is True
    assert google["added_at"] is not None
    assert google["last_used_at"].startswith("2026-10-18T09:00")
    assert body["fresh_sign_in"] is True and body["fresh_minutes"] == 10


def test_a_fresh_session_removes_google_with_an_audit_event_and_a_notice(
    postgres_harness: _Harness,
) -> None:
    tenant_id, person_id = _seed(postgres_harness, password=True, providers=(GOOGLE,))
    response = _run_async(
        _call(
            postgres_harness,
            tenant_id=tenant_id,
            person_id=person_id,
            age=timedelta(minutes=2),
            method="POST",
            path="/v1/me/sign-in-methods/google/remove",
        )
    )
    assert response.status_code == 200 and response.json() == {"removed": "google"}
    assert _google_rows(postgres_harness, person_id) == 0
    [event], [notice] = _removals(postgres_harness, person_id)
    assert event.payload == {"provider": "google", "ip_address": "127.0.0.1"}
    assert notice.payload == {"audit_event_id": str(event.id)}


@pytest.mark.parametrize(
    ("password", "staff", "age", "status", "code"),
    [
        (True, False, timedelta(minutes=20), 409, "fresh_sign_in"),
        (False, True, timedelta(minutes=1), 409, "last_method"),
    ],
    ids=["stale-session", "staff-last-way-in"],
)
def test_removal_is_refused_and_changes_nothing(
    postgres_harness: _Harness,
    password: bool,
    staff: bool,
    age: timedelta,
    status: int,
    code: str,
) -> None:
    tenant_id, person_id = _seed(
        postgres_harness, password=password, providers=(GOOGLE,), staff=staff
    )
    response = _run_async(
        _call(
            postgres_harness,
            tenant_id=tenant_id,
            person_id=person_id,
            age=age,
            method="POST",
            path="/v1/me/sign-in-methods/google/remove",
        )
    )
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code
    assert _google_rows(postgres_harness, person_id) == 1
    assert _removals(postgres_harness, person_id) == ([], [])


def test_staff_see_no_email_code_and_their_only_provider_is_not_removable(
    postgres_harness: _Harness,
) -> None:
    tenant_id, person_id = _seed(postgres_harness, password=False, providers=(GOOGLE,), staff=True)
    body = _run_async(
        _call(
            postgres_harness,
            tenant_id=tenant_id,
            person_id=person_id,
            age=timedelta(0),
            method="GET",
            path="/v1/me/sign-in-methods",
        )
    ).json()
    assert body["methods"] == [
        {
            "kind": "google",
            "added_at": body["methods"][0]["added_at"],
            "last_used_at": body["methods"][0]["last_used_at"],
            "removable": False,
        }
    ]


def test_another_origin_or_a_missing_provider_is_refused(postgres_harness: _Harness) -> None:
    tenant_id, person_id = _seed(postgres_harness, password=True, providers=(GOOGLE,))
    foreign = _run_async(
        _call(
            postgres_harness,
            tenant_id=tenant_id,
            person_id=person_id,
            age=timedelta(0),
            method="POST",
            path="/v1/me/sign-in-methods/google/remove",
            origin="https://attacker.example",
        )
    )
    assert foreign.status_code == 403
    missing = _run_async(
        _call(
            postgres_harness,
            tenant_id=tenant_id,
            person_id=person_id,
            age=timedelta(0),
            method="POST",
            path="/v1/me/sign-in-methods/apple/remove",
        )
    )
    assert missing.status_code == 404
    assert _google_rows(postgres_harness, person_id) == 1


@pytest.mark.parametrize("role", ["owner", "admin", "support"])
def test_platform_staff_email_code_never_counts_so_their_only_provider_stays(
    postgres_harness: _Harness, role: str
) -> None:
    """Email codes are never sent to owner, admin or support staff, so with only
    Google and an email address, Google is their last way in."""

    tenant_id, person_id = _seed(
        postgres_harness, password=False, providers=(GOOGLE,), staff=True, role=role
    )
    listing = _run_async(
        _call(
            postgres_harness,
            tenant_id=tenant_id,
            person_id=person_id,
            age=timedelta(0),
            method="GET",
            path="/v1/me/sign-in-methods",
        )
    ).json()
    assert [(item["kind"], item["removable"]) for item in listing["methods"]] == [("google", False)]
    response = _run_async(
        _call(
            postgres_harness,
            tenant_id=tenant_id,
            person_id=person_id,
            age=timedelta(minutes=1),
            method="POST",
            path="/v1/me/sign-in-methods/google/remove",
        )
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "last_method"
    assert _google_rows(postgres_harness, person_id) == 1
    assert _removals(postgres_harness, person_id) == ([], [])


def test_a_customer_organisation_admin_keeps_email_codes_so_google_can_go(
    postgres_harness: _Harness,
) -> None:
    """Organisation owners and admins do get email codes, so a code still counts."""

    tenant_id, person_id = _seed(
        postgres_harness,
        password=False,
        providers=(GOOGLE,),
        staff=True,
        role=MembershipRole.ADMIN.value,
        organisation=True,
    )
    response = _run_async(
        _call(
            postgres_harness,
            tenant_id=tenant_id,
            person_id=person_id,
            age=timedelta(minutes=1),
            method="POST",
            path="/v1/me/sign-in-methods/google/remove",
        )
    )
    assert response.status_code == 200
    assert _google_rows(postgres_harness, person_id) == 0


@pytest.mark.parametrize(
    ("role", "organisation"),
    [
        ("owner", False),
        ("admin", False),
        ("support", False),
        ("owner", True),
        ("admin", True),
        ("member", False),
    ],
)
def test_the_email_code_rule_and_the_removal_rule_name_the_same_staff(
    postgres_harness: _Harness, role: str, organisation: bool
) -> None:
    """Sign-in methods count an email code exactly where the email-code service sends one."""

    _, person_id = _seed(
        postgres_harness,
        password=False,
        providers=(),
        staff=True,
        role=role,
        organisation=organisation,
    )

    async def compare() -> tuple[bool, bool]:
        engine = create_async_engine(postgres_harness.schema_url, pool_pre_ping=True)
        try:
            async with async_sessionmaker(engine)() as database:
                email_rule = await EmailLoginCodeService(
                    database,
                    challenge_secret="x" * 40,  # noqa: S106
                )._has_privileged_membership(person_id)
                removal_rule = await has_platform_staff_membership(database, person_id)
                return email_rule, removal_rule
        finally:
            await engine.dispose()

    email_rule, removal_rule = _run_async(compare())
    assert email_rule == removal_rule
    assert email_rule is (role in {"owner", "admin", "support"} and not organisation)
