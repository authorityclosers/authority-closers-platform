"""The trial policy: a derived lot, never a stored ledger row (ADR 0052, section A/D).

``v1`` is today's shared quota: limits.TRIAL_SECONDS (three hours, owner,
13 Nov 2026) with no end. ``v2`` is 6,000
seconds or ``TRIAL_DAYS`` (30 days, one month) from the first use, whichever
comes first. Either's longest
call is the one call-length limit (limits.CALL_LIMIT_SECONDS, 23 Oct 2026). Production stays on
``v1`` until the owner's activation step; dev and staging switch at a fixed
UTC instant, before which ``v1`` still applies, so nobody's clock starts
retroactively.

The window's end is computed from the first use on every read, never stored,
so ``TRIAL_DAYS`` moves every running trial at once. A window that had already
ended under the earlier 14 days before ``TRIAL_DAYS_CHANGED_AT`` stays ended:
the change lengthens the trials running then and reopens none.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from ac_platform.billing.projection import Lot, LotKind
from ac_platform.conversation_intelligence.limits import CALL_LIMIT_SECONDS, TRIAL_SECONDS

TrialVersion = Literal["v1", "v2"]
TRIAL_LOT_ID = "trial"
#: The trial's length: one month (owner, 22 Nov 2026: "the Sales X-Ray trial is
#: 1 MONTH (30 days), not 15 days"). The one place the number lives.
TRIAL_DAYS = 30
#: The length before that decision, and the decision's instant (20:15 IST). A v2
#: window whose 14 days had ended by then keeps that end; every later one gets 30.
EARLIER_TRIAL_DAYS = 14
TRIAL_DAYS_CHANGED_AT = datetime(2026, 11, 22, 14, 45, tzinfo=UTC)
_SECONDS = {"v1": TRIAL_SECONDS, "v2": 6000}
_PER_CALL = {"v1": CALL_LIMIT_SECONDS, "v2": CALL_LIMIT_SECONDS}
_DURATION: dict[str, timedelta | None] = {"v1": None, "v2": timedelta(days=TRIAL_DAYS)}


def _window_end(start: datetime, duration: timedelta) -> datetime:
    """``start + duration``, unless the earlier 14-day window had ended before the change."""

    earlier = start + timedelta(days=EARLIER_TRIAL_DAYS)
    return earlier if earlier <= TRIAL_DAYS_CHANGED_AT else max(earlier, start + duration)


def trial_enabled_for_tenant(tenant_id: UUID | None, public_learner_tenant_id: UUID | None) -> bool:
    """Only the public learner tenant receives a derived trial (ADR 0052)."""
    return tenant_id is not None and tenant_id == public_learner_tenant_id


def _aware(moment: datetime, name: str) -> datetime:
    if not isinstance(moment, datetime) or moment.tzinfo is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")
    return moment


@dataclass(frozen=True, slots=True)
class TrialPolicy:
    version: TrialVersion = "v1"
    switch_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.version not in _SECONDS:
            raise ValueError("trial policy version must be v1 or v2")
        if self.switch_at is not None:
            _aware(self.switch_at, "switch_at")
        if self.version == "v1" and self.switch_at is not None:
            raise ValueError("trial policy v1 has no switch time")

    def active_version(self, now: datetime) -> TrialVersion:
        """``v2`` only from its switch instant on; ``v1`` before it."""

        _aware(now, "now")
        if self.version == "v2" and self.switch_at is not None and now < self.switch_at:
            return "v1"
        return self.version

    def seconds(self, now: datetime) -> int:
        return _SECONDS[self.active_version(now)]

    def per_call_seconds(self, now: datetime) -> int:
        """The longest single upload the trial admits."""

        return _PER_CALL[self.active_version(now)]

    def lot(self, *, first_use_at: datetime | None, now: datetime) -> Lot:
        """The derived trial lot for one person or guest.

        The window starts at the first reservation of the person or any guest
        they claimed (or now, when there is none) and, under ``v2``, never
        before the switch instant.
        """

        version = self.active_version(now)
        start = now if first_use_at is None else min(_aware(first_use_at, "first_use_at"), now)
        if version == "v2" and self.switch_at is not None:
            start = max(start, self.switch_at)
        duration = _DURATION[version]
        return Lot(
            lot_id=TRIAL_LOT_ID,
            kind=LotKind.TRIAL,
            seconds=_SECONDS[version],
            valid_from=start,
            expires_at=None if duration is None else _window_end(start, duration),
        )


__all__ = [
    "EARLIER_TRIAL_DAYS",
    "TRIAL_DAYS",
    "TRIAL_DAYS_CHANGED_AT",
    "TRIAL_LOT_ID",
    "TrialPolicy",
    "TrialVersion",
    "trial_enabled_for_tenant",
]
