"""Real Chromium proof of hosted authority admission and saved report reuse.

The server uses the disposable PostgreSQL authority fixture and a synthetic
ReportingBroker. Browser traffic reaches the actual FastAPI routes over a real
loopback TCP socket with the AC session cookie; no provider route is mocked and
no external request is permitted.
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
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from playwright.sync_api import Page, sync_playwright
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.inference_worker import ConversationInferenceWorker
from ac_platform.conversation_intelligence.intake import IntakePolicy
from ac_platform.http.auth import install_identity_http
from ac_platform.http.conversation import install_conversation_http
from ac_platform.http.conversation_intake import ConversationIntakeRuntime
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.models import Session as IdentitySession
from tests.database.test_conversation_authority_postgresql import (
    AuthorityFixture,
    _setup,
)
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_reporting_pipeline_postgresql import ReportingBroker


@pytest.fixture(scope="module")
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


@pytest.fixture(scope="module")
def authority_setup(
    postgres_harness: Any, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[AuthorityFixture]:
    setup = run(_setup(postgres_harness, tmp_path_factory.mktemp("hosted-authority")))
    try:
        yield setup
    finally:
        run(setup.engine.dispose())


def _receipt_path() -> Path:
    default = Path(
        "D:/Projects/authority-closers-release-transfer/2026-09-13-sales-xray/receipts/"
        "hosted-authority-browser-v1.json"
    )
    return Path(os.environ.get("AC_SALES_XRAY_AUTHORITY_BROWSER_RECEIPT", str(default)))


def _fetch(
    page: Page,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    *,
    key: str | None = None,
) -> dict[str, Any]:
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
        raise AssertionError(f"Malformed API response for {method} {path}")
    if result["status"] >= 400:
        raise AssertionError(f"HTTP {result['status']} for {method} {path}")
    payload = result.get("body")
    if not isinstance(payload, dict):
        raise AssertionError(f"Non-object API response for {method} {path}")
    return payload


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
        raise AssertionError(f"Malformed API response for {method} {path}")
    payload = result.get("body")
    return result["status"], payload if isinstance(payload, dict) else {}


def _wait_stage(page: Page, recording_id: str, stage: str) -> dict[str, Any]:
    deadline = time.monotonic() + 45
    path = f"/v1/conversation/recordings/{recording_id}/analysis"
    while time.monotonic() < deadline:
        progress = _fetch(page, "GET", path)
        for item in progress.get("stages", []):
            if isinstance(item, dict) and item.get("stage") == stage:
                state = item.get("state")
                if state == "completed":
                    return item
                if state in {"failed", "cancelled", "uncertain"}:
                    raise AssertionError(f"{stage} ended in {state}")
        page.wait_for_timeout(100)
    raise AssertionError(f"Timed out waiting for {stage}")


@dataclass(frozen=True)
class BrowserServer:
    origin: str
    cookie_name: str
    cookie_value: str
    worker: ConversationInferenceWorker
    broker: ReportingBroker


@contextmanager
def _start_server(setup: AuthorityFixture) -> Iterator[BrowserServer]:
    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    origin = f"http://127.0.0.1:{listener.getsockname()[1]}"
    token = secrets.token_urlsafe(32)
    pepper = "synthetic-hosted-authority-browser-pepper"
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
    stopped = threading.Event()
    control: dict[str, Any] = {}

    # The fixture's engine is intentionally not shared across event loops. The
    # harness exposes its disposable URL through the setup session bind; build
    # a fresh async engine in the server thread below.
    postgres_url = setup.engine.url.render_as_string(hide_password=False)

    async def run_server() -> None:
        engine = create_async_engine(postgres_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        worker_task: asyncio.Task[Any] | None = None
        try:
            async with sessions() as database, database.begin():
                await database.execute(
                    update(IdentitySession)
                    .where(IdentitySession.id == setup.prepared.state.session_id)
                    .values(
                        token_hash=hmac.new(
                            pepper.encode(), token.encode(), hashlib.sha256
                        ).digest()
                    )
                )
            app = FastAPI(docs_url=None, redoc_url=None)

            @app.get("/", response_class=HTMLResponse)
            async def browser_probe_home() -> str:
                return (
                    "<!doctype html><html><body><h1>Hosted authority browser proof</h1>"
                    "</body></html>"
                )

            register_problem_handlers(app)
            require_actor = install_identity_http(app, settings=settings, sessions=sessions)
            bundle = setup.bundle
            runtime = ConversationIntakeRuntime(
                policy=IntakePolicy(
                    budget_scope_id=bundle.budget_scope_id,
                    tenant_ids=frozenset(item.tenant_id for item in bundle.allowances),
                    authorization_ref=bundle.intake_authorization_ref,
                    retention_ref=bundle.intake_retention_ref,
                    retention_days=bundle.retention_days,
                ),
                storage=setup.prepared.storage,
                scratch=setup.prepared.scratch,
                authority=setup.authority,
            )
            install_conversation_http(
                app,
                settings=settings,
                require_actor=require_actor,
                intake_runtime=runtime,
            )
            worker = ConversationInferenceWorker(
                sessions,
                setup.prepared.storage,
                broker := ReportingBroker(setup.prepared.data),
                authority=setup.authority,
            )
            control["worker"] = worker
            control["broker"] = broker

            async def pump() -> None:
                try:
                    while not stopped.is_set():
                        await worker.run_once()
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

    thread = threading.Thread(target=start, name="hosted-authority-browser-api", daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 30
        while not getattr(control.get("server"), "started", False):
            if "server_error" in control:
                raise AssertionError("Hosted authority API failed to start")
            if time.monotonic() >= deadline:
                raise AssertionError("Hosted authority API did not start")
            time.sleep(0.05)
        yield BrowserServer(
            origin,
            settings.session_cookie_name,
            token,
            control["worker"],
            control["broker"],
        )
    finally:
        stopped.set()
        server = control.get("server")
        if server is not None:
            server.should_exit = True
        thread.join(timeout=20)
        listener.close()
        assert not thread.is_alive(), "Hosted authority API failed to stop"
        assert "server_error" not in control, "Hosted authority API failed"
        assert "worker_error" not in control, "Hosted authority worker failed"


@pytest.mark.e2e
def test_real_browser_hosted_authority_c2_c4_c5_and_cached_report(
    authority_setup: AuthorityFixture,
) -> None:
    receipt_path = _receipt_path()
    if receipt_path.exists():
        pytest.fail("Use a fresh hosted authority browser receipt path.")
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    proof: dict[str, Any] = {
        "transport": "Chromium real TCP HTTP -> AC cookie auth -> disposable PostgreSQL",
        "data": "synthetic one-second WAV and synthetic ReportingBroker responses",
        "api_route_mocks_configured": False,
        "provider_network_requests": 0,
        "external_requests": [],
        "network": [],
        "checks": [],
        "passed": False,
    }
    try:
        with _start_server(authority_setup) as server:
            external: list[str] = []
            network: list[dict[str, Any]] = []
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(service_workers="block")
                try:

                    def boundary(route: Any) -> None:
                        hostname = urlsplit(route.request.url).hostname or "unknown"
                        if hostname != "127.0.0.1":
                            external.append(hostname)
                            route.abort()
                        else:
                            route.continue_()

                    context.route("**/*", boundary)
                    page = context.new_page()
                    page.on(
                        "response",
                        lambda response: (
                            network.append(
                                {
                                    "method": response.request.method,
                                    "path": urlsplit(response.url).path,
                                    "status": response.status,
                                }
                            )
                            if urlsplit(response.url).path.startswith("/v1/")
                            else None
                        ),
                    )
                    page.goto(server.origin, wait_until="networkidle")
                    status, _ = _fetch_status(page, "GET", "/v1/conversation/recordings")
                    assert status == 401
                    proof["checks"].append("Unauthenticated history request is rejected.")
                    context.add_cookies(
                        [
                            {
                                "name": server.cookie_name,
                                "value": server.cookie_value,
                                "url": server.origin,
                                "httpOnly": True,
                                "sameSite": "Lax",
                            }
                        ]
                    )
                    workspace = _fetch(page, "GET", "/v1/conversation/workspace")
                    assert workspace.get("authenticated") is True
                    assert workspace.get("intake_enabled") is True
                    proof["checks"].append(
                        "Current AC cookie authenticates the selected workspace."
                    )

                    recording_id = str(authority_setup.prepared.recording_id)
                    source_sha256 = authority_setup.prepared.state.source_sha256
                    c2_quote = _fetch(
                        page,
                        "POST",
                        f"/v1/conversation/recordings/{recording_id}/analysis/quote",
                        {"stage": "C2"},
                        key="browser-authority-c2-quote",
                    )
                    assert c2_quote["provider"] == "elevenlabs"
                    assert c2_quote["model"] == "scribe_v2"
                    assert c2_quote["max_cost_paise"] == 0
                    assert c2_quote["input_sha256"] == source_sha256
                    c2_quote_id = c2_quote["id"]
                    c2_acceptance = {
                        "quote_id": c2_quote_id,
                        "selection": {"stage": "C2"},
                        "quote_fingerprint": c2_quote["quote_fingerprint"],
                        "privacy_revision": c2_quote["privacy_revision"],
                        "accepted": True,
                    }
                    c2_run = _fetch(
                        page,
                        "POST",
                        f"/v1/conversation/recordings/{recording_id}/analysis",
                        c2_acceptance,
                        key="browser-authority-c2-run",
                    )
                    c2_status = _wait_stage(page, recording_id, "C2")
                    assert c2_status["run_id"] == c2_run["id"]
                    c2_checkpoint = c2_status["checkpoint_id"]
                    proof["checks"].append(
                        "C2 quote, explicit consent, queued run and native completion passed."
                    )

                    c4_selection = {
                        "stage": "C4",
                        "transcript_checkpoint_id": c2_checkpoint,
                    }
                    c4_quote = _fetch(
                        page,
                        "POST",
                        f"/v1/conversation/recordings/{recording_id}/analysis/quote",
                        c4_selection,
                        key="browser-authority-c4-quote",
                    )
                    c4_run = _fetch(
                        page,
                        "POST",
                        f"/v1/conversation/recordings/{recording_id}/analysis",
                        {
                            "quote_id": c4_quote["id"],
                            "selection": c4_selection,
                            "quote_fingerprint": c4_quote["quote_fingerprint"],
                            "privacy_revision": c4_quote["privacy_revision"],
                            "accepted": True,
                        },
                        key="browser-authority-c4-run",
                    )
                    c4_status = _wait_stage(page, recording_id, "C4")
                    assert c4_status["run_id"] == c4_run["id"]
                    c4_checkpoint = c4_status["checkpoint_id"]
                    proof["checks"].append("C4 source-bound fact extraction completed.")

                    c5_selection = {
                        "stage": "C5",
                        "transcript_checkpoint_id": c2_checkpoint,
                        "fact_checkpoint_ids": [c4_checkpoint],
                    }
                    c5_quote = _fetch(
                        page,
                        "POST",
                        f"/v1/conversation/recordings/{recording_id}/analysis/quote",
                        c5_selection,
                        key="browser-authority-c5-quote",
                    )
                    c5_run = _fetch(
                        page,
                        "POST",
                        f"/v1/conversation/recordings/{recording_id}/analysis",
                        {
                            "quote_id": c5_quote["id"],
                            "selection": c5_selection,
                            "quote_fingerprint": c5_quote["quote_fingerprint"],
                            "privacy_revision": c5_quote["privacy_revision"],
                            "accepted": True,
                        },
                        key="browser-authority-c5-run",
                    )
                    c5_status = _wait_stage(page, recording_id, "C5")
                    assert c5_status["run_id"] == c5_run["id"]
                    report = _fetch(page, "GET", f"/v1/conversation/runs/{c5_run['id']}/report")
                    assert report["recording_id"] == recording_id
                    assert report["report"] is not None
                    assert report["report"]["review_status"] == "draft_not_dipak_adjudicated"
                    transcript = _fetch(
                        page,
                        "GET",
                        f"/v1/conversation/recordings/{recording_id}/transcript",
                    )
                    assert transcript["source_sha256"] == source_sha256
                    assert transcript["duration_ms"] == 1_000
                    assert transcript["segments"]
                    proof["checks"].append(
                        "C5 report is readable with source-bound transcript and review status."
                    )

                    calls_before_reload = server.broker.calls
                    second_report = _fetch(
                        page, "GET", f"/v1/conversation/runs/{c5_run['id']}/report"
                    )
                    assert second_report["report"] == report["report"]
                    assert server.worker.broker.calls == calls_before_reload
                    page.reload(wait_until="networkidle")
                    reloaded = _fetch(page, "GET", f"/v1/conversation/runs/{c5_run['id']}/report")
                    assert reloaded["report"] == report["report"]
                    assert server.worker.broker.calls == calls_before_reload
                    proof["checks"].append(
                        "Repeated report reads and browser reload reused the saved report "
                        "without a provider call."
                    )
                    proof["network"] = network
                    proof["external_requests"] = external
                    proof["provider_calls"] = server.broker.calls
                    assert server.broker.calls == 3
                    assert not external
                    proof["passed"] = True
                finally:
                    proof["network"] = network
                    proof["external_requests"] = external
                    context.close()
                    browser.close()
    finally:
        receipt_path.write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")
