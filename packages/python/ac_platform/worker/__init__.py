"""Durable worker entrypoint; job behavior is registered by domain modules."""

from __future__ import annotations

import asyncio

import structlog

from ac_platform.application.settings import get_settings


async def run() -> None:
    settings = get_settings()
    structlog.get_logger().info(
        "worker_started",
        release_id=settings.release_id,
        environment=settings.environment,
        side_effects_hold=settings.external_side_effects_hold,
    )
    shutdown = asyncio.Event()
    await shutdown.wait()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
