"""Campaigns and their status (owner, 2 Nov 2026: "live, paused and old campaigns managed so
the app isn't cluttered"; design approved by ux-audit and the orchestrator that day).

A lead's campaign is what its source says: a Meta form's campaign name, a website form's
``utm_campaign``, else the lead's own source label (a file's Campaign or Source column, a
sheet or form's name). Each campaign is Live, Paused or Ended. The status is the owner's
word, kept in the workspace's Lead Desk settings; a campaign nobody has set reads Live, or
Ended when every lead in it is history. What a status changes beyond Analytics' grouping
is the sources' own switch (a sheet, form or website turned off), never a dropped
enquiry."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final, Literal

from sqlalchemy import func

from ac_platform.lead_desk.contracts import CampaignStatusCommand
from ac_platform.lead_desk.errors import DeskError
from ac_platform.lead_desk.models import Lead, LeadDeskSettings

if TYPE_CHECKING:
    from ac_platform.lead_desk.store import LeadDesk

Status = Literal["live", "paused", "ended"]
STATUSES: Final[tuple[Status, ...]] = ("live", "paused", "ended")
KEY: Final = "campaigns"
MAX_CAMPAIGNS: Final = 500


def label_sql() -> Any:
    """SQL for a lead's campaign name: the ad's, the website visit's, else its label."""
    return func.coalesce(
        func.nullif(func.trim(Lead.payload[("meta", "campaign_name")].as_string()), ""),
        func.nullif(func.trim(Lead.payload[("attribution", "utm_campaign")].as_string()), ""),
        Lead.source_label,
    )


def campaign_key(source: str, label: str | None) -> str:
    """One campaign's key: its source and its name, spaces and case aside."""
    name = " ".join((label or "").split()).casefold()[:120]
    return f"{source}:{name}" if name else source


def statuses(config: dict[str, Any]) -> dict[str, Status]:
    """The owner's word on each campaign, from the workspace's settings."""
    found = config.get(KEY)
    if not isinstance(found, dict):
        return {}
    out: dict[str, Status] = {}
    for key, value in found.items():
        status = value.get("status") if isinstance(value, dict) else None
        if isinstance(key, str) and status in STATUSES:
            out[key] = status
    return out


def status_of(said: dict[str, Status], key: str, *, history_only: bool) -> Status:
    """A campaign's status: the owner's word, else Ended for old leads only, else Live."""
    return said.get(key) or ("ended" if history_only else "live")


async def set_status(desk: LeadDesk, command: CampaignStatusCommand) -> int:
    """An owner or admin marks one campaign Live, Paused or Ended. Returns the settings'
    new revision; a stale revision is refused, as for every team setting."""
    desk._require_manager()
    row = await desk.db.get(LeadDeskSettings, desk.tenant_id, with_for_update=True)
    current = row.revision if row else 0
    if current != command.expected_revision:
        raise DeskError(409, "Someone changed these settings. Reload and try again.")
    config = dict(row.config) if row else {}
    campaigns = dict(config.get(KEY) or {})
    if command.key not in campaigns and len(campaigns) >= MAX_CAMPAIGNS:
        raise DeskError(422, "Too many campaigns have a status. Set an older one back to Live.")
    campaigns[command.key] = {
        "status": command.status,
        "at": desk.now.isoformat(),
        "by": str(desk.viewer.person_id),
    }
    config[KEY] = campaigns
    if row is None:
        row = LeadDeskSettings(tenant_id=desk.tenant_id, revision=0, config={})
        desk.db.add(row)
    row.revision = current + 1
    row.config = config
    row.updated_by_person_id = desk.viewer.person_id
    row.updated_at = desk.now
    await desk.db.flush()
    return row.revision
