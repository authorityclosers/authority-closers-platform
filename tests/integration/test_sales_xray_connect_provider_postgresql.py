"""PostgreSQL proof: Settings -> Connect adds Google, Apple or Facebook to the signed-in
Sales Xray account (owner, 20 Oct 2026), by page redirect, right after a sign-in."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit
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
from ac_platform.identity.application import AsyncIdentityApplication
from ac_platform.identity.models import ProviderAuthorizationTransaction, ProviderIdentity
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.identity.provider_link_email import (
    PROVIDER_CONNECTED_ACTION,
    PROVIDER_CONNECTED_EVENT,
)
from ac_platform.outbox.models import OutboxEvent
from tests.integration.test_password_identity_http_postgresql import _Harness, _run_async
from tests.integration.test_password_identity_http_postgresql import (
    postgres_harness as _postgres_harness,
)
from tests.integration.test_sales_xray_provider_sign_in_postgresql import (
    ISSUERS,
    SALES_ORIGIN,
    _Provider,
    _settings,
)
from tests.integration.test_sales_xray_sign_in_methods_postgresql import _seed


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[_Harness]:
    yield from _postgres_harness.__wrapped__()


async def _connect(
    harness: _Harness,
    *,
    tenant_id: UUID,
    person_id: UUID | None,
    provider: _Provider,
    age: timedelta = timedelta(minutes=1),
    app_challenge: str | None = None,
) -> tuple[str, httpx.Response, dict[str, object]]:
    """Start a Connect from Settings and finish it; returns the result and the listing."""

    engine = create_async_engine(harness.schema_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    settings = _settings(harness, tenant_id=tenant_id)
    try:
        cookies: dict[str, str] = {}
        if person_id is not None:
            async with sessions() as database, database.begin():
                issued = await AsyncIdentityApplication(
                    database, token_pepper=settings.session_token_pepper.get_secret_value()
                ).issue_authenticated_session(person_id, user_agent="test", ip_address=None)
                await database.execute(
                    update(IdentitySession)
                    .where(IdentitySession.id == issued.metadata.id)
                    .values(created_at=datetime.now(UTC) - age)
                )
            cookies[settings.session_cookie_name] = issued.token
        application = FastAPI()
        register_problem_handlers(application)
        google = provider if provider.name == "google" else None
        require_actor = install_identity_http(
            application,
            settings=settings,
            sessions=sessions,
            provider=google,
            extra_providers={} if google is not None else {provider.name: provider},
        )
        install_sign_in_methods(
            application,
            RouteContext(settings=settings, require_actor=require_actor, sessions=sessions),
        )
        transport = httpx.ASGITransport(app=application, client=("127.0.0.1", 12345))
        async with httpx.AsyncClient(
            transport=transport, base_url=SALES_ORIGIN, cookies=cookies
        ) as client:
            params = {
                "action": "link",
                "surface": "sales_xray",
                "return_path": f"/auth/complete?flow={uuid4()}",
            }
            if app_challenge is not None:
                params["app_challenge"] = app_challenge
            started = await client.get(
                f"/v1/auth/{provider.name}/start", params=params, follow_redirects=False
            )
            assert started.status_code == 303
            location = urlsplit(started.headers["location"])
            if location.path == "/auth/complete":
                finished = started
            elif provider.name == "apple":
                # Apple's cross-site form_post, then the same-site GET it redirects to.
                transaction = provider.transactions[-1]
                posted = await client.post(
                    "/v1/auth/apple/callback",
                    data={"state": transaction.state, "code": "apple-code"},
                    headers={"origin": "https://appleid.apple.com"},
                    follow_redirects=False,
                )
                finished = await client.get(posted.headers["location"], follow_redirects=False)
            else:
                transaction = provider.transactions[-1]
                finished = await client.get(
                    f"/v1/auth/{provider.name}/callback",
                    params={"state": transaction.state, "code": f"{provider.name}-code"},
                    follow_redirects=False,
                )
            assert finished.status_code == 303
            result = parse_qs(urlsplit(finished.headers["location"]).query)["auth_result"][0]
            listing = (
                (await client.get("/v1/me/sign-in-methods")).json() if person_id is not None else {}
            )
            return result, finished, listing
    finally:
        await engine.dispose()


def _rows(harness: _Harness, issuer: str, subject: str) -> list[ProviderIdentity]:
    with Session(harness.engine) as database:
        return list(
            database.scalars(
                select(ProviderIdentity).where(
                    ProviderIdentity.issuer == issuer, ProviderIdentity.subject == subject
                )
            )
        )


def _connected(harness: _Harness, person_id: UUID) -> tuple[list[AuditEvent], list[OutboxEvent]]:
    with Session(harness.engine) as database:
        events = list(
            database.scalars(
                select(AuditEvent).where(
                    AuditEvent.actor_person_id == person_id,
                    AuditEvent.action == PROVIDER_CONNECTED_ACTION,
                )
            )
        )
        notices = list(
            database.scalars(
                select(OutboxEvent).where(
                    OutboxEvent.event_type == PROVIDER_CONNECTED_EVENT,
                    OutboxEvent.aggregate_id == person_id,
                )
            )
        )
        return events, notices


@pytest.mark.parametrize("provider_name", ["facebook", "google", "apple"])
def test_a_fresh_session_connects_a_provider_whose_email_differs(
    postgres_harness: _Harness, provider_name: str
) -> None:
    tenant_id, person_id = _seed(postgres_harness, password=True, providers=())
    subject = f"{provider_name}-connect-{uuid4().hex}"
    provider = _Provider(provider_name, email=f"other-{uuid4().hex}@example.test", subject=subject)

    result, finished, listing = _run_async(
        _connect(postgres_harness, tenant_id=tenant_id, person_id=person_id, provider=provider)
    )

    assert result == "linked"
    # The session that connected stays; no new one is issued.
    assert "ac_session" not in finished.cookies
    [row] = _rows(postgres_harness, ISSUERS[provider_name], subject)
    assert row.person_id == person_id
    [event], [notice] = _connected(postgres_harness, person_id)
    assert event.payload == {"provider": provider_name, "ip_address": "127.0.0.1"}
    assert notice.payload == {"audit_event_id": str(event.id)}
    providers = listing["providers"]
    assert isinstance(providers, dict)
    assert providers[provider_name] == {"linked": True, "can_connect": False}
    assert provider_name in [method["kind"] for method in listing["methods"]]  # type: ignore[index, union-attr]


def test_connect_offers_only_configured_providers_not_yet_linked(
    postgres_harness: _Harness,
) -> None:
    tenant_id, person_id = _seed(postgres_harness, password=True, providers=())
    provider = _Provider(
        "facebook", email=f"x-{uuid4().hex}@example.test", subject=f"fb-{uuid4().hex}"
    )
    _, _, listing = _run_async(
        _connect(
            postgres_harness,
            tenant_id=tenant_id,
            person_id=person_id,
            provider=provider,
            age=timedelta(minutes=30),
        )
    )
    assert listing["providers"] == {
        "google": {"linked": False, "can_connect": False},  # not configured here
        "apple": {"linked": False, "can_connect": False},
        "facebook": {"linked": False, "can_connect": True},
    }


def test_a_stale_session_is_asked_to_sign_in_again_before_anything_starts(
    postgres_harness: _Harness,
) -> None:
    tenant_id, person_id = _seed(postgres_harness, password=True, providers=())
    provider = _Provider(
        "facebook", email=f"x-{uuid4().hex}@example.test", subject=f"fb-{uuid4().hex}"
    )
    result, _, _ = _run_async(
        _connect(
            postgres_harness,
            tenant_id=tenant_id,
            person_id=person_id,
            provider=provider,
            age=timedelta(minutes=20),
        )
    )
    assert result == "fresh_sign_in"
    assert provider.transactions == []
    with Session(postgres_harness.engine) as database:
        assert (
            database.scalar(
                select(func.count())
                .select_from(ProviderAuthorizationTransaction)
                .where(ProviderAuthorizationTransaction.person_id == person_id)
            )
            == 0
        )


def test_a_provider_account_already_on_another_account_is_refused(
    postgres_harness: _Harness,
) -> None:
    _, other_id = _seed(postgres_harness, password=True, providers=())
    subject = f"fb-taken-{uuid4().hex}"
    with Session(postgres_harness.engine) as database, database.begin():
        database.add(
            ProviderIdentity(person_id=other_id, issuer=ISSUERS["facebook"], subject=subject)
        )
    tenant_id, person_id = _seed(postgres_harness, password=True, providers=())
    provider = _Provider("facebook", email=f"x-{uuid4().hex}@example.test", subject=subject)

    result, _, _ = _run_async(
        _connect(postgres_harness, tenant_id=tenant_id, person_id=person_id, provider=provider)
    )

    assert result == "already_linked"
    [row] = _rows(postgres_harness, ISSUERS["facebook"], subject)
    assert row.person_id == other_id
    assert _connected(postgres_harness, person_id) == ([], [])


def test_connecting_a_provider_already_on_this_account_changes_nothing(
    postgres_harness: _Harness,
) -> None:
    subject = f"fb-mine-{uuid4().hex}"
    tenant_id, person_id = _seed(postgres_harness, password=True, providers=())
    with Session(postgres_harness.engine) as database, database.begin():
        database.add(
            ProviderIdentity(person_id=person_id, issuer=ISSUERS["facebook"], subject=subject)
        )
    provider = _Provider("facebook", email=f"x-{uuid4().hex}@example.test", subject=subject)

    result, _, _ = _run_async(
        _connect(postgres_harness, tenant_id=tenant_id, person_id=person_id, provider=provider)
    )

    assert result == "linked"
    assert len(_rows(postgres_harness, ISSUERS["facebook"], subject)) == 1
    assert _connected(postgres_harness, person_id) == ([], [])


def test_signed_out_or_from_the_phone_app_tab_connect_is_refused(
    postgres_harness: _Harness,
) -> None:
    tenant_id, person_id = _seed(postgres_harness, password=True, providers=())
    provider = _Provider(
        "facebook", email=f"x-{uuid4().hex}@example.test", subject=f"fb-{uuid4().hex}"
    )
    signed_out, _, _ = _run_async(
        _connect(postgres_harness, tenant_id=tenant_id, person_id=None, provider=provider)
    )
    from_app, _, _ = _run_async(
        _connect(
            postgres_harness,
            tenant_id=tenant_id,
            person_id=person_id,
            provider=provider,
            app_challenge="A" * 43,
        )
    )
    assert (signed_out, from_app) == ("failed", "failed")
    assert provider.transactions == []
    assert _connected(postgres_harness, person_id) == ([], [])
