"""Old leads kept as history (owner, 2 Nov 2026: an owner brings thousands of already-worked
leads into Sales X-Ray "for history", without cluttering today's work).

A history lead is ``lead_desk_leads.pipeline == "history"`` (the 0146 column; empty or
"live" is Inbound, "cold" is Cold). It keeps its own date (``received_at``), stage and
salesperson, and it never sits in a work list: no To Call, Follow-ups or All Leads row or
count, no timer, alert, push, bell line, routing or reassignment. It counts in Analytics.

Reads only: nothing here writes."""

from __future__ import annotations

from typing import Any, Final

from sqlalchemy import func

from ac_platform.lead_desk.models import Lead

HISTORY: Final = "history"
# Leads on neither of these are Inbound: an empty side reads Inbound.
NOT_INBOUND: Final[tuple[str, ...]] = ("cold", HISTORY)


def worked() -> Any:
    """SQL for the leads someone works today: every lead but history."""
    return Lead.pipeline.is_distinct_from(HISTORY)


def inbound_only() -> Any:
    """SQL for Inbound leads: empty or "live", never Cold, never history."""
    return func.coalesce(Lead.pipeline, "live").not_in(NOT_INBOUND)


def is_history(pipeline: str | None) -> bool:
    return pipeline == HISTORY
