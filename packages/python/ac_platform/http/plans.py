"""Unauthenticated public plans catalogue: ``GET /v1/plans`` (ADR 0046, Plans C2)."""

from __future__ import annotations

from fastapi import APIRouter, FastAPI, Response
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ac_platform.plans.catalogue import PublicPlanCatalogue, read_public_catalogue


def install_plans_http(application: FastAPI, *, sessions: async_sessionmaker[AsyncSession]) -> None:
    """Register the public catalogue read; it needs no actor and grants nothing."""

    router = APIRouter(prefix="/v1", tags=["plans"])

    @router.get("/plans", response_model=PublicPlanCatalogue)
    async def list_plans(response: Response) -> PublicPlanCatalogue:
        async with sessions() as database, database.begin():
            catalogue = await read_public_catalogue(database)
        response.headers["cache-control"] = "public, max-age=60"
        return catalogue

    application.include_router(router)
