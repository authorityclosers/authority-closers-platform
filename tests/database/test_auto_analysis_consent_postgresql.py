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

import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select, update

from ac_platform.audit.models import AuditEvent
from ac_platform.call_ai import auto_consent
from ac_platform.call_ai.http import install_call_ai_http
from ac_platform.conversation_intelligence import auto_start
from ac_platform.conversation_intelligence.acquisition_sessions import MeasuredSource
from ac_platform.conversation_intelligence.models import (
    ConversationProcessingPlan,
    ConversationRun,
)
from ac_platform.http.routes import RouteContext
from tests.database.test_conversation_account_library_postgresql import _session
from tests.database.test_conversation_failure_observation_postgresql import seed_measured_fixture
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_submission_http_postgresql import (
    ORIGIN,
    PREFIX,
    _headers,
    _setup,
    _upload_for_read_test,
)
from tests.database.test_conversation_worker_postgresql import _reconcile, _wav_one_second_48k
from tests.database.test_lead_desk_postgresql import _organisation
from tests.unit.conversation_intelligence.test_acquisition_source import ValidationFixtureRuntime
from tests.unit.conversation_intelligence.test_alignment import _signal

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


def test_an_upload_relies_on_a_current_consent_only(postgres_harness: Any, tmp_path: Path) -> None:
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

                # Agreed for these terms: it's taken, and names the consent it relied on.
                terms = (await client.get(PREFIX + "/upload-policy")).json()["policy_sha256"]
                assert (await _turn_on(client, terms)).status_code == 200
                started = await upload()
                assert started.status_code == 202, started.text
                person = setup.state.person_id
                consents = await _events(setup, person, auto_consent.ACTION)
                starts = await _events(setup, person, "conversation.auto_upload_accepted")
                assert [event.payload["standing_consent_event_id"] for event in starts] == [
                    str(consents[-1].id)
                ]

                # Turned off: the next call waits for its tap again.
                await client.post(AUTO, json={"decision": "withdrawn"}, headers=WRITE)
                assert (await upload()).status_code == 409
                assert len(await _events(setup, person, "conversation.auto_upload_accepted")) == 1
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


def test_the_analysis_starts_by_itself_only_on_ones_own_call_with_a_current_consent(
    postgres_harness: Any, tmp_path: Path
) -> None:
    """The provider analysis starts when its plan is accepted: with a standing consent,
    the seller's own call's plan is accepted without a tap, and the start names the
    consent; the plan's receipt stays the plan's own."""

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path, gemini=True)
        setup.native.validate_source = ValidationFixtureRuntime().validate_source
        try:
            await _organisation(setup)
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
                path, _ = await _upload_for_read_test(setup, client)
                await _reconcile(setup.sessions, setup.state)
                recording_id = UUID((await client.get(path)).json()["recording_id"])
                await seed_measured_fixture(
                    setup.sessions,
                    SimpleNamespace(recording_id=recording_id),
                    signal_payload=_signal(
                        source_sha256=hashlib.sha256(_wav_one_second_48k()).hexdigest()
                    ),
                )
                quoted = await client.post(
                    path + "/plan/quote", headers={"Origin": ORIGIN, "Idempotency-Key": "auto"}
                )
                assert quoted.status_code == 201, quoted.text
                plan = quoted.json()

                async def accept(key: str) -> httpx.Response:
                    return await client.post(
                        path + "/plan",
                        json={
                            "plan_id": plan["id"],
                            "plan_fingerprint": plan["plan_fingerprint"],
                            "privacy_revision": plan["privacy_revision"],
                            "accepted": True,
                        },
                        headers={
                            "Origin": ORIGIN,
                            "Idempotency-Key": key,
                            "X-Upload-Consent": "standing",
                        },
                    )

                # No consent yet: it waits for the tap.
                refused = await accept("auto:1")
                assert refused.status_code == 409
                assert "Tap Analyse this call" in refused.text

                # An admin's standing consent never starts someone else's call.
                terms = (await client.get(PREFIX + "/upload-policy")).json()["policy_sha256"]
                as_(setup.token)
                assert (await _turn_on(client, terms)).status_code == 200
                theirs = await accept("auto:2")
                assert theirs.status_code == 409
                assert "your own calls" in theirs.text

                # The seller's own consent: the plan is accepted without a tap.
                as_(seller_token)
                assert (await _turn_on(client, terms)).status_code == 200
                started = await accept("auto:3")
                assert started.status_code == 202, started.text
                consent = (await _events(setup, seller.person_id, auto_consent.ACTION))[-1]
                starts = await _events(
                    setup, seller.person_id, "conversation.auto_analysis_started"
                )
                assert [event.payload for event in starts] == [
                    {"standing_consent_event_id": str(consent.id), "plan_id": plan["id"]}
                ]
        finally:
            await setup.engine.dispose()

    run(exercise())


async def _standing_call(setup: Any, client: httpx.AsyncClient) -> tuple[str, UUID]:
    """The signed-in seller uploads one call marked "standing"; its audio check (C1) is then
    done, as the worker leaves it: C0/C1 checkpoints saved and the local run completed."""
    data, submission = _wav_one_second_48k(), uuid4()
    path = f"{PREFIX}/submissions/{submission}"
    headers = {**await _headers(client, data), "X-Upload-Consent": "standing"}
    uploaded = await client.put(path + "/source", content=data, headers=headers)
    assert uploaded.status_code == 202, uploaded.text
    await _reconcile(setup.sessions, setup.state)
    recording_id = UUID((await client.get(path)).json()["recording_id"])
    await seed_measured_fixture(
        setup.sessions,
        SimpleNamespace(recording_id=recording_id),
        signal_payload=_signal(source_sha256=hashlib.sha256(data).hexdigest()),
    )
    async with setup.sessions() as db, db.begin():
        await db.execute(
            update(ConversationRun)
            .where(ConversationRun.recording_id == recording_id)
            .values(state="completed", completed_at=setup.clock[0])
        )
    return path, recording_id


async def _plans(setup: Any, recording_id: UUID) -> list[ConversationProcessingPlan]:
    async with setup.sessions() as db:
        rows = await db.scalars(
            select(ConversationProcessingPlan).where(
                ConversationProcessingPlan.recording_id == recording_id
            )
        )
        return list(rows.all())


async def _seller_with_consent(setup: Any, client: httpx.AsyncClient) -> Any:
    seller = await seed(setup.engine, tenant_id=setup.state.tenant_id, role="member")
    client.cookies.clear()
    client.cookies.set(setup.settings.session_cookie_name, await _session(setup, seller))
    terms = (await client.get(PREFIX + "/upload-policy")).json()["policy_sha256"]
    assert (await _turn_on(client, terms)).status_code == 200
    return seller


def _starter(setup: Any) -> auto_start.AutoStart:
    return auto_start.AutoStart(
        sessions=setup.sessions, runtime=setup.runtime, factory=setup.factory
    )


def test_the_server_starts_a_standing_call_once_its_audio_check_is_done(
    postgres_harness: Any, tmp_path: Path
) -> None:
    """Orchestrator, 14 Nov 2026: reports waited for the phone's background worker to come
    back and accept the plan (70-270 s and more). The server now quotes and accepts the plan
    of a call its seller's standing consent covers as soon as C1 is done, names the consent,
    and the phone's own start afterwards changes nothing."""

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path, gemini=True)
        setup.native.validate_source = ValidationFixtureRuntime().validate_source
        try:
            await _organisation(setup)
            _install(setup)
            starter = _starter(setup)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                seller = await _seller_with_consent(setup, client)
                path, recording_id = await _standing_call(setup, client)

                assert await starter.tick(now=setup.clock[0]) == ["started"]
                (plan,) = await _plans(setup, recording_id)
                assert plan.acceptance_command_id is not None
                consent = (await _events(setup, seller.person_id, auto_consent.ACTION))[-1]
                starts = await _events(setup, seller.person_id, auto_start.STARTED)
                assert [event.payload for event in starts] == [
                    {
                        "standing_consent_event_id": str(consent.id),
                        "plan_id": str(plan.id),
                        "started_by": "server",
                    }
                ]
                # The session that uploaded the call is the one that started it.
                (uploaded,) = await _events(setup, seller.person_id, auto_start.UPLOADED)
                assert uploaded.session_id is not None
                assert starts[0].session_id == uploaded.session_id
                # Nothing left to start: a second sweep is a no-op.
                assert await starter.tick(now=setup.clock[0]) == []

                # The phone comes back late while the plan runs: its quote shows the same
                # accepted plan, and accepting it again starts nothing and records no start.
                if plan.state == "active":
                    quoted = await client.post(
                        path + "/plan/quote",
                        headers={"Origin": ORIGIN, "Idempotency-Key": "late"},
                    )
                    assert quoted.status_code in {200, 201}, quoted.text
                    shown = quoted.json()
                    assert (shown["id"], shown["accepted"]) == (str(plan.id), True)
                    again = await client.post(
                        path + "/plan",
                        json={
                            "plan_id": shown["id"],
                            "plan_fingerprint": shown["plan_fingerprint"],
                            "privacy_revision": shown["privacy_revision"],
                            "accepted": True,
                        },
                        headers={
                            "Origin": ORIGIN,
                            "Idempotency-Key": "late:accept",
                            "X-Upload-Consent": "standing",
                        },
                    )
                    assert again.status_code == 202, again.text
                    assert again.json()["id"] == str(plan.id)
                    assert len(await _plans(setup, recording_id)) == 1
                assert len(await _events(setup, seller.person_id, auto_start.STARTED)) == 1
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_without_a_current_consent_the_call_keeps_its_tap(
    postgres_harness: Any, tmp_path: Path
) -> None:
    """Consent turned off after the upload: the server starts nothing, marks the call
    waiting once, and the seller's own tap still quotes the plan."""

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path, gemini=True)
        setup.native.validate_source = ValidationFixtureRuntime().validate_source
        try:
            await _organisation(setup)
            _install(setup)
            starter = _starter(setup)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                seller = await _seller_with_consent(setup, client)
                path, recording_id = await _standing_call(setup, client)
                withdrawn = await client.post(AUTO, json={"decision": "withdrawn"}, headers=WRITE)
                assert withdrawn.status_code == 200, withdrawn.text

                assert await starter.tick(now=setup.clock[0]) == ["waiting:consent"]
                assert await _plans(setup, recording_id) == []
                assert await starter.tick(now=setup.clock[0]) == []  # marked once
                waits = await _events(setup, seller.person_id, auto_start.WAITING)
                assert [event.payload["reason"] for event in waits] == ["consent"]
                assert await _events(setup, seller.person_id, auto_start.STARTED) == []

                # The tap stays: the seller's own quote still works.
                quoted = await client.post(
                    path + "/plan/quote", headers={"Origin": ORIGIN, "Idempotency-Key": "tap"}
                )
                assert quoted.status_code == 201, quoted.text
                assert quoted.json()["accepted"] is False
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_out_of_minutes_nothing_is_uploaded_or_started(
    postgres_harness: Any, tmp_path: Path
) -> None:
    """The minutes are taken when the call is uploaded, before its audio check: with none
    left the upload is refused, so there is no call for the server to start."""

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path, gemini=True)
        setup.native.validate_source = ValidationFixtureRuntime().validate_source
        try:
            await _organisation(setup)
            _install(setup)
            starter = _starter(setup)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                seller = await _seller_with_consent(setup, client)
                # Use up the seller's minutes, one call under the 60-minute limit at a time.
                for _ in range(64):
                    async with setup.sessions() as db, db.begin():
                        sessions = setup.factory(db, setup.state.tenant_id)
                        left = await sessions.allowance(actor=seller.actor)
                        assert not left.get("unlimited"), left
                        seconds = min(int(left["available_seconds"] or 0), 3599)
                        if seconds <= 0:
                            break
                        await sessions.reserve(
                            MeasuredSource(uuid4(), "a" * 64, seconds * 1000, "b" * 64),
                            actor=seller.actor,
                        )
                data = _wav_one_second_48k()
                headers = {**await _headers(client, data), "X-Upload-Consent": "standing"}
                refused = await client.put(
                    f"{PREFIX}/submissions/{uuid4()}/source", content=data, headers=headers
                )
                assert refused.status_code in {402, 409}, refused.text
                assert await _events(setup, seller.person_id, auto_start.UPLOADED) == []
                assert await starter.tick(now=setup.clock[0]) == []
        finally:
            await setup.engine.dispose()

    run(exercise())
