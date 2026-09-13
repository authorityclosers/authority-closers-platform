"""Local browser + real PostgreSQL/HTTP proof, with synthetic identities and audio only.

Run through the reviewed loopback PostgreSQL test launcher. A production learner
Next build serves on REVIEW_UI_UPSTREAM (default http://127.0.0.1:3100).
Admin mode requires its development server and explicit local preview setting.
Only the session-resolution boundary and shell profile reads are fixtures.
The mounted review router, service, source storage, migrations and database are real.
No provider network or production account is used.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit
from uuid import UUID

import httpx
import uvicorn
from fastapi import FastAPI, Request, Response
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright
from sqlalchemy import func, select

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.application import ConversationApplication
from ac_platform.conversation_intelligence.models import (
    ConversationReviewFeedback,
    ConversationReviewInvitation,
)
from ac_platform.conversation_intelligence.review_contracts import ReviewInvitationCreateRequest
from ac_platform.conversation_intelligence.review_invitations import decrypt_invitation_token
from ac_platform.conversation_intelligence.review_service import ConversationReviewService
from ac_platform.http.auth import AuthenticatedTransaction
from ac_platform.http.conversation_reviews import install_conversation_review_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.application import ResolvedActorContext
from ac_platform.identity.models import Person
from tests.database.test_conversation_postgresql import postgres_harness as postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_reviews_postgresql import (
    _build_report_case,
    _create_assignment,
)

ORIGIN = os.environ.get("REVIEW_UI_ORIGIN", "http://127.0.0.1:3187")
if urlsplit(ORIGIN).hostname != "127.0.0.1":
    raise ValueError("Browser proof requires loopback origin")
UPSTREAM = os.environ.get("REVIEW_UI_UPSTREAM", "http://127.0.0.1:3100")
EVIDENCE = Path(os.environ["REVIEW_UI_EVIDENCE_DIR"])
ADMIN_UI = os.environ.get("REVIEW_UI_ADMIN") == "true"
INVITATIONS = os.environ.get("REVIEW_UI_INVITATIONS") == "true"


def test_real_review_browser(postgres_harness: Any, tmp_path: Path) -> None:  # noqa: F811
    async def exercise() -> None:
        case = await _build_report_case(postgres_harness, tmp_path)
        assignment = await _create_assignment(
            case, key="browser-assignment", lenses=("sales", "technical", "ux")
        )
        assignment_id = assignment["id"]
        actor = case.admin_actor if ADMIN_UI else case.reviewer_actor
        role = "owner" if ADMIN_UI else "learner"
        application = FastAPI()
        register_problem_handlers(application)

        async def require_actor(_request: Request):
            async with case.sessions() as database, database.begin():
                yield AuthenticatedTransaction(
                    database=database,
                    identity=cast(Any, None),
                    token="synthetic-test-session",  # noqa: S106 - isolated actor fixture
                    resolved=ResolvedActorContext(
                        actor=actor,
                        membership_role=role,
                        person_revision=0,
                        session_revision=0,
                        tenant_revision=0,
                        membership_revision=0,
                    ),
                )

        settings = Settings(
            _env_file=None,
            environment="test",
            public_app_url=ORIGIN,
            admin_app_url=UPSTREAM if ADMIN_UI else "http://admin.test",
            coach_app_url="http://coach.test",
            api_url=ORIGIN,
            operations_tenant_id=case.operations_tenant_id,
            email_challenge_secret="review-browser-fixture-secret-012345678901234567890",  # noqa: S106
        )
        invitation_token = None
        if INVITATIONS and not ADMIN_UI:
            async with case.sessions() as database, database.begin():
                reviewer = await database.get(Person, case.reviewer_actor.person_id)
                assert reviewer is not None and reviewer.email is not None
                service = ConversationReviewService(
                    ConversationApplication(database),
                    operations_tenant_id=case.operations_tenant_id,
                    token_secret=settings.email_challenge_secret.get_secret_value(),
                )
                invitation = await service.invite(
                    case.admin_actor,
                    ReviewInvitationCreateRequest(
                        schema="ac.sales-xray.review-invitation-create/1",
                        run_id=case.report_run_id,
                        invited_email=reviewer.email,
                        allowed_lenses=("sales", "technical", "ux"),
                        expires_at_epoch=assignment["expires_at_epoch"],
                    ),
                    "browser-invitation",
                )
                row = await database.get(ConversationReviewInvitation, UUID(invitation["id"]))
                assert row is not None
                # Local synthetic token stays in memory; never put it in evidence.
                invitation_token = decrypt_invitation_token(
                    settings.email_challenge_secret.get_secret_value(), row.encrypted_token, row.id
                )
        install_conversation_review_http(
            application,
            settings=settings,
            require_actor=require_actor,
            storage=case.prepared.storage,
        )

        @application.get("/v1/me")
        async def me():
            return {
                "person_id": str(actor.person_id),
                "email": "admin@authorityclosers.com" if ADMIN_UI else "reviewer@example.test",
                "display_name": "Synthetic administrator" if ADMIN_UI else "Synthetic reviewer",
                "email_verified_at": case.prepared.state.now.isoformat(),
                "selected_tenant_id": str(actor.tenant_id),
                "membership_role": role,
                "permissions": list(actor.permissions),
            }

        @application.get("/v1/context")
        async def context():
            return {
                "person_id": str(actor.person_id),
                "session_id": str(actor.session_id),
                "tenant_id": str(actor.tenant_id),
                "membership_role": role,
                "permissions": list(actor.permissions),
            }

        @application.get("/v1/me/studio-access")
        async def studio_access():
            return {
                "person_id": str(actor.person_id),
                "session_id": str(actor.session_id),
                "tenant_id": str(actor.tenant_id),
                "studio_capabilities": [],
            }

        @application.get("/v1/me/avatar")
        async def avatar():
            return {"avatar": None, "pending": None}

        transport = httpx.AsyncClient(base_url=UPSTREAM, timeout=30)

        @application.api_route("/{path:path}", methods=["GET", "HEAD"])
        async def frontend(request: Request, path: str):
            if path.startswith("v1/"):
                return Response(status_code=404)
            target = "/" + path + ("?" + request.url.query if request.url.query else "")
            forwarded = {
                key: value
                for key, value in request.headers.items()
                if key.lower()
                in {"rsc", "next-router-state-tree", "next-router-prefetch", "next-url", "accept"}
            }
            result = await transport.get(target, headers=forwarded)
            return Response(
                result.content,
                status_code=result.status_code,
                headers={
                    key: value
                    for key, value in result.headers.items()
                    if key.lower() in {"content-type", "cache-control", "vary"}
                },
            )

        config = uvicorn.Config(
            application,
            host="127.0.0.1",
            port=urlsplit(ORIGIN).port,
            log_level="error",
            access_log=False,
        )
        server = uvicorn.Server(config)
        task = asyncio.create_task(server.serve())
        try:
            for _ in range(100):
                if server.started:
                    break
                if task.done():
                    await task
                    raise AssertionError("Test HTTP server did not start")
                await asyncio.sleep(0.05)
            assert server.started
            result = (
                await asyncio.to_thread(
                    admin_browser_proof,
                    str(case.report_run_id),
                    str(case.reviewer_actor.person_id),
                    str(assignment["expires_at_epoch"]),
                )
                if ADMIN_UI
                else await asyncio.to_thread(browser_proof, assignment_id, invitation_token)
            )
            async with case.sessions() as database:
                count = await database.scalar(
                    select(func.count())
                    .select_from(ConversationReviewFeedback)
                    .where(
                        ConversationReviewFeedback.assignment_id
                        == result.get("assignment_id", assignment_id)
                    )
                )
                assert count == (0 if ADMIN_UI else 1)
            result["database_submission_count"] = count
            result["backend_commit"] = os.environ.get("REVIEW_UI_BACKEND_COMMIT")
            result["invitation_mode"] = INVITATIONS
            result["authentication"] = (
                "synthetic canonical actor fixture; session resolver not under test"
            )
            result["api"] = "real installed review HTTP router and PostgreSQL service"
            await asyncio.to_thread(write_receipt, result)
        finally:
            server.should_exit = True
            await task
            await transport.aclose()
            await case.engine.dispose()

    run(exercise())


def write_receipt(result: dict[str, Any]) -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    source_root = Path(__file__).resolve().parents[1]
    source_paths = [
        source_root
        / (
            "apps/admin-web/app/components/admin-shell.tsx"
            if ADMIN_UI
            else "apps/learner-web/app/components/site-shell.tsx"
        )
    ]
    source_directories = (
        ["apps/admin-web/app/sales-xray/review"]
        if ADMIN_UI
        else [
            "apps/learner-web/app/sales-xray/review",
            "packages/typescript/sales-xray-review-ui/src",
        ]
    )
    for relative in source_directories:
        source_paths.extend(
            path
            for path in (source_root / relative).rglob("*")
            if path.suffix in {".ts", ".tsx", ".css"} and ".test." not in path.name
        )
    result["frontend_source_sha256"] = {
        path.relative_to(source_root).as_posix(): hashlib.sha256(
            path.read_text(encoding="utf-8").encode("utf-8")
        ).hexdigest()
        for path in sorted(source_paths)
    }
    result["frontend_source_hash_encoding"] = "UTF-8 with LF line endings"
    (
        EVIDENCE / ("admin-review-browser-proof.json" if ADMIN_UI else "review-browser-proof.json")
    ).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


def browser_proof(assignment_id: str, invitation_token: str | None = None) -> dict[str, Any]:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        errors: list[str] = []
        pending: set[str] = set()
        page.on("request", lambda request: pending.add(request.url))
        page.on("requestfinished", lambda request: pending.discard(request.url))
        page.on("requestfailed", lambda request: pending.discard(request.url))
        requests: list[dict[str, Any]] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "response",
            lambda response: (
                requests.append(
                    {
                        "method": response.request.method,
                        "path": response.url.split(ORIGIN)[-1],
                        "status": response.status,
                    }
                )
                if "/v1/conversation/review-assignments/" in response.url
                else None
            ),
        )
        try:
            if invitation_token:
                # Script runs before hydration; navigation itself has no bearer in its URL.
                page.add_init_script(
                    "if (location.pathname === '/sales-xray/review/invite') {"
                    "history.replaceState(history.state, '', location.pathname + '#token=' + "
                    + json.dumps(invitation_token)
                    + ");}"
                )
                with page.expect_response(
                    lambda response: response.url.endswith("/review-invitations/accept")
                ) as accepted:
                    page.goto(f"{ORIGIN}/sales-xray/review/invite", wait_until="domcontentloaded")
                assert accepted.value.status == 201
                assignment_id = accepted.value.json()["id"]
                page.wait_for_url(f"{ORIGIN}/sales-xray/review/{assignment_id}")
                assert "#" not in page.url
                assert not page.evaluate(
                    "token => [localStorage, sessionStorage].some(storage => "
                    "Object.values(storage).some(value => String(value).includes(token)))",
                    invitation_token,
                )
            page.goto(
                f"{ORIGIN}/sales-xray/review/{assignment_id}",
                wait_until="domcontentloaded",
                timeout=60000,
            )
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except PlaywrightTimeout:
                (EVIDENCE / "pending-network.json").write_text(
                    json.dumps(sorted(pending), indent=2), encoding="utf-8"
                )
            page.get_by_role("heading", name="Conversation review", exact=True).wait_for()
            page.get_by_text("No feedback has been saved for this assignment yet.").wait_for(
                timeout=15000
            )
            assert page.get_by_role("button", name="Save feedback", exact=True).is_disabled()
            assert (
                page.get_by_text("Report reference and technical details", exact=True)
                .locator("..")
                .get_attribute("open")
                is None
            )
            page.screenshot(path=str(EVIDENCE / "review-ready-desktop.png"), full_page=True)
            page.get_by_label("Feedback", exact=True).fill(
                "Browser proof: the cited moment supports this observation."
            )
            dialogs: list[str] = []

            def cancel_navigation(dialog):
                dialogs.append(dialog.message)
                dialog.dismiss()

            page.on("dialog", cancel_navigation)
            current_url = page.url
            page.locator('a[href="/home"]').first.click()
            assert len(dialogs) == 1 and page.url == current_url
            page.get_by_role("heading", name="Conversation review", exact=True).click()
            page.keyboard.press("g")
            page.keyboard.press("h")
            assert len(dialogs) == 2 and page.url == current_url
            assert (
                page.get_by_label("Feedback", exact=True).input_value().startswith("Browser proof:")
            )
            page.remove_listener("dialog", cancel_navigation)
            page.get_by_label("Confidence", exact=True).select_option("high")
            page.get_by_role("button", name="Developer", exact=False).click()
            page.get_by_label("Suggest a specific correction", exact=True).check()
            page.get_by_label("Correction area", exact=True).select_option("transcript")
            page.get_by_label("Current observation", exact=True).fill("Current transcript wording.")
            page.get_by_label("Suggested correction", exact=True).fill(
                "Proposed transcript wording."
            )
            page.get_by_label("Reason", exact=True).fill(
                "The selected source span supports the correction."
            )
            with page.expect_response(
                lambda response: (
                    "/submissions" in response.url and response.request.method == "POST"
                )
            ) as saved:
                page.get_by_role("button", name="Save feedback", exact=True).click()
            assert saved.value.status == 201
            body = saved.value.json()
            assert body["author_person_id"] == body["reviewer_person_id"]
            assert body["lens"] == "technical" and body["lane"] == "signal"
            assert body["proposed_correction"]["target_layer"] == "transcript"
            page.get_by_text("Feedback saved.", exact=True).wait_for()
            history = page.get_by_role("region", name="Review history", exact=True)
            history.get_by_text(
                "Browser proof: the cited moment supports this observation.", exact=True
            ).wait_for()
            page.screenshot(path=str(EVIDENCE / "review-saved-desktop.png"), full_page=True)
            # A real identical HTTP replay must return the same durable submission.
            replay = page.request.post(
                f"{ORIGIN}/v1/conversation/review-assignments/{assignment_id}/submissions",
                headers={"Origin": ORIGIN, "Content-Type": "application/json"},
                data=saved.value.request.post_data,
            )
            assert replay.status == 201 and replay.json()["id"] == body["id"]
            page.reload(wait_until="domcontentloaded")
            history.get_by_text(
                "Browser proof: the cited moment supports this observation.", exact=True
            ).wait_for()
            history.get_by_text(body["id"], exact=True).wait_for()
            assert page.get_by_label("Feedback", exact=True).input_value() == ""
            assert history.locator("article").count() == 1
            page.screenshot(path=str(EVIDENCE / "review-reloaded-desktop.png"), full_page=True)
            # Actual private source range read, using synthetic one-second WAV.
            audio = page.request.get(
                f"{ORIGIN}/v1/conversation/review-assignments/{assignment_id}/source",
                headers={"Range": "bytes=0-127"},
            )
            assert audio.status == 206 and len(audio.body()) == 128
            dimensions = []
            for width in [390, 320]:
                page.set_viewport_size({"width": width, "height": 900})
                page.wait_for_function(
                    "document.querySelector('main').getBoundingClientRect().width"
                    " >= window.innerWidth - 1"
                )
                page.wait_for_function(
                    "document.querySelector('[aria-labelledby=assigned-review-title]')"
                    ".getBoundingClientRect().width >= window.innerWidth - 80"
                )
                page.screenshot(path=str(EVIDENCE / f"review-reloaded-{width}.png"), full_page=True)
                overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
                assert not overflow, f"Horizontal overflow at {width}"
                dimensions.append({"width": width, "horizontal_overflow": overflow})
            for width in [1440, 320]:
                page.set_viewport_size({"width": width, "height": 1000})
                if width < 1024:
                    page.wait_for_function(
                        "document.querySelector('[aria-labelledby=assigned-review-title]')"
                        ".getBoundingClientRect().width >= window.innerWidth - 80"
                    )
                page.evaluate('document.documentElement.dataset.theme = "dark"')
                page.screenshot(path=str(EVIDENCE / f"review-dark-{width}.png"), full_page=True)
                assert not page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
            assert not errors, errors
            return {
                "status": "passed",
                "assignment_id": assignment_id,
                "invitation_accept_status": 201 if invitation_token else None,
                "invitation_token_persisted": False if invitation_token else None,
                "origin": ORIGIN,
                "source": "synthetic local WAV",
                "save_status": saved.value.status,
                "replay_same_id": True,
                "cancelled_dirty_navigation": ["sidebar dashboard link", "G H keyboard shortcut"],
                "dark_viewports": [1440, 320],
                "reload_history_count": 1,
                "audio_range_status": audio.status,
                "viewports": dimensions,
                "page_errors": errors,
                "review_requests": requests,
            }
        except BaseException:
            page.screenshot(path=str(EVIDENCE / "review-browser-failed.png"), full_page=True)
            (EVIDENCE / "review-browser-failed.json").write_text(
                json.dumps(
                    {
                        "errors": errors,
                        "requests": requests,
                        "page_text": page.locator("body").inner_text(),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            raise
        finally:
            browser.close()


def admin_browser_proof(run_id: str, reviewer_id: str, expiry: str) -> dict[str, Any]:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1100})

        def forward_api(route):
            url = urlsplit(route.request.url)
            response = route.fetch(
                url=ORIGIN + url.path + ("?" + url.query if url.query else ""), max_redirects=0
            )
            route.fulfill(response=response)

        page.route("**/v1/**", forward_api)
        errors: list[str] = []
        responses: list[dict[str, Any]] = []
        page.on(
            "response",
            lambda response: responses.append({"url": response.url, "status": response.status}),
        )
        page.on(
            "console",
            lambda message: errors.append(message.text) if message.type == "error" else None,
        )
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            page.goto(f"{UPSTREAM}/sales-xray/review", wait_until="networkidle")
            page.bring_to_front()
            page.get_by_text("Advanced: assign an existing reviewer by ID", exact=True).click()
            page.get_by_role("heading", name="Create a reviewer assignment", exact=True).wait_for()
            page.locator("#review-run-id").fill(run_id)
            page.get_by_label("Reviewer person ID", exact=False).fill(reviewer_id)
            calendar_expiry = page.evaluate(
                "epoch => {const d = new Date(Number(epoch)*1000); "
                "return new Date(d.getTime()-d.getTimezoneOffset()*60000)"
                ".toISOString().slice(0,16);}",
                expiry,
            )
            page.locator("#review-expiry").fill(calendar_expiry)
            with page.expect_response(
                lambda response: (
                    response.request.method == "POST"
                    and response.url.endswith("/review-assignments")
                )
            ) as created:
                page.get_by_role("button", name="Create assignment", exact=True).click()
            assert created.value.status == 201, created.value.text()
            assignment = created.value.json()
            assert (
                assignment["reviewer_person_id"] == reviewer_id and assignment["run_id"] == run_id
            )
            page.get_by_text("Assignment created and confirmed.", exact=True).wait_for()
            invitation_proof = None
            if INVITATIONS:
                panel = page.get_by_role("region", name="Invite a reviewer")
                panel.locator("#invitation-run-id").fill(run_id)
                panel.get_by_label("Invited email", exact=True).fill(
                    "Browser.Reviewer@example.test"
                )
                panel.locator("#invitation-expiry").fill(calendar_expiry)
                with page.expect_response(
                    lambda response: (
                        response.request.method == "POST"
                        and response.url.endswith("/review-invitations")
                    )
                ) as invited:
                    panel.get_by_role("button", name="Send invitation", exact=True).click()
                assert invited.value.status == 201
                invitation = invited.value.json()
                panel.get_by_text("Invitation queued for delivery.", exact=True).wait_for()
                page.screenshot(
                    path=str(EVIDENCE / "admin-invitation-queued-desktop.png"), full_page=True
                )
                page.reload(wait_until="networkidle")
                panel.get_by_text(
                    "Invitations you send during this visit will appear here.", exact=False
                ).wait_for()
                panel.get_by_text("Revoke an earlier invitation by ID", exact=True).click()
                panel.get_by_label("Revoke a known invitation", exact=False).fill(invitation["id"])
                with page.expect_response(
                    lambda response: (
                        response.request.method == "POST"
                        and response.url.endswith(f"/review-invitations/{invitation['id']}/revoke")
                    )
                ) as invitation_revoked:
                    panel.get_by_role("button", name="Revoke known invitation", exact=True).click()
                assert invitation_revoked.value.status == 200
                panel.get_by_text("Invitation revoked.", exact=False).wait_for()
                invitation_proof = {"create_status": 201, "revoke_after_reload_status": 200}
                for width in [390, 320]:
                    page.set_viewport_size({"width": width, "height": 1000})
                    page.screenshot(
                        path=str(EVIDENCE / f"admin-invitation-revoked-{width}.png"), full_page=True
                    )
                    assert not page.evaluate(
                        "document.documentElement.scrollWidth > window.innerWidth"
                    )
                page.set_viewport_size({"width": 1440, "height": 1100})
            page.screenshot(path=str(EVIDENCE / "admin-review-created-desktop.png"), full_page=True)
            page.reload(wait_until="networkidle")
            assignment_link = page.locator(f'a[href="/sales-xray/review/{assignment["id"]}"]')
            assignment_link.first.wait_for()
            assignment_link.first.click()
            page.get_by_role("button", name="Revoke assignment", exact=True).wait_for()
            academy_link = page.get_by_role("link", name="Open in Academy")
            assert academy_link.get_attribute("href") == (
                f"http://learner.localhost:3100/sales-xray/review/{assignment['id']}"
            )
            assert "PREVIEW DATA" not in page.locator("body").inner_text()
            assert "AUDIT EVENT: NONE" not in page.locator("body").inner_text()
            page.screenshot(path=str(EVIDENCE / "admin-review-detail-desktop.png"), full_page=True)
            page.get_by_role("button", name="Revoke assignment", exact=True).click()
            with page.expect_response(
                lambda response: (
                    response.request.method == "POST" and response.url.endswith("/revoke")
                )
            ) as revoked:
                page.get_by_role("button", name="Confirm revoke", exact=True).click()
            assert revoked.value.status == 200
            assert revoked.value.json()["state"] == "revoked"
            page.reload(wait_until="networkidle")
            page.get_by_text("Revoked", exact=True).first.wait_for()
            page.screenshot(path=str(EVIDENCE / "admin-review-revoked-desktop.png"), full_page=True)
            dimensions = []
            for width in [390, 320]:
                page.set_viewport_size({"width": width, "height": 900})
                page.screenshot(
                    path=str(EVIDENCE / f"admin-review-revoked-{width}.png"), full_page=True
                )
                overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
                assert not overflow
                dimensions.append({"width": width, "horizontal_overflow": overflow})
            assert not errors, errors
            return {
                "status": "passed",
                "origin": UPSTREAM,
                "frontend": "Next development server with local preview enabled",
                "transport": "Browser route forwards API requests to actual loopback HTTP server",
                "create_status": 201,
                "invitation": invitation_proof,
                "revoke_status": 200,
                "reloaded_state": "revoked",
                "viewports": dimensions,
                "page_errors": errors,
            }
        except BaseException:
            page.screenshot(path=str(EVIDENCE / "admin-review-browser-failed.png"), full_page=True)
            (EVIDENCE / "admin-review-browser-failed.json").write_text(
                json.dumps(
                    {
                        "errors": errors,
                        "responses": responses,
                        "page_text": page.locator("body").inner_text(),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            raise
        finally:
            browser.close()
