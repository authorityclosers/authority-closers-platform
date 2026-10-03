"""Add an API module with ORDER and install(app, ctx); pick an ORDER, never edit app.py.

Orders below 500 install before conversation composition; 500..1499 follow
conversation routes; 1500..1699 follow planning; 1700+ follow learning.
Explicit runtime-dependent installers keep their positions between these batches.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ac_platform.application.settings import Settings
    from ac_platform.http.auth import RequireActor


@dataclass(frozen=True, slots=True)
class RouteContext:
    settings: Settings
    require_actor: RequireActor
    sessions: async_sessionmaker[AsyncSession]


RouteInstaller = Callable[["FastAPI", RouteContext], None]


@dataclass(frozen=True, slots=True)
class RouteModule:
    order: int
    name: str
    install: RouteInstaller


def discover_routes() -> tuple[RouteModule, ...]:
    """Validate all modules before installing any, without a mutable registry."""
    modules = []
    for info in pkgutil.iter_modules(__path__):
        name = f"{__name__}.{info.name}"
        module = importlib.import_module(name)
        order = getattr(module, "ORDER", None)
        install = getattr(module, "install", None)
        if type(order) is not int:
            raise RuntimeError(f"Route module {name} must expose ORDER: int")
        if not callable(install):
            raise RuntimeError(f"Route module {name} must expose callable install(app, ctx)")
        modules.append(RouteModule(order, name, cast(RouteInstaller, install)))
    return tuple(sorted(modules, key=lambda module: (module.order, module.name)))


def install_routes(
    application: FastAPI,
    ctx: RouteContext,
    modules: Sequence[RouteModule],
    *,
    start: int | None = None,
    stop: int | None = None,
) -> None:
    """Install a batch at its original position among the explicit installers."""
    for module in modules:
        if (start is None or module.order >= start) and (stop is None or module.order < stop):
            module.install(application, ctx)
