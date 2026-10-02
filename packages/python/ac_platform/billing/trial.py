"""The trial policy: a derived lot, never a stored ledger row (ADR 0052, section A/D).

``v1`` is today's shared quota: 3,600 seconds with no end and a 6,000-second
longest upload. ``v2`` is 6,000 seconds or 14 days from the first use,
whichever comes first, with a 3,600-second longest call. Production stays on
``v1`` until the owner's activation step; dev and staging switch at a fixed
UTC instant, before which ``v1`` still applies, so nobody's clock starts
retroactively.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from ac_platform.billing.projection import Lot, LotKind

TrialVersion = Literal["v1", "v2"]
TRIAL_LOT_ID = "trial"
_SECONDS = {"v1": 3600, "v2": 6000}
_PER_CALL = {"v1": 6000, "v2": 3600}
_DURATION: dict[str, timedelta | None] = {"v1": None, "v2": timedelta(days=14)}


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
            expires_at=None if duration is None else start + duration,
        )


__all__ = ["TRIAL_LOT_ID", "TrialPolicy", "TrialVersion"]
