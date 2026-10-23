"""PostgreSQL proof: Google and Facebook sign-in inside the Android app (owner, 23 Oct
2026: no jump to Chrome). The page starts a transaction by fetch, the phone's own
sign-in hands it a token, and the page posts that token; the account rules are the
web flow's: Google links by verified email, Facebook never does, staff never."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from ac_platform.audit.models import AuditEvent
from ac_platform.http.auth import install_identity_http
from ac_platform.http.auth_transactions import AuthTransaction
from ac_platform.http.identity_provider import IdentityProviderRejected
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.services import VerifiedProviderAssertion
from tests.integration.test_password_identity_http_postgresql import _Harness, _run_async
from tests.integration.test_password_identity_http_postgresql import (
    postgres_harness as _postgres_harness,
)
from tests.integration.test_sales_xray_provider_sign_in_postgresql import (
    CONSENT_VERSION,
    ISSUERS,
    LINK_ACTION,
    SALES_ORIGIN,
    _identities,
    _link_notices_for,
    _people_with_email,
    _Provider,
    _seed,
    _sessions_of,
    _settings,
)

CLIENT_TOKEN = "fixture-facebook-client-token"  # noqa: S105


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[_Harness]:
    yield from _postgres_harness.__wrapped__()


class _PhoneProvider(_Provider):
    """The phone's token double: this path never exchanges an authorization code."""

    def __init__(self, name: str, *, email: str, subject: str) -> None:
        super().__init__(name, email=email, subject=subject)
        self.token = f"{name}-token-from-the-phone"
        self.nonces: list[str] = []

    async def exchange_code(self, *args: Any, **kwargs: Any) -> VerifiedProviderAssertion:
        raise AssertionError("sign-in on the phone never exchanges a code")

    async def verify_native_token(
        self,
        token: str,
        transaction: AuthTransaction,
        *,
        callback_state: str,
    ) -> VerifiedProviderAssertion:
        if token != self.token:
            raise IdentityProviderRejected("not a token the provider issued")
        self.nonces.append(transaction.nonce)
        return await super().exchange_code(
            f"{self.name}-code",
            transaction,
            callback_state=callback_state,
            redirect_uri=f"{SALES_ORIGIN}/v1/auth/{self.name}/callback",
        )


async def _phone_sign_in(
    harness: _Harness,
    *,
    tenant_id: UUID,
    provider: _PhoneProvider,
    token: str | None = None,
    client_token: str | None = CLIENT_TOKEN,
    action: str = "authenticate",
    finish_as: str | None = None,
    finish_origin: str = SALES_ORIGIN,
) -> tuple[httpx.Response, httpx.Response | None]:
    """Native start by fetch, then the page's form post with the phone's token."""

    engine = create_async_engine(harness.schema_url, pool_pre_ping=True)
    settings = _settings(harness, tenant_id=tenant_id).model_copy(
        update={
            "facebook_login_client_token": (
                SecretStr(client_token) if client_token is not None else None
            )
        }
    )
    try:
        application = FastAPI()
        register_problem_handlers(application)
        google = provider if provider.name == "google" else None
        install_identity_http(
            application,
            settings=settings,
            sessions=async_sessionmaker(engine, expire_on_commit=False),
            provider=google,
            extra_providers={} if google is not None else {provider.name: provider},
        )
        transport = httpx.ASGITransport(app=application, client=("127.0.0.1", 12345))
        async with httpx.AsyncClient(
            transport=transport, base_url=SALES_ORIGIN, headers={"origin": SALES_ORIGIN}
        ) as client:
            started = await client.post(
                f"/v1/auth/{provider.name}/native/start",
                json={
                    "action": action,
                    "return_path": f"/auth/complete?flow={uuid4()}",
                    "consent": True,
                    "age_attested": True,
                    "consent_version": CONSENT_VERSION,
                },
            )
            if started.status_code != 200:
                return started, None
            finished = await client.post(
                f"/v1/auth/{finish_as or provider.name}/native/finish",
                data={"state": started.json()["state"], "token": token or provider.token},
                headers={"origin": finish_origin},
                follow_redirects=False,
            )
            return started, finished
    finally:
        await engine.dispose()


def _result(finished: httpx.Response | None) -> str:
    assert finished is not None and finished.status_code == 303
    return parse_qs(urlsplit(finished.headers["location"]).query)["auth_result"][0]


def test_google_on_the_phone_links_a_verified_email_like_the_web(
    postgres_harness: _Harness,
) -> None:
    email = f"phone.{uuid4().hex}@example.test"
    tenant_id, person_id = _seed(postgres_harness, email=email)
    assert person_id is not None
    subject = f"google-phone-{uuid4().hex}"
    provider = _PhoneProvider("google", email=email, subject=subject)

    started, finished = _run_async(
        _phone_sign_in(postgres_harness, tenant_id=tenant_id, provider=provider)
    )

    # What the phone needs for Android's account sheet: our web client and the nonce.
    answer = started.json()
    assert set(answer) == {"state", "nonce", "client_id"}
    assert answer["client_id"] == provider.audience
    assert started.headers["cache-control"] == "no-store"
    assert _result(finished) == "success"
    assert finished is not None and finished.cookies.get("ac_session")
    assert provider.nonces == [answer["nonce"]]
    [identity] = _identities(postgres_harness, ISSUERS["google"], subject)
    assert identity.person_id == person_id
    assert _people_with_email(postgres_harness, email) == 1
    assert _sessions_of(postgres_harness, person_id) == 1
    with Session(postgres_harness.engine) as database:
        [event] = database.scalars(
            select(AuditEvent).where(
                AuditEvent.actor_person_id == person_id, AuditEvent.action == LINK_ACTION
            )
        )
        assert event.payload == {"provider": "google", "ip_address": "127.0.0.1"}
    assert len(_link_notices_for(postgres_harness, person_id)) == 1


@pytest.mark.parametrize("staff", [False, True], ids=["facebook-never-links", "google-staff"])
def test_an_email_that_may_not_be_linked_is_refused_on_the_phone_too(
    postgres_harness: _Harness, staff: bool
) -> None:
    email = f"kept-phone-{uuid4().hex}@example.test"
    tenant_id, person_id = _seed(postgres_harness, email=email, staff=staff)
    assert person_id is not None
    name = "google" if staff else "facebook"
    subject = f"{name}-phone-{uuid4().hex}"
    provider = _PhoneProvider(name, email=email, subject=subject)

    _, finished = _run_async(
        _phone_sign_in(postgres_harness, tenant_id=tenant_id, provider=provider)
    )

    assert _result(finished) == "account_exists"
    assert finished is not None and "ac_session" not in finished.cookies
    assert _identities(postgres_harness, ISSUERS[name], subject) == []
    assert _sessions_of(postgres_harness, person_id) == 0
    assert _link_notices_for(postgres_harness, person_id) == []


@pytest.mark.parametrize("provider_name", ["google", "facebook"])
def test_a_new_person_on_the_phone_gets_one_account_and_comes_back_to_it(
    postgres_harness: _Harness, provider_name: str
) -> None:
    tenant_id, _ = _seed(postgres_harness)
    email = f"new-phone-{provider_name}-{uuid4().hex}@example.test"
    subject = f"{provider_name}-phone-{uuid4().hex}"
    provider = _PhoneProvider(provider_name, email=email, subject=subject)

    first_start, first = _run_async(
        _phone_sign_in(postgres_harness, tenant_id=tenant_id, provider=provider)
    )
    _, second = _run_async(_phone_sign_in(postgres_harness, tenant_id=tenant_id, provider=provider))

    assert (_result(first), _result(second)) == ("success", "success")
    if provider_name == "facebook":
        # What the phone needs to start the Facebook SDK for this environment.
        assert first_start.json()["app_id"] == provider.audience
        assert first_start.json()["client_token"] == CLIENT_TOKEN
    [identity] = _identities(postgres_harness, ISSUERS[provider_name], subject)
    assert _people_with_email(postgres_harness, email) == 1
    assert _sessions_of(postgres_harness, identity.person_id) == 2


def test_a_token_the_provider_does_not_vouch_for_signs_nobody_in(
    postgres_harness: _Harness,
) -> None:
    tenant_id, _ = _seed(postgres_harness)
    email = f"forged-{uuid4().hex}@example.test"
    subject = f"google-phone-{uuid4().hex}"
    provider = _PhoneProvider("google", email=email, subject=subject)

    _, finished = _run_async(
        _phone_sign_in(
            postgres_harness,
            tenant_id=tenant_id,
            provider=provider,
            token="forged.token.value",  # noqa: S106
        )
    )

    assert _result(finished) == "failed"
    assert finished is not None and "ac_session" not in finished.cookies
    assert _identities(postgres_harness, ISSUERS["google"], subject) == []
    assert _people_with_email(postgres_harness, email) == 0


def test_another_providers_finish_another_site_or_connect_never_sign_in(
    postgres_harness: _Harness,
) -> None:
    tenant_id, _ = _seed(postgres_harness)
    email = f"misused-{uuid4().hex}@example.test"
    provider = _PhoneProvider("google", email=email, subject=f"google-phone-{uuid4().hex}")

    # A Google transaction posted to the Facebook finish: the transaction is refused.
    _, crossed = _run_async(
        _phone_sign_in(
            postgres_harness, tenant_id=tenant_id, provider=provider, finish_as="facebook"
        )
    )
    # Another site posting the form: refused before anything is read.
    _, foreign = _run_async(
        _phone_sign_in(
            postgres_harness,
            tenant_id=tenant_id,
            provider=provider,
            finish_origin="https://evil.example.test",
        )
    )
    # Settings -> Connect is not offered on the phone.
    connect, nothing = _run_async(
        _phone_sign_in(postgres_harness, tenant_id=tenant_id, provider=provider, action="link")
    )

    assert _result(crossed) == "failed"
    assert foreign is not None and foreign.status_code == 403
    assert connect.status_code >= 400 and nothing is None
    assert provider.nonces == []
    assert _people_with_email(postgres_harness, email) == 0


def test_facebook_on_the_phone_waits_for_its_client_token(postgres_harness: _Harness) -> None:
    tenant_id, _ = _seed(postgres_harness)
    provider = _PhoneProvider(
        "facebook", email=f"later-{uuid4().hex}@example.test", subject=f"fb-{uuid4().hex}"
    )

    started, finished = _run_async(
        _phone_sign_in(postgres_harness, tenant_id=tenant_id, provider=provider, client_token=None)
    )

    # The page falls back to Facebook in the phone's browser; nothing was issued.
    assert started.status_code >= 400 and finished is None
    assert not [name for name in started.cookies if name.startswith("ac_oauth_transaction")]
