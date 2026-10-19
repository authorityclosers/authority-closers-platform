"""PostgreSQL proof: Settings -> Connect by POST, the contract the Settings pages use
(admin-2, 20 Oct 2026).

POST /v1/me/sign-in-methods/{provider}/connect {"return_to"} answers the provider's
address; the provider comes back through the callback, which goes to
return_to?connected=<provider> or ?connect_error=<in_use|cancelled|failed>.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from ac_platform.http.auth import install_identity_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.http.routes import RouteContext
from ac_platform.http.routes.sign_in_methods import install as install_sign_in_methods
from ac_platform.identity.application import AsyncIdentityApplication
from ac_platform.identity.models import ProviderAuthorizationTransaction, ProviderIdentity
from ac_platform.identity.models import Session as IdentitySession
from tests.integration.test_password_identity_http_postgresql import _Harness, _run_async
from tests.integration.test_password_identity_http_postgresql import (
    postgres_harness as _postgres_harness,
)
from tests.integration.test_sales_xray_connect_provider_postgresql import _connected, _rows
from tests.integration.test_sales_xray_provider_sign_in_postgresql import (
    ISSUERS,
    SALES_ORIGIN,
    _Provider,
    _settings,
)
from tests.integration.test_sales_xray_sign_in_methods_postgresql import _seed

SETTINGS_HASH = "/#settings/security"


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[_Harness]:
    yield from _postgres_harness.__wrapped__()


@asynccontextmanager
async def _sales_xray(
    harness: _Harness,
    *,
    tenant_id: UUID,
    person_id: UUID | None,
    provider: _Provider,
    age: timedelta = timedelta(minutes=1),
) -> AsyncIterator[httpx.AsyncClient]:
    """A Sales Xray browser, signed in ``age`` ago when ``person_id`` is given."""

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
            transport=transport,
            base_url=SALES_ORIGIN,
            cookies=cookies,
            headers={"origin": SALES_ORIGIN},
        ) as client:
            yield client
    finally:
        await engine.dispose()


async def _start(
    client: httpx.AsyncClient,
    provider: str,
    return_to: str = SETTINGS_HASH,
    **headers: str,
) -> httpx.Response:
    return await client.post(
        f"/v1/me/sign-in-methods/{provider}/connect",
        json={"return_to": return_to},
        headers=headers,
    )


async def _come_back(
    client: httpx.AsyncClient, provider: _Provider, *, error: str | None = None
) -> httpx.Response:
    """The provider sends the browser back to the callback."""

    transaction = provider.transactions[-1]
    answer = {"state": transaction.state}
    answer.update({"error": error} if error else {"code": f"{provider.name}-code"})
    if provider.name == "apple":
        # Apple's cross-site form_post, then the same-site GET it redirects to.
        posted = await client.post(
            "/v1/auth/apple/callback",
            data=answer,
            headers={"origin": "https://appleid.apple.com"},
            follow_redirects=False,
        )
        return await client.get(posted.headers["location"], follow_redirects=False)
    return await client.get(
        f"/v1/auth/{provider.name}/callback", params=answer, follow_redirects=False
    )


def _transactions(harness: _Harness, person_id: UUID) -> int:
    with Session(harness.engine) as database:
        return int(
            database.scalar(
                select(func.count())
                .select_from(ProviderAuthorizationTransaction)
                .where(ProviderAuthorizationTransaction.person_id == person_id)
            )
            or 0
        )


@pytest.mark.parametrize("provider_name", ["facebook", "google", "apple"])
def test_settings_connect_links_the_provider_and_goes_back_to_the_settings_hash(
    postgres_harness: _Harness, provider_name: str
) -> None:
    tenant_id, person_id = _seed(postgres_harness, password=True, providers=())
    subject = f"{provider_name}-settings-{uuid4().hex}"
    provider = _Provider(provider_name, email=f"other-{uuid4().hex}@example.test", subject=subject)

    async def scenario() -> tuple[httpx.Response, httpx.Response, dict[str, object]]:
        async with _sales_xray(
            postgres_harness, tenant_id=tenant_id, person_id=person_id, provider=provider
        ) as client:
            before = (await client.get("/v1/me/sign-in-methods")).json()
            started = await _start(client, provider_name)
            finished = await _come_back(client, provider)
            after = (await client.get("/v1/me/sign-in-methods")).json()
            return started, finished, {"before": before, "after": after}

    started, finished, listings = _run_async(scenario())

    assert started.status_code == 200
    assert started.headers["cache-control"] == "no-store"
    assert urlsplit(started.json()["redirect_url"]).netloc == f"{provider_name}.example.test"
    assert finished.status_code == 303
    assert finished.headers["location"] == (
        f"{SALES_ORIGIN}/?connected={provider_name}#settings/security"
    )
    # The session that connected stays; no new one is issued.
    assert "ac_session" not in finished.cookies
    [row] = _rows(postgres_harness, ISSUERS[provider_name], subject)
    assert row.person_id == person_id
    [event], [notice] = _connected(postgres_harness, person_id)
    assert event.payload == {"provider": provider_name, "ip_address": "127.0.0.1"}
    assert notice.payload == {"audit_event_id": str(event.id)}
    label = {"google": "Google", "apple": "Apple", "facebook": "Facebook"}[provider_name]
    assert listings["before"]["available"] == [  # type: ignore[index]
        {"kind": provider_name, "label": label, "connected": False}
    ]
    assert listings["after"]["available"] == [  # type: ignore[index]
        {"kind": provider_name, "label": label, "connected": True}
    ]


def test_a_plain_page_path_gets_the_outcome_in_its_query(postgres_harness: _Harness) -> None:
    tenant_id, person_id = _seed(postgres_harness, password=True, providers=())
    provider = _Provider(
        "facebook", email=f"x-{uuid4().hex}@example.test", subject=f"fb-{uuid4().hex}"
    )

    async def scenario() -> httpx.Response:
        async with _sales_xray(
            postgres_harness, tenant_id=tenant_id, person_id=person_id, provider=provider
        ) as client:
            started = await _start(client, "facebook", "/settings/security")
            assert started.status_code == 200
            return await _come_back(client, provider)

    finished = _run_async(scenario())
    assert finished.headers["location"] == f"{SALES_ORIGIN}/settings/security?connected=facebook"


def test_a_stale_session_gets_403_fresh_sign_in_and_nothing_starts(
    postgres_harness: _Harness,
) -> None:
    tenant_id, person_id = _seed(postgres_harness, password=True, providers=())
    provider = _Provider(
        "facebook", email=f"x-{uuid4().hex}@example.test", subject=f"fb-{uuid4().hex}"
    )

    async def scenario() -> httpx.Response:
        async with _sales_xray(
            postgres_harness,
            tenant_id=tenant_id,
            person_id=person_id,
            provider=provider,
            age=timedelta(minutes=20),
        ) as client:
            return await _start(client, "facebook")

    started = _run_async(scenario())
    assert started.status_code == 403
    assert started.json()["code"] == "fresh_sign_in"
    assert provider.transactions == []
    assert _transactions(postgres_harness, person_id) == 0


def test_a_provider_already_on_this_account_gets_409_already_connected(
    postgres_harness: _Harness,
) -> None:
    tenant_id, person_id = _seed(postgres_harness, password=True, providers=(ISSUERS["facebook"],))
    provider = _Provider(
        "facebook", email=f"x-{uuid4().hex}@example.test", subject=f"fb-{uuid4().hex}"
    )

    async def scenario() -> httpx.Response:
        async with _sales_xray(
            postgres_harness, tenant_id=tenant_id, person_id=person_id, provider=provider
        ) as client:
            return await _start(client, "facebook")

    started = _run_async(scenario())
    assert started.status_code == 409
    assert started.json() == {
        "detail": "Facebook is already connected.",
        "code": "already_connected",
    }
    assert provider.transactions == []


def test_a_provider_account_on_another_account_comes_back_in_use(
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

    async def scenario() -> httpx.Response:
        async with _sales_xray(
            postgres_harness, tenant_id=tenant_id, person_id=person_id, provider=provider
        ) as client:
            assert (await _start(client, "facebook")).status_code == 200
            return await _come_back(client, provider)

    finished = _run_async(scenario())
    assert finished.headers["location"] == (
        f"{SALES_ORIGIN}/?connect_error=in_use#settings/security"
    )
    [row] = _rows(postgres_harness, ISSUERS["facebook"], subject)
    assert row.person_id == other_id
    assert _connected(postgres_harness, person_id) == ([], [])


def test_cancelling_at_the_provider_or_signing_out_meanwhile_links_nothing(
    postgres_harness: _Harness,
) -> None:
    tenant_id, person_id = _seed(postgres_harness, password=True, providers=())
    subject = f"fb-{uuid4().hex}"
    provider = _Provider("facebook", email=f"x-{uuid4().hex}@example.test", subject=subject)

    async def scenario() -> tuple[httpx.Response, httpx.Response]:
        async with _sales_xray(
            postgres_harness, tenant_id=tenant_id, person_id=person_id, provider=provider
        ) as client:
            assert (await _start(client, "facebook")).status_code == 200
            cancelled = await _come_back(client, provider, error="access_denied")
            assert (await _start(client, "facebook")).status_code == 200
            for cookie in list(client.cookies.jar):
                if cookie.name.endswith("session"):
                    client.cookies.delete(cookie.name)
            signed_out = await _come_back(client, provider)
            return cancelled, signed_out

    cancelled, signed_out = _run_async(scenario())
    assert cancelled.headers["location"] == (
        f"{SALES_ORIGIN}/?connect_error=cancelled#settings/security"
    )
    assert signed_out.headers["location"] == (
        f"{SALES_ORIGIN}/?connect_error=failed#settings/security"
    )
    assert _rows(postgres_harness, ISSUERS["facebook"], subject) == []
    assert _connected(postgres_harness, person_id) == ([], [])


@pytest.mark.parametrize(
    "return_to",
    [
        "//evil.example.test/x",
        "https://evil.example.test/x",
        "/v1/me",
        "/auth/complete",
        "/auth",
        "/settings?next=/x",
        "/#other",
        "/../x",
        "/settings#settings/../x",
    ],
)
def test_only_a_sales_xray_page_may_be_returned_to(
    postgres_harness: _Harness, return_to: str
) -> None:
    tenant_id, person_id = _seed(postgres_harness, password=True, providers=())
    provider = _Provider(
        "facebook", email=f"x-{uuid4().hex}@example.test", subject=f"fb-{uuid4().hex}"
    )

    async def scenario() -> httpx.Response:
        async with _sales_xray(
            postgres_harness, tenant_id=tenant_id, person_id=person_id, provider=provider
        ) as client:
            return await _start(client, "facebook", return_to)

    started = _run_async(scenario())
    assert started.status_code == 422
    assert started.json()["code"] == "return_to"
    assert provider.transactions == []


def test_refusals_answer_with_a_code_and_start_nothing(postgres_harness: _Harness) -> None:
    tenant_id, person_id = _seed(postgres_harness, password=True, providers=())
    provider = _Provider(
        "facebook", email=f"x-{uuid4().hex}@example.test", subject=f"fb-{uuid4().hex}"
    )

    async def scenario() -> dict[str, httpx.Response]:
        answers: dict[str, httpx.Response] = {}
        async with _sales_xray(
            postgres_harness, tenant_id=tenant_id, person_id=person_id, provider=provider
        ) as client:
            answers["app"] = await _start(
                client, "facebook", **{"user-agent": "Mozilla/5.0 SalesXrayApp/0.3.64"}
            )
            answers["staff_key"] = await _start(
                client, "facebook", authorization="Bearer ac_staff_key_example"
            )
            answers["origin"] = await _start(client, "facebook", origin="https://evil.example.test")
            answers["not_configured"] = await _start(client, "apple")
        async with _sales_xray(
            postgres_harness, tenant_id=tenant_id, person_id=None, provider=provider
        ) as client:
            answers["signed_out"] = await _start(client, "facebook")
        return answers

    answers = _run_async(scenario())
    assert {
        name: (answer.status_code, answer.json()["code"]) for name, answer in answers.items()
    } == {
        "app": (409, "app_not_supported"),
        "staff_key": (403, "staff_key"),
        "origin": (403, "origin"),
        "not_configured": (404, "not_configured"),
        "signed_out": (401, "sign_in"),
    }
    assert provider.transactions == []
    assert _transactions(postgres_harness, person_id) == 0
