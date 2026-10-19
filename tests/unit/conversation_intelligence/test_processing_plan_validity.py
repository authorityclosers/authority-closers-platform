"""A person's acceptance covers 24 hours, never past an approval (orchestrator, 19 Oct 2026)."""

from datetime import timedelta

from ac_platform.conversation_intelligence.application import ConversationDenied
from ac_platform.conversation_intelligence.guest_ownership import CONTINUATION_VALIDITY
from ac_platform.conversation_intelligence.processing_plan import (
    NEEDS_ACCEPTANCE_CODE,
    PLAN_VALIDITY,
    PlanNeedsAcceptance,
    plan_expires_at_epoch,
)

NOW = 1_800_000_000
DAY = 24 * 3600


def test_a_new_plan_holds_for_24_hours_when_every_approval_allows() -> None:
    assert PLAN_VALIDITY == timedelta(hours=24) == CONTINUATION_VALIDITY
    assert plan_expires_at_epoch(NOW, NOW + 30 * DAY, NOW + 7 * DAY) == NOW + DAY


def test_it_never_outlives_the_release_a_stage_or_the_retry_grant() -> None:
    assert plan_expires_at_epoch(NOW, NOW + 3600, NOW + 30 * DAY) == NOW + 3600
    assert plan_expires_at_epoch(NOW, NOW + 30 * DAY, NOW + 600) == NOW + 600
    assert plan_expires_at_epoch(NOW, NOW + 30 * DAY, NOW + 30 * DAY, NOW + 7200) == NOW + 7200


def test_a_new_release_stops_the_plan_as_needs_your_ok() -> None:
    error = PlanNeedsAcceptance("This analysis needs your OK to continue.")
    # Every caller that treats a plan as not approved still does.
    assert isinstance(error, ConversationDenied)
    assert NEEDS_ACCEPTANCE_CODE == "needs_new_acceptance"
