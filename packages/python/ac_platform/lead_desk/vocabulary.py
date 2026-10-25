"""The Lead Desk's words, copied from NeoDove's call-and-dispose loop (15 Oct decision).

After every call the seller answers "Was the call connected?":

- Not connected: pick one of ten fixed reasons (NeoDove's list). The desk
  schedules the retry for the first seven reasons (after 1 hour, then after
  1 day); the last three (bad numbers) get no automatic retry.
- Connected: pick the lead's stage. Won and Lost close the lead; Follow-up
  and Interested need a next follow-up date and time.

Junk (Lead OS, 24 Oct 2026) is the seventh desk stage: a fake, invalid or unusable
lead. It is closed like Won and Lost but kept apart from both, so it never counts as a
lost sale. A lead is never made Junk because calls went unanswered; a seller marks it,
with a reason.

Evidence: docs/product/lead-desk/neodove-evidence.md (section 1.6 and 9.1).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Final, Literal

Stage = Literal["new", "not_connected", "follow_up", "interested", "won", "lost", "junk"]
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
    "junk",
)
OPEN_STAGES: Final[frozenset[str]] = frozenset({"new", "not_connected", "follow_up", "interested"})
CLOSED_STAGES: Final[frozenset[str]] = frozenset({"won", "lost", "junk"})
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
    "junk": "Junk",
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
# Why a lead was lost, and why it is junk (Lead OS, 24 Oct 2026). A business's own
# stage list may carry its own lists; these are the defaults. "other" always needs a
# note. The first five lost reasons are the sales team's own list; price, not now and
# not a fit let a call's objection name a reason.
OTHER_REASON: Final[str] = "other"
LOST_REASONS: Final[tuple[tuple[str, str], ...]] = (
    ("not_interested", "Not interested"),
    ("chose_other", "Chose another provider"),
    ("declined_offer", "Declined the offer"),
    ("decided_not_to_proceed", "Decided not to proceed"),
    ("no_response", "No response after follow-ups"),
    ("price", "Price or budget"),
    ("not_now", "Not the right time"),
    ("not_a_fit", "Not a fit"),
    (OTHER_REASON, "Other"),
)
# A lead that was never real, where the stage list has no Junk of its own (the sales team's
# eight stages, owner, 25 Oct 2026): Lost with this reason.
NOT_A_LEAD: Final[str] = "not_a_lead"
SALES_LOST_REASONS: Final[tuple[tuple[str, str], ...]] = (
    *LOST_REASONS[:-1],
    (NOT_A_LEAD, "Junk / not a real lead"),
    LOST_REASONS[-1],
)
JUNK_REASONS: Final[tuple[tuple[str, str], ...]] = (
    ("fake", "Fake enquiry"),
    ("invalid_number", "Wrong or invalid number"),
    ("someone_else", "Number belongs to someone else"),
    ("unusable_contact", "Contact details unusable"),
    ("unreachable_verified", "Switched off or unreachable after checks"),
    ("spam_test", "Spam or test entry"),
    (OTHER_REASON, "Other"),
)
# Lost leads that come in by import have no reason given (DESIGN §2.4).
IMPORTED_LOST: Final[str] = "imported"
# A lead merged into another is Junk with this reason (duplicates; the lead it went into
# carries its history on).
MERGED_DUPLICATE: Final[str] = "merged"
MERGED_WORDS: Final[str] = "Merged into another lead"

# The reply drafted after a call in the call's language (call_data.reply): its words
# come with the lead's facts, and like the others only its key is kept.
AFTER_CALL_REPLY: Final[str] = "after_call"
TEMPLATE_KEYS: Final[frozenset[str]] = frozenset(
    {*(key for key, _, _ in MESSAGE_TEMPLATES), AFTER_CALL_REPLY}
)
TEMPLATE_LABELS: Final[dict[str, str]] = {
    **{key: label for key, label, _ in MESSAGE_TEMPLATES},
    AFTER_CALL_REPLY: "After the call",
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
    """A lead keeps a stage it already earned; an unreached lead becomes Not connected.

    A closed lead (Won, Lost or Junk) stays closed: an unanswered call never reopens
    it, and never makes a lead Junk (the sales team's spec, 24 Oct 2026)."""
    if current in {"follow_up", "interested"} or current in CLOSED_STAGES:
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
