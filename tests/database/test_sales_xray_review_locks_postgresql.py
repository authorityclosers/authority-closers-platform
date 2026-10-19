"""19 Oct incident, on PostgreSQL: review reads never queue for minutes behind a row lock."""

import time
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from ac_platform.conversation_intelligence.gold_review_account import badge
from ac_platform.conversation_intelligence.gold_review_models import GoldReviewer
from ac_platform.http.sales_xray_review import signed_in
from tests.database.test_conversation_reviews_postgresql import (
    postgres_harness as postgres_harness,
)
from tests.database.test_conversation_reviews_postgresql import (
    review_case as review_case,
)
from tests.database.test_conversation_reviews_postgresql import run
from tests.database.test_gold_reviews_postgresql import prepare


@pytest.fixture(scope="module")
def locked_case(review_case):
    run(prepare(review_case))
    return review_case


def _real(case):
    """A sign-in that yields a real transaction, as the account resolver does."""

    async def resolve(request: object):
        async with case.sessions() as database, database.begin():
            yield SimpleNamespace(database=database)

    return resolve


def test_a_held_row_lock_costs_a_review_request_seconds_not_minutes(locked_case) -> None:
    case = locked_case
    reviewer = case.reviewer_actor.person_id

    async def exercise() -> None:
        async with case.sessions() as holder, holder.begin():
            # Someone else holds this reviewer's row for as long as they like.
            await holder.execute(
                select(GoldReviewer).where(GoldReviewer.person_id == reviewer).with_for_update()
            )
            # The badge reads take no row locks, so they answer at once.
            started = time.monotonic()
            async with signed_in(_real(case), object(), 5) as auth:
                shown = await badge(
                    auth.database, case.operations_tenant_id, reviewer, case.prepared.state.now
                )
            assert shown["reviewer"] is True and time.monotonic() - started < 2
            # A locking statement gives up at lock_timeout and answers busy.
            started = time.monotonic()
            with pytest.raises(HTTPException) as caught:
                async with signed_in(_real(case), object(), 15) as auth:
                    await auth.database.execute(
                        select(GoldReviewer)
                        .where(GoldReviewer.person_id == reviewer)
                        .with_for_update()
                    )
            assert caught.value.status_code == 503
            assert time.monotonic() - started < 5

    run(exercise())
