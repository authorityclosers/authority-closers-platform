"""Real loopback browser -> AC cookie auth -> PostgreSQL -> private WAV storage.

Requires the standalone static export and explicit disposable loopback database.
All call data and session credentials are synthetic. No API route is mocked;
no provider request, Google sign-in, production runtime or VPS is exercised.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import secrets
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import patch
from urllib.parse import urlsplit
from uuid import UUID

import pytest
import uvicorn
from fastapi import FastAPI
from playwright.sync_api import expect, sync_playwright
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.staticfiles import StaticFiles

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.application import ConversationApplication
from ac_platform.conversation_intelligence.inference_worker import ConversationInferenceWorker
from ac_platform.conversation_intelligence.models import ConversationCheckpoint
from ac_platform.conversation_intelligence.report_store import ConversationReports
from ac_platform.conversation_intelligence.reporting_pipeline import StageRequest
from ac_platform.conversation_intelligence.worker import OfflineConversationWorker
from ac_platform.http.auth import install_identity_http
from ac_platform.http.conversation import install_conversation_http
from ac_platform.http.conversation_intake import ConversationIntakeRuntime
from ac_platform.http.problem import register_problem_handlers
from ac_platform.http.request_limits import RequestBodyLimitMiddleware
from ac_platform.identity.models import Session as IdentitySession
from tests.database.test_conversation_inference_postgresql import _provider_quote
from tests.database.test_conversation_intake_postgresql import policy
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_reporting_pipeline_postgresql import (
    ReportingBroker,
    completed_checkpoint,
    enqueue,
    text_quote,
)
from tests.database.test_conversation_reports_postgresql import _build_fixture

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True, repr=False)
class BrowserBackend:
    origin: str
    cookie_name: str
    cookie_value: str
    recording_id: str
    source_sha256: str
    upload_bytes: bytes
    mode: str
    report_summary: str


async def _generate_durable_report(postgres_harness: Any, fixture: Any) -> None:
    """Generate one report through the durable C2/C4/C5 worker before serving HTTP."""

    prepared = fixture.prepared
    engine = create_async_engine(postgres_harness.url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    broker = ReportingBroker(prepared.data)
    worker = ConversationInferenceWorker(sessions, prepared.storage, broker)
    try:
        source_sha256 = hashlib.sha256(prepared.data).hexdigest()
        quote_id, quote = await _provider_quote(
            sessions,
            prepared.state,
            prepared.recording_id,
            prepared.scope_id,
            source_sha256,
        )
        asr = await enqueue(sessions, prepared, quote_id, quote, None, "browser-durable-asr")
        assert await worker.run_once()
        async with sessions() as db:
            c2_row = await db.scalar(
                select(ConversationCheckpoint)
                .where(
                    ConversationCheckpoint.recording_id == prepared.recording_id,
                    ConversationCheckpoint.stage == "C2",
                )
                .order_by(ConversationCheckpoint.created_at)
            )
            assert c2_row is not None
            c2 = c2_row.id
        assert c2 == await completed_checkpoint(sessions, asr)

        facts = StageRequest(stage="C4", transcript_checkpoint_id=c2)
        quote_id, quote = await text_quote(sessions, prepared, facts)
        fact_view = await enqueue(
            sessions, prepared, quote_id, quote, facts, "browser-durable-facts"
        )
        assert await worker.run_once()
        c4 = await completed_checkpoint(sessions, fact_view)

        coaching = StageRequest(
            stage="C5",
            transcript_checkpoint_id=c2,
            fact_checkpoint_ids=(c4,),
            max_completion_tokens=1_800,
        )
        quote_id, quote = await text_quote(sessions, prepared, coaching)
        report_view = await enqueue(
            sessions, prepared, quote_id, quote, coaching, "browser-durable-coaching"
        )
        assert await worker.run_once()
        await completed_checkpoint(sessions, report_view)
        async with sessions() as db:
            async with db.begin():
                report = await ConversationReports(ConversationApplication(db)).get(
                    fixture.actor, UUID(report_view["id"])
                )
            assert report["report"] is not None
            assert report["report"]["summary"] == "A synthetic draft from saved facts."
    finally:
        await engine.dispose()


@pytest.fixture
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


def _make_live_backend(
    postgres_harness: Any,
    tmp_path_factory: pytest.TempPathFactory,
    request: pytest.FixtureRequest,
    *,
    mode: str,
) -> Iterator[BrowserBackend]:
    exported = ROOT / "apps/sales-xray-web/out"
    if not (exported / "index.html").is_file():
        pytest.fail("Build the Sales Xray static export before this browser proof.")
    fixture = run(_build_fixture(postgres_harness, tmp_path_factory.mktemp("browser-call")))
    if mode == "durable":
        run(_generate_durable_report(postgres_harness, fixture))
    elif mode != "imported":
        raise AssertionError(f"Unknown browser proof mode: {mode}")
    prepared = fixture.prepared
    token = secrets.token_urlsafe(32)
    pepper = "synthetic-browser-proof-session-pepper"
    listener = socket.socket()
    request.addfinalizer(listener.close)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    origin = f"http://127.0.0.1:{listener.getsockname()[1]}"
    settings = Settings(
        _env_file=None,
        environment="test",
        public_app_url=origin,
        admin_app_url="http://admin.test",
        coach_app_url="http://coach.test",
        api_url=origin,
        session_token_pepper=pepper,
        oauth_transaction_secret=secrets.token_urlsafe(32),
        email_challenge_secret=secrets.token_urlsafe(32),
    )
    control: dict[str, Any] = {}
    stopped = threading.Event()

    async def serve() -> None:
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        worker_task: asyncio.Task[Any] | None = None
        try:
            async with sessions() as database, database.begin():
                await database.execute(
                    update(IdentitySession)
                    .where(IdentitySession.id == prepared.state.session_id)
                    .values(
                        token_hash=hmac.new(
                            pepper.encode(), token.encode(), hashlib.sha256
                        ).digest()
                    )
                )
                if mode == "imported":
                    # c8499b8 deliberately gives each shared-PG browser
                    # actor a unique synthetic email. Keep that identity
                    # while exercising the provider-admin checks; the
                    # production control-account address is not a fixture
                    # prerequisite for this disposable proof.
                    with patch(
                        "ac_platform.conversation_intelligence.provider_admin.CONTROL_ACCOUNT",
                        f"sales-xray-browser-{prepared.state.person_id}@example.test",
                    ):
                        await ConversationReports(
                            ConversationApplication(database)
                        ).import_internal_draft(
                            fixture.actor,
                            prepared.run_id,
                            fixture.intent,
                            storage=prepared.storage,
                            key="synthetic-browser-prepared-draft",
                        )
            app = FastAPI(docs_url=None, redoc_url=None)
            register_problem_handlers(app)
            require_actor = install_identity_http(app, settings=settings, sessions=sessions)
            install_conversation_http(
                app,
                settings=settings,
                require_actor=require_actor,
                intake_runtime=ConversationIntakeRuntime(
                    policy(prepared.scope_id, prepared.state.tenant_id),
                    prepared.storage,
                    prepared.scratch,
                ),
            )
            app.add_middleware(
                RequestBodyLimitMiddleware,
                conversation_upload_max_bytes=prepared.storage.max_bytes,
            )
            app.mount("/", StaticFiles(directory=exported, html=True))
            worker = OfflineConversationWorker(
                sessions, storage=prepared.storage, scratch=prepared.scratch, environment="test"
            )

            async def pump() -> None:
                while not stopped.is_set():
                    await worker.run_once()
                    await asyncio.sleep(0.1)

            worker_task = asyncio.create_task(pump())
            server = uvicorn.Server(
                uvicorn.Config(app, host="127.0.0.1", log_level="error", access_log=False)
            )
            control["server"] = server
            await server.serve(sockets=[listener])
        except BaseException as error:
            # Do not emit driver tracebacks, credentials or provider payloads.
            control["error_type"] = type(error).__name__
        finally:
            stopped.set()
            if worker_task is not None:
                await worker_task
            await engine.dispose()

    def start() -> None:
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            runner.run(serve())

    thread = threading.Thread(target=start, name="sales-xray-synthetic-browser-api", daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 30
        while not getattr(control.get("server"), "started", False):
            assert "error_type" not in control, control.get("error_type")
            assert time.monotonic() < deadline, "Synthetic browser API did not start."
            time.sleep(0.05)
        # Distinct valid WAV bytes ensure the upload cannot reuse the prepared call.
        upload = bytearray(prepared.data)
        upload[44:46] = b"\x01\x00"
        yield BrowserBackend(
            origin,
            settings.session_cookie_name,
            token,
            str(prepared.recording_id),
            prepared.state.source_sha256,
            bytes(upload),
            mode,
            (
                "A synthetic qualitative draft for human review."
                if mode == "imported"
                else "A synthetic draft from saved facts."
            ),
        )
    finally:
        stopped.set()
        server = control.get("server")
        if server is not None:
            server.should_exit = True
        thread.join(timeout=20)
        listener.close()
        assert not thread.is_alive(), "Synthetic browser API failed to stop."
        assert "error_type" not in control, control.get("error_type")


@pytest.fixture
def live_backend(
    postgres_harness: Any,
    tmp_path_factory: pytest.TempPathFactory,
    request: pytest.FixtureRequest,
) -> Iterator[BrowserBackend]:
    yield from _make_live_backend(postgres_harness, tmp_path_factory, request, mode="imported")


@pytest.fixture
def durable_live_backend(
    postgres_harness: Any,
    tmp_path_factory: pytest.TempPathFactory,
    request: pytest.FixtureRequest,
) -> Iterator[BrowserBackend]:
    yield from _make_live_backend(postgres_harness, tmp_path_factory, request, mode="durable")


def _exercise_browser(backend: BrowserBackend, evidence: Path) -> None:
    evidence.mkdir(parents=True, exist_ok=True)
    prefix = "durable-" if backend.mode == "durable" else ""
    receipt_path = evidence / f"{prefix}authenticated-browser.json"
    assert not receipt_path.exists(), "Use a fresh browser evidence directory."
    network: list[dict[str, Any]] = []
    external: list[str] = []
    errors: list[str] = []
    checks: list[str] = []
    proof: dict[str, Any] = {
        "transport": "Chromium real TCP HTTP -> AC cookie auth -> disposable PostgreSQL",
        "data": (
            "synthetic WAV and synthetic provider-response fixture"
            if backend.mode == "imported"
            else "synthetic WAV and synthetic durable C2/C4/C5/C6 worker output"
        ),
        "source": (
            "synthetic imported private draft"
            if backend.mode == "imported"
            else "synthetic durable C2/C4/C5/C6 worker via ReportingBroker"
        ),
        "generatedViaDurableWorker": backend.mode == "durable",
        "api_route_mocks_configured": False,
        "provider_processing_configured": False,
        "worker_kind": (
            "OfflineConversationWorker"
            if backend.mode == "imported"
            else "ConversationInferenceWorker with synthetic ReportingBroker"
        ),
        "expected_provider_calls": 0,
        "provider_network_counter_installed": False,
        "google_login_tested": False,
        "production_runtime_tested": False,
        "checks": checks,
        "network": network,
        "external_requests": external,
        "browser_errors": errors,
        "passed": False,
    }
    with sync_playwright() as playwright, ExitStack() as cleanup:
        browser = playwright.chromium.launch(headless=True)
        cleanup.callback(browser.close)
        context = browser.new_context(
            viewport={"width": 1365, "height": 1000}, service_workers="block"
        )
        cleanup.callback(context.close)

        def boundary(route: Any) -> None:
            if route.request.url.startswith(backend.origin + "/"):
                route.continue_()
            else:
                external.append(urlsplit(route.request.url).hostname or "non-http")
                route.abort()

        context.route("**/*", boundary)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)[:300]))

        def record(response: Any) -> None:
            path = urlsplit(response.url).path
            if path.startswith("/v1/"):
                network.append(
                    {"method": response.request.method, "path": path, "status": response.status}
                )

        page.on("response", record)
        try:
            page.goto(backend.origin, wait_until="networkidle")
            proof["initial_headings"] = page.get_by_role("heading").all_text_contents()
            expect(page.get_by_role("link", name="Sign in with AC")).to_be_visible()
            expect(page.locator(".recording-history-item")).to_have_count(0)
            assert not any(item["path"] == "/v1/conversation/recordings" for item in network)
            page.screenshot(path=str(evidence / f"{prefix}onboarding-desktop.png"), full_page=True)
            checks.append("Unauthenticated onboarding shows AC sign-in and no private history.")
            context.add_cookies(
                [
                    {
                        "name": backend.cookie_name,
                        "value": backend.cookie_value,
                        "url": backend.origin,
                        "httpOnly": True,
                        "sameSite": "Lax",
                    }
                ]
            )
            page.reload(wait_until="networkidle")
            expect(page.get_by_role("heading", name="Saved calls")).to_be_visible()
            page.locator(".recording-history-item").filter(has_text="Open report").click()
            expect(page.get_by_role("region", name="Sales call report")).to_be_visible()
            expect(page.get_by_text(backend.report_summary)).to_be_visible()
            expect(
                page.get_by_text("AI draft · Dipak has not reviewed this", exact=True)
            ).to_be_visible()
            page.wait_for_function("document.querySelector('audio')?.readyState >= 1")
            assert page.locator("audio").get_attribute("src") == (
                f"/v1/conversation/recordings/{backend.recording_id}/source"
            )
            assert page.locator("audio").evaluate("audio => audio.duration") == 1
            page.locator("audio").evaluate("audio => { audio.currentTime = 0.5; }")
            page.get_by_role("region", name="Sales call report").get_by_role(
                "button", name="00:00–00:00"
            ).first.click()
            assert page.locator("audio").evaluate("audio => audio.currentTime") == 0
            source = context.request.get(
                backend.origin + f"/v1/conversation/recordings/{backend.recording_id}/source",
                headers={"Range": "bytes=4-99"},
            )
            assert source.status == 206 and len(source.body()) == 96
            assert source.headers["cache-control"] == "private, no-store"
            checks.append(
                "Saved draft opens with bound transcript, authenticated WAV playback "
                "and timestamp seek."
            )
            checks.append(
                "Authenticated single-byte-range playback returns 206 and private no-store."
            )
            page.screenshot(
                path=str(evidence / f"{prefix}saved-report-desktop.png"), full_page=True
            )
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            page.screenshot(path=str(evidence / f"{prefix}saved-report-mobile.png"), full_page=True)
            checks.append("Report fits a 390px viewport without horizontal page overflow.")
            page.set_viewport_size({"width": 1365, "height": 1000})
            page.reload(wait_until="networkidle")
            page.locator(".recording-history-item").filter(has_text="Open report").click()
            expect(page.get_by_role("region", name="Sales call report")).to_be_visible()
            assert not any(item["method"] != "GET" for item in network)
            checks.append(
                "Refreshing and reopening a saved report requires no upload or provider rerun."
            )
            page.get_by_role("button", name="Analyze another call").click()
            page.get_by_label("Choose sales call audio").set_input_files(
                {
                    "name": "Synthetic browser call.wav",
                    "mimeType": "audio/wav",
                    "buffer": backend.upload_bytes,
                }
            )
            expect(page.get_by_role("button", name="Continue to analysis")).to_be_enabled()
            page.get_by_role("button", name="Continue to analysis").click()
            expect(page.get_by_role("heading", name="Ready to analyze")).to_be_visible()
            expect(page.get_by_text("₹0 · local audio measurements", exact=True)).to_be_visible()
            expect(page.get_by_role("button", name="Analyze my call")).to_be_disabled()
            page.get_by_role("checkbox").check()
            page.get_by_role("button", name="Analyze my call").click()
            expect(page.get_by_role("heading", name="Local audio analysis is ready")).to_be_visible(
                timeout=45000
            )
            expect(page.get_by_role("region", name="Sales call report")).to_have_count(0)
            checks.append(
                "New WAV follows real quote, consent, upload, queued native worker "
                "and local completion."
            )
            checks.append("A local measurements run does not fabricate a generated sales report.")
            page.screenshot(
                path=str(evidence / f"{prefix}local-analysis-completed.png"), full_page=True
            )
            report_reads = sum(item["path"].endswith("/report") for item in network)
            page.wait_for_timeout(16000)
            assert report_reads == sum(item["path"].endswith("/report") for item in network)
            checks.append(
                "Completed local runs stop polling, observed beyond the 15-second retry cap."
            )
            assert not errors
            assert not external
            assert any(item["status"] == 202 and item["method"] == "POST" for item in network)
            proof["passed"] = True
        finally:
            if not proof["passed"]:
                proof["failure_visible_text"] = page.locator("body").inner_text()[:12000]
                page.screenshot(path=str(evidence / f"{prefix}failure.png"), full_page=True)
            receipt_path.write_text(
                json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8"
            )


@pytest.mark.e2e
def test_real_browser_saved_report_playback_and_local_upload(
    live_backend: BrowserBackend, tmp_path: Path
) -> None:
    evidence = Path(os.environ.get("AC_SALES_XRAY_BROWSER_EVIDENCE_DIR", str(tmp_path)))
    _exercise_browser(live_backend, evidence)


@pytest.mark.e2e
def test_real_browser_durable_worker_report_playback(
    durable_live_backend: BrowserBackend, tmp_path: Path
) -> None:
    evidence = Path(os.environ.get("AC_SALES_XRAY_BROWSER_EVIDENCE_DIR", str(tmp_path)))
    _exercise_browser(durable_live_backend, evidence)
