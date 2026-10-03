"""Self-registering HTTP route modules.

Each route module in ``ac_platform.http`` adds one installer with
``@route_installer(order=...)``.  ``create_app`` installs identity first (it
provides ``require_actor``), composes the shared runtimes once, and then calls
``install_registered_routes``.  Every module in this package is imported before
installation, so a new API adds its own module and never edits ``app.py``.

Installers run in ascending ``order`` and then by module name, so FastAPI's
first-match route order is fixed.  Existing modules use steps of 100; pick a
free number between the neighbours your routes must follow and precede.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ac_platform.application.settings import Settings
    from ac_platform.billing.application import BillingApplication
    from ac_platform.conversation_intelligence.internal_tester import InternalTesterPolicy
    from ac_platform.http.auth import RequireActor
    from ac_platform.http.conversation_acquisition_runtime import AcquisitionRuntime
    from ac_platform.http.conversation_intake import ConversationIntakeRuntime
    from ac_platform.http.studio_video_bytes import StudioVideoByteTransport
    from ac_platform.media.runtime import MediaRuntime
    from ac_platform.media.service import MediaService
    from ac_platform.media.studio_video_completion import StudioVideoCompletion
    from ac_platform.media.studio_video_runtime import StudioVideoRuntime

# Modules that compose, serve or register the application rather than add routes.
_NOT_ROUTE_MODULES = frozenset({"__main__", "app", "registry", "serve"})


@dataclass(frozen=True, slots=True)
class StudioRouteParts:
    service: MediaService
    byte_transport: StudioVideoByteTransport | None
    video_completion: StudioVideoCompletion | None
    video_upload_max_source_bytes: int | None
    runtime: StudioVideoRuntime | None


@dataclass(frozen=True, slots=True)
class RouteContext:
    """The composed dependencies an installer may pass to its routes."""

    application: FastAPI
    settings: Settings
    sessions: async_sessionmaker[AsyncSession]
    require_actor: RequireActor
    conversation: ConversationIntakeRuntime | None
    acquisition: AcquisitionRuntime | None
    tester_policy: InternalTesterPolicy | None
    media: MediaRuntime
    studio: StudioRouteParts
    billing: BillingApplication | None


RouteInstaller = Callable[[RouteContext], None]


@dataclass(frozen=True, slots=True)
class RegisteredInstaller:
    order: int
    module: str
    install: RouteInstaller


_INSTALLERS: dict[str, RegisteredInstaller] = {}


def route_installer(*, order: int) -> Callable[[RouteInstaller], RouteInstaller]:
    """Register the decorated function as its module's one route installer."""

    def register(install: RouteInstaller) -> RouteInstaller:
        module = install.__module__
        existing = _INSTALLERS.get(module)
        # A reloaded module replaces its own installer; a second one is a bug.
        if existing is not None and existing.install.__qualname__ != install.__qualname__:
            raise RuntimeError(f"{module} already registers a route installer")
        _INSTALLERS[module] = RegisteredInstaller(order=order, module=module, install=install)
        return install

    return register


def _import_route_modules() -> None:
    package = importlib.import_module(__package__ or "ac_platform.http")
    for module in pkgutil.iter_modules(package.__path__):
        if module.name not in _NOT_ROUTE_MODULES:
            importlib.import_module(f"{package.__name__}.{module.name}")


def registered_installers() -> tuple[RegisteredInstaller, ...]:
    """Every route installer in this package, in installation order."""
    _import_route_modules()
    return tuple(sorted(_INSTALLERS.values(), key=lambda entry: (entry.order, entry.module)))


def install_registered_routes(context: RouteContext) -> None:
    for entry in registered_installers():
        entry.install(context)
