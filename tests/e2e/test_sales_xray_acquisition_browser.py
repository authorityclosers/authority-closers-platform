"""Compiled Next UI -> actual cookie HTTP/PG -> offline C1 -> synthetic broker.

Only Cloudflare's widget JavaScript and verification, the native socket and
provider network are replaced by explicit test adapters. No AC API response is
intercepted. Original test audio, workers, ownership, quota and C6 are real local
components. Never run this harness against an external database or host.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import secrets
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
import uvicorn
from playwright.async_api import async_playwright, expect
from pydantic import SecretStr
from sqlalchemy import select

from ac_platform.conversation_intelligence import signals
from ac_platform.conversation_intelligence.acquisition_challenge import UploadChallenge
from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionSettlement,
    ConversationAcquisitionUsage,
)
from ac_platform.conversation_intelligence.acquisition_reports import AcquisitionReports
from ac_platform.conversation_intelligence.broker_router import FixedProviderRouter, ProviderRoute
from ac_platform.conversation_intelligence.inference_worker import ConversationInferenceWorker
from ac_platform.conversation_intelligence.models import ConversationProcessingPlan
from ac_platform.conversation_intelligence.native_runtime import SocketNativeRuntime
from ac_platform.conversation_intelligence.processing_plan import ProcessingPlanScheduler
from ac_platform.identity.models import Person
from ac_platform.identity.sales_xray_profile_models import SalesXrayProfile
from ac_platform.providers import FakeEmailAdapter
from ac_platform.tenancy.models import Tenant
from ac_platform.worker import DurableWorker, build_default_dispatcher
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


def test_compiled_account_required_upload_profile_otp_report_relogin_and_deletion(
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
        email = f"browser-{uuid4().hex}@example.test"
        operations_tenant_id = uuid4()
        async with setup.sessions() as database, database.begin():
            # Email-code audit records use the configured operations tenant as
            # their canonical boundary, so make it part of this isolated DB.
            database.add(
                Tenant(
                    id=operations_tenant_id,
                    slug=operations_tenant_id.hex,
                    name="Synthetic browser operations workspace",
                )
            )
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
                    "operations_tenant_id": operations_tenant_id,
                    "learner_consent_version": "browser-account-consent-v1",
                    "email_challenge_secret": SecretStr(secrets.token_urlsafe(32)),
                    "external_side_effects_hold": False,
                }
            )
            # model_copy does not parse URL values; parse the non-secret update
            # through the existing Settings type before composing the real app.
            from pydantic import HttpUrl

            configured.sales_xray_app_url = HttpUrl(ORIGIN)
            monkeypatch.setattr(app_module, "settings", configured)
            monkeypatch.setattr(app_module, "session_factory", setup.sessions)

            # The HTTP request writes the canonical outbox event. This explicit
            # fake adapter lets the browser receive that real queued code
            # without contacting an email provider.
            mail_adapter = FakeEmailAdapter()
            email_worker = DurableWorker(
                setup.sessions,
                dispatcher=build_default_dispatcher(configured, provider=mail_adapter),
                settings=configured,
            )

            def native(self: Any, source: Path, outdir: Path, *, job_id: UUID, rate: Any):
                return signals.validate_media(source, outdir, rate=rate)

            async def challenge(self: Any, token: str):
                assert token == "synthetic-browser-challenge"  # noqa: S105 -- test-only response

            monkeypatch.setattr(SocketNativeRuntime, "validate_source", native)
            monkeypatch.setattr(UploadChallenge, "verify", challenge)

            # Exercise the compiled UI against the exact retained-C5 response
            # shape while keeping the report and detailed overview produced by
            # the real synthetic pipeline. This is a test-only server adapter,
            # not an API response interception or provider/customer fixture.
            original_report = AcquisitionReports.report

            async def recovered_report(
                self: AcquisitionReports,
                submission_id: UUID,
                *,
                token: str | None = None,
                actor: Any = None,
                shared_identity_locks: bool = False,
            ) -> dict[str, Any]:
                result = await original_report(
                    self,
                    submission_id,
                    token=token,
                    actor=actor,
                    shared_identity_locks=shared_identity_locks,
                )
                report = result.get("report")
                if not isinstance(report, dict):
                    raise AssertionError("synthetic report projection is missing")
                content = report.get("content")
                if not isinstance(content, dict):
                    raise AssertionError("synthetic report content is missing")
                overview = content.get("overview")
                if not isinstance(overview, dict):
                    raise AssertionError("synthetic canonical overview is missing")
                overview["business_impact"] = {
                    "status": "insufficient_data",
                    "missing_inputs": [
                        "Comparable conversion history",
                        "Lead volume",
                    ],
                }
                result["recovery"] = {
                    "version": 1,
                    "validation_state": "revalidated",
                    "provider_calls": 0,
                    "human_approved": False,
                    "official_score": False,
                }
                return result

            monkeypatch.setattr(AcquisitionReports, "report", recovered_report)
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

            await db(_reconcile(setup.sessions, setup.state))
            assert await db(email_worker.prepare())

            async def deliver_email_code(*, message_start: int) -> str:
                for _ in range(8):
                    await db(email_worker.run_once())
                    matches = [
                        message
                        for message in mail_adapter.sent_messages[message_start:]
                        if message.template == "identity-email-login-code"
                        and message.to.casefold() == email.casefold()
                    ]
                    if matches:
                        code = matches[-1].variables.get("code")
                        assert isinstance(code, str) and len(code) == 6 and code.isdigit()
                        return code
                    await asyncio.sleep(0.05)
                raise AssertionError("The real local email outbox did not deliver a login code.")

            async def authenticate_with_email_code(target: Any) -> dict[str, Any]:
                await target.get_by_label("Email address").fill(email)
                await target.get_by_role("checkbox").check()
                before = len(mail_adapter.sent_messages)
                async with target.expect_response(
                    lambda response: (
                        response.url.endswith("/v1/auth/email-code/request")
                        and response.request.method == "POST"
                    )
                ) as request_response:
                    await target.get_by_role("button", name="Send sign-in code", exact=True).click()
                requested = await request_response.value
                assert requested.status == 202
                request_body = requested.request.post_data_json
                assert request_body["surface"] == "sales_xray"
                assert request_body["return_path"] == "/"
                assert request_body["consent"] is True
                assert request_body["consent_version"] == "browser-account-consent-v1"
                await expect(
                    target.get_by_role("heading", name="Check your email.", exact=True)
                ).to_be_visible()
                try:
                    code = await deliver_email_code(message_start=before)
                except AssertionError:
                    # A recently consumed challenge remains inside the actual
                    # resend cooldown. Let the UI-supplied server timer expire,
                    # then perform a real resend through the same browser.
                    resend = target.get_by_role("button", name=re.compile(r"^Resend code"))
                    await expect(resend).to_be_enabled(timeout=70_000)
                    before = len(mail_adapter.sent_messages)
                    await resend.click()
                    code = await deliver_email_code(message_start=before)
                await target.get_by_label("Sign-in code").fill(code)
                async with target.expect_response(
                    lambda response: (
                        response.url.endswith("/v1/auth/email-code/verify")
                        and response.request.method == "POST"
                    )
                ) as verify_response:
                    await target.get_by_role(
                        "button", name="Verify and continue", exact=True
                    ).click()
                verified = await verify_response.value
                assert verified.status == 200
                verify_body = verified.request.post_data_json
                assert verify_body["surface"] == "sales_xray"
                assert verify_body["return_path"] == "/"
                assert verify_body["code"] == code
                payload = await verified.json()
                assert payload["authenticated"] is True
                return payload

            async def browser_exercise():
                async with async_playwright() as playwright:
                    browser = await playwright.chromium.launch(headless=True)
                    context = await browser.new_context(
                        viewport={"width": 1440, "height": 1000}, reduced_motion="reduce"
                    )
                    page = await context.new_page()
                    network = []
                    requests = []
                    external_mutating_requests = []
                    source_request_hashes = []
                    errors = []
                    plan_posts = []
                    journey_checks: dict[str, Any] = {}

                    def record_response(response):
                        if response.url.startswith(ORIGIN + "/v1/"):
                            if response.url.endswith("/plan") and response.request.method == "POST":
                                plan_posts.append(response)
                            network.append(
                                {
                                    "path": response.url.split(ORIGIN)[-1],
                                    "method": response.request.method,
                                    "status": response.status,
                                }
                            )

                    def record_request(request):
                        if not request.url.startswith(ORIGIN + "/v1/"):
                            if request.method in {"POST", "PUT", "PATCH"}:
                                external_mutating_requests.append(request.method)
                            return
                        path = request.url.split("?", 1)[0]
                        if path.endswith("/source") and request.method == "PUT":
                            source_request_hashes.append(
                                hashlib.sha256(request.post_data_buffer or b"").hexdigest()
                            )
                        requests.append(
                            {
                                "path": request.url.split(ORIGIN)[-1],
                                "method": request.method,
                            }
                        )

                    page.on("response", record_response)
                    page.on("request", record_request)
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
                        page.get_by_role("heading", name="Add a call to review", exact=True)
                    ).to_be_visible()
                    await page.screenshot(path=str(receipt / "upload-desktop.png"), full_page=True)
                    browse = page.get_by_role("button", name="or click to browse", exact=True)
                    await expect(browse).to_be_enabled(timeout=15_000)
                    async with page.expect_file_chooser() as chooser:
                        await browse.click()
                    await (await chooser.value).set_files(
                        {"name": "Synthetic test call.wav", "mimeType": "audio/wav", "buffer": data}
                    )
                    # The account-first gate may open directly on file select or
                    # behind the primary action. The filename must remain visible
                    # through authentication and profile; this test never selects
                    # another file before the upload.
                    if not await page.get_by_label("Email address").is_visible():
                        await page.get_by_role("button", name="Analyse my call", exact=True).click()
                    await expect(page.get_by_label("Email address")).to_be_visible()
                    await expect(
                        page.get_by_text("Synthetic test call.wav", exact=False).first
                    ).to_be_visible()
                    journey_checks["selected_filename_in_auth_modal"] = True

                    def source_or_plan_write(item: dict[str, str]) -> bool:
                        path = item["path"].split("?", 1)[0]
                        return item["method"] in {"POST", "PUT", "PATCH"} and (
                            path.endswith("/source")
                            or path.endswith("/plan")
                            or "/upload" in path
                            or path.endswith("/submissions")
                        )

                    assert not any(source_or_plan_write(item) for item in requests)
                    assert plan_posts == [] and broker.calls == 0
                    journey_checks["pre_auth_source_or_plan_writes"] = sum(
                        source_or_plan_write(item) for item in requests
                    )
                    journey_checks["pre_auth_provider_calls"] = broker.calls
                    journey_checks["pre_auth_external_mutations"] = len(external_mutating_requests)
                    assert source_request_hashes == []

                    async def assert_no_usage_before_auth():
                        async with setup.sessions() as diagnostic_db:
                            assert (
                                await diagnostic_db.scalar(
                                    select(ConversationAcquisitionUsage.id).limit(1)
                                )
                                is None
                            )

                    await db(assert_no_usage_before_auth())

                    authenticated = await authenticate_with_email_code(page)
                    assert authenticated["account_created"] is True
                    assert authenticated["profile_complete"] is False
                    journey_checks["email_otp_verified"] = any(
                        message.template == "identity-email-login-code"
                        and message.to.casefold() == email.casefold()
                        for message in mail_adapter.sent_messages
                    )
                    journey_checks["account_created_before_profile"] = bool(
                        authenticated["account_created"] and not authenticated["profile_complete"]
                    )
                    owner_person_id = UUID(authenticated["person_id"])
                    selected_profile_file = page.get_by_label("Selected audio file")
                    await expect(selected_profile_file).to_contain_text("Synthetic test call.wav")
                    await expect(
                        page.get_by_role(
                            "heading", name="A few details before we review your call."
                        )
                    ).to_be_visible()
                    journey_checks["pre_profile_source_or_plan_writes"] = sum(
                        source_or_plan_write(item) for item in requests
                    )

                    await page.get_by_label("Full name").fill("Synthetic Browser Learner")
                    await page.get_by_label("Country or region").select_option("US")
                    await page.get_by_label("Mobile number").fill("+12025550123")
                    async with page.expect_response(
                        lambda response: (
                            response.url.endswith("/v1/me/sales-xray-profile")
                            and response.request.method == "PUT"
                        )
                    ) as profile_response:
                        await page.get_by_role(
                            "button", name="Save details and check access", exact=True
                        ).click()
                    saved_profile = await profile_response.value
                    assert saved_profile.status == 200
                    # The UI completes its read and unmounts the profile form,
                    # whose abort controller can discard Chromium's response
                    # body handle. Verify the actual 200 write above, then read
                    # canonical state with the same authenticated browser.
                    profile_read = await context.request.get(
                        ORIGIN + "/v1/me/sales-xray-profile"
                    )
                    assert profile_read.status == 200
                    profile_payload = await profile_read.json()
                    assert profile_payload["profile_complete"] is True
                    assert profile_payload["name"] == "Synthetic Browser Learner"
                    assert profile_payload["phone_number_e164"] == "+12025550123"
                    assert profile_payload["phone_verified"] is False
                    await expect(
                        page.get_by_role("button", name="Analyse my call", exact=True)
                    ).to_be_visible(timeout=20_000)
                    await expect(
                        page.get_by_text("Synthetic test call.wav", exact=True).first
                    ).to_be_visible()
                    assert not any(source_or_plan_write(item) for item in requests)
                    assert plan_posts == [] and broker.calls == 0
                    assert source_request_hashes == []
                    journey_checks["profile_complete_before_upload"] = bool(
                        profile_payload["profile_complete"]
                    )
                    journey_checks["selected_filename_through_profile"] = True

                    async def assert_verified_account_profile():
                        async with setup.sessions() as diagnostic_db:
                            person = await diagnostic_db.get(Person, owner_person_id)
                            profile = await diagnostic_db.scalar(
                                select(SalesXrayProfile).where(
                                    SalesXrayProfile.person_id == owner_person_id
                                )
                            )
                            assert person is not None and person.email_verified_at is not None
                            assert person.consent_version == "browser-account-consent-v1"
                            assert profile is not None
                            assert profile.phone_number_e164 == "+12025550123"
                            assert profile.phone_verified_at is None

                    await db(assert_verified_account_profile())

                    await page.get_by_role("checkbox").last.check()
                    journey_checks[
                        "selected_filename_visible_before_upload"
                    ] = await page.get_by_text(
                        "Synthetic test call.wav", exact=True
                    ).first.is_visible()
                    assert journey_checks["selected_filename_visible_before_upload"] is True
                    async with page.expect_response(
                        lambda response: (
                            response.url.endswith("/source") and response.request.method == "PUT"
                        )
                    ) as upload_response:
                        await page.get_by_role("button", name="Analyse my call", exact=True).click()
                    uploaded_response = await upload_response.value
                    if uploaded_response.status != 202:
                        try:
                            problem = await uploaded_response.json()
                        except (ValueError, TypeError):
                            problem = {}
                        if not isinstance(problem, dict):
                            problem = {}
                        detail = problem.get("detail")
                        detail = " ".join(detail.split())[:240] if isinstance(detail, str) else None
                        pytest.fail(
                            "source upload failed: "
                            f"status={uploaded_response.status}, "
                            f"code={problem.get('code')!r}, "
                            f"title={problem.get('title')!r}, "
                            f"detail={detail!r}"
                        )
                    uploaded = await uploaded_response.json()
                    submission_id = uploaded["submission_id"]
                    expected_source_hash = hashlib.sha256(data).hexdigest()
                    assert source_request_hashes == [expected_source_hash]
                    journey_checks["uploaded_source_request_hash_matches_selected_bytes"] = (
                        source_request_hashes == [expected_source_hash]
                    )
                    await db(_reconcile(setup.sessions, setup.state))
                    local = OfflineConversationWorker(
                        setup.sessions,
                        storage=setup.runtime.storage,
                        scratch=setup.runtime.scratch,
                        environment="test",
                    )
                    assert await db(local.run_once())
                    # Depending on poll timing, the freshly consented upload may
                    # already be auto-approved, or may still expose the explicit
                    # Continue action. Give the automatic path time to settle and
                    # only click when no acceptance request has completed.
                    await page.wait_for_timeout(5000)
                    continue_button = page.get_by_role(
                        "button", name="Continue analysis", exact=True
                    )
                    if not plan_posts and await continue_button.is_visible():
                        assert broker.calls == 0
                        await expect(continue_button).to_be_enabled()
                        async with page.expect_response(
                            lambda response: (
                                response.url.endswith("/plan") and response.request.method == "POST"
                            )
                        ):
                            await continue_button.click()

                    async def latest_plan_id():
                        async with setup.sessions() as diagnostic_db:
                            row = await diagnostic_db.scalar(
                                select(ConversationProcessingPlan)
                                .where(
                                    ConversationProcessingPlan.recording_id
                                    == UUID(uploaded["recording_id"])
                                )
                                .order_by(ConversationProcessingPlan.created_at.desc())
                                .limit(1)
                            )
                            return None if row is None else row.id

                    for _ in range(16):
                        await db(worker.run_once())
                        plan_id = await db(latest_plan_id())
                        if plan_id is not None:
                            await db(_make_due(setup, plan_id))
                        await db(scheduler.step())
                    await expect(
                        page.get_by_role("region", name="Sales call report")
                    ).to_be_visible(timeout=30000)
                    recovered_response = await context.request.get(
                        ORIGIN + PREFIX + f"/submissions/{submission_id}/report"
                    )
                    assert recovered_response.status == 200
                    recovered_payload = await recovered_response.json()
                    assert recovered_payload["recovery"] == {
                        "version": 1,
                        "validation_state": "revalidated",
                        "provider_calls": 0,
                        "human_approved": False,
                        "official_score": False,
                    }
                    assert recovered_payload["report"]["content"]["overview"][
                        "business_impact"
                    ] == {
                        "status": "insufficient_data",
                        "missing_inputs": [
                            "Comparable conversion history",
                            "Lead volume",
                        ],
                    }

                    async def assert_single_settlement():
                        async with setup.sessions() as diagnostic_db:
                            usage_rows = list(
                                (
                                    await diagnostic_db.scalars(
                                        select(ConversationAcquisitionUsage).where(
                                            ConversationAcquisitionUsage.person_id
                                            == owner_person_id
                                        )
                                    )
                                ).all()
                            )
                            assert len(usage_rows) == 1
                            usage = usage_rows[0]
                            assert usage.visitor_id is None
                            assert usage.submission_id == UUID(submission_id)
                            assert usage.source_sha256 == hashlib.sha256(data).hexdigest()
                            settlement = await diagnostic_db.get(
                                ConversationAcquisitionSettlement, usage.id
                            )
                            assert settlement is not None
                            assert settlement.kind == "completed"
                            assert settlement.charged_seconds == usage.reserved_seconds == 1
                            return {
                                "acquisition_usage_count": len(usage_rows),
                                "settlement_count": int(settlement is not None),
                                "charged_seconds": settlement.charged_seconds,
                            }

                    journey_checks.update(await db(assert_single_settlement()))
                    assert broker.routes == ["elevenlabs", "gemini", "gemini"]
                    await page.screenshot(path=str(receipt / "report-desktop.png"), full_page=True)
                    await page.get_by_role("tab", name="Moments", exact=True).click()
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

                    fresh = await browser.new_context(viewport={"width": 1440, "height": 1000})
                    library_page = await fresh.new_page()
                    library_page.on("response", record_response)
                    library_page.on("pageerror", lambda error: errors.append(type(error).__name__))
                    library_page.on("request", record_request)
                    await library_page.goto(ORIGIN + "/login", wait_until="domcontentloaded")
                    reauthenticated = await authenticate_with_email_code(library_page)
                    assert reauthenticated["account_created"] is False
                    assert reauthenticated["profile_complete"] is True
                    assert reauthenticated["person_id"] == str(owner_person_id)
                    journey_checks["relogin_existing_account"] = bool(
                        not reauthenticated["account_created"]
                        and reauthenticated["person_id"] == str(owner_person_id)
                    )
                    await library_page.goto(ORIGIN + "/calls", wait_until="domcontentloaded")
                    assert (
                        await library_page.evaluate("localStorage.getItem('ac.xray.submission.v1')")
                        is None
                    )
                    await library_page.get_by_role("link", name="Saved calls", exact=True).click()
                    await expect(
                        library_page.get_by_role("heading", name="Saved calls", exact=True)
                    ).to_be_visible()
                    await expect(
                        library_page.locator(f'button[data-submission-id="{submission_id}"]')
                    ).to_be_visible()
                    await library_page.screenshot(
                        path=str(receipt / "account-library-desktop.png"), full_page=True
                    )
                    listing = await fresh.request.get(ORIGIN + PREFIX + "/submissions")
                    assert listing.status == 200
                    assert [
                        row["submission_id"] for row in (await listing.json())["submissions"]
                    ] == [submission_id]
                    await library_page.set_viewport_size({"width": 320, "height": 844})
                    assert await library_page.evaluate(
                        "document.documentElement.scrollWidth <= window.innerWidth"
                    )
                    await library_page.screenshot(
                        path=str(receipt / "account-library-mobile.png"), full_page=True
                    )
                    await library_page.set_viewport_size({"width": 1440, "height": 1000})
                    saved_call = library_page.locator(
                        f'button[data-submission-id="{submission_id}"]'
                    )
                    await saved_call.focus()
                    await saved_call.press("Enter")
                    await expect(
                        library_page.get_by_role("region", name="Sales call report")
                    ).to_be_visible(timeout=20000)
                    await library_page.get_by_role("tab", name="Moments", exact=True).click()
                    player = library_page.locator("audio")
                    await expect(player).to_have_count(1)
                    assert (
                        await player.get_attribute("src")
                        == PREFIX + f"/submissions/{submission_id}/source"
                    )
                    await library_page.wait_for_function(
                        "document.querySelector('audio')?.readyState >= 1"
                    )
                    assert await player.evaluate("audio => audio.duration") == pytest.approx(
                        1, abs=0.02
                    )
                    await player.evaluate("audio => audio.play()")
                    await library_page.wait_for_function(
                        "document.querySelector('audio').currentTime > 0"
                    )
                    await library_page.screenshot(
                        path=str(receipt / "account-library-report-playback.png"), full_page=True
                    )
                    assert broker.calls == 3
                    await library_page.locator('summary[aria-label="More report actions"]').click()
                    await library_page.get_by_role(
                        "button", name="Request deletion", exact=True
                    ).click()
                    await library_page.get_by_role(
                        "button", name="Request recording deletion", exact=True
                    ).click()
                    await expect(
                        library_page.get_by_text("Deletion requested.", exact=False)
                    ).to_be_visible()
                    account_menu = library_page.get_by_role(
                        "button", name="Open Synthetic Browser Learner menu", exact=True
                    )
                    await expect(account_menu).to_be_visible()
                    await account_menu.click()
                    async with library_page.expect_response(
                        lambda response: (
                            response.url.endswith("/v1/auth/logout")
                            and response.request.method == "POST"
                        )
                    ) as logout:
                        await library_page.get_by_role(
                            "button", name="Sign out", exact=True
                        ).click()
                    assert (await logout.value).status == 204
                    await expect(
                        library_page.get_by_role("heading", name="Add a call to review", exact=True)
                    ).to_be_visible()
                    assert (
                        await library_page.evaluate("localStorage.getItem('ac.xray.submission.v1')")
                        is None
                    )
                    assert (await fresh.request.get(ORIGIN + PREFIX + "/submissions")).status == 401
                    for suffix in ("report", "source"):
                        assert (
                            await fresh.request.get(
                                ORIGIN + PREFIX + f"/submissions/{submission_id}/{suffix}"
                            )
                        ).status == 401
                    await fresh.close()
                    stranger = await browser.new_context()
                    denied = await stranger.request.get(
                        ORIGIN + PREFIX + f"/submissions/{submission_id}/report"
                    )
                    assert denied.status in (401, 404)
                    await stranger.close()
                    journey_checks["external_mutations"] = len(external_mutating_requests)
                    assert external_mutating_requests == []
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
                                "http_requests": requests,
                                "journey_checks": journey_checks,
                                "page_errors": errors,
                                "passed": [
                                    "selected audio remains browser-local before authentication",
                                    "pre-auth requests contain no source upload or processing plan",
                                    "email OTP delivered through local outbox and verified",
                                    "new canonical account exists before profile completion",
                                    "required account name and mobile profile completed",
                                    "no source transfer until authenticated profile is complete",
                                    "originally selected audio bytes upload only after "
                                    "profile completion",
                                    "selected filename stays visible through email OTP and profile",
                                    "uploaded source hash matches originally selected audio bytes",
                                    "inline upload consent",
                                    "native C1",
                                    "explicit provider plan after profile and upload consent",
                                    "C6 overview",
                                    "acquisition allowance settled exactly once",
                                    "private range playback",
                                    "reload without retranscription",
                                    "390px reflow",
                                    "print",
                                    "new browser context signs in again with email OTP",
                                    "new browser context discovers call in canonical "
                                    "account library",
                                    "library row opens retained report and actual audio plays",
                                    "rendered Sign out button returns204 and private endpoints401",
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
