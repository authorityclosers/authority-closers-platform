"""Old leads kept as history (owner, 2 Nov 2026: an owner brings thousands of already-worked
leads into Sales X-Ray "for history", without cluttering today's work).

A history lead is ``lead_desk_leads.pipeline == "history"`` (the 0146 column; empty or
"live" is Inbound, "cold" is Cold). It keeps its own date (``received_at``), stage and
salesperson, and it never sits in a work list: no To Call, Follow-ups or All Leads row or
count, no timer, alert, push, bell line, routing or reassignment. It counts in Analytics.

Reads only: nothing here writes."""

from __future__ import annotations

from typing import Any, Final

from sqlalchemy import and_, func

from ac_platform.lead_desk.models import Lead

HISTORY: Final = "history"
# Leads on neither of these are Inbound: an empty side reads Inbound.
NOT_INBOUND: Final[tuple[str, ...]] = ("cold", HISTORY)


def on_desk() -> Any:
    """SQL for leads neither archived nor in the Bin (migration 0158, shelf.py): an archived
    or binned lead is in no work list, count, queue, timer or push, like history."""
    return and_(Lead.archived_at.is_(None), Lead.binned_at.is_(None))


def worked() -> Any:
    """SQL for the leads someone works today: every lead but history, archived or binned."""
    return and_(Lead.pipeline.is_distinct_from(HISTORY), on_desk())


def inbound_only() -> Any:
    """SQL for Inbound leads: empty or "live", never Cold, never history, archived or
    binned."""
    return and_(func.coalesce(Lead.pipeline, "live").not_in(NOT_INBOUND), on_desk())


def is_history(pipeline: str | None) -> bool:
    return pipeline == HISTORY
