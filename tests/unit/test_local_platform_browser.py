"""Offline browser-helper contracts; no browser, credentials or live network used."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/open-local-platform-browser.py"
EXPECTED_SURFACES = (
    ("learner", "http://learner.localhost:3100", "learner@ac.localhost", None, "/home"),
    ("admin", "http://admin.localhost:3101", "admin@ac.localhost", "operations_tenant_id", "/"),
    (
        "coach",
        "http://coach.localhost:3102",
        "coach@ac.localhost",
        "academy_tenant_id",
        "/studio/programs",
    ),
)


@pytest.fixture
def browser_helper():
    spec = importlib.util.spec_from_file_location("local_browser_test_helper", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_surface_accounts_and_selected_tenants_are_distinct(browser_helper):
    assert browser_helper.SURFACES == EXPECTED_SURFACES
    assert {surface[1] for surface in EXPECTED_SURFACES} == browser_helper.LOCAL_ORIGINS


@pytest.mark.parametrize(
    "url",
    [
        "https://learner.localhost:3100/home",
        "http://learner.localhost:3101/home",
        "http://admin.localhost:3100/",
        "http://coach.localhost:3101/studio/programs",
        "http://learner.localhost/home",
        "http://127.0.0.1:3100/home",
        "http://localhost:3100/home",
        "http://learner.localhost:3100.attacker.test/home",
        "http://learner.localhost.attacker.test:3100/home",
        "http://user@learner.localhost:3100/home",
        "http://user:password@learner.localhost:3100/home",
        "http://learner.localhost:3100@attacker.test/home",
        "https://external.example.test/",
        "file:///C:/Windows/system.ini",
        "data:text/plain,not-local",
        "//learner.localhost:3100/home",
        "/home",
    ],
)
def test_allowed_origin_rejects_wrong_surface_and_url_authority(browser_helper, url):
    assert browser_helper.allowed_origin(url) is False


@pytest.mark.parametrize("origin", [surface[1] for surface in EXPECTED_SURFACES])
def test_allowed_origin_accepts_only_exact_local_origins(browser_helper, origin):
    assert browser_helper.allowed_origin(origin)
    assert browser_helper.allowed_origin(origin + "/login?return_to=%2Fhome#signin")
    assert browser_helper.allowed_origin(origin + "/v1/me")


class FakeRoute:
    def __init__(self, url):
        self.request = SimpleNamespace(url=url)
        self.events = []

    def abort(self):
        self.events.append("abort")

    def continue_(self):
        self.events.append("continue")


class FakeLocator:
    def __init__(self, page, label):
        self.page, self.label = page, label

    def to_be_enabled(self, *, timeout):
        assert self.label == "Email address" and timeout == 30000

    def fill(self, value):
        self.page.fields[self.label] = value

    def click(self):
        assert self.label == "Sign in"
        if self.page.owner.fail_origin == self.page.origin:
            raise RuntimeError("synthetic sign-in refusal")
        self.page.url = self.page.origin + "/authenticated"


class FakePage:
    def __init__(self, owner, url="about:blank"):
        self.owner, self.url = owner, url
        self.fields, self.events, self.routes = {}, [], []
        self.origin = None

    def route(self, pattern, callback):
        assert pattern == "**/*" and not self.routes
        self.routes.append(callback)
        self.events.append("route")
        for url, expected in (
            ("https://external.example.test/", "abort"),
            ("http://coach.localhost:3103/", "abort"),
            ("http://user@admin.localhost:3101/", "abort"),
            ("http://learner.localhost:3100/home", "continue"),
        ):
            request = FakeRoute(url)
            callback(request)
            assert request.events == [expected]

    def unroute(self, pattern, callback):
        assert pattern == "**/*" and self.routes == [callback]
        self.routes.clear()
        self.events.append("unroute")

    def goto(self, url, *, wait_until):
        assert wait_until == "domcontentloaded" and len(self.routes) == 1
        self.origin = next(
            origin for _, origin, *_ in EXPECTED_SURFACES if url.startswith(origin + "/")
        )
        self.url = url
        self.events.append(("goto", url))

    def get_by_label(self, label, *, exact=False):
        assert label in {"Email address", "Password", "Local tenant ID"}
        if label != "Email address":
            assert exact is True
        return FakeLocator(self, label)

    def get_by_role(self, role, *, name, exact):
        # No Open program locator/count gates are part of authentication.
        assert (role, name, exact) == ("button", "Sign in", True)
        return FakeLocator(self, name)

    def wait_for_url(self, predicate, *, timeout):
        assert timeout == 30000
        assert predicate(self.url) is True
        assert predicate(self.origin + "/login") is False
        assert predicate("https://external.example.test/authenticated") is False

    def bring_to_front(self):
        self.owner.fronted.append(self)

    def close(self):
        raise AssertionError("The helper must leave user tabs open")


class FakeBrowser:
    def __init__(self, *, reuse, fail_origin):
        self.fail_origin = fail_origin
        self.fronted, self.requests, self.connected = [], [], []
        self.contexts = [self]
        self.pages = [FakePage(self, "https://unrelated.example.test/user-tab")]
        if reuse:
            self.pages.extend(
                FakePage(self, origin + "/previous") for _, origin, *_ in EXPECTED_SURFACES
            )
        self.request = SimpleNamespace(get=self.get)

    def new_page(self):
        page = FakePage(self)
        self.pages.append(page)
        return page

    def get(self, url, *, max_redirects):
        assert url in {origin + "/v1/me" for _, origin, *_ in EXPECTED_SURFACES}
        assert max_redirects == 0
        self.requests.append(url)
        return SimpleNamespace(status=200)

    def connect_over_cdp(self, url):
        assert url == "http://127.0.0.1:9327"
        self.connected.append(url)
        return self

    def close(self):
        raise AssertionError("The helper must never close separately launched Chrome")

    def __enter__(self):
        return SimpleNamespace(chromium=self)

    def __exit__(self, *_args):
        assert all(not page.routes for page in self.pages)


def configure_fake(browser_helper, monkeypatch, tmp_path, *, reuse, fail_origin=None):
    sandbox = tmp_path / ".tmp/local-platform/sandbox.json"
    sandbox.parent.mkdir(parents=True)
    sandbox.write_text(
        json.dumps(
            {
                "academy_tenant_id": "synthetic-academy",
                "operations_tenant_id": "synthetic-operations",
            }
        )
    )
    monkeypatch.setattr(browser_helper, "ROOT", tmp_path)
    monkeypatch.setenv("AC_LOCAL_BROWSER_TEST_PASSWORD", "synthetic-only-password")
    browser = FakeBrowser(reuse=reuse, fail_origin=fail_origin)
    monkeypatch.setattr(browser_helper, "sync_playwright", lambda: browser)
    monkeypatch.setattr(browser_helper, "expect", lambda locator: locator)
    return browser


@pytest.mark.parametrize("reuse", [False, True])
def test_three_normal_signins_leave_app_tabs_open_and_detach_guards(
    browser_helper, monkeypatch, tmp_path, capsys, reuse
):
    browser = configure_fake(browser_helper, monkeypatch, tmp_path, reuse=reuse)
    browser_helper.main()
    assert len(browser.pages) == 4 and browser.pages[0].events == []
    assert browser.connected == ["http://127.0.0.1:9327"]
    for page, (_, origin, email, tenant_key, destination) in zip(
        browser.pages[1:], EXPECTED_SURFACES, strict=True
    ):
        assert page.fields["Email address"] == email
        assert page.fields["Password"] == "synthetic-only-password"  # noqa: S105 - fake-only input
        if tenant_key:
            assert page.fields["Local tenant ID"] == (
                "synthetic-academy" if tenant_key == "academy_tenant_id" else "synthetic-operations"
            )
        else:
            assert "Local tenant ID" not in page.fields
        assert page.events == [
            "route",
            ("goto", origin + "/login"),
            ("goto", origin + destination),
            "unroute",
        ]
        assert not page.routes and page.url == origin + destination
    assert browser.requests == [origin + "/v1/me" for _, origin, *_ in EXPECTED_SURFACES]
    assert browser.fronted == [*browser.pages[1:], browser.pages[1]]
    output = capsys.readouterr().out
    assert "synthetic-only-password" not in output
    assert json.loads(output) == {
        "status": "open",
        "apps": {
            name: origin + destination for name, origin, _, _, destination in EXPECTED_SURFACES
        },
        "persistent_profile": "disposable-local-platform",
    }


def test_failed_coach_signin_detaches_its_guard_without_closing_browser(
    browser_helper, monkeypatch, tmp_path, capsys
):
    browser = configure_fake(
        browser_helper, monkeypatch, tmp_path, reuse=True, fail_origin=EXPECTED_SURFACES[2][1]
    )
    with pytest.raises(RuntimeError, match="synthetic sign-in refusal"):
        browser_helper.main()
    assert browser.pages[0].events == [] and len(browser.pages) == 4
    assert all(not page.routes and page.events[-1] == "unroute" for page in browser.pages[1:])
    assert browser.requests == [origin + "/v1/me" for _, origin, *_ in EXPECTED_SURFACES[:2]]
    assert capsys.readouterr().out == ""
