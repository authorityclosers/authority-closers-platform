from fastapi import FastAPI

from ac_platform.http.product_updates import install_product_updates_http
from ac_platform.http.routes import RouteContext

ORDER = 1201


def install(app: FastAPI, ctx: RouteContext) -> None:
    install_product_updates_http(app, settings=ctx.settings, require_actor=ctx.require_actor)
