"""Developer platform on PostgreSQL: an organisation admin makes a key, an app uses it.

Settings -> Integrations makes a key (shown once, audited), the Sales X-Ray API answers
for that key's organisation within its scopes, revoking ends it, and a member who is
not an owner or admin cannot see the page. Sealed secrets open only for their own
organisation and not once retired. Disposable loopback PostgreSQL, fictional rows only.
"""

from __future__ import annotations

import base64
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import sessionmaker

from ac_platform.audit.models import AuditEvent
from ac_platform.http.routes import RouteContext
from ac_platform.integrations import keys, sealed
from ac_platform.integrations.api_http import install_integrations_api
from ac_platform.integrations.http import install_integrations_http
from ac_platform.integrations.models import IntegrationApiKey
from ac_platform.tenancy.models import Membership
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_lead_desk_postgresql import _organisation

WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
PAGE = "/v1/sales-xray/integrations"
SEAL = sealed.key_from(base64.urlsafe_b64encode(b"s" * 32).decode())


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def test_an_admin_makes_a_key_and_an_app_uses_it(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            context = RouteContext(setup.settings, setup.require_actor, setup.sessions)
            install_integrations_http(setup.app, context)
            install_integrations_api(setup.app, context)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                page = await client.get(PAGE)
                assert page.status_code == 200, page.text
                assert page.json()["keys"] == [] and page.json()["key_mode"] == "test"
                assert page.json()["api_base"].endswith("/v1/api")

                made = await client.post(
                    f"{PAGE}/keys",
                    headers=WRITE,
                    json={"name": "Partner app", "scopes": ["leads:read", "leads:write"]},
                )
                assert made.status_code == 200, made.text
                key = made.json()["key"]
                assert key.startswith("sxk_test_") and made.json()["prefix"] == key[:13]
                listed = (await client.get(PAGE)).json()["keys"]
                assert [item["state"] for item in listed] == ["active"]
                assert key not in str(listed)  # shown once, never listed
                reader = await client.post(
                    f"{PAGE}/keys",
                    headers=WRITE,
                    json={"name": "Reader", "scopes": ["calls:read"], "expires_days": 30},
                )
                assert reader.status_code == 200 and reader.json()["expires_at"]
                bad = await client.post(
                    f"{PAGE}/keys", headers=WRITE, json={"name": "x", "scopes": ["calls:write"]}
                )
                assert bad.status_code == 422
                cross_site = await client.post(
                    f"{PAGE}/keys",
                    headers={**WRITE, "Origin": "https://evil.example"},
                    json={"name": "x", "scopes": ["calls:read"]},
                )
                assert cross_site.status_code == 403

                # The key, not the browser session: a fresh client with no cookies.
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
                ) as app:
                    bearer = {"Authorization": f"Bearer {key}"}
                    missing = await app.get("/v1/api/me")
                    assert missing.status_code == 401
                    assert missing.headers["WWW-Authenticate"].startswith("Bearer")
                    assert missing.json()["error"]["code"] == "key_missing"
                    wrong = await app.get(
                        "/v1/api/me", headers={"Authorization": f"Bearer {key[:-1]}X"}
                    )
                    assert wrong.status_code == 401
                    live = "sxk_live_" + key[9:]
                    assert (
                        await app.get("/v1/api/me", headers={"Authorization": f"Bearer {live}"})
                    ).status_code == 401  # a live key never works outside production
                    me = await app.get("/v1/api/me", headers=bearer)
                    assert me.status_code == 200, me.text
                    assert me.json()["organisation"]["id"] == str(setup.state.tenant_id)
                    assert me.json()["key"]["scopes"] == ["leads:read", "leads:write"]

                    calls = await app.get("/v1/api/calls", headers=bearer)
                    assert calls.status_code == 403
                    assert calls.json()["error"]["code"] == "scope_missing"
                    added = await app.post(
                        "/v1/api/leads",
                        headers=bearer,
                        json={"name": "Asha Rao", "phone": "+919800000001", "external_id": "x1"},
                    )
                    assert added.status_code == 201, added.text
                    again = await app.post(
                        "/v1/api/leads",
                        headers=bearer,
                        json={"name": "Asha Rao", "phone": "+919800000001", "external_id": "x1"},
                    )
                    assert again.status_code == 200 and again.json()["outcome"] == "known"
                    assert again.json()["id"] == added.json()["id"]
                    empty = await app.post("/v1/api/leads", headers=bearer, json={"city": "Pune"})
                    assert empty.status_code == 422
                    leads = await app.get("/v1/api/leads", headers=bearer)
                    assert leads.status_code == 200
                    assert added.json()["id"] in leads.text
                    one = await app.get(f"/v1/api/leads/{added.json()['id']}", headers=bearer)
                    assert one.status_code == 200 and "Asha Rao" in one.text

                    calls_key = reader.json()["key"]
                    listed_calls = await app.get(
                        "/v1/api/calls", headers={"Authorization": f"Bearer {calls_key}"}
                    )
                    assert listed_calls.status_code == 200, listed_calls.text
                    assert listed_calls.json()["calls"] == []

                    revoked = await client.post(
                        f"{PAGE}/keys/{made.json()['id']}/revoke", headers=WRITE
                    )
                    assert revoked.status_code == 200 and revoked.json()["state"] == "revoked"
                    assert (await app.get("/v1/api/me", headers=bearer)).status_code == 401
                    other = await client.post(f"{PAGE}/keys/{uuid4()}/revoke", headers=WRITE)
                    assert other.status_code == 404

            async with setup.sessions() as db:
                actions = (
                    await db.scalars(
                        select(AuditEvent.action).where(
                            AuditEvent.tenant_id == setup.state.tenant_id,
                            AuditEvent.action.like("integration.%"),
                        )
                    )
                ).all()
                assert sorted(actions) == [
                    "integration.api_key_created",
                    "integration.api_key_created",
                    "integration.api_key_revoked",
                ]
                used = await db.scalar(
                    select(IntegrationApiKey.last_used_at).where(
                        IntegrationApiKey.id == made.json()["id"]
                    )
                )
                assert used is not None

            # A member who is not an owner or admin does not see the page.
            async with setup.sessions() as db, db.begin():
                await db.execute(
                    update(Membership)
                    .where(Membership.person_id == setup.state.person_id)
                    .values(role="member")
                )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                assert (await client.get(PAGE)).status_code == 403
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_keys_and_sealed_secrets_on_the_database(postgres_harness: Any, tmp_path: Path) -> None:
    async def prepare() -> Any:
        setup = await _setup(postgres_harness, tmp_path)
        await _organisation(setup)
        await setup.engine.dispose()
        return setup.state

    state = run(prepare())
    assert SEAL is not None
    sessions = sessionmaker(postgres_harness, expire_on_commit=False)
    now = datetime.now(UTC)
    with sessions() as session, session.begin():
        connection = session.connection()
        key, view = keys.create(
            connection,
            tenant_id=state.tenant_id,
            person_id=state.person_id,
            name="  Short   lived ",
            scopes=["calls:read"],
            expires_days=30,
            environment="staging",
            now=now,
        )
        assert view["name"] == "Short lived"
        assert keys.authenticate(connection, key, environment="staging", now=now) is not None
        later = now + timedelta(days=31)
        assert keys.authenticate(connection, key, environment="staging", now=later) is None
        assert keys.authenticate(connection, key, environment="production", now=now) is None
        with pytest.raises(Exception, match="expiry"):
            keys.create(
                connection,
                tenant_id=state.tenant_id,
                person_id=state.person_id,
                name="x",
                scopes=["calls:read"],
                expires_days=7,
                environment="staging",
                now=now,
            )

        secret_id = sealed.create(
            connection,
            SEAL,
            tenant_id=state.tenant_id,
            purpose="webhook_signing",
            value="whsec_" + "a" * 40,
            person_id=state.person_id,
            meta={"for": "webhook"},
            now=now,
        )
        ref = sealed.ref_for(secret_id)
        assert sealed.resolve(connection, ref, tenant_id=state.tenant_id, key=SEAL) == (
            b"whsec_" + b"a" * 40
        )
        assert sealed.hint(connection, ref) == "aaaa"
        assert sealed.resolve(connection, ref, tenant_id=uuid4(), key=SEAL) is None
        assert (
            sealed.resolve(
                connection, "AC_PARTNER_WEBHOOK_SECRET__X", tenant_id=state.tenant_id, key=SEAL
            )
            is None
        )
        stored = connection.scalar(
            select(sealed._TABLE.c.sealed).where(sealed._TABLE.c.id == secret_id)
        )
        assert "whsec_" not in stored
        sealed.retire(connection, secret_id, by="test", now=now)
        assert sealed.resolve(connection, ref, tenant_id=state.tenant_id, key=SEAL) is None


def test_an_admin_runs_the_webhook_from_the_page(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hashlib
    import hmac

    monkeypatch.setenv(sealed.ENV, base64.urlsafe_b64encode(b"s" * 32).decode())
    received: list[httpx.Request] = []

    def partner(request: httpx.Request) -> httpx.Response:
        received.append(request)
        return httpx.Response(204)

    def signed_by(request: httpx.Request, secret: str) -> bool:
        parts = dict(
            item.split("=", 1) for item in request.headers["X-SX-Signature"].split(",")[:1]
        )
        values = [
            item.split("=", 1)[1]
            for item in request.headers["X-SX-Signature"].split(",")
            if item.startswith("v1=")
        ]
        expected = hmac.new(
            secret.encode(), f"{parts['t']}.".encode() + request.content, hashlib.sha256
        ).hexdigest()
        return expected in values

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            context = RouteContext(setup.settings, setup.require_actor, setup.sessions)
            install_integrations_http(setup.app, context)
            setup.app.state.integrations_http_client = httpx.AsyncClient(
                transport=httpx.MockTransport(partner)
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                page = (await client.get(PAGE)).json()
                assert page["webhooks_ready"] is True and page["webhook"] is None
                assert "analysis.completed" in {
                    item["key"] for item in page["webhook_menu"]["events"]
                }
                assert (await client.post(f"{PAGE}/webhook/test", headers=WRITE)).status_code == 409

                url = "https://partner.example.test/hooks/sales-xray"
                saved = await client.put(
                    f"{PAGE}/webhook",
                    headers=WRITE,
                    json={"url": url, "events": ["analysis.completed", "lead.created"]},
                )
                assert saved.status_code == 200, saved.text
                secret = saved.json()["secret"]
                assert secret.startswith("whsec_")
                hook = saved.json()["webhook"]
                assert hook["managed_in_app"] and hook["secret_hint"] == secret[-4:]
                refused = await client.put(
                    f"{PAGE}/webhook",
                    headers=WRITE,
                    json={"url": "http://partner.example.test/x", "events": ["lead.created"]},
                )
                assert refused.status_code == 422
                changed = await client.put(
                    f"{PAGE}/webhook", headers=WRITE, json={"url": url, "events": ["lead.created"]}
                )
                assert changed.status_code == 200 and changed.json()["secret"] is None
                assert changed.json()["webhook"]["events"] == ["lead.created"]

                tested = await client.post(f"{PAGE}/webhook/test", headers=WRITE)
                assert tested.status_code == 200, tested.text
                assert tested.json()["delivered"] and tested.json()["http_status"] == 204
                assert signed_by(received[-1], secret)
                assert received[-1].headers["X-SX-Event-Type"] == "test"

                rotated = await client.post(f"{PAGE}/webhook/rotate", headers=WRITE)
                assert rotated.status_code == 200, rotated.text
                second = rotated.json()["secret"]
                assert second != secret and rotated.json()["webhook"]["rotating"]
                assert (
                    await client.post(f"{PAGE}/webhook/rotate", headers=WRITE)
                ).status_code == 409
                await client.post(f"{PAGE}/webhook/test", headers=WRITE)
                assert signed_by(received[-1], secret) and signed_by(received[-1], second)
                finished = await client.post(f"{PAGE}/webhook/rotate/finish", headers=WRITE)
                assert finished.status_code == 200
                assert not finished.json()["webhook"]["rotating"]
                assert finished.json()["webhook"]["secret_hint"] == second[-4:]
                await client.post(f"{PAGE}/webhook/test", headers=WRITE)
                assert signed_by(received[-1], second) and not signed_by(received[-1], secret)

                log = await client.get(f"{PAGE}/webhook/deliveries")
                assert log.status_code == 200 and log.json()["deliveries"] == []
                missing = await client.post(
                    f"{PAGE}/webhook/deliveries/{uuid4()}/retry", headers=WRITE
                )
                assert missing.status_code == 404
                off = await client.post(f"{PAGE}/webhook/disable", headers=WRITE)
                assert off.status_code == 200 and off.json()["webhook"] is None
                assert (await client.get(PAGE)).json()["webhook"] is None
            await setup.app.state.integrations_http_client.aclose()
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_the_runner_reads_sealed_and_environment_secrets(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ac_platform.partner_events.delivery import read_secrets_for

    monkeypatch.setenv(sealed.ENV, base64.urlsafe_b64encode(b"s" * 32).decode())
    monkeypatch.setenv("AC_PARTNER_WEBHOOK_SECRET__OLD", "from-the-environment")

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            assert SEAL is not None
            async with setup.sessions() as db, db.begin():
                secret_id = await db.run_sync(
                    lambda sync: sealed.create(
                        sync.connection(),
                        SEAL,
                        tenant_id=setup.state.tenant_id,
                        purpose="webhook_signing",
                        value="whsec_sealed",
                        person_id=setup.state.person_id,
                        meta={},
                        now=datetime.now(UTC),
                    )
                )
            ref = sealed.ref_for(secret_id)

            def sessions() -> AsyncSession:
                return setup.sessions()

            tenant = setup.state.tenant_id
            assert await read_secrets_for(sessions, tenant, ref, None) == [b"whsec_sealed"]
            assert await read_secrets_for(
                sessions, tenant, "AC_PARTNER_WEBHOOK_SECRET__OLD", ref
            ) == [b"from-the-environment", b"whsec_sealed"]
            assert await read_secrets_for(sessions, uuid4(), ref, None) is None
            assert await read_secrets_for(
                sessions, tenant, "AC_PARTNER_WEBHOOK_SECRET__OLD", None
            ) == [b"from-the-environment"]
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_platform_admins_see_and_stop_every_integration(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:

    from ac_platform.integrations import admin_http, webhooks

    monkeypatch.setenv(sealed.ENV, base64.urlsafe_b64encode(b"s" * 32).decode())

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            assert SEAL is not None
            tenant, person = setup.state.tenant_id, setup.state.person_id
            now = datetime.now(UTC)
            async with setup.sessions() as db, db.begin():
                _, fresh = await db.run_sync(
                    lambda sync: keys.create(
                        sync.connection(),
                        tenant_id=tenant,
                        person_id=person,
                        name="Fresh",
                        scopes=["calls:read"],
                        expires_days=None,
                        environment="test",
                        now=now,
                    )
                )
                await db.run_sync(
                    lambda sync: keys.create(
                        sync.connection(),
                        tenant_id=tenant,
                        person_id=person,
                        name="Old and idle",
                        scopes=["leads:read"],
                        expires_days=None,
                        environment="test",
                        now=now - timedelta(days=45),
                    )
                )
                await webhooks.save(
                    db,
                    SEAL,
                    tenant_id=tenant,
                    person_id=person,
                    url="https://partner.example.test/hooks",
                    events=["analysis.completed"],
                    facts_profile=None,
                    environment="test",
                    now=now,
                )
            admin = setup.state.actor  # a real session, as the Admin sign-in gives
            async with setup.sessions() as db:
                seen = await admin_http.overview(
                    db,
                    operations_tenant_id=None,
                    personal_tenant_id=None,
                    environment="test",
                    now=now,
                )
            assert seen["schema"] == "sx-integrations-admin/2"
            assert seen["counts"] == {
                "active_keys": 2,
                "keys_unused_30d": 1,
                "active_webhooks": 1,
                "webhooks_failing": 0,
                "connected_apps": 0,
            }
            [organisation] = seen["organisations"]
            assert organisation["id"] == str(tenant) and organisation["kind"]
            by_name = {key["name"]: key for key in organisation["keys"]}
            assert by_name["Old and idle"]["unused_30d"] and not by_name["Fresh"]["unused_30d"]
            assert by_name["Fresh"]["created_by"]["person_id"] == str(person)
            [hook] = organisation["webhooks"]
            assert hook["host"] == "https://partner.example.test" and hook["managed_in_app"]
            assert hook["failures_24h"] == 0 and hook["last_status"] is None
            shown = str(seen)
            # Keys by prefix only, secrets never.
            assert "whsec_" not in shown
            assert re.search(r"sxk_(test|live)_[A-Za-z0-9]{40}", shown) is None

            async with setup.sessions() as db, db.begin():
                revoked = await admin_http.revoke_key(
                    db, key_id=UUID(fresh["id"]), actor=admin, now=now
                )
                stopped = await admin_http.disable_webhook(
                    db, endpoint_id=UUID(hook["id"]), actor=admin, now=now
                )
            assert revoked["state"] == "revoked"
            assert revoked["revoked_by"]["person_id"] == str(person)
            assert stopped["status"] == "disabled" and stopped["disabled_at"]
            async with setup.sessions() as db:
                actions = (
                    await db.scalars(
                        select(AuditEvent.action).where(
                            AuditEvent.tenant_id == tenant,
                            AuditEvent.action.in_(
                                ["integration.api_key_revoked", "integration.webhook_disabled"]
                            ),
                        )
                    )
                ).all()
            assert sorted(actions) == [
                "integration.api_key_revoked",
                "integration.webhook_disabled",
            ]
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_an_admin_sets_up_the_hand_over_with_a_pasted_key(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ac_platform.partner_events.delivery import read_secrets_for
    from ac_platform.partner_events.models import PartnerHandoverRecipient

    monkeypatch.setenv(sealed.ENV, base64.urlsafe_b64encode(b"s" * 32).decode())
    service_key = "psvc_" + "f" * 36 + "_" + "k" * 20

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            install_integrations_http(
                setup.app, RouteContext(setup.settings, setup.require_actor, setup.sessions)
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                page = (await client.get(PAGE)).json()
                assert page["handover"] is None
                assert page["handover_menu"]["path"] == "/api/v1/service/customers/handover"
                no_key = await client.put(
                    f"{PAGE}/handover", headers=WRITE, json={"address": "https://app.example.test"}
                )
                assert no_key.status_code == 422
                fields = {
                    "send": ["email", "address"],
                    "questions": {"address.city": "Which city is the site in?"},
                }
                saved = await client.put(
                    f"{PAGE}/handover",
                    headers=WRITE,
                    json={
                        "address": "https://app.example.test/",
                        "service_key": service_key,
                        "lead_fields": fields,
                    },
                )
                assert saved.status_code == 200, saved.text
                shown = saved.json()["handover"]
                assert shown["url"] == "https://app.example.test/api/v1/service/customers/handover"
                assert shown["managed_in_app"] and shown["key_hint"] == service_key[-4:]
                assert service_key not in saved.text
                wrong = await client.put(
                    f"{PAGE}/handover",
                    headers=WRITE,
                    json={
                        "address": "https://app.example.test",
                        "lead_fields": {"send": ["email"], "questions": {"address.city": "x"}},
                    },
                )
                assert wrong.status_code == 422  # a question for a part not sent
                kept = await client.put(
                    f"{PAGE}/handover",
                    headers=WRITE,
                    json={"address": "https://app.example.test", "lead_fields": {"send": []}},
                )
                assert kept.status_code == 200 and kept.json()["handover"]["key_hint"] == "kkkk"

                async with setup.sessions() as db:
                    recipient = await db.scalar(
                        select(PartnerHandoverRecipient).where(
                            PartnerHandoverRecipient.tenant_id == setup.state.tenant_id,
                            PartnerHandoverRecipient.status == "active",
                        )
                    )
                assert recipient is not None and recipient.lead_fields == {
                    "send": [],
                    "questions": {},
                    "consents": [],
                }

                def sessions() -> AsyncSession:
                    return setup.sessions()

                assert await read_secrets_for(
                    sessions, setup.state.tenant_id, recipient.secret_ref, None
                ) == [service_key.encode()]
                off = await client.post(f"{PAGE}/handover/disable", headers=WRITE)
                assert off.status_code == 200 and off.json()["handover"] is None
                assert (
                    await read_secrets_for(
                        sessions, setup.state.tenant_id, recipient.secret_ref, None
                    )
                    is None
                )
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_platform_admins_disconnect_an_app(postgres_harness: Any, tmp_path: Path) -> None:
    from ac_platform.integrations import admin_http, oauth

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            tenant, person = setup.state.tenant_id, setup.state.person_id
            now = datetime.now(UTC)
            verifier = "v" * 50
            async with setup.sessions() as db, db.begin():

                def connect(sync: Any) -> dict[str, Any]:
                    connection = sync.connection()
                    app, secret = oauth.register_client(
                        connection,
                        tenant_id=tenant,
                        person_id=person,
                        name="Partner CRM",
                        redirect_uris=["https://partner.example.test/cb"],
                        confidential=True,
                        now=now,
                    )
                    client = oauth.find_client(connection, app["client_id"])
                    code = oauth.issue_code(
                        connection,
                        client=client,
                        tenant_id=tenant,
                        person_id=person,
                        scopes=["calls:read"],
                        redirect_uri="https://partner.example.test/cb",
                        code_challenge=oauth.challenge_for(verifier),
                        now=now,
                    )
                    return oauth.exchange_code(
                        connection,
                        code=code,
                        client_id=app["client_id"],
                        client_secret=secret,
                        redirect_uri="https://partner.example.test/cb",
                        code_verifier=verifier,
                        now=now,
                    )

                tokens = await db.run_sync(connect)
            async with setup.sessions() as db:
                seen = await admin_http.overview(
                    db,
                    operations_tenant_id=None,
                    personal_tenant_id=None,
                    environment="test",
                    now=now,
                )
            assert seen["counts"]["connected_apps"] == 1
            [grant] = seen["organisations"][0]["connections"]
            assert grant["app"] == "Partner CRM" and grant["revoked_at"] is None
            async with setup.sessions() as db, db.begin():
                row = await admin_http.revoke_connection(
                    db, grant_id=UUID(grant["id"]), actor=setup.state.actor, now=now
                )
            assert row["revoked_at"] is not None and row["tenant_id"] == str(tenant)
            async with setup.sessions() as db:
                assert (
                    await db.run_sync(
                        lambda sync: oauth.authenticate(
                            sync.connection(), tokens["access_token"], now=now
                        )
                    )
                    is None
                )
                actions = (
                    await db.scalars(
                        select(AuditEvent.action).where(
                            AuditEvent.tenant_id == tenant,
                            AuditEvent.action == "integration.app_disconnected",
                        )
                    )
                ).all()
            assert actions == ["integration.app_disconnected"]
        finally:
            await setup.engine.dispose()

    run(exercise())
