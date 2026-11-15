"""A seller's call, sent by an organisation's API key, through the HTTP API on PostgreSQL
(API gap 2; the orchestrator, 15 Nov 2026: "build option B now").

An owner or admin switches API uploads on for the workspace in their own session; until
then nothing is taken. A key holding ``recordings:write`` opens an upload for a named
seller, the file comes through the upload's link (no key needed) stating the people on
the call know it is recorded, and the call is the seller's own: their minutes, their
call, the audit naming the key and its maker. Once its audio check is done the server
starts it, naming the terms acceptance and the key; its status reads through the API and
MCP. Everything the app refuses is refused here too. Fictional people and the synthetic
local providers only.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select, update

from ac_platform.audit.models import AuditEvent
from ac_platform.conversation_intelligence import auto_start, key_upload
from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionUsage,
)
from ac_platform.conversation_intelligence.acquisition_processing import upload_policy
from ac_platform.conversation_intelligence.acquisition_sessions import MeasuredSource
from ac_platform.conversation_intelligence.acquisition_source import NativeUploadPreflight
from ac_platform.conversation_intelligence.application import ConversationDenied
from ac_platform.conversation_intelligence.guest_models import ConversationGuestSubmission
from ac_platform.conversation_intelligence.models import (
    ConversationProcessingPlan,
    ConversationRun,
)
from ac_platform.http.routes import RouteContext
from ac_platform.integrations import keys, recordings_api
from ac_platform.integrations.mcp_http import install_mcp_http
from ac_platform.integrations.models import IntegrationApiKey
from ac_platform.tenancy.models import Membership
from tests.database.test_conversation_account_library_postgresql import _session
from tests.database.test_conversation_failure_observation_postgresql import seed_measured_fixture
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_conversation_worker_postgresql import _reconcile, _wav_one_second_48k
from tests.database.test_lead_desk_postgresql import _organisation
from tests.unit.conversation_intelligence.test_acquisition_source import ValidationFixtureRuntime
from tests.unit.conversation_intelligence.test_alignment import _signal

API = "/v1/api/recordings"
WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def _install(setup: Any) -> None:
    # As the other organisation routes do: this harness's own workspace is not the learner one.
    settings = setup.settings.model_copy(update={"public_learner_tenant_id": uuid4()})
    recordings_api.install_recordings_api(
        setup.app,
        settings=settings,
        sessions=setup.sessions,
        require_actor=setup.require_actor,
        runtime=setup.runtime,
        preflight=NativeUploadPreflight(setup.native),
        factory=setup.factory,
    )
    install_mcp_http(setup.app, RouteContext(settings, setup.require_actor, setup.sessions))


async def _key(setup: Any, scopes: list[str], name: str = "Dialler") -> tuple[str, UUID]:
    async with setup.sessions() as db, db.begin():
        key, view = await db.run_sync(
            lambda sync: keys.create(
                sync.connection(),
                tenant_id=setup.state.tenant_id,
                person_id=setup.state.person_id,
                name=name,
                scopes=list(scopes),
                expires_days=None,
                environment="test",
                now=datetime.now(UTC),
            )
        )
    return key, UUID(view["id"])


async def _switch_on(setup: Any, client: httpx.AsyncClient) -> None:
    """The signed-in admin switches API uploads on, in their own session."""
    client.cookies.clear()
    client.cookies.set(setup.settings.session_cookie_name, setup.token)
    shown = (await client.get(recordings_api.TERMS_PATH)).json()
    assert (shown["state"], shown["open"]) == ("ask", True), shown
    assert shown["notice"]["title"] == key_upload.TERMS_TITLE
    turned = await client.post(
        recordings_api.TERMS_PATH,
        json={
            "decision": "granted",
            "policy_sha256": shown["notice"]["policy_sha256"],
            "upload_policy_sha256": shown["upload_policy_sha256"],
        },
        headers=WRITE,
    )
    assert turned.status_code == 200, turned.text
    assert turned.json()["state"] == "on"
    client.cookies.clear()


def _file_headers(data: bytes) -> dict[str, str]:
    return {
        "Content-Type": "application/octet-stream",
        "X-Source-SHA256": hashlib.sha256(data).hexdigest(),
        "X-Recording-Consent": key_upload.CONSENT,
    }


async def _events(setup: Any, action: str, resource_id: str) -> list[AuditEvent]:
    async with setup.sessions() as db:
        rows = await db.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.tenant_id == setup.state.tenant_id,
                AuditEvent.action == action,
                AuditEvent.resource_id == resource_id,
            )
            .order_by(AuditEvent.sequence_no)
        )
        return list(rows.all())


async def _audio_checked(setup: Any, upload_id: UUID, data: bytes) -> UUID:
    """The call's audio check (C1) done, as the worker leaves it."""
    await _reconcile(setup.sessions, setup.state)
    async with setup.sessions() as db:
        link = await db.get(ConversationGuestSubmission, (setup.state.tenant_id, upload_id))
    assert link is not None
    await seed_measured_fixture(
        setup.sessions,
        SimpleNamespace(recording_id=link.recording_id),
        signal_payload=_signal(source_sha256=hashlib.sha256(data).hexdigest()),
    )
    async with setup.sessions() as db, db.begin():
        await db.execute(
            update(ConversationRun)
            .where(ConversationRun.recording_id == link.recording_id)
            .values(state="completed", completed_at=setup.clock[0])
        )
    return UUID(str(link.recording_id))


def test_an_organisation_key_sends_a_sellers_call_and_the_server_starts_it(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path, gemini=True)
        setup.native.validate_source = ValidationFixtureRuntime().validate_source
        try:
            await _organisation(setup)  # the signed-in person is an admin here
            _install(setup)
            seller = await seed(setup.engine, tenant_id=setup.state.tenant_id, role="member")
            key, key_id = await _key(setup, ["recordings:write"])
            bearer = {"Authorization": f"Bearer {key}"}
            body = {"seller_id": str(seller.person_id), "file_name": "call.wav"}
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                # Until an owner or admin switches API uploads on, nothing is taken.
                closed = await client.post(API, json=body, headers=bearer)
                assert closed.status_code == 403, closed.text
                assert closed.json()["error"] == {
                    "code": "api_uploads_off",
                    "message": "API uploads aren't switched on for this workspace yet.",
                }
                await _switch_on(setup, client)

                opened = await client.post(API, json=body, headers=bearer)
                assert opened.status_code == 201, opened.text
                upload = opened.json()
                assert (upload["state"], upload["seller_id"]) == (
                    "waiting_for_file",
                    str(seller.person_id),
                )
                upload_id, link = UUID(upload["id"]), upload["upload_url"]
                assert link.split("?", 1)[0].endswith(f"{API}/{upload_id}/source")

                # The file through the link alone, stating the people on it know.
                data = _wav_one_second_48k()
                unstated = {**_file_headers(data)}
                del unstated["X-Recording-Consent"]
                refused = await client.put(link, content=data, headers=unstated)
                assert refused.status_code == 422, refused.text
                assert refused.json()["error"]["code"] == "recording_consent"
                last = link[-1]
                forged = link[:-1] + ("A" if last != "A" else "B")
                assert (
                    await client.put(forged, content=data, headers=_file_headers(data))
                ).status_code == 401
                sent = await client.put(link, content=data, headers=_file_headers(data))
                assert sent.status_code == 202, sent.text
                assert (sent.json()["state"], sent.json()["call_id"]) == ("queued", str(upload_id))
                # Sending it again changes nothing.
                again = await client.put(link, content=data, headers=_file_headers(data))
                assert again.status_code == 200, again.text

                # The call is the seller's own, and the audit names the key and its maker.
                async with setup.sessions() as db:
                    usage = await db.scalar(
                        select(ConversationAcquisitionUsage).where(
                            ConversationAcquisitionUsage.submission_id == upload_id
                        )
                    )
                assert usage is not None and usage.person_id == seller.person_id
                (uploaded,) = await _events(setup, key_upload.UPLOADED, str(upload_id))
                assert (uploaded.actor_type, uploaded.actor_person_id, uploaded.session_id) == (
                    "api_key",
                    setup.state.person_id,
                    None,
                )
                assert uploaded.payload["key_id"] == str(key_id)
                assert uploaded.payload["seller_person_id"] == str(seller.person_id)
                assert uploaded.payload["recording_consent"] == "participants-informed"

                # Once its audio check is done, the server starts it.
                recording_id = await _audio_checked(setup, upload_id, data)
                starter = auto_start.AutoStart(
                    sessions=setup.sessions,
                    runtime=setup.runtime,
                    factory=setup.factory,
                    environment="test",
                )
                assert await starter.tick(now=setup.clock[0]) == ["started"]
                async with setup.sessions() as db:
                    (plan,) = (
                        await db.scalars(
                            select(ConversationProcessingPlan).where(
                                ConversationProcessingPlan.recording_id == recording_id
                            )
                        )
                    ).all()
                assert plan.acceptance_command_id is not None
                (started,) = await _events(setup, auto_start.STARTED, str(upload_id))
                assert started.payload == {
                    "api_upload_terms_event_id": uploaded.payload["api_upload_terms_event_id"],
                    "key_id": str(key_id),
                    "plan_id": str(plan.id),
                    "started_by": "server",
                }
                assert (started.actor_type, started.actor_person_id, started.session_id) == (
                    "api_key",
                    seller.person_id,
                    None,
                )
                assert await starter.tick(now=setup.clock[0]) == []

                # Its progress, by the API and by MCP.
                expected = "analysing" if plan.state == "active" else "held"
                status = await client.get(f"{API}/{upload_id}", headers=bearer)
                assert status.status_code == 200, status.text
                assert status.json()["state"] == expected
                listed = await client.post(
                    "/v1/mcp",
                    headers=bearer,
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                )
                names = {tool["name"] for tool in listed.json()["result"]["tools"]}
                assert {"create_recording_upload", "recording_status"} <= names
                called = await client.post(
                    "/v1/mcp",
                    headers=bearer,
                    json={
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/call",
                        "params": {
                            "name": "recording_status",
                            "arguments": {"upload_id": str(upload_id)},
                        },
                    },
                )
                result = called.json()["result"]
                shown = result.get("structuredContent") or json.loads(result["content"][0]["text"])
                assert shown["state"] == expected
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_api_uploads_refuse_what_the_app_refuses(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path, gemini=True)
        setup.native.validate_source = ValidationFixtureRuntime().validate_source
        try:
            await _organisation(setup)
            _install(setup)
            seller = await seed(setup.engine, tenant_id=setup.state.tenant_id, role="member")
            key, key_id = await _key(setup, ["recordings:write"])
            reads, _ = await _key(setup, ["calls:read"], name="Reports")
            bearer = {"Authorization": f"Bearer {key}"}
            body = {"seller_id": str(seller.person_id)}
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                # A member can't switch API uploads on.
                client.cookies.set(
                    setup.settings.session_cookie_name, await _session(setup, seller)
                )
                shown = (await client.get(recordings_api.TERMS_PATH)).json()
                member = await client.post(
                    recordings_api.TERMS_PATH,
                    json={
                        "decision": "granted",
                        "policy_sha256": shown["notice"]["policy_sha256"],
                        "upload_policy_sha256": shown["upload_policy_sha256"],
                    },
                    headers=WRITE,
                )
                assert member.status_code == 403, member.text
                await _switch_on(setup, client)

                async def create(**changes: Any) -> httpx.Response:
                    headers = changes.pop("headers", bearer)
                    return await client.post(API, json={**body, **changes}, headers=headers)

                def code(response: httpx.Response) -> tuple[int, str]:
                    return response.status_code, response.json()["error"]["code"]

                # A key without the scope; a seller who isn't here; both or neither named.
                assert code(await create(headers={"Authorization": f"Bearer {reads}"})) == (
                    403,
                    "scope_missing",
                )
                assert code(
                    await client.post(
                        API, json={"seller_email": "nobody@example.test"}, headers=bearer
                    )
                ) == (404, "seller_missing")
                assert code(await create(seller_email="x@example.test")) == (422, "seller")
                assert code(await create(lead_id=str(uuid4()))) == (404, "lead_missing")

                # The key's maker no longer an owner or admin: the key can't upload.
                async with setup.sessions() as db, db.begin():
                    await db.execute(
                        update(Membership)
                        .where(Membership.person_id == setup.state.person_id)
                        .values(role="member")
                    )
                assert code(await create()) == (403, "key_denied")
                async with setup.sessions() as db, db.begin():
                    await db.execute(
                        update(Membership)
                        .where(Membership.person_id == setup.state.person_id)
                        .values(role="admin")
                    )

                # Revoked between opening the upload and sending the file: the link is dead.
                opened = await create()
                assert opened.status_code == 201, opened.text
                async with setup.sessions() as db, db.begin():
                    await db.execute(
                        update(IntegrationApiKey)
                        .where(IntegrationApiKey.id == key_id)
                        .values(
                            revoked_at=datetime.now(UTC), revoked_by_person_id=setup.state.person_id
                        )
                    )
                data = _wav_one_second_48k()
                late = await client.put(
                    opened.json()["upload_url"], content=data, headers=_file_headers(data)
                )
                assert code(late) == (403, "key_denied")

                # Out of minutes: refused before any file is taken.
                fresh, _ = await _key(setup, ["recordings:write"], name="Second")
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
                spent = await create(headers={"Authorization": f"Bearer {fresh}"})
                assert code(spent) == (409, "out_of_minutes")
                assert "allowance" in spent.json()["error"]["message"]

            # Outside local, test and development the terms can't be recorded, and an
            # acceptance already there reads as closed.
            async with setup.sessions() as db, db.begin():
                terms = upload_policy(setup.runtime.policy)["policy_sha256"]
                for place in ("staging", "production"):
                    assert (
                        await key_upload.terms(db, setup.state.tenant_id, terms, place)
                    ).state == "closed"
                    assert await key_upload.may_upload(
                        db, setup.state.tenant_id, seller.person_id, terms, place
                    ) == (None, key_upload.CLOSED)
                    with pytest.raises(ConversationDenied, match="switched on"):
                        await key_upload.record_terms(
                            db,
                            tenant_id=setup.state.tenant_id,
                            person_id=setup.state.person_id,
                            session_id=uuid4(),
                            role="owner",
                            decision="granted",
                            environment=place,
                            policy_sha256=key_upload.notice()["policy_sha256"],
                            upload_policy_sha256=terms,
                            now=datetime.now(UTC),
                        )
                assert (
                    await key_upload.terms(db, setup.state.tenant_id, terms, "test")
                ).state == "on"
        finally:
            await setup.engine.dispose()

    run(exercise())
