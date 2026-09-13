"""Real AC cookie authentication and PostgreSQL through the conversation HTTP routes.

ASGI transport is in process. The real local native worker uses synthetic WAV;
the imported Scribe response is a fixture, not an external inference request.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.application import (
    AUDIOATLAS_HOSTED_RECIPE,
    AUDIOATLAS_RECIPE,
)
from ac_platform.conversation_intelligence.models import ConversationPermission
from ac_platform.http.auth import install_identity_http
from ac_platform.http.conversation import install_conversation_http
from ac_platform.http.conversation_admin import install_conversation_admin_http
from ac_platform.http.conversation_intake import ConversationIntakeRuntime
from ac_platform.http.problem import register_problem_handlers
from ac_platform.http.request_limits import RequestBodyLimitMiddleware
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from tests.database.test_conversation_intake_postgresql import policy
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_reports_postgresql import (
    _build_fixture,
    shared_provider_admin_context,
)


@pytest.fixture(scope="module")
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


def test_cookie_authenticated_saved_report_history_transcript_and_private_playback(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        fixture = await _build_fixture(postgres_harness, tmp_path)
        prepared = fixture.prepared
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        pepper = "synthetic-http-session-pepper-for-local-proof"
        token = secrets.token_urlsafe(32)
        settings = Settings(
            _env_file=None,
            environment="test",
            public_app_url="http://learner.test",
            admin_app_url="http://admin.test",
            coach_app_url="http://coach.test",
            api_url="http://api.test",
            session_token_pepper=pepper,
            oauth_transaction_secret=secrets.token_urlsafe(32),
            email_challenge_secret=secrets.token_urlsafe(32),
        )
        runtime = ConversationIntakeRuntime(
            replace(
                policy(prepared.scope_id, prepared.state.tenant_id),
                acoustic_recipe=AUDIOATLAS_HOSTED_RECIPE,
            ),
            prepared.storage,
            prepared.scratch,
        )
        app = FastAPI()
        register_problem_handlers(app)
        require_actor = install_identity_http(app, settings=settings, sessions=sessions)
        install_conversation_http(
            app, settings=settings, require_actor=require_actor, intake_runtime=runtime
        )
        install_conversation_admin_http(
            app, settings=settings, require_actor=require_actor, import_storage=prepared.storage
        )
        app.add_middleware(RequestBodyLimitMiddleware)

        async def set_token(session_id: Any, value: str) -> None:
            async with sessions() as database, database.begin():
                await database.execute(
                    update(IdentitySession)
                    .where(IdentitySession.id == session_id)
                    .values(
                        token_hash=hmac.new(
                            pepper.encode(), value.encode(), hashlib.sha256
                        ).digest()
                    )
                )

        def cookie(value: str) -> dict[str, str]:
            return {"Cookie": f"{settings.session_cookie_name}={value}"}

        root = "/v1/conversation"
        source_path = f"{root}/recordings/{prepared.recording_id}/source"
        transcript_path = f"{root}/recordings/{prepared.recording_id}/transcript"
        report_path = f"{root}/runs/{prepared.run_id}/report"
        admin_path = f"/v1/admin/conversation/runs/{prepared.run_id}/draft"
        admin_headers = {
            **cookie(token),
            "Origin": "http://admin.test",
            "Idempotency-Key": "http-draft",
        }
        try:
            await set_token(prepared.state.session_id, token)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://learner.test"
            ) as client:
                for path in (source_path, transcript_path, report_path, f"{root}/recordings"):
                    assert (await client.get(path)).status_code == 401
                stale_run = await client.post(
                    f"{root}/runs",
                    headers={
                        **cookie(token),
                        "Origin": "http://learner.test",
                        "Idempotency-Key": "stale-recipe-after-cutover",
                    },
                    json={
                        "recording_id": str(prepared.recording_id),
                        "source_revision": "1",
                        "quote_id": str(prepared.quote_id),
                        "recipe_revision": AUDIOATLAS_RECIPE,
                    },
                )
                assert stale_run.status_code == 409
                assert "recipe changed" in stale_run.text
                before = await client.get(report_path, headers=cookie(token))
                assert before.status_code == 200, before.text
                assert before.json()["report"] is None
                assert before.json()["state"] == "completed"
                assert (await client.get(transcript_path, headers=cookie(token))).status_code == 404
                blocked_surface = await client.post(
                    admin_path, headers=admin_headers, json=fixture.intent.model_dump(mode="json")
                )
                assert blocked_surface.status_code == 403
                blocked_origin = await client.post(
                    f"http://admin.test{admin_path}",
                    headers={**admin_headers, "Origin": "https://untrusted.invalid"},
                    json=fixture.intent.model_dump(mode="json"),
                )
                assert blocked_origin.status_code == 403
                with shared_provider_admin_context(fixture):
                    imported = await client.post(
                        f"http://admin.test{admin_path}",
                        headers=admin_headers,
                        json=fixture.intent.model_dump(mode="json"),
                    )
                assert imported.status_code == 201, imported.text
                assert imported.headers["cache-control"] == "private, no-store"
                report = await client.get(report_path, headers=cookie(token))
                assert report.status_code == 200
                assert report.json() == imported.json()
                assert report.json()["report"]["source_sha256"] == prepared.state.source_sha256
                assert report.json()["report"]["review_status"] == "draft_not_dipak_adjudicated"
                history = await client.get(f"{root}/recordings", headers=cookie(token))
                assert history.status_code == 200
                entries = history.json()["recordings"]
                assert len(entries) == 1
                assert entries[0]["id"] == str(prepared.recording_id)
                assert entries[0]["latest_run"]["id"] == str(prepared.run_id)
                assert entries[0]["has_report"] is True
                assert entries[0]["latest_run"]["has_report"] is True
                transcript = await client.get(transcript_path, headers=cookie(token))
                assert transcript.status_code == 200
                assert transcript.json()["duration_ms"] == 1000
                assert transcript.json()["segments"][0]["text"] == "Hello buyer"
                assert (
                    transcript.json()["revision"] == report.json()["report"]["transcript_revision"]
                )
                assert "native_json" not in transcript.json()
                assert "evidence_receipt" not in report.json()
                whole = await client.get(source_path, headers=cookie(token))
                assert whole.status_code == 200, whole.text[:100]
                assert whole.content == prepared.data
                assert whole.headers["cache-control"] == "private, no-store"
                assert whole.headers["x-content-type-options"] == "nosniff"
                part = await client.get(
                    source_path, headers={**cookie(token), "Range": "bytes=4-99"}
                )
                assert part.status_code == 206
                assert part.content == prepared.data[4:100]
                assert part.headers["content-range"] == f"bytes 4-99/{len(prepared.data)}"
                suffix = await client.get(
                    source_path, headers={**cookie(token), "Range": "bytes=-16"}
                )
                assert suffix.status_code == 206 and suffix.content == prepared.data[-16:]
                invalid = await client.get(
                    source_path, headers={**cookie(token), "Range": "bytes=1-2,5-6"}
                )
                assert invalid.status_code == 416
                assert (
                    await client.get(source_path + "?tenant_id=other", headers=cookie(token))
                ).status_code == 422
                for same_tenant in (True, False):
                    other = await seed(
                        engine, tenant_id=prepared.state.tenant_id if same_tenant else None
                    )
                    other_token = f"synthetic_http_other_session_token_{other.session_id.hex}"
                    await set_token(other.session_id, other_token)
                    async with sessions() as database, database.begin():
                        await database.execute(
                            update(Person)
                            .where(Person.id == other.person_id)
                            .values(email=f"synthetic-{other.person_id.hex}@example.test")
                        )
                    assert (
                        await client.get("/v1/me", headers=cookie(other_token))
                    ).status_code == 200
                    for path in (source_path, transcript_path, report_path):
                        denied = await client.get(path, headers=cookie(other_token))
                        assert denied.status_code == 404, denied.text
                    assert (
                        await client.get(f"{root}/recordings", headers=cookie(other_token))
                    ).json() == {"recordings": []}
                oversized = await client.post(
                    f"http://admin.test{admin_path}",
                    headers=admin_headers,
                    content=b" " * (4 * 1024 * 1024 + 1),
                )
                assert oversized.status_code == 413
                async with sessions() as database, database.begin():
                    await database.execute(
                        update(ConversationPermission)
                        .where(ConversationPermission.id == prepared.state.permission_id)
                        .values(revoked_at=prepared.state.now)
                    )
                for path in (source_path, transcript_path, report_path):
                    assert (await client.get(path, headers=cookie(token))).status_code == 403
                assert (await client.get(f"{root}/recordings", headers=cookie(token))).json() == {
                    "recordings": []
                }
        finally:
            await engine.dispose()

    run(exercise())
