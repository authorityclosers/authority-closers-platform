"""Real private cookie/HTTP/store proof on disposable PostgreSQL; fictional C2."""

import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select, update
from starlette.requests import ClientDisconnect, Request

from ac_platform.audit.models import AuditEvent
from ac_platform.conversation_intelligence.acquisition_reports import AcquisitionReports
from ac_platform.conversation_intelligence.speaker_map_models import ConversationSpeakerMapRevision
from ac_platform.db.models import model_metadata
from ac_platform.http.auth import AuthenticatedTransaction
from ac_platform.http.conversation_submissions import install_submission_http
from ac_platform.identity.models import Person
from ac_platform.kernel.authz import ActorContext
from tests.database.test_conversation_account_library_postgresql import (
    _seed_retained_guest_submission,
    _session,
)
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, PREFIX, _setup
from tests.unit.conversation_intelligence.test_speaker_map_service import TRANSCRIPT
from tests.unit.http.test_conversation_learner_acquisition import (
    PERSON_ID,
    PUBLIC_TENANT,
    SESSION_ID,
    _Database,
    _runtime,
    _Service,
    _settings,
)

HEADERS = {"Origin": ORIGIN, "If-Match": '"call-label-0"'}
CHOICES = [
    {"speaker_id": "speaker_0", "role": "you", "display_name": None},
    {"speaker_id": "speaker_1", "role": "prospect", "display_name": "रवि जी", "icon": "carpentry"},
]


@pytest.fixture(scope="module")
def postgres_harness():
    yield from _postgres_harness.__wrapped__()


def test_http_predictions_confirmations_fences_and_no_analysis_side_effects(
    postgres_harness, tmp_path, monkeypatch
):
    async def exercise():
        setup = await _setup(postgres_harness, tmp_path)
        try:
            source = await _seed_retained_guest_submission(setup)
            path = PREFIX + f"/submissions/{source['submission_id']}/speaker-map"
            transport = httpx.ASGITransport(app=setup.app)
            async with httpx.AsyncClient(transport=transport, base_url=ORIGIN) as owner:
                owner.cookies.set(setup.settings.session_cookie_name, setup.token)
                assert (await owner.get(path)).status_code == 404  # unclaimed
                async with setup.sessions() as db, db.begin():
                    await setup.factory(db).claim(setup.guest.token, setup.state.actor)
                    await db.execute(
                        update(Person)
                        .where(Person.id == setup.state.person_id)
                        .values(display_name="Different Name")
                    )
                unavailable = await owner.get(path)
                assert unavailable.status_code == 200 and unavailable.json()["speakers"] == []
                assert unavailable.json()["unavailable_reason"] == "transcript_not_ready"
                assert unavailable.headers["etag"] == '"call-label-0"'
                transcript = deepcopy(TRANSCRIPT)

                async def render(_self, recording):
                    assert recording.id == source["recording_id"]
                    assert recording.person_id != setup.state.person_id
                    return transcript

                monkeypatch.setattr(AcquisitionReports, "render_transcript", render)
                result = await owner.get(path)
                body = result.json()
                assert set(body) == {
                    "schema",
                    "submission_id",
                    "status",
                    "unavailable_reason",
                    "transcript_revision",
                    "map_revision",
                    "user_revision",
                    "speakers",
                    "report_basis",
                }
                assert (
                    body["schema"] == "ac.sales-xray.speaker-map/1"
                    and body["status"] == "predicted"
                )
                assert body["report_basis"] is None and len(body["map_revision"]) == 64
                assert body["speakers"][0]["role"] == "salesperson"  # not profile owner
                assert body["speakers"][0]["display_name"] == "Zoya"
                assert set(body["speakers"][0]) == {
                    "speaker_id",
                    "number",
                    "role",
                    "role_source",
                    "display_name",
                    "name_source",
                    "name_evidence",
                    "role_cues",
                    "channel",
                    "confidence",
                }
                assert (
                    result.headers["cache-control"] == "private, no-store"
                    and result.headers["vary"] == "Cookie"
                )

                # Preserve complete row contents, not just counts, for all processing,
                # report and usage tables. Identity session telemetry is independent.
                tables = [
                    table
                    for name, table in model_metadata().tables.items()
                    if name.startswith("conversation_")
                    and name != "conversation_speaker_map_revisions"
                ]

                async def processing_state():
                    async with setup.sessions() as db:
                        return {
                            table.name: [
                                dict(row) for row in (await db.execute(select(table))).mappings()
                            ]
                            for table in tables
                        }

                before = await processing_state()
                payload = {"transcript_revision": transcript["revision"], "speakers": CHOICES}
                saved = await owner.put(path, json=payload, headers=HEADERS)
                assert saved.status_code == 200, saved.text
                assert (
                    saved.headers["etag"] == '"call-label-1"'
                    and saved.json()["status"] == "confirmed"
                )
                assert saved.json()["speakers"][0]["display_name"] == "Different Name"
                assert saved.json()["speakers"][1]["display_name"] == "रवि जी"
                assert saved.json()["speakers"][1]["icon"] == "carpentry"
                retry = await owner.put(
                    path, json={**payload, "speakers": list(reversed(CHOICES))}, headers=HEADERS
                )
                assert retry.status_code == 200 and retry.json() == saved.json()
                assert (await owner.get(path)).json() == saved.json()
                legacy = [
                    {key: value for key, value in row.items() if key != "icon"} for row in CHOICES
                ]
                assert (
                    await owner.put(path, json={**payload, "speakers": legacy}, headers=HEADERS)
                ).json() == saved.json()
                async with httpx.AsyncClient(transport=transport, base_url=ORIGIN) as reopened:
                    reopened.cookies.set(setup.settings.session_cookie_name, setup.token)
                    assert (await reopened.get(path)).json() == saved.json()
                assert (
                    await owner.put(
                        path,
                        json={**payload, "speakers": [CHOICES[0], {**CHOICES[1], "icon": None}]},
                        headers=HEADERS,
                    )
                ).status_code == 409
                swapped = [{**CHOICES[0], "role": "salesperson"}, {**CHOICES[1], "role": "you"}]
                stale = await owner.put(
                    path, json={**payload, "speakers": swapped}, headers=HEADERS
                )
                assert (
                    stale.status_code == 409
                    and stale.json()["detail"]
                    == "The speakers changed. Reload before saving again."
                )
                assert (
                    await owner.put(
                        path, json={**payload, "transcript_revision": "old"}, headers=HEADERS
                    )
                ).status_code == 409
                simultaneous = await asyncio.gather(
                    *(
                        owner.put(
                            path,
                            json={
                                **payload,
                                "speakers": [
                                    swapped[0],
                                    {**swapped[1], "display_name": name, "icon": None},
                                ],
                            },
                            headers={**HEADERS, "If-Match": '"call-label-1"'},
                        )
                        for name in ("रवि जी", "Other choice")
                    )
                )
                assert sorted(item.status_code for item in simultaneous) == [200, 409]
                changed = next(item for item in simultaneous if item.status_code == 200)
                assert changed.status_code == 200 and changed.headers["etag"] == '"call-label-2"'
                assert changed.json()["speakers"][1]["icon"] is None
                transcript["revision"] = "new-c2"
                fresh = await owner.get(path)
                assert (
                    fresh.json()["status"] == "predicted"
                    and fresh.headers["etag"] == '"call-label-2"'
                )
                assert (
                    await owner.put(
                        path,
                        json={**payload, "transcript_revision": "new-c2"},
                        headers={**HEADERS, "If-Match": '"call-label-2"'},
                    )
                ).status_code == 200
                for invalid in (None, 'W/"call-label-3"', '"call-label-3", "call-label-3"'):
                    headers = (
                        {"Origin": ORIGIN} if invalid is None else {**HEADERS, "If-Match": invalid}
                    )
                    assert (await owner.put(path, json=payload, headers=headers)).status_code == 422
                assert (
                    await owner.put(
                        path, content=b"{}", headers={**HEADERS, "Content-Type": "text/plain"}
                    )
                ).status_code == 415
                assert (
                    await owner.put(
                        path,
                        content=b"x" * 8193,
                        headers={**HEADERS, "Content-Type": "application/json"},
                    )
                ).status_code == 413
                payload["transcript_revision"] = "new-c2"
                encoded = json.dumps(payload).encode()
                assert (
                    await owner.put(
                        path,
                        content=encoded + b" " * (8192 - len(encoded)),
                        headers={**HEADERS, "Content-Type": "application/json"},
                    )
                ).status_code == 200
                invalid_bodies = [{**payload, "source": "confirmed"}, {"speakers": CHOICES}]
                invalid_bodies += [
                    {**payload, "speakers": [{**CHOICES[0], "display_name": value}, CHOICES[1]]}
                    for value in ("", "x\n", "x\u202e", "x" * 121)
                ]
                invalid_bodies += [
                    {**payload, "speakers": [CHOICES[0], {**CHOICES[1], "icon": value}]}
                    for value in ("../person", "<svg>", "x" * 65, 3)
                ]
                for invalid in invalid_bodies:
                    failure = await owner.put(path, json=invalid, headers=HEADERS)
                    assert (
                        failure.status_code == 422
                        and "call name" not in failure.text
                        and "120" not in failure.text
                    )
                assert (
                    await owner.put(
                        path,
                        json=payload,
                        headers={**HEADERS, "Origin": "https://foreign.example.test"},
                    )
                ).status_code == 403
                assert (await owner.get(path + "?person_id=other")).status_code == 422
                assert await processing_state() == before
                async with setup.sessions() as db:
                    revisions = (
                        await db.scalars(
                            select(ConversationSpeakerMapRevision)
                            .where(
                                ConversationSpeakerMapRevision.submission_id
                                == source["submission_id"]
                            )
                            .order_by(ConversationSpeakerMapRevision.revision)
                        )
                    ).all()
                    assert [row.revision for row in revisions] == [1, 2, 3]
                    assert revisions[0].speakers[1]["icon"] == "carpentry"
                    assert revisions[1].speakers[1]["icon"] is None
                    assert revisions[2].speakers[1]["icon"] == "carpentry"
                    events = (
                        await db.scalars(
                            select(AuditEvent).where(
                                AuditEvent.action == "conversation.speaker_map_changed",
                                AuditEvent.tenant_id == setup.state.tenant_id,
                            )
                        )
                    ).all()
                    assert [row.payload for row in events] == [
                        {"old_revision": n, "new_revision": n + 1} for n in range(3)
                    ]
            for foreign in (False, True):
                stranger = await seed(
                    setup.engine, tenant_id=None if foreign else setup.state.tenant_id
                )
                token = await _session(setup, stranger)
                async with httpx.AsyncClient(transport=transport, base_url=ORIGIN) as other:
                    other.cookies.set(setup.settings.session_cookie_name, token)
                    assert (await other.get(path)).status_code == 404
                    assert (await other.put(path, json=payload, headers=HEADERS)).status_code == 404
            async with httpx.AsyncClient(transport=transport, base_url=ORIGIN) as guest:
                guest.cookies.set("ac_xray_guest", setup.guest.token)
                assert (await guest.get(path)).status_code == 404
                assert (await guest.put(path, json=payload, headers=HEADERS)).status_code == 404
        finally:
            await setup.engine.dispose()

    run(exercise())


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["slow", "disconnect"])
async def test_interrupted_body_is_408_without_store_call(tmp_path, monkeypatch, failure):
    actor = ActorContext(PERSON_ID, SESSION_ID, PUBLIC_TENANT)

    async def require_actor(request):
        yield AuthenticatedTransaction(
            _Database(), SimpleNamespace(), SimpleNamespace(actor=actor), "fictional-session"
        )

    runtime, app = _runtime(tmp_path), FastAPI()
    monkeypatch.setattr(_Service, "clock", None, raising=False)
    install_submission_http(
        app,
        settings=_settings(),
        sessions=None,
        require_actor=require_actor,
        factory=_Service,
        runtime=runtime.intake,
        preflight=runtime.preflight,
    )
    save = AsyncMock()
    monkeypatch.setattr("ac_platform.http.conversation_submissions.confirm_speaker_map", save)

    async def interrupted(self):
        if failure == "slow":
            await asyncio.sleep(6)
            yield b"{}"
        else:
            raise ClientDisconnect()

    monkeypatch.setattr(Request, "stream", interrupted)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://learner.example.test"
    ) as client:
        response = await client.put(
            PREFIX + f"/submissions/{PERSON_ID}/speaker-map",
            json={},
            headers={"Origin": "https://learner.example.test", "If-Match": '"call-label-0"'},
        )
        assert response.status_code == 408
        save.assert_not_awaited()
