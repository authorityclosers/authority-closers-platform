"""Loopback reviewer UI proof with real mailbox jobs, HTTP sessions and PostgreSQL.

The compiled Next app runs independently on REVIEWER_UI_UPSTREAM. Browser-only
DNS maps the canonical test host to loopback TLS. The Next process independently
maps its internal API transport to loopback; production middleware, canonical
session resolution and authorization remain intact. Mail uses a fake adapter.
Synthetic source only. No browser token or credential is written to evidence.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections.abc import Callable, Coroutine
from contextlib import suppress
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import uvicorn
from fastapi import Request, Response
from playwright.async_api import TimeoutError as BrowserTimeout
from playwright.async_api import async_playwright
from sqlalchemy import func, select

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.models import ConversationReviewFeedback
from tests.database.reviewer_http_support import (
    account_token,
    app_for,
    deliver,
    mail_worker,
    settings_for,
)
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_reviews_postgresql import (
    _build_report_case,
)
from tests.database.test_conversation_reviews_postgresql import (
    postgres_harness as postgres_harness,
)

ORIGIN = "https://admin-staging.authorityclosers.com"
UPSTREAM = os.environ.get("REVIEWER_UI_UPSTREAM", "http://127.0.0.1:3192")
EVIDENCE = Path(os.environ["REVIEWER_UI_EVIDENCE_DIR"])
if urlsplit(UPSTREAM).hostname != "127.0.0.1":
    raise ValueError("Reviewer proof requires a loopback frontend")


class SecureTestSettings(Settings):
    @property
    def secure_cookies(self) -> bool:
        return True


def test_reviewer_browser(postgres_harness: Any, tmp_path: Path) -> None:  # noqa: F811
    EVIDENCE.mkdir(parents=True, exist_ok=True)

    async def exercise() -> None:
        case = await _build_report_case(postgres_harness, tmp_path)
        settings = SecureTestSettings(
            **{
                **settings_for(case, origin=ORIGIN).model_dump(),
                "session_cookie_name": "__Host-ac_session",
            },
        )
        application = app_for(case, settings)
        worker, provider = mail_worker(case, settings)
        admin_token = await account_token(case, settings, case.admin_actor.person_id)
        transport = httpx.AsyncClient(base_url=UPSTREAM, timeout=90)

        @application.api_route("/{path:path}", methods=["GET", "HEAD"])
        async def frontend(request: Request, path: str) -> Response:
            if path.startswith("v1/"):
                return Response(status_code=404)
            result = await transport.get(
                "/" + path + ("?" + request.url.query if request.url.query else ""),
                headers={
                    key: value
                    for key, value in request.headers.items()
                    if key.lower()
                    in {
                        "rsc",
                        "next-router-state-tree",
                        "next-router-prefetch",
                        "next-url",
                        "accept",
                        "cookie",
                        "host",
                    }
                },
            )
            return Response(
                result.content,
                status_code=result.status_code,
                headers={
                    key: value
                    for key, value in result.headers.items()
                    if key.lower() in {"content-type", "cache-control", "vary", "location"}
                },
            )

        server = uvicorn.Server(
            uvicorn.Config(
                application,
                host="127.0.0.1",
                port=443,
                ssl_certfile=os.environ["REVIEWER_UI_TLS_CERT"],
                ssl_keyfile=os.environ["REVIEWER_UI_TLS_KEY"],
                log_level="error",
                access_log=False,
            )
        )
        server_task = asyncio.create_task(server.serve())
        internal_server = uvicorn.Server(
            uvicorn.Config(
                application,
                host="127.0.0.1",
                port=8000,
                log_level="error",
                access_log=False,
            )
        )
        internal_task = asyncio.create_task(internal_server.serve())
        backend_loop = asyncio.get_running_loop()

        async def backend_call(coroutine: Coroutine[Any, Any, Any]) -> Any:
            return await asyncio.wrap_future(
                asyncio.run_coroutine_threadsafe(coroutine, backend_loop)
            )

        async def saved_feedback_count() -> int:
            async with case.sessions() as database:
                return int(
                    await database.scalar(select(func.count(ConversationReviewFeedback.id))) or 0
                )

        try:
            for _ in range(100):
                if server.started and internal_server.started:
                    break
                if server_task.done():
                    await server_task
                await asyncio.sleep(0.05)
            assert server.started and internal_server.started

            async def browser_flow() -> None:
                async with async_playwright() as playwright:
                    browser = await playwright.chromium.launch(
                        headless=True,
                        args=[
                            "--host-resolver-rules=MAP "
                            "admin-staging.authorityclosers.com 127.0.0.1",
                            "--no-proxy-server",
                        ],
                    )
                    admin_context = await browser.new_context(
                        viewport={"width": 1440, "height": 1000},
                        ignore_https_errors=True,
                    )
                    await admin_context.add_cookies(
                        [
                            {
                                "name": settings.session_cookie_name,
                                "value": admin_token,
                                "url": ORIGIN,
                                "httpOnly": True,
                                "secure": True,
                                "sameSite": "Lax",
                            }
                        ]
                    )
                    admin = await admin_context.new_page()
                    reviewer_context = await browser.new_context(
                        viewport={"width": 1440, "height": 1100},
                        ignore_https_errors=True,
                    )
                    reviewer = await reviewer_context.new_page()
                    errors: list[str] = []
                    requests: list[dict[str, Any]] = []
                    for page in (admin, reviewer):
                        page.on(
                            "response",
                            lambda response: requests.append(
                                {
                                    "path": urlsplit(response.url).path,
                                    "status": response.status,
                                }
                            ),
                        )
                        page.on(
                            "requestfailed",
                            lambda request: requests.append(
                                {
                                    "path": urlsplit(request.url).path,
                                    "failure": request.failure,
                                }
                            ),
                        )
                    reviewer.on("pageerror", lambda error: errors.append(str(error)))
                    admin.on("pageerror", lambda error: errors.append(str(error)))
                    try:
                        # Real Admin login cookie authorizes the invitation and later history.
                        await admin.goto(
                            f"{ORIGIN}/sales-xray/review",
                            wait_until="domcontentloaded",
                            timeout=90000,
                        )
                        with suppress(BrowserTimeout):
                            await admin.wait_for_load_state("networkidle", timeout=5000)
                        await admin.screenshot(
                            path=str(EVIDENCE / "admin-initial.png"), full_page=True
                        )
                        await asyncio.to_thread(
                            (EVIDENCE / "admin-initial-body.txt").write_text,
                            await admin.locator("body").inner_text(),
                            encoding="utf-8",
                        )
                        diagnostics = {}
                        for api_path in ("/v1/me", "/v1/context", "/v1/me/studio-access"):
                            diagnostics[api_path] = await browser_request(admin, api_path)
                        await asyncio.to_thread(
                            (EVIDENCE / "admin-auth-diagnostic.json").write_text,
                            json.dumps(diagnostics, indent=2),
                            encoding="utf-8",
                        )
                        await admin.get_by_role(
                            "button", name="Send invitation", exact=True
                        ).wait_for()
                        await admin.screenshot(
                            path=str(EVIDENCE / "admin-invitation-ready.png"), full_page=True
                        )
                        email = "browser-reviewer@example.test"
                        await admin.locator("#invitation-run-id").fill(str(case.report_run_id))
                        await admin.get_by_label("Invited email", exact=True).fill(email)
                        expires = await admin.evaluate(
                            "epoch => { const date = new Date(epoch * 1000); return "
                            "new Date(date.getTime() - date.getTimezoneOffset() * 60000)"
                            ".toISOString().slice(0,16); }",
                            int(case.prepared.state.now.timestamp()) + 1800,
                        )
                        await admin.locator("#invitation-expiry").fill(expires)
                        async with admin.expect_response(
                            lambda response: (
                                response.url.endswith("/review-invitations")
                                and response.request.method == "POST"
                            )
                        ) as created:
                            await admin.get_by_role(
                                "button", name="Send invitation", exact=True
                            ).click()
                        creation = await created.value
                        assert creation.status == 201, await creation.text()
                        invitation = await backend_call(
                            deliver(worker, provider, "sales-xray-review-invitation", email)
                        )
                        invite_url = str(invitation.variables["action_link"])
                        invite_token = parse_qs(urlsplit(invite_url).fragment)["token"][0]
                        await reviewer.goto(
                            invite_url, wait_until="domcontentloaded", timeout=90000
                        )
                        await reviewer.get_by_label("Invitation email", exact=True).wait_for()
                        assert "#" not in reviewer.url
                        await reviewer.screenshot(
                            path=str(EVIDENCE / "reviewer-invitation.png"), full_page=True
                        )
                        await reviewer.get_by_label("Invitation email", exact=True).fill(email)
                        async with reviewer.expect_response(
                            lambda response: response.url.endswith("/auth/request")
                        ) as requested:
                            await reviewer.get_by_role(
                                "button", name="Continue with email", exact=True
                            ).click()
                        assert (await requested.value).status == 202
                        sign_in = await backend_call(
                            deliver(worker, provider, "reviewer-sign-in", email)
                        )
                        sign_in_url = str(sign_in.variables["action_link"])
                        sign_in_token = parse_qs(urlsplit(sign_in_url).fragment)["token"][0]
                        # Browser substitution attempt fails before the genuine consumption.
                        victim = await browser.new_context(ignore_https_errors=True)
                        victim_page = await victim.new_page()
                        await victim_page.goto(
                            f"{ORIGIN}/reviewer/login", wait_until="domcontentloaded"
                        )
                        denied = await victim_page.evaluate(
                            "async token => (await fetch('/v1/reviewer/auth/verify', "
                            "{method: 'POST', headers: {'content-type':'application/json'}, "
                            "body:JSON.stringify({token})})).status",
                            sign_in_token,
                        )
                        assert denied == 401
                        await victim.close()
                        async with reviewer.expect_response(
                            lambda response: response.url.endswith("/auth/verify")
                        ) as verified:
                            await reviewer.goto(
                                sign_in_url, wait_until="domcontentloaded", timeout=90000
                            )
                        verification = await verified.value
                        assert verification.status == 200
                        assignment_id = (await verification.json())["assignment_id"]
                        await reviewer.wait_for_url(f"{ORIGIN}/reviewer/review/{assignment_id}")
                        await reviewer.get_by_role(
                            "heading", name="Review the conversation", exact=True
                        ).wait_for()
                        await reviewer.get_by_text(
                            "No feedback has been saved for this assignment yet."
                        ).wait_for()
                        assert not await reviewer.evaluate(
                            "tokens => [localStorage, sessionStorage].some(storage => "
                            "Object.values(storage).some(value => "
                            "tokens.some(token => String(value).includes(token))))",
                            [invite_token, sign_in_token],
                        )
                        assert "#" not in reviewer.url
                        assert (
                            await reviewer.get_by_role(
                                "link", name="Reviewer workspace home"
                            ).count()
                            == 1
                        )
                        assert (
                            await reviewer.get_by_role("link", name="People", exact=True).count()
                            == 0
                        )
                        await reviewer.screenshot(
                            path=str(EVIDENCE / "reviewer-ready-desktop.png"), full_page=True
                        )
                        await reviewer.get_by_label("Feedback", exact=True).fill(
                            "Discard protection proof"
                        )
                        dialogs: list[str] = []

                        async def stay(dialog: Any) -> None:
                            dialogs.append(dialog.message)
                            await dialog.dismiss()

                        reviewer.on("dialog", stay)
                        await reviewer.get_by_role("link", name="Reviewer workspace home").click()
                        assert len(dialogs) == 1 and reviewer.url.endswith(assignment_id)
                        await reviewer.get_by_role("button", name="Sign out", exact=True).click()
                        assert len(dialogs) == 2 and reviewer.url.endswith(assignment_id)
                        reviewer.remove_listener("dialog", stay)
                        saved_ids: list[str] = []
                        for lens, button in (
                            ("sales", "Sales expert"),
                            ("technical", "Developer"),
                            ("ux", "Experience reviewer"),
                        ):
                            if saved_ids:
                                await reviewer.get_by_role(
                                    "button", name="Add another review", exact=True
                                ).click()
                            await reviewer.get_by_role("button", name=button, exact=False).click()
                            await reviewer.get_by_label("Feedback", exact=True).fill(
                                f"Browser {lens} feedback: "
                                "the cited source supports this observation."
                            )
                            await reviewer.get_by_label("Confidence", exact=True).select_option(
                                "high"
                            )
                            async with reviewer.expect_response(
                                lambda response: (
                                    response.url.endswith("/submissions")
                                    and response.request.method == "POST"
                                )
                            ) as saved:
                                await reviewer.get_by_role(
                                    "button", name="Save feedback", exact=True
                                ).click()
                            result = await saved.value
                            assert result.status == 201
                            payload = await result.json()
                            assert payload["lens"] == lens
                            saved_ids.append(payload["id"])
                            await reviewer.get_by_text("Feedback saved.", exact=True).wait_for()
                        await reviewer.reload(wait_until="domcontentloaded")
                        history = reviewer.get_by_role("region", name="Review history", exact=True)
                        await history.locator("article").nth(2).wait_for()
                        assert await history.locator("article").count() == 3
                        for saved_id in saved_ids:
                            await history.get_by_text(saved_id, exact=True).wait_for()
                        audio = await browser_request(
                            reviewer,
                            f"/v1/reviewer/review-assignments/{assignment_id}/source",
                            headers={"Range": "bytes=0-127"},
                            binary=True,
                        )
                        assert audio["status"] == 206 and audio["size"] == 128
                        # Browser audio element itself must be able to decode/play the source.
                        audio_element = reviewer.locator("audio").first
                        await audio_element.evaluate(
                            "async audio => { await audio.play(); audio.pause(); }"
                        )
                        for width in (1440, 390, 320):
                            await reviewer.set_viewport_size({"width": width, "height": 1000})
                            await reviewer.screenshot(
                                path=str(EVIDENCE / f"reviewer-saved-{width}.png"), full_page=True
                            )
                            overflow = await reviewer.evaluate(
                                """() => ({width: innerWidth,
                                scrollWidth: document.documentElement.scrollWidth,
                                elements: [...document.querySelectorAll('body *')]
                                  .filter(element =>
                                    element.getBoundingClientRect().right > innerWidth)
                                  .map(element => ({tag: element.tagName,
                                    className: element.className,
                                    right: element.getBoundingClientRect().right,
                                    text: (element.textContent ?? '').slice(0, 120)}))})"""
                            )
                            await asyncio.to_thread(
                                (EVIDENCE / f"reviewer-overflow-{width}.json").write_text,
                                json.dumps(overflow, indent=2),
                                encoding="utf-8",
                            )
                            assert overflow["scrollWidth"] <= width, overflow
                        await admin.goto(
                            f"{ORIGIN}/sales-xray/review/{assignment_id}",
                            wait_until="domcontentloaded",
                            timeout=90000,
                        )
                        # Unrelated Admin links may keep prefetching routes outside
                        # this fixture. Verify concrete controls and API responses.
                        with suppress(BrowserTimeout):
                            await admin.wait_for_load_state("networkidle", timeout=5000)
                        await admin.screenshot(
                            path=str(EVIDENCE / "admin-initial.png"), full_page=True
                        )
                        await asyncio.to_thread(
                            (EVIDENCE / "admin-initial-body.txt").write_text,
                            await admin.locator("body").inner_text(),
                            encoding="utf-8",
                        )
                        for lens in ("sales", "technical", "ux"):
                            await admin.get_by_text(
                                f"Browser {lens} feedback: "
                                "the cited source supports this observation.",
                                exact=True,
                            ).wait_for()
                        await admin.screenshot(
                            path=str(EVIDENCE / "admin-three-lens-feedback.png"), full_page=True
                        )
                        revoked = await browser_request(
                            admin,
                            f"/v1/admin/conversation/review-assignments/{assignment_id}/revoke",
                            method="POST",
                            headers={"Origin": ORIGIN, "Idempotency-Key": "browser-revoke"},
                        )
                        assert revoked["status"] == 200
                        await reviewer.reload(wait_until="domcontentloaded")
                        await reviewer.get_by_role(
                            "heading", name="Review unavailable", exact=True
                        ).wait_for()
                        assert await reviewer.locator("audio").count() == 0
                        await reviewer.screenshot(
                            path=str(EVIDENCE / "reviewer-revoked-320.png"), full_page=True
                        )
                        async with reviewer.expect_response(
                            lambda response: response.url.endswith("/auth/logout")
                        ) as signed_out:
                            await reviewer.get_by_role(
                                "button", name="Sign out", exact=True
                            ).click()
                        assert (await signed_out.value).status == 204
                        assert (await browser_request(reviewer, "/v1/reviewer/me"))["status"] == 401
                        assert (await browser_request(admin, "/v1/me"))["status"] == 200
                        assert not errors, errors
                        count = await backend_call(saved_feedback_count())
                        assert count == 3
                        receipt = {
                            "status": "passed",
                            "synthetic_source": True,
                            "authentication": "real account and reviewer session resolvers",
                            "email": "actual outbox/worker, fake delivery adapter",
                            "frontend": "compiled production Next build and auth middleware",
                            "browser_substitution_denied": True,
                            "dirty_navigation_guard": True,
                            "feedback_count": count,
                            "lenses": ["sales", "technical", "ux"],
                            "admin_saved_feedback_visible": True,
                            "revocation_denies_source": True,
                            "source_range_status": 206,
                            "audio_element_played": True,
                            "widths_without_overflow": [1440, 390, 320],
                            "page_errors": errors,
                        }
                        await asyncio.to_thread(write_receipt, receipt)
                    finally:
                        await asyncio.to_thread(
                            (EVIDENCE / "browser-network.json").write_text,
                            json.dumps({"errors": errors, "requests": requests}, indent=2),
                            encoding="utf-8",
                        )
                        await browser.close()

            await asyncio.to_thread(run_browser_loop, browser_flow)
        finally:
            server.should_exit = True
            internal_server.should_exit = True
            await server_task
            await internal_task
            await transport.aclose()
            await case.engine.dispose()

    run(exercise())


def run_browser_loop(browser_flow: Callable[[], Coroutine[Any, Any, None]]) -> None:
    # psycopg requires a Selector loop on Windows; Playwright's subprocess driver
    # requires a Proactor loop. Keep browser IO in its own thread/loop, with all
    # database work explicitly marshalled back to the backend's Selector loop.
    factory = asyncio.ProactorEventLoop if os.name == "nt" else asyncio.new_event_loop
    with asyncio.Runner(loop_factory=factory) as runner:
        runner.run(browser_flow())


async def browser_request(
    page: Any,
    path: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    binary: bool = False,
) -> dict[str, Any]:
    # Browser fetch uses the explicit Chromium loopback DNS mapping. Playwright's
    # APIRequestContext has separate Node DNS, so it must not be used for this host.
    return await page.evaluate(
        "async ({path, method, headers, binary}) => {"
        "const response = await fetch(path, {method, headers, cache:'no-store'});"
        "if (binary) return {status:response.status,"
        "size:(await response.arrayBuffer()).byteLength};"
        "const text = await response.text();"
        "return {status:response.status,body:text ? JSON.parse(text):null}; }",
        {"path": path, "method": method, "headers": headers or {}, "binary": binary},
    )


def write_receipt(receipt: dict[str, Any]) -> None:
    source_root = Path(__file__).resolve().parents[1]
    paths = {
        p
        for p in (source_root / "apps/admin-web/app/reviewer").rglob("*")
        if p.suffix in {".ts", ".tsx", ".css"}
    }
    paths.update(
        source_root / relative
        for relative in (
            "apps/admin-web/proxy.ts",
            "apps/admin-web/app/lib/reviewer-server-auth.ts",
            "packages/typescript/operations-web/src/dev-api-proxy.ts",
            "packages/typescript/sales-xray-review-ui/src/assigned-review-form.tsx",
            "packages/typescript/sales-xray-review-ui/src/assigned-review-form.module.css",
            "packages/python/ac_platform/http/reviewer_auth.py",
            "packages/python/ac_platform/identity/reviewer_auth.py",
            "packages/python/ac_platform/worker/reviewer_email.py",
            "packages/python/ac_platform/conversation_intelligence/review_service.py",
            "db/migrations/versions/20260914_0038_reviewer_identity.py",
            "scripts/prove-reviewer-access-browser.py",
        )
    )
    receipt["source_sha256"] = {
        p.relative_to(source_root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(paths)
    }
    receipt["screenshot_sha256"] = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(EVIDENCE.glob("*.png"))
    }
    (EVIDENCE / "reviewer-browser-proof.json").write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
    )
