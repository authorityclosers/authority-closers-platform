from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.routing import iter_route_contexts

import ac_platform.http.app as app_module
import ac_platform.http.registry as registry
from ac_platform.application.settings import Settings
from ac_platform.http.registry import RouteContext, registered_installers, route_installer

# The route table of main before routes registered themselves (AUT-904).
_BASELINE = Path(__file__).parents[2] / "fixtures" / "http_route_table_baseline.txt"


def _route_table(application: FastAPI) -> list[str]:
    return [
        f"{','.join(sorted(route.methods or ()))} {route.path} {route.name}"
        for route in iter_route_contexts(application.router.routes)
    ]


def _test_app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    monkeypatch.setattr(app_module, "settings", Settings(environment="test"))
    return app_module.create_app()


def test_registered_routes_keep_the_baseline_routes_in_their_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = _BASELINE.read_text().splitlines()
    table = _route_table(_test_app(monkeypatch))

    # New modules may add routes anywhere; every baseline route stays, in order.
    remaining = iter(table)
    missing = [route for route in baseline if route not in remaining]
    assert missing == []
    assert len(set(table)) == len(table)


def test_installation_order_is_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    first = registered_installers()
    assert [(entry.order, entry.module) for entry in first] == sorted(
        (entry.order, entry.module) for entry in first
    )
    assert registered_installers() == first
    assert _route_table(_test_app(monkeypatch)) == _route_table(_test_app(monkeypatch))


def test_identity_is_installed_by_the_app_and_every_other_api_by_the_registry() -> None:
    modules = [entry.module.rsplit(".", 1)[1] for entry in registered_installers()]

    assert modules[0] == "organisation"
    assert modules[-1] == "billing"
    assert {"app", "auth", "registry", "serve", "__main__"}.isdisjoint(modules)


def test_a_module_registers_only_one_installer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry, "_INSTALLERS", {})

    def first(context: RouteContext) -> None:
        return None

    def second(context: RouteContext) -> None:
        return None

    route_installer(order=10)(first)
    # A reload of the same module replaces its installer.
    route_installer(order=20)(first)
    assert [entry.order for entry in registry._INSTALLERS.values()] == [20]
    with pytest.raises(RuntimeError, match="already registers a route installer"):
        route_installer(order=30)(second)
