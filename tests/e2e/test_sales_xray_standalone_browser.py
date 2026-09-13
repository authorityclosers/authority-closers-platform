"""Real standalone Sales Xray browser proof for host-only password sessions.

The browser reaches the static export and the real identity/conversation routes over
one loopback TCP origin. The account, memberships, report and password are synthetic
and live in one disposable PostgreSQL schema. No API route or provider request is
mocked, and the proof never contacts Google or an external host.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import pytest
import uvicorn
from fastapi import FastAPI
from playwright.sync_api import expect, sync_playwright
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.staticfiles import StaticFiles

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.application import ConversationApplication
from ac_platform.conversation_intelligence.report_store import ConversationReports
from ac_platform.http.auth import install_identity_http
from ac_platform.http.conversation import install_conversation_http
from ac_platform.http.conversation_intake import ConversationIntakeRuntime
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.models import PasswordCredential, Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.identity.password_auth import hash_password
from ac_platform.tenancy.models import Membership, Tenant
from tests.database.test_conversation_intake_postgresql import policy
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_reports_postgresql import _build_fixture

ROOT = Path(__file__).resolve().parents[2]
SALES_XRAY_BROWSER_ORIGIN_ENV = "AC_SALES_XRAY_STANDALONE_BROWSER_EVIDENCE_DIR"


@dataclass(frozen=True, slots=True)
class BrowserAccount:
    email: str
    password: str
    own_tenant_id: UUID
    second_tenant_id: UUID
    foreign_tenant_id: UUID
    own_workspace_name: str
    recording_id: UUID


@dataclass(frozen=True, slots=True)
class StandaloneBackend:
    origin: str
    account: BrowserAccount
    session_cookie_name: str


@pytest.fixture
def postgres_harness() -> Any:
    """Use the existing loopback-only, schema-isolated PostgreSQL harness."""

    yield from _postgres_harness.__wrapped__()  # type: ignore[attr-defined]


async def _prepare_account(postgres_harness: Any, fixture: Any) -> BrowserAccount:
    """Import one private draft, then attach a verified synthetic password account."""

    person_id = fixture.prepared.state.person_id
    own_tenant_id = fixture.prepared.state.tenant_id
    second_tenant_id = uuid4()
    foreign_tenant_id = uuid4()
    email = f"sales-xray-browser-{uuid4().hex}@example.test"
    password = "Synthetic-browser-" + uuid4().hex + "!"
    own_workspace_name = "Disposable Sales Xray tenant"
    engine = create_async_engine(postgres_harness.url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as database, database.begin():
            # The report fixture is imported through its production report-store
            # boundary while it still has the reviewed control-account actor.
            await ConversationReports(ConversationApplication(database)).import_internal_draft(
                fixture.actor,
                fixture.prepared.run_id,
                fixture.intent,
                storage=fixture.prepared.storage,
                key="standalone-browser-private-draft",
            )
            person = await database.get(Person, person_id)
            assert person is not None
            person.email = email
            person.first_name = "Synthetic browser"
            person.display_name = "Synthetic browser account"
            person.email_verified_at = fixture.prepared.state.now
            membership = await database.scalar(
                select(Membership).where(
                    Membership.tenant_id == own_tenant_id,
                    Membership.person_id == person_id,
                )
            )
            assert membership is not None
            membership.role = "learner"
            existing_session = await database.get(
                IdentitySession, fixture.prepared.state.session_id
            )
            assert existing_session is not None
            existing_session.selected_tenant_id = None
            database.add(
                Tenant(
                    id=second_tenant_id,
                    slug=second_tenant_id.hex,
                    name="Synthetic second Sales Xray workspace",
                )
            )
            await database.flush()
            database.add(
                Membership(
                    tenant_id=second_tenant_id,
                    person_id=person_id,
                    role="learner",
                )
            )
            database.add(
                Tenant(
                    id=foreign_tenant_id,
                    slug=foreign_tenant_id.hex,
                    name="Synthetic foreign tenant",
                )
            )
            database.add(
                PasswordCredential(
                    person_id=person_id,
                    password_hash=hash_password(password),
                )
            )
    finally:
        await engine.dispose()
    return BrowserAccount(
        email=email,
        password=password,
        own_tenant_id=own_tenant_id,
        second_tenant_id=second_tenant_id,
        foreign_tenant_id=foreign_tenant_id,
        own_workspace_name=own_workspace_name,
        recording_id=fixture.prepared.recording_id,
    )


def _make_backend(
    postgres_harness: Any,
    tmp_path_factory: pytest.TempPathFactory,
    request: pytest.FixtureRequest,
) -> Iterator[StandaloneBackend]:
    exported = ROOT / "apps/sales-xray-web/out"
    if not (exported / "index.html").is_file() or not (exported / "login/index.html").is_file():
        pytest.fail("Build the Sales Xray static export with its login route before this proof.")

    fixture = run(_build_fixture(postgres_harness, tmp_path_factory.mktemp("standalone-browser")))
    account = run(_prepare_account(postgres_harness, fixture))
    intake_runtime = ConversationIntakeRuntime(
        policy(fixture.prepared.scope_id, fixture.prepared.state.tenant_id),
        fixture.prepared.storage,
        fixture.prepared.scratch,
    )
    listener = socket.socket()
    request.addfinalizer(listener.close)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    origin = f"http://127.0.0.1:{listener.getsockname()[1]}"
    settings = Settings(
        _env_file=None,
        environment="test",
        public_app_url="http://learner.test",
        admin_app_url="http://admin.test",
        coach_app_url="http://coach.test",
        api_url="http://api.test",
        sales_xray_app_url=origin,
        session_token_pepper=uuid4().hex + uuid4().hex,
        oauth_transaction_secret=uuid4().hex + uuid4().hex,
        email_challenge_secret=uuid4().hex + uuid4().hex,
    )
    control: dict[str, Any] = {}
    stopped = threading.Event()

    async def serve() -> None:
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            application = FastAPI(docs_url=None, redoc_url=None)
            register_problem_handlers(application)
            require_actor = install_identity_http(application, settings=settings, sessions=sessions)
            install_conversation_http(
                application,
                settings=settings,
                require_actor=require_actor,
                intake_runtime=intake_runtime,
            )
            application.mount("/", StaticFiles(directory=exported, html=True))
            server = uvicorn.Server(
                uvicorn.Config(
                    application,
                    host="127.0.0.1",
                    log_level="error",
                    access_log=False,
                )
            )
            control["server"] = server
            await server.serve(sockets=[listener])
        except BaseException as error:
            # Do not expose database URLs, password material or provider payloads.
            control["error_type"] = type(error).__name__
        finally:
            stopped.set()
            await engine.dispose()

    def start() -> None:
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            runner.run(serve())

    thread = threading.Thread(target=start, name="sales-xray-standalone-browser-api", daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 30
        while not getattr(control.get("server"), "started", False):
            assert "error_type" not in control, control.get("error_type")
            assert time.monotonic() < deadline, "Standalone Sales Xray API did not start."
            time.sleep(0.05)
        yield StandaloneBackend(origin, account, settings.session_cookie_name)
    finally:
        stopped.set()
        server = control.get("server")
        if server is not None:
            server.should_exit = True
        thread.join(timeout=20)
        listener.close()
        assert not thread.is_alive(), "Standalone Sales Xray API failed to stop."
        assert "error_type" not in control, control.get("error_type")


@pytest.fixture
def standalone_backend(
    postgres_harness: Any,
    tmp_path_factory: pytest.TempPathFactory,
    request: pytest.FixtureRequest,
) -> Iterator[StandaloneBackend]:
    yield from _make_backend(postgres_harness, tmp_path_factory, request)


def _evidence_dir(tmp_path: Path) -> Path:
    evidence = Path(os.environ.get(SALES_XRAY_BROWSER_ORIGIN_ENV, str(tmp_path))).resolve()
    if evidence == ROOT or ROOT in evidence.parents:
        pytest.fail("Browser evidence must be outside the user Git workspace.")
    evidence.mkdir(parents=True, exist_ok=True)
    return evidence


def _metric_value(page: Any, label: str, unit: str) -> float:
    metric = page.get_by_text(label, exact=True).locator("..")
    value = metric.locator("strong").inner_text()
    match = re.fullmatch(rf"(-?\d+(?:\.\d+)?)\s+{re.escape(unit)}", value.strip())
    assert match is not None, f"Unexpected {label} value: {value!r}"
    return float(match.group(1))


def _exercise_browser(backend: StandaloneBackend, evidence: Path) -> None:
    receipt_path = evidence / "standalone-auth-browser.json"
    assert not receipt_path.exists(), "Use a fresh standalone browser evidence directory."
    network: list[dict[str, Any]] = []
    external: list[str] = []
    browser_errors: list[str] = []
    request_failures: list[str] = []
    checks: list[str] = []
    proof: dict[str, Any] = {
        "transport": "Chromium real TCP HTTP -> AC password cookie -> disposable PostgreSQL",
        "static_export": "apps/sales-xray-web/out",
        "api_route_mocks_configured": False,
        "provider_requests_configured": False,
        "google_login_tested": False,
        "credentials": "synthetic verified account; password excluded from evidence",
        "checks": checks,
        "network": network,
        "external_requests": external,
        "browser_errors": browser_errors,
        "request_failures": request_failures,
        "passed": False,
    }
    with sync_playwright() as playwright, ExitStack() as cleanup:
        browser = playwright.chromium.launch(headless=True)
        cleanup.callback(browser.close)
        context = browser.new_context(
            viewport={"width": 1365, "height": 1000},
            service_workers="block",
        )
        cleanup.callback(context.close)

        def boundary(route: Any) -> None:
            request_url = route.request.url
            if request_url.startswith(backend.origin + "/"):
                route.continue_()
                return
            external.append(urlsplit(request_url).hostname or "non-http")
            route.abort()

        context.route("**/*", boundary)
        page = context.new_page()
        page.on("pageerror", lambda error: browser_errors.append(str(error)[:300]))
        page.on(
            "requestfailed",
            lambda failed: request_failures.append(
                f"{failed.method} {urlsplit(failed.url).path}: {failed.failure}"
            ),
        )

        def record(response: Any) -> None:
            path = urlsplit(response.url).path
            if path.startswith("/v1/"):
                network.append(
                    {
                        "method": response.request.method,
                        "path": path,
                        "status": response.status,
                        "cache_control": (response.header_value("cache-control") or "")[:128],
                        "content_type": (response.header_value("content-type") or "")[:128],
                    }
                )

        page.on("response", record)
        try:
            page.goto(backend.origin, wait_until="networkidle")
            expect(page.get_by_role("link", name="Sign in with AC")).to_be_visible()
            expect(page.locator(".recording-history-item")).to_have_count(0)
            assert not any(item["path"] == "/v1/conversation/recordings" for item in network)
            page.screenshot(path=str(evidence / "anonymous-home.png"), full_page=True)
            checks.append("Anonymous home shows AC sign-in and no private history request.")

            page.get_by_role("link", name="Sign in with AC").click()
            expect(page).to_have_url(re.compile(re.escape(f"{backend.origin}/login") + r"/?$"))
            expect(page.get_by_role("heading", name="Welcome back.")).to_be_visible()
            page.screenshot(path=str(evidence / "login.png"), full_page=True)
            page.get_by_label("Email address").fill(backend.account.email)
            page.get_by_label("Password").fill(backend.account.password)
            page.get_by_role("button", name="Sign in").click()
            expect(page).to_have_url(f"{backend.origin}/")
            page.wait_for_load_state("networkidle")
            checks.append("Correct password login navigates the standalone host to /.")

            expect(
                page.get_by_role("heading", name="Choose your Sales Xray workspace.")
            ).to_be_visible()
            workspace_buttons = page.locator("button[data-tenant-id]")
            expect(workspace_buttons).to_have_count(2)
            own_button = page.get_by_role(
                "button", name=backend.account.own_workspace_name, exact=True
            )
            expect(own_button).to_be_visible()
            page.screenshot(path=str(evidence / "workspace-chooser.png"), full_page=True)
            checks.append("Workspace choices came from GET /v1/me/workspaces.")

            own_button.click()
            expect(page.get_by_text("Start with your sales call", exact=True)).to_be_visible()
            expect(page.get_by_role("heading", name="Saved calls")).to_be_visible()
            expect(page.locator(".recording-history-item")).to_have_count(1)
            checks.append("Selecting the assigned workspace opens CallStudio and private history.")

            saved_call = page.locator(".recording-history-item").first
            expect(saved_call.get_by_text("Open report", exact=True)).to_be_visible()
            saved_call.click()
            expect(
                page.get_by_role("heading", name="What to take into your next call.")
            ).to_be_visible()
            checks.append("Opening the saved call loads its source-bound report.")

            audio = page.locator("audio").first
            expect(audio).to_be_visible()
            page.wait_for_function("document.querySelector('audio')?.readyState >= 1")
            assert audio.get_attribute("src") == (
                f"/v1/conversation/recordings/{backend.account.recording_id}/source"
            )
            duration = audio.evaluate("audio => audio.duration")
            assert duration == pytest.approx(1, abs=0.02)
            source_events = [
                item
                for item in network
                if item["method"] == "GET" and item["path"].endswith("/source")
            ]
            assert source_events
            assert any(
                item["status"] in (200, 206)
                and item["content_type"].startswith("audio/wav")
                and item["cache_control"] == "private, no-store"
                for item in source_events
            )
            playback = audio.evaluate(
                """
                async audio => {
                  await audio.play();
                  return {paused: audio.paused, readyState: audio.readyState};
                }
                """
            )
            assert playback["paused"] is False
            page.wait_for_function("document.querySelector('audio')?.currentTime > 0.05")
            audio.evaluate("audio => { audio.pause(); audio.currentTime = 0.5; }")
            page.wait_for_function(
                "Math.abs((document.querySelector('audio')?.currentTime ?? 0) - 0.5) < 0.05"
            )
            assert audio.evaluate("audio => audio.currentTime") == pytest.approx(0.5, abs=0.05)
            checks.append(
                "The saved report plays synthetic source audio over authenticated HTTP "
                "and seeks it."
            )

            page.get_by_role("tab", name="Sound", exact=True).click()
            measurement_summary = (
                page.locator("details").filter(has_text="Sound of the recording").locator("summary")
            )
            expect(measurement_summary).to_be_visible()
            measurement_url = re.compile(
                re.escape(
                    f"{backend.origin}/v1/conversation/recordings/"
                    f"{backend.account.recording_id}/measurements"
                )
            )
            with page.expect_response(measurement_url) as measurement_info:
                measurement_summary.click()
            measurement_response = measurement_info.value
            assert measurement_response.status == 200
            assert measurement_response.header_value("cache-control") == "private, no-store"
            measurements = measurement_response.json()
            assert measurements["availability"] == "available"
            assert measurements["checkpoint"]["stage"] == "C1"
            assert measurements["source"]["recording_id"] == str(backend.account.recording_id)
            channel = measurements["audioatlas"]["channels"][0]
            assert channel["level"]["status"] == "available"
            assert channel["pitch"]["status"] == "available"
            level = float(channel["level"]["value"])
            pitch = float(channel["pitch"]["value"])
            assert abs(_metric_value(page, "Typical recorded level", "dBFS") - level) < 0.051
            assert abs(_metric_value(page, "Typical pitch estimate", "Hz") - pitch) < 0.051
            checks.append(
                "The report displays saved C1 level and pitch from the private API response."
            )

            pitch_button = page.get_by_role("button", name="Pitch estimate", exact=True)
            pitch_button.click()
            expect(pitch_button).to_have_attribute("aria-pressed", "true")
            expect(
                page.get_by_role(
                    "img", name=re.compile("Pitch estimate over the decoded recording")
                )
            ).to_be_visible()
            checks.append(
                "The saved measurement chart switches from sound level to pitch estimate."
            )

            page.get_by_role("tab", name="Sales factors", exact=True).click()
            factors = page.get_by_role("region", name="Sales factors")
            expect(factors.get_by_role("heading", name="Explore the sales factors")).to_be_visible()
            factor_details = factors.locator("details")
            expect(factor_details).to_have_count(8)
            factor_details.first.locator("summary").click()
            expect(factor_details.first.locator("p")).to_be_visible()
            checks.append(
                "The report exposes all eight saved sales factors with bounded observations."
            )

            page.get_by_role("tab", name="Transcript", exact=True).click()
            transcript = page.locator("details").filter(has_text="Read full transcript")
            expect(transcript.locator("summary")).to_be_visible()
            transcript.locator("summary").click()
            expect(transcript.get_by_role("search")).to_be_visible()
            expect(transcript.locator("button[data-segment-id]")).to_have_count(1)
            expect(transcript.get_by_text("Hello buyer", exact=True)).to_be_visible()
            checks.append("The report exposes the one source-bound synthetic transcript segment.")
            page.screenshot(path=str(evidence / "authenticated-call-studio.png"), full_page=True)
            page.screenshot(
                path=str(evidence / "authenticated-report-measurements.png"), full_page=True
            )

            cookies = context.cookies(backend.origin)
            session_cookie = next(
                item for item in cookies if item["name"] == backend.session_cookie_name
            )
            assert session_cookie["domain"] == urlsplit(backend.origin).hostname
            assert session_cookie["path"] == "/"
            assert session_cookie["httpOnly"] is True
            assert session_cookie["sameSite"] == "Lax"
            assert session_cookie["secure"] is False
            checks.append("Password login issued a same-origin host-only session cookie.")

            denied = page.evaluate(
                """
                async (tenantId) => {
                  const response = await fetch('/v1/context', {
                    method: 'POST',
                    credentials: 'same-origin',
                    headers: {'content-type': 'application/json', 'accept': 'application/json'},
                    body: JSON.stringify({tenant_id: tenantId}),
                  });
                  return {status: response.status, body: await response.json()};
                }
                """,
                str(backend.account.foreign_tenant_id),
            )
            assert denied["status"] == 403
            checks.append("Selecting a tenant without membership is denied by the server.")

            before_logout = len(network)
            logged_out = page.evaluate(
                """
                async () => {
                  const response = await fetch('/v1/auth/logout', {
                    method: 'POST',
                    credentials: 'same-origin',
                  });
                  return response.status;
                }
                """
            )
            assert logged_out == 204
            assert not any(
                item["name"] == backend.session_cookie_name
                for item in context.cookies(backend.origin)
            )
            unauthorized_measurements = page.evaluate(
                """
                async (recordingId) => {
                  const response = await fetch(
                    `/v1/conversation/recordings/${recordingId}/measurements`,
                    {credentials: 'same-origin', cache: 'no-store'},
                  );
                  return {
                    status: response.status,
                    cacheControl: response.headers.get('cache-control'),
                  };
                }
                """,
                str(backend.account.recording_id),
            )
            assert unauthorized_measurements["status"] == 401
            unauthorized_source = page.evaluate(
                """
                async (recordingId) => {
                  const response = await fetch(
                    `/v1/conversation/recordings/${recordingId}/source`,
                    {credentials: 'same-origin', cache: 'no-store'},
                  );
                  return {status: response.status};
                }
                """,
                str(backend.account.recording_id),
            )
            assert unauthorized_source["status"] == 401
            checks.append(
                "After logout, saved measurements and source playback return 401; "
                "the authorized read was private/no-store."
            )
            page.reload(wait_until="networkidle")
            expect(page.get_by_role("link", name="Sign in with AC")).to_be_visible()
            expect(page.locator(".recording-history-item")).to_have_count(0)
            assert not any(
                item["path"] == "/v1/conversation/recordings" for item in network[before_logout:]
            )
            checks.append("Logout clears the session and anonymous reload cannot read history.")
            assert any(
                item["method"] == "POST"
                and item["path"] == "/v1/auth/password/login"
                and item["status"] == 200
                for item in network
            )
            assert any(
                item["method"] == "GET"
                and item["path"] == "/v1/me/workspaces"
                and item["status"] == 200
                for item in network
            )
            assert any(
                item["method"] == "POST" and item["path"] == "/v1/context" and item["status"] == 403
                for item in network
            )
            assert any(
                item["method"] == "POST"
                and item["path"] == "/v1/auth/logout"
                and item["status"] == 204
                for item in network
            )
            assert any(
                item["method"] == "GET"
                and item["path"].endswith("/measurements")
                and item["status"] == 200
                and item["cache_control"] == "private, no-store"
                for item in network
            )
            assert any(
                item["method"] == "GET"
                and item["path"].endswith("/measurements")
                and item["status"] == 401
                for item in network
            )
            assert any(
                item["method"] == "GET"
                and item["path"].endswith("/source")
                and item["status"] in (200, 206)
                and item["content_type"].startswith("audio/wav")
                and item["cache_control"] == "private, no-store"
                for item in network
            )
            assert any(
                item["method"] == "GET"
                and item["path"].endswith("/source")
                and item["status"] == 401
                for item in network
            )
            assert not external
            assert not browser_errors
            # Next's navigation probe and a completed authentication response can
            # be cancelled when a full document navigation replaces the page.
            # Preserve every event in the receipt; only accept the three API
            # cancellations after their exact success status and session effects
            # have independently passed above. Other failures still fail proof.
            accepted_aborts = {"HEAD /: net::ERR_ABORTED"}
            for method, path, status in (
                ("POST", "/v1/auth/password/login", 200),
                ("POST", "/v1/auth/logout", 204),
                (
                    "GET",
                    f"/v1/conversation/recordings/{backend.account.recording_id}/measurements",
                    401,
                ),
                (
                    "GET",
                    f"/v1/conversation/recordings/{backend.account.recording_id}/source",
                    401,
                ),
            ):
                if any(
                    item["method"] == method and item["path"] == path and item["status"] == status
                    for item in network
                ):
                    accepted_aborts.add(f"{method} {path}: net::ERR_ABORTED")
            proof["navigation_cancellations"] = [
                failure for failure in request_failures if failure in accepted_aborts
            ]
            unexpected_failures = [
                failure for failure in request_failures if failure not in accepted_aborts
            ]
            proof["unexpected_request_failures"] = unexpected_failures
            assert not unexpected_failures
            proof["passed"] = True
        finally:
            if not proof["passed"]:
                proof["failure_visible_text"] = page.locator("body").inner_text()[:12000]
                page.screenshot(path=str(evidence / "failure.png"), full_page=True)
            receipt_path.write_text(
                json.dumps(proof, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )


@pytest.mark.e2e
def test_standalone_sales_xray_password_workspace_and_logout_browser_proof(
    standalone_backend: StandaloneBackend,
    tmp_path: Path,
) -> None:
    _exercise_browser(
        standalone_backend,
        _evidence_dir(tmp_path),
    )
