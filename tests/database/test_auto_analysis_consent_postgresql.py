"""Analyse my calls automatically: a seller's standing consent, through the HTTP API on
PostgreSQL (owner, 26 Oct 2026: "approve standing consent for auto-analysis", v0.96).

A seller turns it on for themselves in the owner's words, for the upload terms in front
of them; each choice is an append-only audit event and the newest wins. A call they
upload marked "standing" then starts by itself, and its start names the consent it
relied on. It doesn't start when the consent is off, the words or the upload terms
changed since, or the seller's AI level is Off: the one tap stays. Fictional people
and the synthetic local providers only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select

from ac_platform.audit.models import AuditEvent
from ac_platform.call_ai import auto_consent
from ac_platform.call_ai.http import install_call_ai_http
from ac_platform.http.routes import RouteContext
from tests.database.test_conversation_account_library_postgresql import _session
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_submission_http_postgresql import (
    ORIGIN,
    PREFIX,
    _headers,
    _setup,
)
from tests.database.test_conversation_worker_postgresql import _wav_one_second_48k
from tests.database.test_lead_desk_postgresql import _organisation

WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
LEVELS = "/v1/sales-xray/call-ai"
AUTO = LEVELS + "/auto-analysis"


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def _install(setup: Any) -> None:
    # As the AI-on-calls tests do: this harness's own workspace is not the learner one.
    settings = setup.settings.model_copy(update={"public_learner_tenant_id": uuid4()})
    install_call_ai_http(setup.app, RouteContext(settings, setup.require_actor, setup.sessions))


async def _events(setup: Any, person: UUID, action: str) -> list[AuditEvent]:
    async with setup.sessions() as db:
        rows = await db.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.tenant_id == setup.state.tenant_id,
                AuditEvent.action == action,
                *(
                    (AuditEvent.resource_id == str(person),)
                    if action == auto_consent.ACTION
                    else (AuditEvent.actor_person_id == person,)
                ),
            )
            .order_by(AuditEvent.sequence_no)
        )
        return list(rows.all())


async def _turn_on(client: httpx.AsyncClient, terms: str) -> httpx.Response:
    shown = (await client.get(AUTO)).json()["notice"]
    return await client.post(
        AUTO,
        json={
            "decision": "granted",
            "policy_sha256": shown["policy_sha256"],
            "upload_policy_sha256": terms,
            "language": "en",
        },
        headers=WRITE,
    )


def test_a_seller_turns_it_on_and_off_for_themselves(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)  # the signed-in person is an admin here
            _install(setup)
            seller = await seed(setup.engine, tenant_id=setup.state.tenant_id, role="member")
            seller_token = await _session(setup, seller)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:

                def as_(token: str) -> None:
                    client.cookies.clear()
                    client.cookies.set(setup.settings.session_cookie_name, token)

                as_(seller_token)
                first = (await client.get(AUTO)).json()
                assert (first["state"], first["can_start"]) == ("ask", False)
                assert first["notice"]["title"] == "Analyse my calls automatically"
                assert first["notice"]["text"].startswith(
                    "When I record a sales call with Sales X-Ray in "
                )
                assert "{organisation}" not in first["notice"]["text"]
                assert first["pending_languages"] == ["hi", "mr"]
                terms = (await client.get(PREFIX + "/upload-policy")).json()["policy_sha256"]

                # Words other than those shown, or a language still under review: refused.
                stale = await client.post(
                    AUTO,
                    json={
                        "decision": "granted",
                        "policy_sha256": "0" * 64,
                        "upload_policy_sha256": terms,
                    },
                    headers=WRITE,
                )
                assert stale.status_code == 409
                hindi = await client.post(
                    AUTO,
                    json={
                        "decision": "granted",
                        "policy_sha256": first["notice"]["policy_sha256"],
                        "upload_policy_sha256": terms,
                        "language": "hi",
                    },
                    headers=WRITE,
                )
                assert hindi.status_code == 422
                elsewhere = await client.post(
                    AUTO,
                    json={"decision": "withdrawn"},
                    headers={"Content-Type": "application/json"},
                )
                assert elsewhere.status_code == 403

                # A seller (not a manager) turns it on for themselves.
                on = await _turn_on(client, terms)
                assert on.status_code == 200, on.text
                assert (on.json()["state"], on.json()["can_start"]) == ("on", True)
                assert on.json()["terms_sha256"] == terms

                # The seller's AI level at Off: on, but nothing starts by itself.
                as_(setup.token)
                revision = (await client.get(LEVELS)).json()["revision"]
                off = await client.put(
                    f"{LEVELS}/people/{seller.person_id}",
                    json={"expected_revision": revision, "level": "off"},
                    headers=WRITE,
                )
                assert off.status_code == 200, off.text
                as_(seller_token)
                held = (await client.get(AUTO)).json()
                assert (held["state"], held["ai_level"], held["can_start"]) == ("on", "off", False)
                async with setup.sessions() as db:
                    assert (
                        await auto_consent.may_start(
                            db, setup.state.tenant_id, seller.person_id, terms
                        )
                        is None
                    )

                # Turned off (a double tap, one key): newest wins, both choices kept.
                once = {**WRITE, "Idempotency-Key": str(uuid4())}
                for _ in range(2):
                    withdrawn = await client.post(
                        AUTO, json={"decision": "withdrawn"}, headers=once
                    )
                    assert withdrawn.json()["state"] == "off"
                events = await _events(setup, seller.person_id, auto_consent.ACTION)
                assert [event.payload["decision"] for event in events] == ["granted", "withdrawn"]
                granted = events[0].payload
                assert granted["upload_policy_sha256"] == terms
                assert granted["notice_version"] == auto_consent.NOTICE_VERSION
                assert granted["policy_sha256"] == first["notice"]["policy_sha256"]
                # The hash covers the sealed words; the text as shown, with the name, is kept.
                assert granted["text_shown"] == first["notice"]["text"]
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_new_words_ask_again(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            _install(setup)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                terms = (await client.get(PREFIX + "/upload-policy")).json()["policy_sha256"]
                assert (await _turn_on(client, terms)).json()["state"] == "on"
                monkeypatch.setitem(
                    auto_consent.WORDS, "en", "New words for {organisation}, not yet agreed."
                )
                again = (await client.get(AUTO)).json()
                assert (again["state"], again["can_start"]) == ("ask", False)
                async with setup.sessions() as db:
                    assert (
                        await auto_consent.may_start(
                            db, setup.state.tenant_id, setup.state.person_id, terms
                        )
                        is None
                    )
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_a_call_starts_by_itself_only_with_a_current_consent(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            _install(setup)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)

                async def upload() -> httpx.Response:
                    data = _wav_one_second_48k()
                    headers = {**await _headers(client, data), "X-Upload-Consent": "standing"}
                    return await client.put(
                        f"{PREFIX}/submissions/{uuid4()}/source", content=data, headers=headers
                    )

                # No consent yet: the call waits for its tap.
                refused = await upload()
                assert refused.status_code == 409
                assert "Tap Analyse this call" in refused.text

                # Agreed for other upload terms: the server asks again, and it's still the tap.
                elsewhere = await _turn_on(client, "a" * 64)
                assert elsewhere.status_code == 200, elsewhere.text
                assert (elsewhere.json()["state"], elsewhere.json()["can_start"]) == ("ask", False)
                assert (await upload()).status_code == 409

                # Agreed for these terms: it starts, and names the consent it relied on.
                terms = (await client.get(PREFIX + "/upload-policy")).json()["policy_sha256"]
                assert (await _turn_on(client, terms)).status_code == 200
                started = await upload()
                assert started.status_code == 202, started.text
                person = setup.state.person_id
                consents = await _events(setup, person, auto_consent.ACTION)
                starts = await _events(setup, person, "conversation.auto_analysis_started")
                assert [event.payload["standing_consent_event_id"] for event in starts] == [
                    str(consents[-1].id)
                ]

                # Turned off: the next call waits for its tap again.
                await client.post(AUTO, json={"decision": "withdrawn"}, headers=WRITE)
                assert (await upload()).status_code == 409
                assert len(await _events(setup, person, "conversation.auto_analysis_started")) == 1
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_a_personal_workspace_is_told_plainly(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            _install(setup)  # no organisation: the person's own workspace
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                view = await client.get(AUTO)
                assert view.status_code == 200, view.text
                assert view.json() == {
                    "schema": "sales-xray-auto-analysis/1",
                    "state": "unavailable",
                    "can_start": False,
                }
        finally:
            await setup.engine.dispose()

    run(exercise())
