"""The Feature catalogue's generator: every seeded feature still points at real code, and
release history decides "live since" with the history gap marked as "by"."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "build_feature_catalogue", ROOT / "scripts/catalogue/build_feature_catalogue.py"
)
assert spec is not None and spec.loader is not None
catalogue = importlib.util.module_from_spec(spec)
sys.modules["build_feature_catalogue"] = catalogue  # its dataclass looks itself up here
spec.loader.exec_module(catalogue)


def test_every_seeded_feature_points_at_code_that_exists() -> None:
    built, problems = catalogue.build(use_git=False, main_ref="origin/main")
    assert problems == []
    seed = json.loads(catalogue.SEED.read_text(encoding="utf-8"))
    assert [f["id"] for f in built["features"]] == [f["id"] for f in seed["features"]]
    for feature in built["features"]:
        assert feature["status"] in {"dev", "planned"}  # no release history without git
        assert all(anchor["exists"] for anchor in feature["anchors"])


def test_pages_and_api_routes_are_read_from_the_code() -> None:
    built, _ = catalogue.build(use_git=False, main_ref="origin/main")
    apps = {app["key"]: app for app in built["pages"]}
    assert apps["sx"]["pages"] > 10 and apps["admin"]["pages"] > 10
    assert all(
        not route.startswith("/review-fixture") for a in apps.values() for route in a["unnamed"]
    )
    assert built["api"]["routes"] > 100
    assert any(area["prefix"] == "/v1/lead-desk" for area in built["api"]["areas"])


def test_router_prefixes_join_relative_paths(tmp_path: Path) -> None:
    source = tmp_path / "routes.py"
    source.write_text(
        'router = APIRouter(prefix="/v1/things", tags=["x"])\n'
        '@router.get("")\n@router.post("/{id}/done")\n@other.get("/v1/plain")\n'
        '@other.get("/not-v1")\n',
        encoding="utf-8",
    )
    assert catalogue.api_routes([source]) == [
        "GET /v1/plain",
        "GET /v1/things",
        "GET /v1/things/not-v1",
        "POST /v1/things/{id}/done",
    ]


def release(version: str, day: str) -> object:
    return catalogue.Release(sha=version, version=version, date=day, title="")


def test_first_release_and_history_gap(monkeypatch: pytest.MonkeyPatch) -> None:
    history = [
        release("v0.1", "2026-09-03"),
        release("v0.40.0", "2026-10-11"),
        release("v0.41.0", "2026-10-12"),
        release("v0.42.0", "2026-10-13"),
    ]
    carried = {"v0.41.0", "v0.42.0"}
    monkeypatch.setattr(catalogue, "in_release", lambda r, _path, _needle: r.version in carried)
    assert catalogue.first_release(history, "x", None) == 2
    assert catalogue.history_starts(history) == {0, 1}
    carried.clear()
    assert catalogue.first_release(history, "x", None) is None


def test_page_anchor_resolves_to_its_page_file() -> None:
    routes = {key: catalogue.page_routes(app[0]) for key, app in catalogue.APPS.items()}
    path, needle = catalogue.resolve_anchor("admin:/catalogue#Everything", routes)
    assert path == "apps/admin-web/app/(console)/catalogue/page.tsx"
    assert needle == "Everything"
    assert catalogue.fixture_url("/review-fixture/leads") == (
        "https://salesxray-dev.authorityclosers.com/review-fixture/leads"
    )
