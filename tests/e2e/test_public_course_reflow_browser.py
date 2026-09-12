"""Public curriculum geometry using the real same-origin catalog response.

Run serially with AC_LEARNER_E2E_BASE_URL. Optional per-width proof is written
before geometry assertions to a fresh AC_PUBLIC_COURSE_REFLOW_EVIDENCE_DIR.
This test does not authenticate, publish fixtures, or submit enrollment.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Browser, Page, Route, expect, sync_playwright  # noqa: E402

FREE_COURSE_SLUG = "authority-closers-free-course"
PUBLIC_PROGRAM_PATH = f"/v1/programs/{FREE_COURSE_SLUG}"
TOLERANCE = 1.0


@pytest.fixture(scope="module")
def public_course_base_url() -> str:
    base_url = os.getenv("AC_LEARNER_E2E_BASE_URL")
    if not base_url:
        pytest.skip("set AC_LEARNER_E2E_BASE_URL to run the browser regression")
    return base_url.rstrip("/")


@pytest.fixture(scope="module")
def public_course_browser(public_course_base_url: str) -> Iterator[Browser]:
    # The base-url dependency skips before allocating a browser when not configured.
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            yield browser
        finally:
            browser.close()


def _curriculum_geometry(page: Page) -> list[dict[str, Any]]:
    return cast(
        list[dict[str, Any]],
        page.evaluate(
            """() => {
              const rect = (element) => {
                const r = element.getBoundingClientRect();
                return {
                  left: r.left, top: r.top, right: r.right, bottom: r.bottom,
                  width: r.width, height: r.height,
                };
              };
              return [...document.querySelectorAll('.public-module-detail-card')].map((card) => {
                const header = card.querySelector('.public-module-card__header');
                const title = card.querySelector('.public-module-card__title');
                const number = card.querySelector('.public-module-card__number');
                const count = card.querySelector('.public-module-card__activity-badge');
                if (!header || !title || !number || !count) {
                  throw new Error('Public curriculum module is missing its title or metadata');
                }
                const headerStyle = getComputedStyle(header);
                const titleStyle = getComputedStyle(title);
                const inset = (name) => parseFloat(headerStyle[name]) || 0;
                const range = document.createRange();
                range.selectNodeContents(title);
                return {
                  titleId: title.id,
                  titleText: title.textContent,
                  numberText: number.textContent,
                  countText: count.textContent,
                  header: rect(header),
                  title: rect(title),
                  number: rect(number),
                  count: rect(count),
                  availableWidth: header.getBoundingClientRect().width
                    - inset('paddingLeft') - inset('paddingRight')
                    - inset('borderLeftWidth') - inset('borderRightWidth'),
                  fontSize: parseFloat(titleStyle.fontSize),
                  lineHeight: parseFloat(titleStyle.lineHeight),
                  textRects: [...range.getClientRects()]
                    .filter((r) => r.width > 0 && r.height > 0)
                    .map((r) => ({
                      left: r.left, top: r.top, right: r.right, bottom: r.bottom,
                      width: r.width, height: r.height,
                    })),
                };
              });
            }"""
        ),
    )


def _overlap(first: dict[str, float], second: dict[str, float]) -> bool:
    return (
        min(first["right"], second["right"]) - max(first["left"], second["left"]) > TOLERANCE
        and min(first["bottom"], second["bottom"]) - max(first["top"], second["top"]) > TOLERANCE
    )


def _contains(outer: dict[str, float], inner: dict[str, float]) -> bool:
    return (
        inner["left"] >= outer["left"] - TOLERANCE
        and inner["right"] <= outer["right"] + TOLERANCE
        and inner["top"] >= outer["top"] - TOLERANCE
        and inner["bottom"] <= outer["bottom"] + TOLERANCE
    )


def _layout_violations(module: dict[str, Any], width: int) -> list[str]:
    errors: list[str] = []
    title, number, count, header = (module[key] for key in ("title", "number", "count", "header"))
    for name in ("title", "number", "count"):
        bounds = module[name]
        if bounds["width"] <= 0 or bounds["height"] <= 0:
            errors.append(f"{name} must be visible")
        if not _contains(header, bounds):
            errors.append(f"{name} escapes the module header")
    for first, second in (("title", "number"), ("title", "count"), ("number", "count")):
        if _overlap(module[first], module[second]):
            errors.append(f"{first} overlaps {second}")
    if not module["textRects"]:
        errors.append("title has no rendered text rectangles")
    for text in module["textRects"]:
        if not _contains(header, text):
            errors.append("title text escapes the module header")
        if _overlap(text, number) or _overlap(text, count):
            errors.append("title text overlaps module metadata")
    if width <= 760:
        if title["width"] < module["availableWidth"] - TOLERANCE:
            errors.append("phone title does not use the available header width")
        if title["top"] < number["bottom"] - TOLERANCE:
            errors.append("phone title must start below the module number")
        if count["top"] < title["bottom"] - TOLERANCE:
            errors.append("phone count must start below the title")
        if module["lineHeight"] < module["fontSize"] * 1.2:
            errors.append("phone title line height is below 1.2 times its font size")
    else:
        if number["right"] > title["left"] + TOLERANCE:
            errors.append("wide module number must remain before the title")
        if title["right"] > count["left"] + TOLERANCE:
            errors.append("wide count must remain after the title")
        if min(number["bottom"], title["bottom"], count["bottom"]) <= max(
            number["top"], title["top"], count["top"]
        ):
            errors.append("wide number, title and count must share a horizontal row")
    return errors


def _write_evidence(page: Page, width: int, proof: dict[str, Any]) -> None:
    evidence_dir = os.getenv("AC_PUBLIC_COURSE_REFLOW_EVIDENCE_DIR")
    if not evidence_dir:
        return
    output_dir = Path(evidence_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    proof_path = output_dir / f"public-course-curriculum-{width}.json"
    screenshot_path = output_dir / f"public-course-{width}.png"
    if proof_path.exists() or screenshot_path.exists():
        raise FileExistsError("Use a fresh AC_PUBLIC_COURSE_REFLOW_EVIDENCE_DIR for each run")
    with proof_path.open("x", encoding="utf-8") as output:
        json.dump(proof, output, ensure_ascii=False, indent=2)
        output.write("\n")
    # Element screenshots scroll under the sticky site header. Capture the real
    # page from its origin so the header cannot obscure a curriculum title.
    page.evaluate("window.scrollTo({top: 0, left: 0, behavior: 'instant'})")
    page.screenshot(path=str(screenshot_path), full_page=True)


@pytest.mark.e2e
@pytest.mark.parametrize("width", [320, 390, 768, 1440])
def test_public_course_module_headers_reflow(
    public_course_browser: Browser, public_course_base_url: str, width: int
) -> None:
    context = public_course_browser.new_context(
        viewport={"width": width, "height": 1024}, service_workers="block"
    )
    mutations: list[str] = []

    def prevent_mutations(route: Route) -> None:
        if route.request.method not in {"GET", "HEAD", "OPTIONS"}:
            mutations.append(f"{route.request.method} {urlsplit(route.request.url).path}")
            route.abort()
        else:
            route.continue_()

    context.route("**/*", prevent_mutations)
    page = context.new_page()
    try:
        page.goto(
            f"{public_course_base_url}/programs/{FREE_COURSE_SLUG}",
            wait_until="domcontentloaded",
        )
        source = page.evaluate(
            """async (path) => {
              const response = await fetch(path, {
                method: 'GET', mode: 'same-origin', credentials: 'omit', cache: 'no-store',
              });
              return {status: response.status, program: await response.json()};
            }""",
            PUBLIC_PROGRAM_PATH,
        )
        assert source["status"] == 200, "The same-origin public catalog must be available"
        program = source["program"]
        assert program["slug"] == FREE_COURSE_SLUG
        expected = [
            {
                "titleId": f"program-module-{module['id']}-title",
                "titleText": module["title"],
                "numberText": f"Module {module['position']}",
                "countText": (
                    f"{len(module['activities'])} "
                    + ("activity" if len(module["activities"]) == 1 else "activities")
                ),
            }
            for module in program["modules"]
        ]
        assert expected, "Reflow regression requires published modules from the public catalog"
        expect(page.locator(".public-module-detail-card")).to_have_count(
            len(expected), timeout=30000
        )
        page.evaluate(
            """async () => {
              await document.fonts.ready;
              await new Promise((resolve) => {
                requestAnimationFrame(() => requestAnimationFrame(resolve));
              });
            }"""
        )
        measured = _curriculum_geometry(page)
        document_width = page.evaluate(
            "Math.max(document.documentElement.scrollWidth, document.body.scrollWidth)"
        )
        violations = [
            f"{module['titleId']}: {error}"
            for module in measured
            for error in _layout_violations(module, width)
        ]
        _write_evidence(
            page,
            width,
            {
                "viewportWidth": width,
                "documentWidth": document_width,
                "publicApiPath": PUBLIC_PROGRAM_PATH,
                "expectedModules": expected,
                "measuredModules": measured,
                "blockedMutationRequests": mutations,
                "geometryViolations": violations,
                "scope": "Public curriculum layout only; no identity or enrollment proof.",
            },
        )
        assert not mutations, f"Unexpected mutating requests were blocked: {mutations}"
        assert document_width <= width + TOLERANCE, (
            f"{width}px public curriculum has document overflow: {document_width}px"
        )
        actual = [
            {key: module[key] for key in ("titleId", "titleText", "numberText", "countText")}
            for module in measured
        ]
        assert actual == expected, (
            "Rendered curriculum must preserve the public API titles and counts"
        )
        assert not violations, f"{width}px public curriculum reflow: " + "; ".join(violations)
    finally:
        context.close()
