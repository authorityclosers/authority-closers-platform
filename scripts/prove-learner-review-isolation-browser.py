"""Prove the retired reviewer paths stay outside the built learner UI.

Uses only a loopback Next server and synthetic fragment material. No account,
invitation, provider, or production state is created.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright


def main() -> None:
    origin = os.environ.get("LEARNER_ISOLATION_ORIGIN", "http://127.0.0.1:3115")
    parsed = urlsplit(origin)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("This proof accepts only an explicit loopback HTTP origin.")
    evidence = Path(os.environ["LEARNER_ISOLATION_EVIDENCE"])
    evidence.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parent.parent
    sources = (
        "apps/learner-web/app/components/login-form.tsx",
        "apps/learner-web/app/components/password-auth-forms.tsx",
        "apps/learner-web/app/components/site-shell.tsx",
        "apps/learner-web/app/sales-xray/review/invite/page.tsx",
        "apps/learner-web/app/sales-xray/review/[assignmentId]/page.tsx",
    )
    result: dict[str, object] = {
        "scope": "Built learner UI only; reviewer login and deployment remain pending",
        "source_sha256": {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in sources
        },
        "legacy_routes": [],
        "learner_auth": [],
    }
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        review_requests: list[str] = []
        page.on(
            "request",
            lambda request: (
                review_requests.append(urlsplit(request.url).path)
                if "/v1/conversation/review" in request.url or "/v1/reviewer/" in request.url
                else None
            ),
        )
        for path in (
            "/sales-xray/review/invite",
            "/sales-xray/review/11111111-1111-4111-8111-111111111111",
        ):
            response = page.goto(origin + path, wait_until="networkidle")
            assert response is not None and response.status == 404
            assert page.get_by_role("heading", name="Conversation review", exact=True).count() == 0
            assert page.get_by_role("heading", name="Review invitation", exact=True).count() == 0
            result["legacy_routes"].append({"path": path, "status": response.status})
        page.screenshot(path=str(evidence / "legacy-review-404.png"))
        fragment = "#review_invitation=synthetic-fixture-" + "x" * 48
        for path in ("/login", "/register", "/forgot-password", "/verify-email"):
            response = page.goto(origin + path + fragment, wait_until="networkidle")
            assert response is not None and response.status == 200
            assert page.locator('a[href*="review"]').count() == 0
            body = page.locator("body").inner_text().lower()
            for text in ("continue to review", "open review", "return to invitation"):
                assert text not in body
            result["learner_auth"].append({"path": path, "review_links": 0})
            if path == "/login":
                page.screenshot(path=str(evidence / "learner-sign-in.png"))
        assert review_requests == []
        result["review_api_requests"] = 0
        browser.close()
    (evidence / "proof.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print("PASS: legacy review URLs return 404; learner auth has no review links or API calls.")


if __name__ == "__main__":
    main()
