"""Recordings an app sends for a person (POST /v1/api/calls) on PostgreSQL.

A member connects Pulse for their own account with ``calls:write``. Pulse sends a
recording with its hash, consent statement and its own id: it waits for that person
(nothing is analysed or charged), a retry is the same upload, the same id with another
file is refused, a body that doesn't match its hash is kept nowhere, and an
organisation API key can't send one. The person sees it, takes the bytes for the usual
upload, can't mark it added with a call that isn't this file, and can discard it, after
which the bytes are gone. Fictional files and people only.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import update

from ac_platform.http.routes import RouteContext
from ac_platform.integrations.app_uploads import install_app_uploads_http
from ac_platform.tenancy.models import Membership
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_integrations_platform_apps_postgresql import (
    PULSE_RETURN,
    WRITE,
    _connect,
    _install,
)
from tests.database.test_lead_desk_postgresql import _organisation

AUDIO = b"ID3" + bytes(range(256)) * 40  # a fictional file; never decoded here
# Pulse set up here (fictional): app call uploads are on only then.
PULSE_ON = {
    "pulse_issuer": "https://pulse.example.test",
    "pulse_client_id": "sx-test",
    "pulse_client_secret": SecretStr("fictional-secret-0000"),
}


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def _headers(body: bytes, **over: str) -> dict[str, str]:
    headers = {
        "Authorization": "",
        "Content-Type": "application/octet-stream",
        "X-Source-SHA256": hashlib.sha256(body).hexdigest(),
        "X-Recording-Consent": "participants-informed",
        "X-External-Id": "pulse-call-0001",
        "X-Call-Title": "Discovery%20call%20%E2%80%94%20Greenleaf",
        "X-Call-At": "2026-10-25T09:30:00+05:30",
        "X-File-Name": "greenleaf-call.mp3",
        "X-Media-Type": "audio/mpeg",
    }
    headers.update(over)
    return headers


def test_a_recording_from_pulse_waits_for_its_person(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            async with setup.sessions() as db, db.begin():
                await db.execute(
                    update(Membership)
                    .where(Membership.person_id == setup.state.person_id)
                    .values(role="member")
                )
            settings = setup.settings.model_copy(
                update={
                    "public_learner_tenant_id": uuid4(),
                    "sales_xray_storage_root": str(tmp_path / "storage"),
                    **PULSE_ON,
                }
            )
            _install(setup, settings)
            install_app_uploads_http(
                setup.app, RouteContext(settings, setup.require_actor, setup.sessions)
            )
            transport = httpx.ASGITransport(app=setup.app)
            async with (
                httpx.AsyncClient(transport=transport, base_url=ORIGIN) as person,
                httpx.AsyncClient(transport=transport, base_url=ORIGIN) as server,
            ):
                person.cookies.set(setup.settings.session_cookie_name, setup.token)
                pulse = (
                    await server.post(
                        "/v1/oauth/register",
                        json={
                            "client_name": "Pulse",
                            "redirect_uris": [PULSE_RETURN],
                            "grant_types": ["authorization_code", "refresh_token"],
                            "token_endpoint_auth_method": "client_secret_basic",
                        },
                    )
                ).json()
                _, tokens, _ = await _connect(
                    person, server, pulse, PULSE_RETURN, "calls:write leads:read"
                )
                bearer = f"Bearer {tokens['access_token']}"

                sent = await server.post(
                    "/v1/api/calls", content=AUDIO, headers=_headers(AUDIO, Authorization=bearer)
                )
                assert sent.status_code == 202, sent.text
                upload = sent.json()
                assert upload["state"] == "waiting_for_person"
                assert upload["call_id"] is None
                assert upload["open_url"].startswith(f"{ORIGIN}/analysis/calls?app-upload=")

                again = await server.post(
                    "/v1/api/calls", content=AUDIO, headers=_headers(AUDIO, Authorization=bearer)
                )
                assert again.status_code == 200 and again.json()["id"] == upload["id"]
                other = AUDIO + b"x"
                reused = await server.post(
                    "/v1/api/calls", content=other, headers=_headers(other, Authorization=bearer)
                )
                assert reused.status_code == 409
                assert reused.json()["error"]["code"] == "external_id_reused"
                no_consent = await server.post(
                    "/v1/api/calls",
                    content=AUDIO,
                    headers=_headers(
                        AUDIO,
                        Authorization=bearer,
                        **{"X-Recording-Consent": "yes", "X-External-Id": "pulse-call-0002"},
                    ),
                )
                assert no_consent.status_code == 422
                assert no_consent.json()["error"]["code"] == "consent"
                lying = await server.post(
                    "/v1/api/calls",
                    content=AUDIO,
                    headers=_headers(
                        AUDIO,
                        Authorization=bearer,
                        **{
                            "X-Source-SHA256": "0" * 64,
                            "X-External-Id": "pulse-call-0003",
                        },
                    ),
                )
                assert lying.status_code == 422
                assert lying.json()["error"]["code"] == "sha256"
                inbox = tmp_path / "storage" / "app-inbox"
                assert len(list(inbox.rglob("*"))) == 2  # the folder and one recording

                async with setup.sessions() as db, db.begin():
                    await db.execute(
                        update(Membership)
                        .where(Membership.person_id == setup.state.person_id)
                        .values(role="admin")
                    )
                # An organisation's API key is no person: it can't hold calls:write.
                refused_key = await person.post(
                    "/v1/sales-xray/integrations/keys",
                    headers=WRITE,
                    json={"name": "Fictional script", "scopes": ["calls:write"]},
                )
                assert refused_key.status_code == 422
                key = (
                    await person.post(
                        "/v1/sales-xray/integrations/keys",
                        headers=WRITE,
                        json={"name": "Fictional script", "scopes": ["calls:read"]},
                    )
                ).json()["key"]
                keyed = await server.post(
                    "/v1/api/calls",
                    content=AUDIO,
                    headers=_headers(
                        AUDIO, Authorization=f"Bearer {key}", **{"X-External-Id": "key-1"}
                    ),
                )
                assert keyed.status_code == 403
                assert keyed.json()["error"]["code"] == "scope_missing"

                # The person sees it and takes the bytes for the usual upload.
                waiting = (await person.get("/v1/sales-xray/app-uploads")).json()["uploads"]
                assert [item["id"] for item in waiting] == [upload["id"]]
                assert waiting[0]["app"] == "Pulse"
                assert waiting[0]["title"] == "Discovery call — Greenleaf"
                got = await person.get(f"/v1/sales-xray/app-uploads/{upload['id']}/file")
                assert got.status_code == 200 and got.content == AUDIO
                not_this = await person.post(
                    f"/v1/sales-xray/app-uploads/{upload['id']}/imported",
                    headers=WRITE,
                    json={"submission_id": str(uuid4())},
                )
                assert not_this.status_code == 409
                gone = await person.post(
                    f"/v1/sales-xray/app-uploads/{upload['id']}/discard", headers=WRITE
                )
                assert gone.status_code == 200 and gone.json()["state"] == "discarded"
                assert not list(inbox.rglob("*.bin"))
                status = await server.get(
                    f"/v1/api/calls/uploads/{upload['id']}", headers={"Authorization": bearer}
                )
                assert status.status_code == 200 and status.json()["state"] == "discarded"
                assert (
                    await person.get(f"/v1/sales-xray/app-uploads/{upload['id']}/file")
                ).status_code == 410
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_app_recordings_are_off_until_pulse_is_set_up(
    postgres_harness: Any, tmp_path: Path
) -> None:
    """Without AC_PULSE_*: an app may still be granted calls:write, but sending a
    recording, reading one's state and the person's inbox all answer as the rest of Pulse
    does when it is off, so no "From Pulse" inbox shows."""

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            settings = setup.settings.model_copy(
                update={
                    "public_learner_tenant_id": uuid4(),
                    "sales_xray_storage_root": str(tmp_path / "storage"),
                }
            )
            assert not settings.pulse_configured
            _install(setup, settings)
            install_app_uploads_http(
                setup.app, RouteContext(settings, setup.require_actor, setup.sessions)
            )
            transport = httpx.ASGITransport(app=setup.app)
            async with (
                httpx.AsyncClient(transport=transport, base_url=ORIGIN) as person,
                httpx.AsyncClient(transport=transport, base_url=ORIGIN) as server,
            ):
                person.cookies.set(setup.settings.session_cookie_name, setup.token)
                pulse = (
                    await server.post(
                        "/v1/oauth/register",
                        json={"client_name": "Pulse", "redirect_uris": [PULSE_RETURN]},
                    )
                ).json()
                seen, tokens, _ = await _connect(
                    person, server, pulse, PULSE_RETURN, "calls:write leads:read"
                )
                assert "calls:write" in {scope["key"] for scope in seen["scopes"]}
                bearer = f"Bearer {tokens['access_token']}"
                off = {"error": {"code": "pulse_off", "message": "Pulse isn't set up here."}}
                sent = await server.post(
                    "/v1/api/calls", content=AUDIO, headers=_headers(AUDIO, Authorization=bearer)
                )
                assert (sent.status_code, sent.json()) == (404, off)
                state = await server.get(
                    f"/v1/api/calls/uploads/{uuid4()}", headers={"Authorization": bearer}
                )
                assert (state.status_code, state.json()) == (404, off)
                inbox = await person.get("/v1/sales-xray/app-uploads")
                assert inbox.status_code == 404
                assert inbox.json()["detail"] == "Pulse isn't set up here."
                # Everything else the connection may do still answers.
                assert (
                    await server.get("/v1/api/leads", headers={"Authorization": bearer})
                ).status_code == 200
        finally:
            await setup.engine.dispose()

    run(exercise())
