"""Pure contracts and projections for the bounded planning proposal."""

from __future__ import annotations

from enum import StrEnum
from typing import TypedDict


class PlanPeriod(StrEnum):
    """Presentation labels, not date arithmetic or a generated schedule."""

    TODAY = "today"
    WEEK = "week"
    MONTH = "month"


class AnalyticsEventDefinition(TypedDict):
    event_version: str
    allowed_payload_keys: tuple[str, ...]
    requires_period: bool


PROPOSED_ANALYTICS_EVENTS: dict[str, AnalyticsEventDefinition] = {
    "analytics.plan_viewed": {
        "event_version": "1.0",
        "allowed_payload_keys": ("period",),
        "requires_period": True,
    },
    "analytics.plan_period_selected": {
        "event_version": "1.0",
        "allowed_payload_keys": ("period",),
        "requires_period": True,
    },
    "analytics.up_next_opened": {
        "event_version": "1.0",
        "allowed_payload_keys": (),
        "requires_period": False,
    },
    "analytics.progress_viewed": {
        "event_version": "1.0",
        "allowed_payload_keys": (),
        "requires_period": False,
    },
    "analytics.insight_viewed": {
        "event_version": "1.0",
        "allowed_payload_keys": (),
        "requires_period": False,
    },
}


__all__ = ["AnalyticsEventDefinition", "PROPOSED_ANALYTICS_EVENTS", "PlanPeriod"]
