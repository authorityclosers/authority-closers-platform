"""Compiled Next UI -> actual cookie HTTP/PG -> offline C1 -> synthetic broker.

Only Cloudflare's widget JavaScript and verification, the native socket and
provider network are replaced by explicit test adapters. No AC API response is
intercepted. Original test audio, workers, ownership, quota and C6 are real local
components. Never run this harness against an external database or host.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
import uvicorn
from playwright.async_api import async_playwright, expect

from ac_platform.conversation_intelligence import signals
from ac_platform.conversation_intelligence.acquisition_challenge import UploadChallenge
from ac_platform.conversation_intelligence.broker_router import FixedProviderRouter, ProviderRoute
from ac_platform.conversation_intelligence.inference_worker import ConversationInferenceWorker
from ac_platform.conversation_intelligence.native_runtime import SocketNativeRuntime
from ac_platform.conversation_intelligence.processing_plan import ProcessingPlanScheduler
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_processing_plan_postgresql import _make_due
from tests.database.test_conversation_reporting_pipeline_postgresql import ReportingBroker
from tests.database.test_conversation_submission_http_postgresql import _setup
from tests.database.test_conversation_worker_postgresql import (
    OfflineConversationWorker,
    _reconcile,
    _wav_one_second_48k,
)

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "apps/sales-xray-web"
API_ORIGIN = "http://127.0.0.1:18116"
ORIGIN = "http://127.0.0.1:18117"
PREFIX = "/v1/conversation/acquisition"


@pytest.fixture
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


def test_compiled_guest_upload_report_reload_claim_and_deletion(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence = os.environ.get("AC_SALES_XRAY_ACQUISITION_BROWSER_EVIDENCE_DIR")
    node = os.environ.get("AC_SALES_XRAY_TEST_NODE")
    if not evidence or not node:
        pytest.skip("Opt in with a fresh external receipt directory and Node path.")
    receipt = Path(evidence)
    receipt.mkdir(parents=True, exist_ok=True)
    if not (WEB / ".next/BUILD_ID").is_file():
        pytest.fail("Build the actual Next app with API origin 127.0.0.1:18116 first.")

    async def exercise() -> None:
        import ac_platform.http.app as app_module

        setup = await _setup(postgres_harness, tmp_path, gemini=True)
        server: uvicorn.Server | None = None
        serving = None
        web = None
        try:
            secret_file = tmp_path / "challenge.secret"
            secret_file.write_text(secrets.token_urlsafe(32), encoding="ascii")
            secret_file.chmod(0o600)
            configured = setup.settings.model_copy(
                update={
                    "sales_xray_app_url": ORIGIN,
                    "sales_xray_acquisition_enabled": True,
                    "sales_xray_acquisition_policy_revision": "guest-processing-v1",
                    "sales_xray_challenge_secret_file": str(secret_file),
                    "sales_xray_challenge_site_key": "synthetic-browser-key",
                    "sales_xray_native_socket_path": str(
                        Path(tempfile.gettempdir()) / "ac-xray-browser.sock"
                    ),
                    "sales_xray_native_image_ref": "sha256:" + "a" * 64,
                }
            )
            # model_copy does not parse URL values; parse the non-secret update
            # through the existing Settings type before composing the real app.
            from pydantic import HttpUrl

            configured.sales_xray_app_url = HttpUrl(ORIGIN)
            monkeypatch.setattr(app_module, "settings", configured)
            monkeypatch.setattr(app_module, "session_factory", setup.sessions)

            def native(self: Any, source: Path, outdir: Path, *, job_id: UUID, rate: Any):
                return signals.inspect_media(source, outdir, rate=rate)

            async def challenge(self: Any, token: str):
                assert token == "synthetic-browser-challenge"  # noqa: S105 -- test-only response

            monkeypatch.setattr(SocketNativeRuntime, "inspect", native)
            monkeypatch.setattr(UploadChallenge, "verify", challenge)
            application = app_module.create_app(conversation_intake_runtime=setup.runtime)
            assert application.state.sales_xray_acquisition_configured
            server = uvicorn.Server(
                uvicorn.Config(
                    application,
                    host="127.0.0.1",
                    port=18116,
                    access_log=False,
                    log_level="critical",
                    lifespan="off",
                )
            )
            serving = asyncio.create_task(server.serve())
            async with httpx.AsyncClient() as client:
                for _ in range(100):
                    if server.started:
                        break
                    await asyncio.sleep(0.05)
                assert server.started
                # A fixed test-only local process. No shell, secrets or live config.
                web = await asyncio.to_thread(
                    subprocess.Popen,
                    [
                        node,
                        "node_modules/next/dist/bin/next",
                        "start",
                        "--hostname",
                        "127.0.0.1",
                        "--port",
                        "18117",
                    ],
                    cwd=WEB,
                    env={
                        **{
                            key: os.environ[key]
                            for key in ("PATH", "SystemRoot", "WINDIR", "TEMP", "TMP")
                            if key in os.environ
                        },
                        "AC_CONVERSATION_API_ORIGIN": API_ORIGIN,
                        "NODE_ENV": "production",
                    },
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                for _ in range(100):
                    try:
                        ready = await client.get(ORIGIN, timeout=2)
                        if ready.status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    await asyncio.sleep(0.2)
                else:
                    pytest.fail("The compiled local UI did not become ready.")

            data = _wav_one_second_48k()
            broker = ReportingBroker(data)
            router = FixedProviderRouter(
                {
                    provider: ProviderRoute(provider, f"ref:credential:{provider}", broker)
                    for provider in ("elevenlabs", "gemini")
                },
                authority=setup.authority,
            )
            worker = ConversationInferenceWorker(
                setup.sessions, setup.runtime.storage, router, authority=setup.authority
            )
            scheduler = ProcessingPlanScheduler(setup.sessions, setup.authority)
            database_loop = asyncio.get_running_loop()

            async def db(operation):
                return await asyncio.wrap_future(
                    asyncio.run_coroutine_threadsafe(operation, database_loop)
                )

            async def browser_exercise():
                async with async_playwright() as playwright:
                    browser = await playwright.chromium.launch(headless=True)
                    context = await browser.new_context(
                        viewport={"width": 1440, "height": 1000}, reduced_motion="reduce"
                    )
                    page = await context.new_page()
                    network = []
                    errors = []
                    page.on(
                        "response",
                        lambda response: (
                            network.append(
                                {"path": response.url.split(ORIGIN)[-1], "status": response.status}
                            )
                            if response.url.startswith(ORIGIN + PREFIX)
                            else None
                        ),
                    )
                    page.on("pageerror", lambda error: errors.append(type(error).__name__))
                    await page.route(
                        "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit",
                        lambda route: route.fulfill(
                            content_type="text/javascript",
                            body=(
                                "window.turnstile={render:function(el,options){setTimeout(function(){"
                                "options.callback('synthetic-browser-challenge')},20);"
                                "return 'synthetic-widget'},remove:function(){}};"
                            ),
                        ),
                    )
                    await page.goto(ORIGIN, wait_until="domcontentloaded")
                    await expect(
                        page.get_by_role("heading", name="Start with your sales call")
                    ).to_be_visible()
                    await page.screenshot(path=str(receipt / "upload-desktop.png"), full_page=True)
                    await page.get_by_label("Choose sales call audio").set_input_files(
                        {"name": "Synthetic test call.wav", "mimeType": "audio/wav", "buffer": data}
                    )
                    await expect(
                        page.get_by_role("button", name="Upload my call", exact=True)
                    ).to_be_disabled()
                    await page.get_by_role("checkbox", name="I have permission").check()
                    async with page.expect_response(
                        lambda response: (
                            response.url.endswith("/source") and response.request.method == "PUT"
                        )
                    ) as upload_response:
                        await page.get_by_role("button", name="Upload my call", exact=True).click()
                    uploaded_response = await upload_response.value
                    assert uploaded_response.status == 202
                    uploaded = await uploaded_response.json()
                    submission_id = uploaded["submission_id"]
                    await db(_reconcile(setup.sessions, setup.state))
                    local = OfflineConversationWorker(
                        setup.sessions,
                        storage=setup.runtime.storage,
                        scratch=setup.runtime.scratch,
                        environment="test",
                    )
                    assert await db(local.run_once())
                    await expect(
                        page.get_by_role("button", name="Analyse my call", exact=True)
                    ).to_be_visible(timeout=20000)
                    assert broker.calls == 0
                    await expect(
                        page.get_by_role("button", name="Analyse my call", exact=True)
                    ).to_be_disabled()
                    await page.get_by_role(
                        "checkbox", name="I approve this exact provider plan"
                    ).check()
                    async with page.expect_response(
                        lambda response: (
                            response.url.endswith("/plan") and response.request.method == "POST"
                        )
                    ) as plan_response:
                        await page.get_by_role("button", name="Analyse my call", exact=True).click()
                    plan_result = await (await plan_response.value).json()
                    for _ in range(8):
                        await db(worker.run_once())
                        await db(_make_due(setup, UUID(plan_result["id"])))
                        await db(scheduler.step())
                    await expect(
                        page.get_by_role("region", name="Sales call report")
                    ).to_be_visible(timeout=30000)
                    assert broker.routes == ["elevenlabs", "gemini", "gemini"]
                    await page.screenshot(path=str(receipt / "report-desktop.png"), full_page=True)
                    await page.get_by_role("tab", name="Transcript & moments").click()
                    assert (
                        await page.locator("audio").get_attribute("src")
                        == PREFIX + f"/submissions/{submission_id}/source"
                    )
                    replay = await context.request.get(
                        ORIGIN + PREFIX + f"/submissions/{submission_id}/source",
                        headers={"Range": "bytes=0-31"},
                    )
                    assert replay.status == 206 and len(await replay.body()) == 32
                    await page.reload(wait_until="domcontentloaded")
                    await expect(
                        page.get_by_role("region", name="Sales call report")
                    ).to_be_visible(timeout=20000)
                    assert broker.calls == 3
                    await page.set_viewport_size({"width": 390, "height": 844})
                    await page.screenshot(path=str(receipt / "report-mobile.png"), full_page=True)
                    assert await page.evaluate(
                        "document.documentElement.scrollWidth <= window.innerWidth"
                    )
                    await page.pdf(path=str(receipt / "report-print.pdf"), print_background=True)
                    # Real current account cookie; the UI must offer a claim, not
                    # silently turn the guest credential into an account session.
                    await context.add_cookies(
                        [
                            {
                                "name": "ac_session",
                                "value": setup.token,
                                "url": ORIGIN,
                                "httpOnly": True,
                                "sameSite": "Lax",
                            }
                        ]
                    )
                    await page.reload(wait_until="domcontentloaded")
                    await expect(
                        page.get_by_role("button", name="Save to my account", exact=True)
                    ).to_be_visible()
                    await page.get_by_role("button", name="Save to my account", exact=True).click()
                    await expect(
                        page.get_by_role("region", name="Sales call report")
                    ).to_be_visible(timeout=20000)
                    stranger = await browser.new_context()
                    denied = await stranger.request.get(
                        ORIGIN + PREFIX + f"/submissions/{submission_id}/report"
                    )
                    assert denied.status in (401, 404)
                    await stranger.close()
                    await page.get_by_role("button", name="Delete this call", exact=True).click()
                    await page.get_by_role(
                        "button", name="Delete recording and report", exact=True
                    ).click()
                    await expect(
                        page.get_by_text("Deletion requested.", exact=False)
                    ).to_be_visible()
                    assert not errors
                    (receipt / "browser-network.json").write_text(
                        json.dumps(
                            {
                                "route": "/",
                                "compiled_build_id": (WEB / ".next/BUILD_ID").read_text().strip(),
                                "api_interceptions": 0,
                                "synthetic_provider_calls": broker.calls,
                                "provider_network_calls": 0,
                                "native_socket_simulated": True,
                                "challenge_simulated": True,
                                "http_receipts": network,
                                "page_errors": errors,
                                "passed": [
                                    "inline upload consent",
                                    "native C1",
                                    "explicit provider plan",
                                    "C6 overview",
                                    "private range playback",
                                    "reload without retranscription",
                                    "390px reflow",
                                    "print",
                                    "explicit account claim",
                                    "stranger denied",
                                    "deletion accepted",
                                ],
                            },
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                    await context.close()
                    await browser.close()

            # Psycopg uses the selector loop; Playwright subprocesses use the
            # platform default loop in a separate thread. All DB work remains
            # on its original loop, including the live ASGI server.
            await asyncio.to_thread(lambda: asyncio.run(browser_exercise()))
        finally:
            if web is not None:
                web.terminate()
                await asyncio.to_thread(web.wait, 15)
            if server is not None:
                server.should_exit = True
            if serving is not None:
                await serving
            await setup.engine.dispose()

    run(exercise())
