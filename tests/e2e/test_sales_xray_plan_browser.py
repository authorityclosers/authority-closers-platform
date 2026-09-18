"""Real Chromium probe for one explicit Sales Xray processing plan.

The browser loads a tiny synthetic probe page and sends real cookie-authenticated
requests over a loopback TCP socket. PostgreSQL, the plan scheduler and durable
C2/C4/C5/C6 worker are real disposable local components. ReportingBroker returns
synthetic native and text responses; no provider network, credentials, paid
allowance, static export or hosted deployment is exercised.
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
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from playwright.sync_api import Page, expect, sync_playwright
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.application import AUDIOATLAS_HOSTED_RECIPE
from ac_platform.conversation_intelligence.contracts import RunIntent
from ac_platform.conversation_intelligence.hosted_runtime import compose_hosted_intake
from ac_platform.conversation_intelligence.inference_worker import ConversationInferenceWorker
from ac_platform.conversation_intelligence.models import (
    ConversationCheckpoint,
    ConversationInferenceTask,
    ConversationProcessingPlan,
)
from ac_platform.conversation_intelligence.processing_plan import ProcessingPlanScheduler
from ac_platform.conversation_intelligence.signals import inspect_media
from ac_platform.conversation_intelligence.worker import HostedConversationWorker
from ac_platform.http.auth import install_identity_http
from ac_platform.http.conversation import install_conversation_http
from ac_platform.http.conversation_intake import ConversationIntakeRuntime
from ac_platform.http.problem import register_problem_handlers
from ac_platform.http.request_limits import RequestBodyLimitMiddleware
from ac_platform.identity.application import AsyncIdentityApplication
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from tests.database.test_conversation_authority_postgresql import AuthorityFixture, _setup
from tests.database.test_conversation_postgresql import application as build_application
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_worker_postgresql import _add_quote


@pytest.fixture(scope="module")
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


@dataclass(frozen=True, repr=False)
class BrowserServer:
    origin: str
    database_url: str
    cookie_name: str
    cookie_value: str
    other_cookie_value: str
    recording_id: str
    source_sha256: str
    report_summary: str
    hosted_c1_rate: int
    worker: ConversationInferenceWorker
    broker: Any


async def _set_session_token(
    sessions: async_sessionmaker[Any],
    session_id: UUID,
    token: str,
    pepper: str,
) -> None:
    expected = hmac.new(pepper.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).digest()
    async with sessions() as database, database.begin():
        updated = await database.execute(
            update(IdentitySession)
            .where(IdentitySession.id == session_id)
            .values(token_hash=expected)
        )
        if updated.rowcount != 1:
            raise AssertionError("Synthetic browser session fixture did not update exactly one row")
        stored = await database.scalar(
            select(IdentitySession.token_hash).where(IdentitySession.id == session_id)
        )
        if stored != expected:
            raise AssertionError("Synthetic browser session fixture hash did not persist")


async def _verify_person(
    sessions: async_sessionmaker[Any], person_id: UUID, verified_at: Any
) -> None:
    async with sessions() as database, database.begin():
        updated = await database.execute(
            update(Person)
            .where(Person.id == person_id)
            .values(
                email=f"browser-owner-{person_id.hex}@authorityclosers.test",
                email_verified_at=verified_at,
            )
        )
        if updated.rowcount != 1:
            raise AssertionError("Synthetic browser person fixture did not update exactly one row")


def _read_plan_counts(database_url: Any, recording_id: str) -> tuple[int, int, int]:
    result: list[tuple[int, int, int]] = []
    failure: list[BaseException] = []

    def read() -> None:
        try:
            result.append(run(_plan_counts(database_url, recording_id)))
        except BaseException as error:
            failure.append(error)

    thread = threading.Thread(target=read, name="sales-xray-plan-browser-db-read")
    thread.start()
    thread.join(timeout=15)
    if thread.is_alive():
        raise AssertionError("Plan browser database read did not finish")
    if failure:
        raise failure[0]
    assert result
    return result[0]


async def _finish_hosted_c1(setup: AuthorityFixture) -> int:
    """Add a real 16 kHz hosted-profile checkpoint beside the local 48 kHz one."""

    calls: list[tuple[UUID, int]] = []

    class SyntheticNativeAdapter:
        def inspect(
            self, source: Path, outdir: Path, *, job_id: UUID, rate: Literal[16000]
        ) -> dict[str, Any]:
            if rate != 16_000:
                raise AssertionError("Hosted test adapter received a non-hosted profile.")
            calls.append((job_id, rate))
            return inspect_media(source, outdir, rate=rate)

    quote_id = await _add_quote(
        setup.sessions,
        setup.prepared.state,
        setup.prepared.recording_id,
        setup.prepared.scope_id,
        setup.prepared.state.source_sha256,
        recipe_revision=AUDIOATLAS_HOSTED_RECIPE,
    )
    async with setup.sessions() as database, database.begin():
        requested = await build_application(database, setup.prepared.state).request_run(
            setup.prepared.state.actor,
            RunIntent(
                recording_id=setup.prepared.recording_id,
                source_revision="1",
                quote_id=quote_id,
                recipe_revision=AUDIOATLAS_HOSTED_RECIPE,
            ),
            key="plan-browser-hosted-c1",
        )
    hosted = HostedConversationWorker(
        setup.sessions,
        storage=setup.prepared.storage,
        scratch=setup.prepared.scratch,
        environment="staging",
        native_runtime=SyntheticNativeAdapter(),
    )
    if not await hosted.run_once():
        raise AssertionError("Synthetic hosted C1 fixture did not complete.")
    if len(calls) != 1 or calls[0][1] != 16_000:
        raise AssertionError("Synthetic hosted adapter did not receive exactly one 16 kHz run.")

    async with setup.sessions() as database:
        checkpoints = (
            await database.scalars(
                select(ConversationCheckpoint).where(
                    ConversationCheckpoint.recording_id == setup.prepared.recording_id,
                    ConversationCheckpoint.stage == "C1",
                    ConversationCheckpoint.erased_at.is_(None),
                )
            )
        ).all()
    rates = {
        payload.get("timebase", {}).get("rate")
        for checkpoint in checkpoints
        if isinstance(payload := checkpoint.payload, dict)
    }
    if rates != {16_000, 48_000}:
        raise AssertionError("Hosted C1 fixture did not preserve both exact profiles.")
    if requested.get("recipe_revision") != AUDIOATLAS_HOSTED_RECIPE:
        raise AssertionError("Hosted C1 fixture run was not issued with the hosted recipe.")
    return calls[0][1]


def _compose_runtime(setup: AuthorityFixture, settings: Settings) -> ConversationIntakeRuntime:
    """Compose the actual hosted policy from a synthetic pinned approval file."""

    raw = setup.bundle.to_json()
    approval_path = setup.prepared.scratch.root.parent / "hosted-plan-browser-approval.json"
    approval_path.write_bytes(raw)
    configured = settings.model_copy(
        update={
            "sales_xray_enabled": True,
            "sales_xray_approval_path": str(approval_path),
            "sales_xray_approval_sha256": hashlib.sha256(raw).hexdigest(),
            "sales_xray_storage_root": str(setup.prepared.storage.root),
            "sales_xray_scratch_root": str(setup.prepared.scratch.root),
        }
    )
    runtime = compose_hosted_intake(configured)
    if runtime is None or runtime.authority is None:
        raise AssertionError("Synthetic hosted intake composition did not produce a runtime.")
    if runtime.policy.acoustic_recipe != AUDIOATLAS_HOSTED_RECIPE:
        raise AssertionError("Synthetic hosted intake composed the wrong acoustic recipe.")
    return runtime


async def _plan_counts(database_url: Any, recording_id: str) -> tuple[int, int, int]:
    engine = create_async_engine(database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as database:
            task_count = await database.scalar(
                select(func.count())
                .select_from(ConversationInferenceTask)
                .where(
                    ConversationInferenceTask.recording_id == recording_id,
                    ConversationInferenceTask.stage.in_(("C2", "C4", "C5")),
                )
            )
            plan_count = await database.scalar(
                select(func.count())
                .select_from(ConversationProcessingPlan)
                .where(ConversationProcessingPlan.recording_id == recording_id)
            )
            pending_count = await database.scalar(
                select(func.count())
                .select_from(ConversationInferenceTask)
                .where(
                    ConversationInferenceTask.recording_id == recording_id,
                    ConversationInferenceTask.state.in_(("queued", "running")),
                )
            )
            return int(task_count or 0), int(plan_count or 0), int(pending_count or 0)
    finally:
        await engine.dispose()


def _fetch_status(
    page: Page,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    *,
    key: str | None = None,
) -> tuple[int, dict[str, Any]]:
    result = page.evaluate(
        """
        async ({method, path, body, key}) => {
          const headers = {};
          if (body !== null) headers['content-type'] = 'application/json';
          if (key !== null) headers['Idempotency-Key'] = key;
          const response = await fetch(path, {
            method,
            headers,
            body: body === null ? undefined : JSON.stringify(body),
            credentials: 'same-origin',
          });
          let parsed = {};
          try { parsed = await response.json(); } catch (_) {}
          return {status: response.status, body: parsed};
        }
        """,
        {"method": method, "path": path, "body": body, "key": key},
    )
    if not isinstance(result, dict) or not isinstance(result.get("status"), int):
        raise AssertionError(f"Malformed probe response for {method} {path}")
    body_value = result.get("body")
    return result["status"], body_value if isinstance(body_value, dict) else {}


def _fetch(
    page: Page,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    *,
    key: str | None = None,
) -> dict[str, Any]:
    status, payload = _fetch_status(page, method, path, body, key=key)
    if status >= 400:
        raise AssertionError(f"HTTP {status} for {method} {path}")
    if not payload:
        raise AssertionError(f"Non-object probe response for {method} {path}")
    return payload


def _wait_plan(page: Page, recording_id: str) -> dict[str, Any]:
    path = f"/v1/conversation/recordings/{recording_id}/plan"
    deadline = time.monotonic() + 90
    stages: set[str] = set()
    while time.monotonic() < deadline:
        view = _fetch(page, "GET", path)
        current = view.get("current_stage")
        if isinstance(current, str):
            stages.add(current)
        if view.get("state") == "completed" and view.get("report_ready"):
            view["observed_stages"] = sorted(stages)
            return view
        if view.get("state") in {"held", "cancelled"}:
            raise AssertionError(f"Plan ended in {view.get('state')}")
        page.wait_for_timeout(200)
    raise AssertionError("Timed out waiting for the durable processing plan")


def _start_server(
    setup: AuthorityFixture, other_actor: Any, hosted_c1_rate: int
) -> Iterator[BrowserServer]:
    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    origin = f"http://127.0.0.1:{listener.getsockname()[1]}"
    token = secrets.token_urlsafe(32)
    other_token = secrets.token_urlsafe(32)
    pepper = "synthetic-plan-browser-session-pepper"
    settings = Settings(
        _env_file=None,
        environment="test",
        operations_tenant_id=setup.prepared.state.tenant_id,
        public_app_url=origin,
        admin_app_url="http://admin.test",
        coach_app_url="http://coach.test",
        api_url=origin,
        session_token_pepper=pepper,
        oauth_transaction_secret=secrets.token_urlsafe(32),
        email_challenge_secret=secrets.token_urlsafe(32),
    )
    stopped = threading.Event()
    control: dict[str, Any] = {}
    postgres_url = setup.engine.url.render_as_string(hide_password=False)

    async def run_server() -> None:
        engine = create_async_engine(postgres_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        worker_task: asyncio.Task[Any] | None = None
        try:
            await _set_session_token(sessions, setup.prepared.state.session_id, token, pepper)
            await _set_session_token(sessions, other_actor.session_id, other_token, pepper)
            await _verify_person(sessions, other_actor.person_id, other_actor.now)
            async with sessions() as database, database.begin():
                await AsyncIdentityApplication(database, token_pepper=pepper).resolve_actor(
                    other_token
                )
            app = FastAPI(docs_url=None, redoc_url=None)

            @app.get("/", response_class=HTMLResponse)
            async def browser_probe_home() -> str:
                return (
                    "<!doctype html><html><body><main>"
                    "<h1>Sales Xray processing plan browser probe</h1>"
                    "<p>API behavior is exercised with real browser fetch requests.</p>"
                    "</main></body></html>"
                )

            register_problem_handlers(app)
            require_actor = install_identity_http(app, settings=settings, sessions=sessions)
            runtime = _compose_runtime(setup, settings)
            install_conversation_http(
                app,
                settings=settings,
                require_actor=require_actor,
                intake_runtime=runtime,
            )
            app.add_middleware(
                RequestBodyLimitMiddleware,
                conversation_upload_max_bytes=setup.prepared.storage.max_bytes,
            )
            broker = setup.broker
            worker = ConversationInferenceWorker(
                sessions,
                runtime.storage,
                broker,
                authority=runtime.authority,
            )
            scheduler = ProcessingPlanScheduler(sessions, runtime.authority)
            control["worker"] = worker
            control["broker"] = broker

            async def pump() -> None:
                try:
                    while not stopped.is_set():
                        await worker.run_once()
                        await scheduler.step()
                        await asyncio.sleep(0.05)
                except BaseException as error:
                    control["worker_error"] = type(error).__name__
                    stopped.set()

            worker_task = asyncio.create_task(pump())
            server = uvicorn.Server(
                uvicorn.Config(app, host="127.0.0.1", log_level="error", access_log=False)
            )
            control["server"] = server
            await server.serve(sockets=[listener])
        except BaseException as error:
            control["server_error"] = type(error).__name__
            stopped.set()
        finally:
            stopped.set()
            if worker_task is not None:
                await worker_task
            await engine.dispose()

    def start() -> None:
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            runner.run(run_server())

    thread = threading.Thread(target=start, name="sales-xray-plan-browser-api", daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 30
        while not getattr(control.get("server"), "started", False):
            if "server_error" in control:
                raise AssertionError("Synthetic plan browser API failed to start")
            if time.monotonic() >= deadline:
                raise AssertionError("Synthetic plan browser API did not start")
            time.sleep(0.05)
        yield BrowserServer(
            origin=origin,
            database_url=setup.engine.url,
            cookie_name=settings.session_cookie_name,
            cookie_value=token,
            other_cookie_value=other_token,
            recording_id=str(setup.prepared.recording_id),
            source_sha256=setup.prepared.state.source_sha256,
            report_summary="A synthetic draft from saved facts.",
            hosted_c1_rate=hosted_c1_rate,
            worker=control["worker"],
            broker=control["broker"],
        )
    finally:
        stopped.set()
        server = control.get("server")
        if server is not None:
            server.should_exit = True
        thread.join(timeout=20)
        listener.close()
        assert not thread.is_alive(), "Synthetic plan browser API failed to stop"
        assert "server_error" not in control, "Synthetic plan browser API failed"
        assert "worker_error" not in control, "Synthetic plan browser worker failed"


@pytest.fixture(scope="module")
def browser_server(
    postgres_harness: Any,
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[BrowserServer]:
    setup = run(_setup(postgres_harness, tmp_path_factory.mktemp("plan-browser")))
    hosted_c1_rate = run(_finish_hosted_c1(setup))
    other_actor = run(seed(setup.engine, tenant_id=setup.prepared.state.tenant_id))
    try:
        yield from _start_server(setup, other_actor, hosted_c1_rate)
    finally:
        run(setup.engine.dispose())


@pytest.mark.e2e
def test_browser_explicit_plan_drives_durable_report_without_duplicate_provider_calls(
    browser_server: BrowserServer, tmp_path: Path
) -> None:
    evidence = Path(
        os.environ.get("AC_SALES_XRAY_PLAN_BROWSER_EVIDENCE_DIR", str(tmp_path))
    ).resolve()
    workspace_root = Path(__file__).resolve().parents[2]
    if workspace_root == evidence or workspace_root in evidence.parents:
        pytest.fail("Browser evidence must be outside the user Git workspace.")
    evidence.mkdir(parents=True, exist_ok=True)
    receipt_path = evidence / "plan-browser-probe.json"
    assert not receipt_path.exists(), "Use a fresh browser probe receipt path."

    backend = browser_server
    browser_requests: list[dict[str, Any]] = []
    network: list[dict[str, Any]] = []
    external: list[str] = []
    errors: list[str] = []
    checks: list[str] = []
    proof: dict[str, Any] = {
        "transport": "Chromium real TCP HTTP -> AC cookie auth -> disposable PostgreSQL",
        "surface": "synthetic HTML probe; this receipt is not a CallStudio UI claim",
        "data": (
            "synthetic one-second WAV, synthetic hosted native adapter at 16 kHz, "
            "and synthetic ReportingBroker responses"
        ),
        "source": (
            "real cookie-authenticated plan routes, compose_hosted_intake, and durable "
            "C2/C4/C5/C6 worker"
        ),
        "generatedViaDurableWorker": True,
        "api_route_mocks_configured": False,
        "provider_processing_configured": False,
        "worker_kind": (
            "HostedConversationWorker with synthetic native adapter + "
            "ConversationInferenceWorker + ProcessingPlanScheduler"
        ),
        "hosted_c1_recipe": AUDIOATLAS_HOSTED_RECIPE,
        "hosted_c1_native_adapter_rate": backend.hosted_c1_rate,
        "local_48k_fixture_preserved": True,
        "expected_provider_calls": 3,
        "provider_network_counter_installed": False,
        "google_login_tested": False,
        "production_runtime_tested": False,
        "checks": checks,
        "network": network,
        "browser_errors": errors,
        "external_requests": external,
        "passed": False,
    }

    with sync_playwright() as playwright, ExitStack() as cleanup:
        browser = playwright.chromium.launch(headless=True)
        cleanup.callback(browser.close)
        context = browser.new_context(service_workers="block")
        cleanup.callback(context.close)

        def boundary(route: Any) -> None:
            hostname = urlsplit(route.request.url).hostname or "unknown"
            if hostname == "127.0.0.1":
                route.continue_()
            else:
                external.append(hostname)
                route.abort()

        context.route("**/*", boundary)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)[:300]))

        def record_response(response: Any) -> None:
            path = urlsplit(response.url).path
            if path.startswith("/v1/"):
                network.append(
                    {"method": response.request.method, "path": path, "status": response.status}
                )

        def record_request(request: Any) -> None:
            path = urlsplit(request.url).path
            if path.startswith("/v1/"):
                browser_requests.append(
                    {
                        "method": request.method,
                        "path": path,
                        "post_data": request.post_data,
                    }
                )

        page.on("response", record_response)
        page.on("request", record_request)
        try:
            assert backend.hosted_c1_rate == 16_000
            page.goto(backend.origin, wait_until="networkidle")
            expect(
                page.get_by_role("heading", name="Sales Xray processing plan browser probe")
            ).to_be_visible()

            unauth = playwright.request.new_context(base_url=backend.origin)
            cleanup.callback(unauth.dispose)
            unauth_response = unauth.get(f"/v1/conversation/recordings/{backend.recording_id}/plan")
            assert unauth_response.status in {401, 403}
            checks.append("Unauthenticated plan progress is denied without private history.")

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
            owner_plan_before_quote = context.request.get(
                backend.origin + f"/v1/conversation/recordings/{backend.recording_id}/plan"
            )
            assert owner_plan_before_quote.status == 404
            checks.append("The current AC owner can address the plan without widening scope.")

            other_context = browser.new_context(service_workers="block")
            cleanup.callback(other_context.close)
            other_context.route("**/*", boundary)
            other_context.add_cookies(
                [
                    {
                        "name": backend.cookie_name,
                        "value": backend.other_cookie_value,
                        "url": backend.origin,
                        "httpOnly": True,
                        "sameSite": "Lax",
                    }
                ]
            )
            assert any(
                cookie["name"] == backend.cookie_name
                and cookie["value"] == backend.other_cookie_value
                for cookie in other_context.cookies()
            )
            other_history_response = other_context.request.get(
                backend.origin + "/v1/conversation/recordings"
            )
            assert other_history_response.status == 200
            other_plan_response = other_context.request.get(
                backend.origin + f"/v1/conversation/recordings/{backend.recording_id}/plan"
            )
            assert other_plan_response.status in {403, 404}
            checks.append(
                "A separately authenticated same-tenant owner can list its own empty history "
                "but cannot address this recording's plan."
            )

            forbidden_origin = context.request.post(
                backend.origin + f"/v1/conversation/recordings/{backend.recording_id}/plan/quote",
                headers={
                    "Origin": "http://evil.test",
                    "Idempotency-Key": "synthetic-forbidden-origin",
                },
            )
            assert forbidden_origin.status in {400, 403}
            checks.append("Cookie-authenticated plan writes reject a foreign Origin.")

            recording_id = backend.recording_id
            quote_path = f"/v1/conversation/recordings/{recording_id}/plan/quote"
            quote_status, quote = _fetch_status(
                page, "POST", quote_path, None, key="browser-plan-quote"
            )
            assert quote_status == 201
            assert quote["recording_id"] == recording_id
            assert quote["max_cost_paise"] == 0
            assert quote["cost_label"] == "₹0 · approved allowance"
            assert [stage["stage"] for stage in quote["stages"]] == ["C2", "C4", "C5"]
            quote_requests = [
                item
                for item in browser_requests
                if item["path"].endswith("/plan/quote") and item["method"] == "POST"
            ]
            assert len(quote_requests) == 1
            assert quote_requests[0]["post_data"] in {None, ""}
            assert _read_plan_counts(backend.database_url, recording_id) == (0, 1, 0)
            checks.append(
                "Bodyless plan quote is side-effect free for stage jobs and provider calls."
            )

            accepted = _fetch(
                page,
                "POST",
                f"/v1/conversation/recordings/{recording_id}/plan",
                {
                    "plan_id": quote["id"],
                    "plan_fingerprint": quote["plan_fingerprint"],
                    "privacy_revision": quote["privacy_revision"],
                    "accepted": True,
                },
                key="browser-plan-accept",
            )
            assert accepted["accepted"] is True
            assert accepted["state"] == "active"
            assert accepted["current_stage"] == "C2"
            accept_requests = [
                item
                for item in browser_requests
                if item["path"].endswith(f"/recordings/{recording_id}/plan")
                and item["method"] == "POST"
            ]
            assert len(accept_requests) == 1
            accepted_payload = json.loads(accept_requests[0]["post_data"] or "{}")
            assert accepted_payload == {
                "plan_id": quote["id"],
                "plan_fingerprint": quote["plan_fingerprint"],
                "privacy_revision": "sales-xray-processing-plan-v1",
                "accepted": True,
            }
            assert not any(item["path"].endswith("/analysis") for item in browser_requests)
            assert not any(
                item["path"].endswith("/runs") and item["method"] == "POST"
                for item in browser_requests
            )
            checks.append(
                "One explicit acceptance starts automatic progression without stage commands."
            )

            completed = _wait_plan(page, recording_id)
            assert completed["report_run_id"]
            assert set(completed["observed_stages"]) >= {"C2", "C4", "C5"}
            report = _fetch(
                page,
                "GET",
                f"/v1/conversation/runs/{completed['report_run_id']}/report",
            )
            assert report["recording_id"] == recording_id
            assert report["report"]["summary"] == backend.report_summary
            transcript = _fetch(
                page,
                "GET",
                f"/v1/conversation/recordings/{recording_id}/transcript",
            )
            assert transcript["source_sha256"] == backend.source_sha256
            assert transcript["duration_ms"] == 1_000
            assert backend.broker.calls == 3
            assert backend.broker.routes == ["elevenlabs", "groq", "groq"]
            checks.append(
                "Scheduler and durable worker saved a synthetic C6 report and bound transcript."
            )

            source = context.request.get(
                backend.origin + f"/v1/conversation/recordings/{recording_id}/source",
                headers={"Range": "bytes=4-99"},
            )
            assert source.status == 206 and len(source.body()) == 96
            assert source.headers["cache-control"] == "private, no-store"
            checks.append(
                "Authenticated source playback retains the private single-range contract."
            )

            before_reload = len(browser_requests)
            page.reload(wait_until="networkidle")
            reloaded_plan = _fetch(page, "GET", f"/v1/conversation/recordings/{recording_id}/plan")
            reloaded_report = _fetch(
                page,
                "GET",
                f"/v1/conversation/runs/{reloaded_plan['report_run_id']}/report",
            )
            reloaded_transcript = _fetch(
                page,
                "GET",
                f"/v1/conversation/recordings/{recording_id}/transcript",
            )
            assert reloaded_report["report"] == report["report"]
            assert reloaded_transcript == transcript
            assert backend.broker.calls == 3
            assert not any(item["method"] == "POST" for item in browser_requests[before_reload:])
            checks.append(
                "Reloaded GET plan/report/transcript reads reuse the saved result with "
                "zero duplicate calls."
            )

            assert not errors
            assert not external
            proof["network"] = network
            proof["passed"] = True
        finally:
            if not proof["passed"]:
                proof["failure_visible_text"] = page.locator("body").inner_text()[:12000]
            proof["network"] = network
            proof["external_requests"] = external
            receipt_path.write_text(
                json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8"
            )
