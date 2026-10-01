"""Offline contract and containment proof: fake browser, fictional session, no remote calls."""

import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location(
    "first_paid_user", Path(__file__).parents[1] / "journey/first_paid_user.py"
)
assert SPEC and SPEC.loader
journey = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(journey)
RELEASE = "a" * 40
ARGS = ["--environment", "dev", "--release-id", RELEASE, "--execute"]


class Locator:
    def __init__(self, items):
        self.items = items

    def count(self):
        return len(self.items)

    def nth(self, index):
        return Locator([self.items[index]])

    def is_visible(self):
        return self.items[0][1]

    def is_enabled(self):
        return self.items[0][2]

    def inner_text(self):
        return self.items[0][0]


class Page:
    def __init__(self, text=journey.NOT_ON_SALE, actions=()):
        self.text, self.actions = text, actions

    def get_by_text(self, text, *, exact):
        assert exact
        return Locator([(text, True, False)] if text in self.text.splitlines() else [])

    def get_by_role(self, role, name=None):
        if role == "main":
            return Locator([(self.text, True, False)])
        return Locator([a[1:] for a in self.actions if a[0] == role and name.search(a[1])])


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    monkeypatch.setattr(journey, "QA_DIR", tmp_path)
    monkeypatch.delenv("AC_QA_SESSION_FILE", raising=False)
    monkeypatch.delenv("DEBUG", raising=False)
    monkeypatch.delenv("PWDEBUG", raising=False)
    manifest = json.loads(journey.MANIFEST.read_text())
    session = {
        "environment": "dev",
        "origin": journey.ORIGIN,
        "release_id": RELEASE,
        "email": manifest["accounts"][0]["email"],
        "person_id": "00000000-0000-4000-8000-000000000001",
        "offline_enabled": False,
        "purchase_enabled": False,
        "storage_state": {
            "origins": [],
            "cookies": [
                {
                    "name": "__Host-ac_session",
                    "value": "fictional-cookie-value",
                    "domain": "salesxray-dev.authorityclosers.com",
                    "path": "/",
                    "expires": -1,
                    "secure": True,
                    "httpOnly": True,
                    "sameSite": "Lax",
                }
            ],
        },
    }
    path = tmp_path / "dev-personal.json"
    path.write_text(json.dumps(session))
    return session, path


@pytest.fixture
def browser(monkeypatch, runtime):
    from playwright import sync_api

    state = SimpleNamespace(
        launches=0, requests=[], page=Page(), status=200, identity=True, closed=False, extra=[]
    )

    class Route:
        def __init__(self, method, url):
            self.request = SimpleNamespace(method=method, url=url)

        def abort(self):
            pass

        def fetch(self, *, url=None, max_redirects):
            assert max_redirects == 0
            url = url or self.request.url
            state.requests.append(url)
            if url.endswith("/v1/me/workspaces"):
                return SimpleNamespace(
                    status=200,
                    json=lambda: {
                        "person_id": runtime[0]["person_id"] if state.identity else "another-person"
                    },
                )
            if url.endswith("/v1/billing/offline-payment"):
                return SimpleNamespace(
                    status=200, json=lambda: {"enabled": runtime[0]["offline_enabled"]}
                )
            return SimpleNamespace(status=state.status)

        def fulfill(self, *, response):
            pass

    class Context:
        def route(self, pattern, callback):
            self.callback = callback

        def route_web_socket(self, pattern, callback):
            assert pattern == "**/*"

        def new_page(self):
            def goto(url, **kwargs):
                self.callback(Route("GET", url))
                self.callback(Route("GET", journey.ORIGIN + "/v1/billing/offline-payment"))
                for method, extra_url in state.extra:
                    self.callback(Route(method, extra_url))
                return SimpleNamespace(status=state.status)

            state.page.goto = goto
            return state.page

    class Browser:
        def launch(self, *, headless):
            assert headless
            state.launches += 1
            return self

        def new_context(self, *, storage_state, service_workers):
            assert service_workers == "block" and storage_state == runtime[0]["storage_state"]
            return Context()

        def close(self):
            state.closed = True

    class Playwright:
        def __enter__(self):
            return SimpleNamespace(chromium=Browser())

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(sync_api, "sync_playwright", Playwright)
    return state


def invoke(capsys, args, expected):
    assert journey.main(args) == expected
    output = capsys.readouterr()
    assert not output.err and "fictional-cookie-value" not in output.out
    assert "Journey passed:" not in output.out
    result = json.loads(output.out)
    assert set(result) == {
        "environment",
        "release_id",
        "source_pin",
        "covered_steps",
        "status",
        "failing_step",
    }
    return result


def test_dry_run_needs_no_session_or_browser(capsys, monkeypatch):
    monkeypatch.setattr(journey, "load_session", lambda *_: pytest.fail("session read"))
    monkeypatch.setattr(journey, "browse", lambda *_: pytest.fail("network"))
    assert invoke(capsys, [], 0)["covered_steps"] == ["fixture_manifest"]
    assert invoke(capsys, ARGS[:-1], 0)["covered_steps"] == ["fixture_manifest"]


@pytest.mark.parametrize(
    "args",
    [
        ["--execute"],
        ["--environment", "dev", "--execute"],
        ["--environment", "staging"],
        ["--environment", "production"],
        ["--environment", "unknown"],
        ["--release-id", "unknown"],
        ["--release-id", "0" * 40],
        ["--mode", "live"],
        ["--mode", "test"],
        ["--origin", "https://salesxray.authorityclosers.com"],
        ["--origin", journey.ORIGIN + "/"],
        ["--unknown", "fictional-cookie-value"],
        ["--release-id", RELEASE, "--execute"],
        ["--env", "dev", "--release-id", RELEASE, "--execute"],
        ["--environment", "dev", "--release-id", "b" * 40, "--execute"],
    ],
)
def test_invalid_target_before_browser(capsys, browser, args):
    assert invoke(capsys, args, 2)["status"] == "invalid"
    assert browser.launches == 0 and not browser.requests


def test_manifest_preserves_distinct_plus_tags():
    manifest = json.loads(journey.MANIFEST.read_text())
    assert journey.validate_manifest(manifest) == manifest["accounts"][0]["email"]
    assert len({a["email"].split("+")[0] for a in manifest["accounts"]}) == 1
    for mutation in ("duplicate", "secret"):
        invalid = copy.deepcopy(manifest)
        if mutation == "duplicate":
            invalid["accounts"][1]["email"] = invalid["accounts"][0]["email"]
        else:
            invalid["accounts"][0]["password"] = object()
        with pytest.raises(journey.InvalidConfig):
            journey.validate_manifest(invalid)


@pytest.mark.parametrize("change", ["missing", "origin", "email", "purchase", "expiry", "debug"])
def test_invalid_session_before_browser(capsys, runtime, browser, monkeypatch, change):
    session, path = runtime
    if change == "missing":
        path.unlink()
    elif change == "debug":
        monkeypatch.setenv("DEBUG", "pw:api")
    else:
        if change == "expiry":
            session["storage_state"]["cookies"][0]["expires"] = 1
        else:
            session[
                {"origin": "origin", "email": "email", "purchase": "purchase_enabled"}[change]
            ] = True if change == "purchase" else "fictional-cookie-value"
        path.write_text(json.dumps(session))
    invoke(capsys, ARGS, 2)
    assert browser.launches == 0


@pytest.mark.parametrize(
    "text,offline,actions,code",
    [
        (journey.NOT_ON_SALE, False, (), 0),
        (journey.NOT_ON_SALE + "\n" + journey.OFFLINE_COPY + "\nUPI", True, (), 0),
        ("Coming soon", False, (), 1),
        (journey.NOT_ON_SALE + "\n" + journey.OFFLINE_COPY + "\nUPI", False, (), 1),
        (journey.NOT_ON_SALE, True, (), 1),
        (journey.NOT_ON_SALE + "\nUPI", False, (), 1),
        (journey.NOT_ON_SALE + "\n₹ 2499", False, (), 1),
        (journey.NOT_ON_SALE + "\nadmin+qa-dev-personal@authorityclosers.com", False, (), 0),
        (journey.NOT_ON_SALE + "\nAfter you pay, we add your minutes\nUPI", True, (), 1),
        (journey.NOT_ON_SALE, False, (("button", "Buy now", True, True),), 2),
        (journey.NOT_ON_SALE, False, (("link", "Checkout", True, False),), 1),
    ],
)
def test_presale_contract_and_exit_codes(capsys, runtime, browser, text, offline, actions, code):
    runtime[0]["offline_enabled"] = offline
    runtime[1].write_text(json.dumps(runtime[0]))
    browser.page = Page(text, actions)
    result = invoke(capsys, ARGS, code)
    assert browser.closed
    assert result["release_id"] == RELEASE and result["source_pin"] == journey.SOURCE_PIN
    assert result["covered_steps"] == (
        ["fixture_manifest", "plans_pre_sale"] if code == 0 else ["fixture_manifest"]
    )


@pytest.mark.parametrize(
    "method,url",
    [
        ("POST", journey.ORIGIN + "/v1/checkout"),
        ("GET", "https://api.razorpay.com"),
        ("GET", "https://salesxray-staging.authorityclosers.com/plans"),
        ("GET", journey.ORIGIN + "/v1/admin/customers"),
        ("GET", journey.ORIGIN + "/v1/orders/mock"),
        ("GET", journey.ORIGIN + "/_next/image?url=https://example.com"),
        ("GET", journey.ORIGIN + "/_next/static/../../v1/orders/other"),
        ("GET", journey.ORIGIN + "/plans%2f"),
        ("GET", journey.ORIGIN + "/calls"),
    ],
)
def test_request_containment(capsys, browser, method, url):
    browser.extra = [(method, url)]
    invoke(capsys, ARGS, 2)
    assert url not in browser.requests and browser.closed


def test_wrong_person_and_redirect_never_inspect_chooser(capsys, browser):
    browser.identity = False
    invoke(capsys, ARGS, 2)
    assert browser.requests == [journey.ORIGIN + "/v1/me/workspaces"]
    browser.identity = True
    browser.status = 302
    invoke(capsys, ARGS, 2)


def test_raw_exception_is_redacted(capsys, runtime, monkeypatch):
    def fail(_):
        raise RuntimeError("fictional-cookie-value")

    monkeypatch.setattr(journey, "browse", fail)
    invoke(capsys, ARGS, 2)
