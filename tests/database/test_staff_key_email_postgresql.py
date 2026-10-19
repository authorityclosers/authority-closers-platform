"""A production staff key enqueues its notice to the control account; others do not."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from ac_platform.admin_settings.staff_key_email import STAFF_KEY_CREATED_EVENT
from ac_platform.outbox.models import OutboxEvent
from tests.database.test_conversation_reviews_postgresql import ReviewCase, run
from tests.database.test_conversation_reviews_postgresql import (
    postgres_harness as postgres_harness,
)
from tests.database.test_conversation_reviews_postgresql import (
    review_case as review_case,
)
from tests.database.test_staff_keys_postgresql import Harness, _retire_earlier_keys


async def exercise(case: ReviewCase) -> None:
    await _retire_earlier_keys(case)
    harness = Harness(case)
    quiet = await harness.make(["settings:read"], "Dev key")
    harness.settings = harness.settings.model_copy(update={"environment": "production"})
    loud: dict[str, Any] = await harness.make(["settings:read"], "Production key")
    assert loud["key"].startswith("ac_live_")
    async with case.sessions() as database:
        events = (
            await database.scalars(
                select(OutboxEvent).where(OutboxEvent.event_type == STAFF_KEY_CREATED_EVENT)
            )
        ).all()
    keyed = {str(event.aggregate_id): event for event in events}
    assert loud["id"] in keyed and quiet["id"] not in keyed
    assert keyed[loud["id"]].payload == {"key_id": loud["id"]}
    # The key itself never reaches the outbox.
    assert loud["key"] not in str(keyed[loud["id"]].payload)


def test_a_production_key_enqueues_its_notice(review_case: ReviewCase) -> None:
    run(exercise(review_case))
