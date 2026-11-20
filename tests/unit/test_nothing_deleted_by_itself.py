"""Nothing deletes a workspace's history by itself (owner, 20 Nov 2026: "No data should be
deleted. Not the call logs, not the recordings, nothing ... they need it for comparing months
and weeks"; and "keep the public learners data too, nothing deleted"). A recording past its
deadline stays; the Bin keeps its leads until a person deletes them for good."""

from __future__ import annotations

import asyncio
import inspect
from typing import Any

from fastapi import FastAPI

from ac_platform.conversation_intelligence import reporting_runtime, retention
from ac_platform.conversation_intelligence.retention import ConversationRetentionScheduler
from ac_platform.lead_desk import shelf


class _NoDatabase:
    def __call__(self, *_: Any, **__: Any) -> Any:
        raise AssertionError("an expiry-off step must not open the database")


def test_the_hosted_service_never_expires_a_recording() -> None:
    assert retention.AUTOMATIC_EXPIRY is False
    source = inspect.getsource(reporting_runtime.compose_hosted_reporting)
    assert "ConversationRetentionScheduler(sessions, expire=AUTOMATIC_EXPIRY)" in source
    scheduler = ConversationRetentionScheduler(_NoDatabase(), expire=False)  # type: ignore[arg-type]
    assert asyncio.run(scheduler.step()) is False


def test_the_bin_is_never_emptied_by_itself() -> None:
    assert shelf.AUTOMATIC_PURGE is False
    application = FastAPI()
    before = application.router.lifespan_context
    shelf.attach(application, _NoDatabase(), "production")  # type: ignore[arg-type]
    assert application.router.lifespan_context is before
