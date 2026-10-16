"""The Lead Desk's words, copied from NeoDove's call-and-dispose loop (15 Oct decision).

After every call the seller answers "Was the call connected?":

- Not connected: pick one of ten fixed reasons (NeoDove's list). The desk
  schedules the retry for the first seven reasons (after 1 hour, then after
  1 day); the last three (bad numbers) get no automatic retry.
- Connected: pick the lead's stage. Won and Lost close the lead; Follow-up
  and Interested need a next follow-up date and time.

Evidence: docs/product/lead-desk/neodove-evidence.md (section 1.6 and 9.1).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Final, Literal

Stage = Literal["new", "not_connected", "follow_up", "interested", "won", "lost"]
ConnectedStage = Literal["follow_up", "interested", "won", "lost"]
Reason = Literal[
    "did_not_pick",
    "busy",
    "disconnected",
    "switched_off",
    "out_of_coverage",
    "not_connected",
    "other",
    "invalid_number",
    "incoming_not_available",
    "not_in_use",
]
Source = Literal["manual", "referral", "csv", "sheet", "webhook", "meta", "synthetic"]

STAGES: Final[tuple[Stage, ...]] = (
    "new",
    "not_connected",
    "follow_up",
    "interested",
    "won",
    "lost",
)
OPEN_STAGES: Final[frozenset[str]] = frozenset({"new", "not_connected", "follow_up", "interested"})
CLOSED_STAGES: Final[frozenset[str]] = frozenset({"won", "lost"})
CONNECTED_STAGES: Final[tuple[ConnectedStage, ...]] = ("follow_up", "interested", "won", "lost")
NEEDS_FOLLOW_UP: Final[frozenset[str]] = frozenset({"follow_up", "interested"})
REASONS: Final[tuple[Reason, ...]] = (
    "did_not_pick",
    "busy",
    "disconnected",
    "switched_off",
    "out_of_coverage",
    "not_connected",
    "other",
    "invalid_number",
    "incoming_not_available",
    "not_in_use",
)
# NeoDove turns automatic retries off for these by default.
NO_RETRY: Final[frozenset[str]] = frozenset(
    {"invalid_number", "incoming_not_available", "not_in_use"}
)
SOURCES: Final[tuple[Source, ...]] = (
    "manual",
    "referral",
    "csv",
    "sheet",
    "webhook",
    "meta",
    "synthetic",
)

STAGE_LABELS: Final[dict[str, str]] = {
    "new": "New",
    "not_connected": "Not connected",
    "follow_up": "Follow-up",
    "interested": "Interested",
    "won": "Won",
    "lost": "Lost",
}
REASON_LABELS: Final[dict[str, str]] = {
    "did_not_pick": "Did not pick",
    "busy": "Busy in another call",
    "disconnected": "Disconnected the call",
    "switched_off": "Switched off",
    "out_of_coverage": "Out of coverage / network issue",
    "not_connected": "Call could not be completed",
    "other": "Other reason",
    "invalid_number": "Invalid number",
    "incoming_not_available": "Incoming calls not available",
    "not_in_use": "Number not in use",
}
SOURCE_LABELS: Final[dict[str, str]] = {
    "manual": "Added by hand",
    "referral": "Referral",
    "csv": "File upload",
    "sheet": "Google Sheet",
    "webhook": "Website form",
    "meta": "Meta lead form",
    "synthetic": "Test data",
}


def retry_after(reason: str, attempts: int) -> timedelta | None:
    """NeoDove's default retry logic: first retry after 1 hour, later ones after 1 day."""
    if reason in NO_RETRY:
        return None
    return timedelta(hours=1) if attempts <= 1 else timedelta(days=1)


def stage_after_connected(stage: str) -> str:
    if stage not in CONNECTED_STAGES:
        raise ValueError("Choose Follow-up, Interested, Won or Lost.")
    return stage


def stage_after_not_connected(current: str) -> str:
    """A lead keeps a stage it already earned; an unreached lead becomes Not connected."""
    if current in {"follow_up", "interested"}:
        return current
    return "not_connected"
