"""One call-length limit everywhere (owner, 23 Oct 2026: "Call length limit: 120 minutes
everywhere"); the analysis pipeline handles two hours since c1f6da4c."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ac_platform.billing.ledger import PER_CALL_DEFAULT_SECONDS, PLAN_PER_CALL_SECONDS
from ac_platform.billing.projection import Lot, LotKind, project
from ac_platform.billing.trial import TrialPolicy
from ac_platform.conversation_intelligence.acquisition_usage import (
    LONGEST_CALL_EXCEEDED_MESSAGE,
    LONGEST_CALL_SECONDS,
)
from ac_platform.conversation_intelligence.limits import CALL_LIMIT_SECONDS
from ac_platform.conversation_intelligence.signals import MAX_SECONDS

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)


def test_every_cap_is_the_one_limit() -> None:
    assert CALL_LIMIT_SECONDS == 120 * 60
    assert LONGEST_CALL_SECONDS == CALL_LIMIT_SECONDS
    assert PER_CALL_DEFAULT_SECONDS == CALL_LIMIT_SECONDS
    assert set(PLAN_PER_CALL_SECONDS.values()) == {CALL_LIMIT_SECONDS}
    assert TrialPolicy("v1").per_call_seconds(NOW) == CALL_LIMIT_SECONDS
    assert TrialPolicy("v2").per_call_seconds(NOW) == CALL_LIMIT_SECONDS


def test_the_limit_never_passes_what_analysis_handles() -> None:
    # Raising it to the owner's 120 minutes needs the pipeline's window first.
    assert CALL_LIMIT_SECONDS <= MAX_SECONDS


def test_a_call_at_the_limit_is_taken_and_one_over_it_is_refused_with_the_limit_named() -> None:
    plenty = project([Lot("grant", LotKind.GRANT, 10 * 3600, NOW - timedelta(days=1))], [], NOW)
    assert plenty.can_reserve(CALL_LIMIT_SECONDS, per_call_limit=CALL_LIMIT_SECONDS)
    assert not plenty.can_reserve(CALL_LIMIT_SECONDS + 1, per_call_limit=CALL_LIMIT_SECONDS)
    assert not plenty.can_reserve(CALL_LIMIT_SECONDS + 60, per_call_limit=CALL_LIMIT_SECONDS)
    assert LONGEST_CALL_EXCEEDED_MESSAGE == (
        "This recording is longer than 120 minutes, the longest call Sales X-Ray analyses. "
        "Split it and try again."
    )
