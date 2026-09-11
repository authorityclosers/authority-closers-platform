"""Exercise normal local sign-in and a real photo save on synthetic accounts.

No SQL, remote traffic, existing browser sessions, or saved credentials in output.
The only profile mutation is an existing brand icon on learner@ac.localhost.
"""

from __future__ import annotations

import json
import os
import traceback
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import Route, expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SURFACES = (
    ("learner", 3100, "learner@ac.localhost", None),
    ("admin", 3101, "admin@ac.localhost", "operations_tenant_id"),
    ("coach", 3102, "coach@ac.localhost", "academy_tenant_id"),
)


def local_route(expected: str):
    def local_only(route: Route) -> None:
        parsed = urlsplit(route.request.url)
        if f"{parsed.scheme}://{parsed.netloc}" != expected:
            route.abort()
        else:
            route.continue_()

    return local_only


def main() -> int:
    password = os.environ["AC_LOCAL_BROWSER_TEST_PASSWORD"]
    sandbox = json.loads((ROOT / ".tmp/local-platform/sandbox.json").read_text())
    output = (
        ROOT
        / ".tmp/local-platform/new/profile-photo"
        / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    )
    output.mkdir(parents=True, exist_ok=False)
    proof: dict[str, object] = {"status": "incomplete", "signins": [], "avatar_requests": []}
    stage = "sign-in"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            learner_page = learner_context = None
            for name, port, email, tenant_key in SURFACES:
                stage = f"sign-in-{name}"
                origin = f"http://{name}.localhost:{port}"
                context = browser.new_context(viewport={"width": 390, "height": 844})

                context.route("**/*", local_route(origin))
                page = context.new_page()
                page.goto(origin + "/login", wait_until="domcontentloaded")
                expect(page.get_by_label("Email address")).to_be_enabled(timeout=30000)
                page.get_by_label("Email address").fill(email)
                page.get_by_label("Password", exact=True).fill(password)
                if tenant_key:
                    page.get_by_label("Local tenant ID", exact=True).fill(sandbox[tenant_key])
                page.get_by_role("button", name="Sign in", exact=True).click()
                page.wait_for_url(
                    lambda url, expected=origin: (
                        url.startswith(expected + "/") and urlsplit(url).path != "/login"
                    ),
                    timeout=30000,
                )
                me = context.request.get(origin + "/v1/me", max_redirects=0)
                proof["last_identity_http_status"] = me.status
                assert me.status == 200
                assert me.json()["email"] == email
                proof["signins"].append({"surface": name, "authenticated": True})
                if name == "learner":
                    learner_context, learner_page = context, page
                else:
                    context.close()

            assert learner_page is not None and learner_context is not None
            page, context = learner_page, learner_context
            origin = "http://learner.localhost:3100"
            stage = "avatar-before"
            before = context.request.get(origin + "/v1/profile/avatar").json()["avatar"]
            proof["previous_photo_present"] = before is not None

            def avatar_response(response) -> None:
                path = urlsplit(response.url).path
                if "/profile/avatar" in path or "/local-avatar-upload/" in path:
                    # Never record signed upload/read URLs, headers, or body content.
                    endpoint = "bytes" if "/local-avatar-upload/" in path else "profile"
                    proof["avatar_requests"].append(
                        {
                            "endpoint": endpoint,
                            "method": response.request.method,
                            "status": response.status,
                        }
                    )

            page.on("response", avatar_response)
            page.goto(origin + "/profile", wait_until="domcontentloaded")
            page.get_by_role("button", name="Change photo", exact=True).click(timeout=30000)
            dialog = page.get_by_role("dialog")
            source = ROOT / "apps/learner-web/public/brand/closers-academy-v0.1/icon-512.png"
            dialog.locator('input[type="file"]').set_input_files(str(source))
            save = dialog.get_by_role("button", name="Save photo", exact=True)
            expect(save).to_be_enabled(timeout=10000)
            page.screenshot(path=str(output / "preview.png"))
            stage = "avatar-save"
            save.click()
            expect(page.get_by_text("Profile photo updated.", exact=True)).to_be_visible(
                timeout=60000
            )
            after_response = context.request.get(origin + "/v1/profile/avatar")
            assert after_response.status == 200
            after = after_response.json()["avatar"]
            assert after and after["state"] == "ready"
            assert before is None or after["version_id"] != before["version_id"]
            proof["new_version_ready"] = True
            stage = "avatar-reload"
            page.reload(wait_until="domcontentloaded")
            expect(page.get_by_role("button", name="Change photo", exact=True)).to_be_visible(
                timeout=30000
            )
            reread = context.request.get(origin + "/v1/profile/avatar").json()["avatar"]
            assert reread["version_id"] == after["version_id"]
            proof["persisted_after_reload"] = True
            photo = page.locator('section[aria-labelledby="identity-card-title"] img')
            expect(photo).to_be_visible()
            expect(photo).to_have_js_property("complete", True)
            assert photo.evaluate("image => image.naturalWidth > 0 && image.naturalHeight > 0")
            proof["image_decoded_after_reload"] = True
            page.screenshot(path=str(output / "saved-reloaded.png"))
            proof["status"] = "passed"
        except Exception as error:
            proof["error_type"] = type(error).__name__
            proof["script_line"] = next(
                (
                    frame.lineno
                    for frame in reversed(traceback.extract_tb(error.__traceback__))
                    if Path(frame.filename) == Path(__file__)
                ),
                None,
            )
            proof["failed_stage"] = stage
            proof["status"] = "failed"
            # No login/credential screenshots or arbitrary server exception strings.
            if stage.startswith("avatar") and learner_page is not None:
                learner_page.screenshot(path=str(output / "failed-avatar.png"))
        finally:
            browser.close()
    (output / "proof.json").write_text(json.dumps(proof, indent=2), encoding="utf-8")
    print(json.dumps({"status": proof["status"], "stage": stage, "evidence": str(output)}))
    return 0 if proof["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
