"""Additive registration; the offer_studio package owns the shared offer store's routes."""

from fastapi import FastAPI

from ac_platform.http.routes import RouteContext
from ac_platform.offer_studio.http import install_offer_studio_http

ORDER = 2200


def install(app: FastAPI, ctx: RouteContext) -> None:
    install_offer_studio_http(app, settings=ctx.settings, require_actor=ctx.require_actor)
