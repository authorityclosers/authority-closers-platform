"""Warm routing and file assets before readiness, on a worker, without endpoints."""

import threading

from fastapi import APIRouter, Depends, FastAPI

from ac_platform.application import request_warmup


async def test_warmup_compiles_routes_without_executing_dependencies(monkeypatch):
    app = FastAPI()
    router = APIRouter()
    calls = []

    async def private_dependency():
        raise AssertionError("warm-up must not execute dependencies")

    @router.get("/private", include_in_schema=False, dependencies=[Depends(private_dependency)])
    async def private():
        raise AssertionError("warm-up must not execute handlers")

    app.include_router(router)
    main = threading.get_ident()

    def matches(scope):
        calls.append(threading.get_ident())
        return original(scope)

    # Spy at the public app-route boundary, rather than FastAPI private types.
    route = app.routes[-1]
    original = route.matches
    monkeypatch.setattr(route, "matches", matches)
    await request_warmup.warmup(app, None)
    assert calls and all(ident != main for ident in calls)


async def test_lifespan_finishes_warmup_before_yield(monkeypatch):
    from ac_platform.http import app as app_module

    seen = []

    async def warm(application, root):
        seen.append("warm")

    monkeypatch.setattr(app_module, "warmup", warm)
    async with app_module.lifespan(FastAPI()):
        assert seen == ["warm"]
