#!/usr/bin/env python3
"""Browser QA operator: upload the known fictional clip, verify Report and call Coaching."""

from __future__ import annotations

import json
import os
import sys
from uuid import UUID

import httpx

from ac_platform.application.asyncio_runtime import run_async
from ac_platform.conversation_intelligence.account_smoke import (
    ORIGINS,
    SmokeFailure,
    account_smoke,
)
from ac_platform.conversation_intelligence.processing_cli import _Parser


async def smoke(args):
    if args.environment == "production" and not args.allow_production:
        raise ValueError("Explicit production run required.")
    async with httpx.AsyncClient(
        base_url=ORIGINS[args.environment], timeout=30, follow_redirects=False
    ) as client:
        result = await account_smoke(
            client,
            environment=args.environment,
            email=os.environ.get("AC_SMOKE_EMAIL", ""),
            password=os.environ.get("AC_SMOKE_PASSWORD", ""),
            timeout_seconds=args.timeout_seconds,
        )
        # The HTTP checks alone cannot certify the deployed interface.
        if args.browser:
            from playwright.async_api import async_playwright

            async with async_playwright() as runtime:
                browser = await runtime.chromium.launch(headless=True)
                try:
                    context = await browser.new_context(viewport={"width": 1440, "height": 900})
                    await context.add_cookies(
                        [
                            {
                                "name": cookie.name,
                                "value": cookie.value,
                                "domain": cookie.domain,
                                "path": cookie.path,
                                "secure": cookie.secure,
                                "httpOnly": True,
                            }
                            for cookie in client.cookies.jar
                        ]
                    )
                    page = await context.new_page()
                    errors = []
                    page.on("pageerror", lambda error: errors.append(True))
                    response = await page.goto(
                        f"{ORIGINS[args.environment]}/analysis/calls/{result['submission_id']}",
                        wait_until="networkidle",
                        timeout=60_000,
                    )
                    if response is None or response.status != 200:
                        raise ValueError("Report page unavailable.")
                    await page.locator("[data-report-modes]").wait_for(
                        state="visible", timeout=30_000
                    )
                    control = page.get_by_title("Coaching view", exact=True)
                    await control.click()
                    await page.locator('[data-call-coaching][data-state="ready"]').wait_for(
                        state="visible", timeout=30_000
                    )
                    if errors:
                        raise ValueError("Report page error.")
                    result["browser_report_and_coaching_visible"] = True
                except Exception:
                    raise SmokeFailure(
                        "qa_browser_unavailable", submission_id=UUID(result["submission_id"])
                    ) from None
                finally:
                    await browser.close()
        return result


def main(argv=None):
    parser = _Parser(description=__doc__, allow_abbrev=False)
    parser.add_argument(
        "--environment", required=True, choices=("development", "staging", "production")
    )
    parser.add_argument("--allow-production", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--browser", action="store_true")
    try:
        result = run_async(smoke(parser.parse_args(argv)))
    except SmokeFailure as error:
        print(
            json.dumps(
                {
                    "schema": "ac.sales-xray.qa-account-smoke/1",
                    "ok": False,
                    "failure_code": error.code,
                    "submission_id": error.submission_id,
                },
                sort_keys=True,
            )
        )
        return 1
    except Exception:
        # Never echo request/response bodies, credentials, cookies or browser errors.
        print(
            "QA smoke failed; inspect the run through the approved QA workspace.", file=sys.stderr
        )
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
