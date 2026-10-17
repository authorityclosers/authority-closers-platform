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

from datetime import datetime, timedelta
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


# A lead is overdue when its next call is more than an hour late. A new lead's
# first call is due the moment it arrives (UX study, 17 Oct 2026).
OVERDUE_AFTER: Final[timedelta] = timedelta(hours=1)
# The desk's "Coming up" list: the next few days, after today.
UPCOMING_DAYS: Final[int] = 7

Channel = Literal["whatsapp", "sms"]
CHANNELS: Final[tuple[Channel, ...]] = ("whatsapp", "sms")
CHANNEL_LABELS: Final[dict[str, str]] = {"whatsapp": "WhatsApp", "sms": "SMS"}

# Ready messages on the lead and after a call (Privyr's quick responses, NeoDove's
# after-call templates). The page fills {first_name}, {my_name}, {org} and
# {about_interest} (" about <interest>", or nothing); the seller reads it,
# changes it if they like, and sends it from their own WhatsApp or SMS. Only
# the template's key is kept on the lead's history, never the text. An editor
# for these comes later.
MESSAGE_TEMPLATES: Final[tuple[tuple[str, str, str], ...]] = (
    (
        "intro",
        "Introduction",
        "Hi {first_name}, this is {my_name} from {org}. Thanks for your enquiry"
        "{about_interest}. When is a good time to call you?",
    ),
    (
        "missed_call",
        "Tried calling",
        "Hi {first_name}, this is {my_name} from {org}. I tried calling you just now."
        " When is a good time to talk?",
    ),
    (
        "follow_up",
        "Following up",
        "Hi {first_name}, just following up on your enquiry{about_interest}. Is this a good"
        " time for a quick call? - {my_name}, {org}",
    ),
    (
        "as_promised",
        "As promised",
        "Hi {first_name}, thank you for your time today. As promised, here are the details:",
    ),
)
TEMPLATE_KEYS: Final[frozenset[str]] = frozenset(key for key, _, _ in MESSAGE_TEMPLATES)
TEMPLATE_LABELS: Final[dict[str, str]] = {key: label for key, label, _ in MESSAGE_TEMPLATES}


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


def due_at(stage: str, next_action_at: datetime | None, created_at: datetime) -> datetime | None:
    """When the lead's next call is due: its follow-up time, or a new lead's arrival."""
    if stage in CLOSED_STAGES:
        return None
    if next_action_at is not None:
        return next_action_at
    return created_at if stage == "new" else None


def is_overdue(
    stage: str, next_action_at: datetime | None, created_at: datetime, now: datetime
) -> bool:
    due = due_at(stage, next_action_at, created_at)
    return due is not None and due < now - OVERDUE_AFTER
