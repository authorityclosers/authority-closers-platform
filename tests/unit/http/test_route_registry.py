from __future__ import annotations

import sys
from collections import Counter
from dataclasses import FrozenInstanceError, fields
from pkgutil import ModuleInfo
from types import ModuleType
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.routing import iter_route_contexts

import ac_platform.http.app as app_module
import ac_platform.http.routes as routes
from ac_platform.application.settings import Settings
from ac_platform.db.session import session_factory
from ac_platform.http.auth import install_identity_http
from ac_platform.http.routes import RouteContext, RouteModule, discover_routes

_PRACTICE_TENANT_ID = UUID("00000000-0000-4000-8000-000000000001")


def _route_table(application: FastAPI) -> list[tuple[tuple[str, ...], str, str]]:
    return [
        (tuple(sorted(route.methods or ())), route.path, route.endpoint.__name__)
        for route in iter_route_contexts(application.router.routes)
    ]


@pytest.mark.parametrize("practice_enabled", [False, True])
def test_no_routes_share_a_method_and_path(
    monkeypatch: pytest.MonkeyPatch, practice_enabled: bool
) -> None:
    monkeypatch.setattr(
        app_module,
        "settings",
        Settings(
            environment="test",
            practice_arcade_preview_enabled=practice_enabled,
            public_learner_tenant_id=_PRACTICE_TENANT_ID,
            operations_tenant_id=UUID("00000000-0000-4000-8000-000000000002"),
        ),
    )
    counts = Counter(
        (method, path)
        for methods, path, _ in _route_table(app_module.create_app())
        for method in methods
    )
    assert {key: count for key, count in counts.items() if count > 1} == {}


@pytest.mark.parametrize("practice_enabled", [False, True])
def test_installation_order_is_deterministic(
    monkeypatch: pytest.MonkeyPatch, practice_enabled: bool
) -> None:
    monkeypatch.setattr(
        app_module,
        "settings",
        Settings(
            environment="test",
            practice_arcade_preview_enabled=practice_enabled,
            public_learner_tenant_id=_PRACTICE_TENANT_ID,
            operations_tenant_id=UUID("00000000-0000-4000-8000-000000000002"),
        ),
    )
    first = discover_routes()
    assert [(module.order, module.name) for module in first] == sorted(
        (module.order, module.name) for module in first
    )
    assert discover_routes() == first
    assert _route_table(app_module.create_app()) == _route_table(app_module.create_app())


@pytest.mark.parametrize("module", discover_routes(), ids=lambda module: module.name)
def test_every_discovered_module_installs_at_least_one_route(module: RouteModule) -> None:
    application = FastAPI()
    # Practice is deliberately absent unless its existing test preview is enabled.
    settings = Settings(
        environment="test",
        practice_arcade_preview_enabled=True,
        public_learner_tenant_id=_PRACTICE_TENANT_ID,
        operations_tenant_id=UUID("00000000-0000-4000-8000-000000000002"),
    )
    ctx = RouteContext(
        settings=settings,
        require_actor=install_identity_http(
            application, settings=settings, sessions=session_factory
        ),
        sessions=session_factory,
    )
    before = len(_route_table(application))
    module.install(application, ctx)
    assert len(_route_table(application)) > before
    assert [field.name for field in fields(ctx)] == ["settings", "require_actor", "sessions"]
    with pytest.raises(FrozenInstanceError):
        ctx.settings = Settings(environment="local")  # type: ignore[misc]


@pytest.mark.parametrize(
    ("attributes", "error"),
    [
        ({"install": lambda app, ctx: None}, "ORDER: int"),
        ({"ORDER": 100}, "callable install"),
        ({"ORDER": "100", "install": lambda app, ctx: None}, "ORDER: int"),
        ({"ORDER": True, "install": lambda app, ctx: None}, "ORDER: int"),
        ({"ORDER": 100, "install": None}, "callable install"),
    ],
)
def test_invalid_module_is_refused_at_startup(
    monkeypatch: pytest.MonkeyPatch, attributes: dict[str, object], error: str
) -> None:
    module = ModuleType(f"{routes.__name__}.invalid")
    module.__dict__.update(attributes)
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr(
        routes.pkgutil, "iter_modules", lambda path: [ModuleInfo(None, "invalid", False)]
    )
    with pytest.raises(RuntimeError, match=error):
        app_module.create_app()


def test_new_modules_are_discovered_and_ties_use_module_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def endpoint() -> dict[str, str]:
        return {"status": "ok"}

    for name, order in (("last", 200), ("beta", 100), ("alpha", 100)):
        module = ModuleType(f"{routes.__name__}.{name}")
        module.__dict__.update(
            ORDER=order,
            install=lambda app, ctx, path=f"/fixture/{name}": app.add_api_route(
                path, endpoint, methods=["GET"]
            ),
        )
        monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr(
        routes.pkgutil,
        "iter_modules",
        lambda path: [ModuleInfo(None, name, False) for name in ("last", "beta", "alpha")],
    )
    assert [module.name.rsplit(".", 1)[1] for module in discover_routes()] == [
        "alpha",
        "beta",
        "last",
    ]
    assert [
        path for _, path, _ in _route_table(app_module.create_app()) if path.startswith("/fixture/")
    ] == ["/fixture/alpha", "/fixture/beta", "/fixture/last"]
