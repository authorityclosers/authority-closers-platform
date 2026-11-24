"""The trial policy: a derived lot, never a stored ledger row (ADR 0052, section A/D).

``v1`` is the shared quota: limits.TRIAL_SECONDS (three hours, owner, 13 Nov 2026)
with no end. ``v2`` is the owner's "1 month + 3 hours" (22 Nov 2026): the same
three hours, or a number of days from the first use (``MONTH_TRIAL_DAYS``, or
``TRIAL_DAYS`` = 15 for a trial that starts from ``fifteen_days_from`` on),
whichever comes first.
Either's longest call is the one call-length limit (limits.CALL_LIMIT_SECONDS,
23 Oct 2026).

An environment moves from v1 to v2 at a fixed UTC instant (the setting
``sales_xray_trial_policy_switch_at``), before which ``v1`` still applies. Nobody
loses access at the switch: someone who started under v1 gets their month from the
switch instant, not from their first use, and the minutes they used before it
still count toward the three hours (the lot is valid from their first use, so
their earlier use is allocated to it). Someone new gets the month from their
first use.

The window's end is computed on every read, never stored, so ``MONTH_TRIAL_DAYS``
moves every running month-long trial at once. A window that had already ended
under the earlier 14 days before ``TRIAL_DAYS_CHANGED_AT`` stays ended: that change
lengthened the trials running then and reopened none.

From the instant ``fifteen_days_from`` (the setting
``sales_xray_trial_15_days_from``) a new trial is ``TRIAL_DAYS`` (15 days) or the
same three hours, whichever ends first (owner, 25 Nov 2026: "fifteen days or three
hours, no card, whichever ends"). A window that started before that instant keeps
its month: nobody's running trial gets shorter. Without the instant every window
keeps the month (the policy before 25 Nov).
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
#: A new trial's length (owner, 25 Nov 2026: "fifteen days or three hours, no card,
#: whichever ends"), from the policy's ``fifteen_days_from`` instant on.
TRIAL_DAYS = 15
#: The month every trial that started before that instant keeps (owner, 22 Nov 2026:
#: "the Sales X-Ray trial is 1 MONTH (30 days)").
MONTH_TRIAL_DAYS = 30
#: The length before that decision, and the decision's instant (20:15 IST). A v2
#: window whose 14 days had ended by then keeps that end; every later one gets 30.
EARLIER_TRIAL_DAYS = 14
TRIAL_DAYS_CHANGED_AT = datetime(2026, 11, 22, 14, 45, tzinfo=UTC)
_SECONDS = {"v1": TRIAL_SECONDS, "v2": TRIAL_SECONDS}
_PER_CALL = {"v1": CALL_LIMIT_SECONDS, "v2": CALL_LIMIT_SECONDS}
_TIMED = {"v1": False, "v2": True}


def _month_end(start: datetime) -> datetime:
    """``start`` + one month, unless the earlier 14-day window had ended before that change."""

    earlier = start + timedelta(days=EARLIER_TRIAL_DAYS)
    month = start + timedelta(days=MONTH_TRIAL_DAYS)
    return earlier if earlier <= TRIAL_DAYS_CHANGED_AT else max(earlier, month)


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
    fifteen_days_from: datetime | None = None

    def __post_init__(self) -> None:
        if self.version not in _SECONDS:
            raise ValueError("trial policy version must be v1 or v2")
        if self.switch_at is not None:
            _aware(self.switch_at, "switch_at")
        if self.version == "v1" and self.switch_at is not None:
            raise ValueError("trial policy v1 has no switch time")
        if self.fifteen_days_from is not None:
            _aware(self.fifteen_days_from, "fifteen_days_from")
            if self.version != "v2":
                raise ValueError("only trial policy v2 has days")

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

    def _window_start(self, first: datetime) -> datetime:
        return first if self.switch_at is None else max(first, self.switch_at)

    def _days_of(self, window_start: datetime) -> int:
        fifteen = self.fifteen_days_from
        return TRIAL_DAYS if fifteen is not None and window_start >= fifteen else MONTH_TRIAL_DAYS

    def lot(self, *, first_use_at: datetime | None, now: datetime) -> Lot:
        """The derived trial lot for one person or guest.

        It is valid from the first reservation of the person or any guest they
        claimed (or now, when there is none). Under ``v2`` its days run from
        that first use, or from the switch instant for someone who started
        before it, so nobody's clock starts retroactively: 15 days for a window
        that starts from ``fifteen_days_from`` on, a month for one before it.
        """

        version = self.active_version(now)
        first = now if first_use_at is None else min(_aware(first_use_at, "first_use_at"), now)
        expires_at = None
        if _TIMED[version]:
            start = self._window_start(first)
            days = self._days_of(start)
            expires_at = start + timedelta(days=days) if days == TRIAL_DAYS else _month_end(start)
        return Lot(
            lot_id=TRIAL_LOT_ID,
            kind=LotKind.TRIAL,
            seconds=_SECONDS[version],
            valid_from=first,
            expires_at=expires_at,
        )

    def days(self, lot: Lot) -> int | None:
        """The trial's length in days, as the person was told it (15, or 30 for a
        month that started before ``fifteen_days_from``); None when it has no end."""

        if lot.expires_at is None:
            return None
        return self._days_of(self._window_start(lot.valid_from))


__all__ = [
    "EARLIER_TRIAL_DAYS",
    "MONTH_TRIAL_DAYS",
    "TRIAL_DAYS",
    "TRIAL_DAYS_CHANGED_AT",
    "TRIAL_LOT_ID",
    "TrialPolicy",
    "TrialVersion",
    "trial_enabled_for_tenant",
]
