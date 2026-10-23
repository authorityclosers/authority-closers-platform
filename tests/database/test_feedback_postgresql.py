"""Feedback and bug voice notes on PostgreSQL (owner, 23 Oct 2026: a reviews engine, and a
bug reporter with voice notes that tells testers when their report is fixed).

The migration passes the schema gate, rolls back only while empty; answers are append-only and a
retry finds the first; the asking state counts answers, "don't ask again" and subjects; a
"Not good" with words becomes a bug report; the team's summary groups by moment, release
and day; a voice note is kept with its report and played back to the team; a person sees
their own reports and where each stands. Disposable loopback PostgreSQL, fictional rows only;
the test's own workspace is the operations workspace.
"""

from __future__ import annotations

import base64
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.bug_reports import http as bug_http
from ac_platform.bug_reports.models import BugReport
from ac_platform.feedback import http as feedback_http
from ac_platform.feedback.models import FeedbackHistoryError, FeedbackResponse
from ac_platform.http.routes import RouteContext
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup

ROOT = Path(__file__).resolve().parents[2]
REVISION, DOWN = "20261023_0127", "20261023_0126"
FILE = "20261023_0127_feedback.py"
WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 200


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


class _Admitted:
    def __init__(self, application: Any) -> None:
        pass

    async def admit(self, actor: Any) -> None:
        return None


def migration() -> Any:
    path = ROOT / "db/migrations/versions" / FILE
    spec = importlib.util.spec_from_file_location("feedback_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_chain_schema_gate_and_forward_only() -> None:
    from scripts.ci.migration_schema_gate import check_operations
    from scripts.ops.migration_safety import classify_source

    module = migration()
    assert (module.revision, module.down_revision) == (REVISION, DOWN)
    path = Path(module.__file__)
    found = classify_source(path.read_text(), str(path))
    check_operations([found], set())
    assert found.verdict == "additive"
    # Rollback is allowed only while both tables are empty; history forces forward recovery.
    module.op = SimpleNamespace(
        execute=lambda statement: None,
        get_bind=lambda: SimpleNamespace(scalar=lambda statement: 1),
    )
    with pytest.raises(RuntimeError, match="history requires forward recovery"):
        module.downgrade()


def _answer(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "command_id": str(uuid4()),
        "moment": "report_read",
        "kind": "rating",
        "rating": 3,
        "comment": None,
        "subject": "call:2b1f",
        "route": "/analysis/calls/2b1f?token=abc",
        "context": {
            "app": {"channel": "android", "release": "rel-1"},
            "device": {"os": "Android 14"},
        },
    }
    body.update(overrides)
    return body


def test_people_answer_and_the_team_sees_trends(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(feedback_http, "ConversationProviderAdmin", _Admitted)
    monkeypatch.setattr(feedback_http, "require_admin_surface", lambda request, settings: None)

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            ctx = RouteContext(
                setup.settings.model_copy(update={"operations_tenant_id": setup.state.tenant_id}),
                setup.require_actor,
                setup.sessions,
            )
            feedback_http.install_feedback_http(setup.app, ctx)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as http:
                http.cookies.set(setup.settings.session_cookie_name, setup.token)
                great = _answer()
                sent = await http.post("/v1/feedback", json=great, headers=WRITE)
                assert sent.status_code == 201, sent.text
                assert "bug_id" not in sent.json()
                again = await http.post("/v1/feedback", json=great, headers=WRITE)
                assert again.status_code == 200
                assert again.json() == {"feedback_id": sent.json()["feedback_id"]}

                for bad in (
                    _answer(moment="somewhere"),
                    _answer(kind="dismissed"),
                    _answer(kind="rating", rating=None),
                    _answer(kind="opt_out", rating=None, comment="why"),
                    _answer(subject="has spaces"),
                ):
                    assert (
                        await http.post("/v1/feedback", json=bad, headers=WRITE)
                    ).status_code == 422
                no_origin = await http.post(
                    "/v1/feedback", json=_answer(), headers={"Content-Type": "application/json"}
                )
                assert no_origin.status_code == 403

                worse = await http.post(
                    "/v1/feedback",
                    json=_answer(
                        moment="call_outcome",
                        rating=1,
                        comment="The outcome sheet lost my note",
                        subject=None,
                        route="/leads?lead=1",
                    ),
                    headers=WRITE,
                )
                assert worse.status_code == 201, worse.text
                bug_id = worse.json()["bug_id"]
                for extra in (
                    _answer(moment="chats_used", kind="dismissed", rating=None, subject=None),
                    _answer(moment="chats_used", kind="opt_out", rating=None, subject=None),
                    _answer(moment="app_update", rating=2, subject="update:v0-86", context={}),
                ):
                    assert (
                        await http.post("/v1/feedback", json=extra, headers=WRITE)
                    ).status_code == 201

                state = (await http.get("/v1/feedback/state")).json()
                assert state["opted_out"] == ["chats_used"]
                assert set(state["last"]) == {
                    "report_read",
                    "call_outcome",
                    "chats_used",
                    "app_update",
                }
                assert state["asked_today"] == 4  # opt-outs are not questions
                assert set(state["subjects"]) == {"call:2b1f", "update:v0-86"}

                summary = (await http.get("/v1/admin/feedback", params={"days": 7})).json()
                moments = {row["moment"]: row for row in summary["moments"]}
                assert moments["report_read"]["good"] == 1
                assert moments["call_outcome"]["bad"] == 1
                assert moments["call_outcome"]["comments"] == 1
                assert moments["chats_used"]["dismissed"] == 1
                assert moments["chats_used"]["opted_out"] == 1
                assert {row["release"] for row in summary["releases"]} >= {"rel-1"}
                assert summary["recent"][0]["comment"] == "The outcome sheet lost my note"
                assert summary["recent"][0]["rating"] == "bad"
                assert summary["week"]["rated"] == 3 and summary["week"]["bad"] == 1
                assert (await http.get("/v1/admin/feedback", params={"days": 5})).status_code == 422
                assert (
                    await http.get("/v1/admin/feedback", params={"moment": "nowhere"})
                ).status_code == 422
            async with setup.sessions() as db:
                report = await db.get(BugReport, bug_id)
                assert report is not None
                assert report.words == "The outcome sheet lost my note"
                assert report.area == "leads"
                assert report.context["feedback"]["moment"] == "call_outcome"
                assert report.context["feedback"]["rating"] == "bad"
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_feedback_is_append_only(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            from datetime import UTC, datetime

            from ac_platform.feedback.store import FeedbackStore, NewFeedback

            async with setup.sessions() as db, db.begin():
                row = await FeedbackStore(db).add(
                    NewFeedback(
                        person_id=setup.state.person_id,
                        tenant_id=setup.state.tenant_id,
                        command_id=uuid4(),
                        moment="general",
                        subject=None,
                        kind="rating",
                        rating=2,
                        comment=None,
                        route="/",
                        release=None,
                        context={},
                    ),
                    now=datetime.now(UTC),
                )
                answer_id = row.id
            async with AsyncSession(setup.engine) as db:
                answer = await db.get(FeedbackResponse, answer_id)
                assert answer is not None
                answer.rating = 3
                with pytest.raises(FeedbackHistoryError):
                    await db.flush()
                await db.rollback()
                answer = await db.get(FeedbackResponse, answer_id)
                assert answer is not None
                await db.delete(answer)
                with pytest.raises(FeedbackHistoryError):
                    await db.flush()
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_voice_notes_and_my_reports(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bug_http, "ConversationProviderAdmin", _Admitted)
    monkeypatch.setattr(bug_http, "require_admin_surface", lambda request, settings: None)
    store_root = tmp_path / "store"
    store_root.mkdir()

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            ctx = RouteContext(
                setup.settings.model_copy(
                    update={
                        "operations_tenant_id": setup.state.tenant_id,
                        "sales_xray_storage_root": str(store_root),
                    }
                ),
                setup.require_actor,
                setup.sessions,
            )
            bug_http.install_bug_reports_http(setup.app, ctx)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as http:
                http.cookies.set(setup.settings.session_cookie_name, setup.token)
                body = {
                    "command_id": str(uuid4()),
                    "words": "Said it instead of typing it",
                    "route": "/leads",
                    "voice": {
                        "content_type": "audio/webm",
                        "data": base64.b64encode(WEBM).decode(),
                        "seconds": 7,
                    },
                }
                sent = await http.post("/v1/bug-reports", json=body, headers=WRITE)
                assert sent.status_code == 201, sent.text
                assert sent.json()["voice"] == "kept"
                bug_id = sent.json()["bug_id"]
                again = await http.post("/v1/bug-reports", json=body, headers=WRITE)
                assert again.json()["voice"] == "kept"
                not_audio = await http.post(
                    "/v1/bug-reports",
                    json={
                        **body,
                        "command_id": str(uuid4()),
                        "voice": {
                            "content_type": "audio/ogg",
                            "data": base64.b64encode(b"not a recording").decode(),
                            "seconds": 3,
                        },
                    },
                    headers=WRITE,
                )
                assert not_audio.status_code == 201
                assert not_audio.json()["voice"] == "skipped"

                detail = (await http.get(f"/v1/admin/bugs/{bug_id}")).json()
                assert detail["voice"] == {
                    "content_type": "audio/webm",
                    "bytes": len(WEBM),
                    "seconds": 7,
                }
                assert detail["from_feedback"] is None
                played = await http.get(f"/v1/admin/bugs/{bug_id}/voice")
                assert played.status_code == 200
                assert played.headers["content-type"] == "audio/webm"
                assert played.content == WEBM
                assert (
                    store_root / "bug-reports" / f"{bug_id.replace('-', '')}.voice.webm"
                ).exists()
                missing = await http.get(f"/v1/admin/bugs/{not_audio.json()['bug_id']}/voice")
                assert missing.status_code == 404

                moved = await http.post(
                    f"/v1/admin/bugs/{bug_id}/events", json={"status": "fixed"}, headers=WRITE
                )
                assert moved.status_code == 200
                mine = (await http.get("/v1/bug-reports/mine")).json()["items"]
                assert [item["status"] for item in mine] == ["new", "fixed"]
                assert mine[1]["words"] == "Said it instead of typing it"
                assert mine[1]["status_at"] >= mine[1]["created_at"]
            async with setup.sessions() as db:
                assert (
                    await db.scalar(select(BugReport).where(BugReport.id == bug_id))
                ) is not None
        finally:
            await setup.engine.dispose()

    run(exercise())
