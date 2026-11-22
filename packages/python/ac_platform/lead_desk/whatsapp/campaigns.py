"""WhatsApp campaigns in the Sales Xray CRM: drip sequences and broadcasts, and their numbers
(owner, 17 Nov 2026: "all of these four, get them all live").

- A **sequence** is up to ten steps on a timer (e.g. day 0 the brochure, day 2 a case
  study, day 5 "shall we talk?"), each an approved template, with a file when the template
  has a file header. A lead joins when they arrive (``trigger`` "new_lead": leads arriving
  one by one, never a file or sheet import) or when they move into a stage ("stage").
  It stops for that lead when they reply, move stage, say STOP or leave Lead Desk.
- A **broadcast** is one approved template to a chosen list (stages, sources, owners or
  named leads), at a set time and pace. Only people with a recorded yes to WhatsApp get it
  (a lead form's yes, a message from them, or the seller's record), never a recorded no; the
  proof is kept per person as it stood when the list was made.
- A sequence needs a recorded yes too, unless a manager confirms that everyone who reaches
  them agreed to WhatsApp (kept with who and when, as for the first reply).
- **Numbers** per campaign: on the list, skipped (and why), sent, delivered, read, failed,
  replied (they wrote after it) and won (the lead is in the Won stage now), from Meta's
  delivery statuses on the webhook.

Sending happens in the WhatsApp loop (runner.py), one pass at a time across API processes.
A campaign is live, paused or ended; a broadcast ends by itself once everyone is done.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Final
from uuid import UUID, uuid4, uuid5

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.lead_desk import outreach
from ac_platform.lead_desk.models import (
    Lead,
    LeadEvent,
    LeadWhatsAppCampaign,
    LeadWhatsAppCampaignLead,
    LeadWhatsAppMedia,
    LeadWhatsAppMessage,
    LeadWhatsAppNumber,
)
from ac_platform.lead_desk.store import DeskError, LeadDesk, Viewer
from ac_platform.lead_desk.whatsapp import cloud, inbox

log = logging.getLogger(__name__)

KINDS: Final[tuple[str, ...]] = ("broadcast", "sequence")
TRIGGERS: Final[tuple[str, ...]] = ("new_lead", "stage")
STEP_LIMIT: Final[int] = 10
LONGEST: Final[timedelta] = timedelta(days=90)
BROADCAST_LIMIT: Final[int] = 5000
JOIN_WITHIN: Final[timedelta] = timedelta(minutes=30)
TICK_SECONDS: Final[int] = 30
SEND_LIMIT_PER_TICK: Final[int] = 300
# The words a value may carry; filled per lead when it goes out.
TOKENS: Final[dict[str, str]] = {"{name}": "first name", "{business}": "business name"}
STOP_WORDS: Final[dict[str, str]] = {
    "replied": "replied",
    "stage": "moved stage",
    "said_stop": "asked not to be messaged",
    "gone": "left Lead Desk",
    "ended": "campaign ended",
}
SKIP_WORDS: Final[dict[str, str]] = {
    **inbox.SKIP_WORDS,
    # The outreach limits held it (v1.95, outreach.py).
    "outreach_limit": "held by the outreach limits",
}
OUTREACH_LIMIT: Final = "outreach_limit"


# ----- checking what a manager asks for ---------------------------------------------------


@dataclass(frozen=True, slots=True)
class Plan:
    ready: list[tuple[Lead, dict[str, Any]]] = field(default_factory=list)
    skipped: dict[str, int] = field(default_factory=dict)
    skipped_leads: list[tuple[Lead, str]] = field(default_factory=list)


def _clean_values(values: Any, needed: int) -> list[str]:
    cleaned = [" ".join(str(value).split())[:200] for value in list(values or [])[:10]]
    if not cleaned and needed:
        cleaned = ["{name}", "{business}"][:needed]
    return cleaned


async def check_steps(
    db: AsyncSession,
    row: LeadWhatsAppNumber,
    raw: Sequence[Mapping[str, Any]],
    *,
    kind: str,
) -> list[dict[str, Any]]:
    """The steps as stored: each an approved template (with a file of the right kind when
    its header carries one), its values, and minutes after the lead joined."""
    if not raw:
        raise DeskError(422, "Add at least one message.")
    if kind == "broadcast" and len(raw) != 1:
        raise DeskError(422, "A broadcast sends one message.")
    if len(raw) > STEP_LIMIT:
        raise DeskError(422, f"Keep a sequence to {STEP_LIMIT} messages.")
    approved = {(t.name, t.language): t for t in await inbox.approved_templates(db, row)}
    steps: list[dict[str, Any]] = []
    last = -1
    for item in raw:
        pair = (str(item.get("template") or ""), str(item.get("language") or ""))
        chosen = approved.get(pair)
        if chosen is None:
            raise DeskError(422, f"Pick an approved template ({pair[0] or 'none'}).")
        minutes = int(item.get("after_minutes") or 0) if kind == "sequence" else 0
        if minutes < 0 or minutes > LONGEST.total_seconds() // 60:
            raise DeskError(422, "Space the messages up to 90 days apart.")
        if minutes < last:
            raise DeskError(422, "Put the messages in time order.")
        last = minutes
        needed = cloud.placeholders(cloud.template_text(chosen.components))
        values = _clean_values(item.get("values"), needed)
        if len([value for value in values if value]) < needed:
            raise DeskError(422, f"Fill in all {needed} parts of {pair[0]}.")
        header = cloud.media_header(chosen.components)
        media_id = item.get("media_id")
        if header is not None:
            if media_id is None:
                raise DeskError(422, f"{pair[0]} sends a {header}: pick the file.")
            media = await db.get(LeadWhatsAppMedia, UUID(str(media_id)))
            if media is None or media.tenant_id != row.tenant_id or media.archived_at:
                raise DeskError(422, "Pick a file from your WhatsApp files.")
            if media.kind != header:
                raise DeskError(422, f"{pair[0]} sends a {header}: pick a {header}.")
        elif media_id is not None:
            raise DeskError(422, f"{pair[0]} has no file in it: pick a template with a file.")
        steps.append(
            {
                "template": pair[0],
                "language": pair[1],
                "values": values[:10],
                "media_id": str(media_id) if header is not None else None,
                "after_minutes": minutes,
            }
        )
    return steps


def fill_values(values: Sequence[str], lead: Lead, business: str) -> list[str]:
    first = inbox.first_name(lead.name)
    return [str(value).replace("{name}", first).replace("{business}", business) for value in values]


async def _proof(
    db: AsyncSession, lead: Lead, rules: Mapping[str, Any], *, now: datetime
) -> tuple[str | None, dict[str, Any] | None]:
    """Why this lead may get it (their recorded yes, as it stands now), or why not."""
    if cloud.wa_id(lead.phone) is None:
        return "no_whatsapp", None
    agreed, how = await inbox.opt_in_state(db, lead, rules)
    if agreed:
        return None, {"how": how, "at": now.isoformat()}
    return ("said_stop" if how else "no_yes"), None


# ----- broadcasts -------------------------------------------------------------------------


async def audience(desk: LeadDesk, filters: Mapping[str, Any]) -> list[Lead]:
    """The leads a broadcast's filters choose (stages, sources, owners, named leads, a city,
    arrived since), never binned ones; at most 5,000."""
    query = select(Lead).where(Lead.tenant_id == desk.tenant_id, Lead.binned_at.is_(None))
    stages = [str(s) for s in filters.get("stages") or []][:20]
    sources = [str(s) for s in filters.get("sources") or []][:20]
    owners = [UUID(str(o)) for o in filters.get("owners") or []][:50]
    named = [UUID(str(i)) for i in filters.get("lead_ids") or []][:BROADCAST_LIMIT]
    if stages:
        query = query.where(Lead.stage.in_(stages))
    if sources:
        query = query.where(Lead.source.in_(sources))
    if owners:
        query = query.where(Lead.owner_person_id.in_(owners))
    if named:
        query = query.where(Lead.id.in_(named))
    if filters.get("city"):
        query = query.where(func.lower(Lead.city) == str(filters["city"]).strip().lower())
    if filters.get("since"):
        query = query.where(Lead.created_at >= datetime.fromisoformat(str(filters["since"])))
    if not (stages or sources or owners or named or filters.get("city") or filters.get("since")):
        raise DeskError(422, "Choose who gets it: stages, sources, owners or leads.")
    return list(
        (await desk.db.scalars(query.order_by(Lead.created_at).limit(BROADCAST_LIMIT + 1))).all()
    )


async def plan(desk: LeadDesk, row: LeadWhatsAppNumber, leads: Sequence[Lead]) -> Plan:
    rules = inbox.number_config(row)["first_reply"]
    out = Plan()
    for lead in leads:
        reason, proof = await _proof(desk.db, lead, rules, now=desk.now)
        if reason:
            out.skipped[reason] = out.skipped.get(reason, 0) + 1
            out.skipped_leads.append((lead, reason))
        else:
            out.ready.append((lead, proof or {}))
    return out


# ----- making, pausing and ending ---------------------------------------------------------


async def create(
    desk: LeadDesk,
    *,
    kind: str,
    name: str,
    number_id: UUID | None,
    steps: Sequence[Mapping[str, Any]],
    trigger: Mapping[str, Any] | None,
    filters: Mapping[str, Any] | None,
    send_at: datetime | None,
    per_minute: int,
    command_id: UUID,
    confirm: int | None,
    agreed: bool,
    dry_run: bool = False,
) -> tuple[LeadWhatsAppCampaign | None, Plan]:
    """A manager starts a broadcast or a sequence (``dry_run``: only who it would reach)."""
    desk._require_manager()
    if kind not in KINDS:
        raise DeskError(422, "Pick a broadcast or a sequence.")
    if not dry_run:
        seen = await desk.db.scalar(
            select(LeadWhatsAppCampaign).where(
                LeadWhatsAppCampaign.tenant_id == desk.tenant_id,
                LeadWhatsAppCampaign.command_id == command_id,
            )
        )
        if seen is not None:
            return seen, Plan()
    words = " ".join(name.split())[:80]
    if not words:
        raise DeskError(422, "Name it, e.g. Diwali offer or New lead follow-up.")
    rows = await inbox.numbers(desk.db, desk.tenant_id)
    row = next((r for r in rows if number_id in (None, r.id)), None)
    if row is None:
        raise DeskError(409, "Connect a WhatsApp number in Settings → Integrations first.")
    stored = await check_steps(desk.db, row, steps, kind=kind)
    if not 1 <= per_minute <= 600:
        raise DeskError(422, "Send between 1 and 600 a minute.")
    found = Plan()
    shape: dict[str, Any]
    if kind == "broadcast":
        leads = await audience(desk, filters or {})
        if len(leads) > BROADCAST_LIMIT:
            raise DeskError(422, f"Send to {BROADCAST_LIMIT:,} leads or fewer at a time.")
        found = await plan(desk, row, leads)
        if dry_run:
            return None, found
        if confirm != len(found.ready):
            raise DeskError(409, "Who gets it changed since you checked. Check again.")
        if not found.ready:
            raise DeskError(422, "Nobody on this list has said yes to WhatsApp yet.")
        shape = {"filters": dict(filters or {}), "listed": len(leads)}
    else:
        rule = dict(trigger or {})
        on = str(rule.get("on") or "new_lead")
        if on not in TRIGGERS:
            raise DeskError(422, "Start it when a lead arrives or moves into a stage.")
        stage = str(rule.get("stage") or "").strip()[:16] or None
        if on == "stage" and not stage:
            raise DeskError(422, "Pick the stage that starts it.")
        shape = {
            "trigger": {"on": on, "stage": stage if on == "stage" else None},
            "agreed_by": str(desk.viewer.person_id) if agreed else None,
            "agreed_at": desk.now.isoformat() if agreed else None,
        }
        if dry_run:
            return None, found
    campaign = LeadWhatsAppCampaign(
        id=uuid4(),
        tenant_id=desk.tenant_id,
        number_id=row.id,
        kind=kind,
        name=words,
        status="live",
        steps=stored,
        audience=shape,
        send_at=(send_at or desk.now) if kind == "broadcast" else None,
        per_minute=per_minute,
        command_id=command_id,
        created_by_person_id=desk.viewer.person_id,
        created_at=desk.now,
        updated_at=desk.now,
    )
    desk.db.add(campaign)
    await desk.db.flush()
    if kind == "broadcast":
        due = campaign.send_at or desk.now
        for lead, proof in found.ready:
            _join(campaign, lead, proof, next_at=due, now=desk.now, db=desk.db)
        for lead, reason in found.skipped_leads:
            desk.db.add(
                LeadWhatsAppCampaignLead(
                    id=uuid4(),
                    tenant_id=desk.tenant_id,
                    campaign_id=campaign.id,
                    lead_id=lead.id,
                    step=0,
                    status="skipped",
                    next_at=None,
                    stage_at_start=lead.stage,
                    reason=reason,
                    proof=None,
                    created_at=desk.now,
                    updated_at=desk.now,
                )
            )
        await desk.db.flush()
    return campaign, found


def _join(
    campaign: LeadWhatsAppCampaign,
    lead: Lead,
    proof: Mapping[str, Any],
    *,
    next_at: datetime,
    now: datetime,
    db: AsyncSession,
) -> None:
    db.add(
        LeadWhatsAppCampaignLead(
            id=uuid4(),
            tenant_id=campaign.tenant_id,
            campaign_id=campaign.id,
            lead_id=lead.id,
            step=0,
            status="waiting",
            next_at=next_at,
            stage_at_start=lead.stage,
            reason=None,
            proof=dict(proof),
            created_at=now,
            updated_at=now,
        )
    )


async def one(db: AsyncSession, tenant_id: UUID, campaign_id: UUID) -> LeadWhatsAppCampaign:
    campaign = await db.get(LeadWhatsAppCampaign, campaign_id)
    if campaign is None or campaign.tenant_id != tenant_id:
        raise DeskError(404, "That campaign isn't here.")
    return campaign


async def set_status(desk: LeadDesk, campaign_id: UUID, status: str) -> LeadWhatsAppCampaign:
    """Pause, resume or end a campaign. Ending stops everyone still waiting."""
    desk._require_manager()
    campaign = await one(desk.db, desk.tenant_id, campaign_id)
    if status not in ("live", "paused", "ended"):
        raise DeskError(422, "Pick live, paused or ended.")
    if campaign.status == "ended":
        if status == "ended":
            return campaign
        raise DeskError(409, "This campaign has ended. Start a new one.")
    campaign.status = status
    campaign.updated_at = desk.now
    if status == "ended":
        campaign.ended_at = desk.now
        await _stop_waiting(desk.db, campaign.id, "ended", now=desk.now)
    await desk.db.flush()
    return campaign


async def _stop_waiting(db: AsyncSession, campaign_id: UUID, reason: str, *, now: datetime) -> None:
    for row in (
        await db.scalars(
            select(LeadWhatsAppCampaignLead).where(
                LeadWhatsAppCampaignLead.campaign_id == campaign_id,
                LeadWhatsAppCampaignLead.status == "waiting",
            )
        )
    ).all():
        row.status, row.reason, row.next_at, row.updated_at = "stopped", reason, None, now


async def listing(db: AsyncSession, tenant_id: UUID) -> list[LeadWhatsAppCampaign]:
    return list(
        (
            await db.scalars(
                select(LeadWhatsAppCampaign)
                .where(LeadWhatsAppCampaign.tenant_id == tenant_id)
                .order_by(LeadWhatsAppCampaign.created_at.desc())
                .limit(100)
            )
        ).all()
    )


# ----- the loop: who joins, who is due, what stops -----------------------------------------


async def enrol(db: AsyncSession, *, now: datetime) -> int:
    """Leads who arrived (or moved into the stage) since a live sequence started, within
    the last 30 minutes, join it once."""
    joined = 0
    for campaign in (
        await db.scalars(
            select(LeadWhatsAppCampaign).where(
                LeadWhatsAppCampaign.kind == "sequence", LeadWhatsAppCampaign.status == "live"
            )
        )
    ).all():
        trigger = dict((campaign.audience or {}).get("trigger") or {})
        since = max(campaign.created_at, now - JOIN_WITHIN)
        already = select(LeadWhatsAppCampaignLead.id).where(
            LeadWhatsAppCampaignLead.campaign_id == campaign.id,
            LeadWhatsAppCampaignLead.lead_id == Lead.id,
        )
        query = select(Lead).where(
            Lead.tenant_id == campaign.tenant_id,
            Lead.phone.is_not(None),
            Lead.binned_at.is_(None),
            ~already.exists(),
        )
        if trigger.get("on") == "stage":
            moved = select(LeadEvent.id).where(
                LeadEvent.tenant_id == campaign.tenant_id,
                LeadEvent.lead_id == Lead.id,
                LeadEvent.kind == "stage",
                LeadEvent.created_at >= since,
                LeadEvent.data["stage"].as_string() == str(trigger.get("stage") or ""),
            )
            query = query.where(Lead.stage == str(trigger.get("stage") or ""), moved.exists())
        else:
            query = query.where(Lead.created_at >= since, Lead.source.in_(inbox.EVERY_LEAD_SOURCES))
        first = int((campaign.steps or [{}])[0].get("after_minutes") or 0)
        for lead in (await db.scalars(query.order_by(Lead.created_at).limit(200))).all():
            start = lead.created_at if trigger.get("on") != "stage" else now
            made = await db.execute(
                insert(LeadWhatsAppCampaignLead)
                .values(
                    id=uuid4(),
                    tenant_id=campaign.tenant_id,
                    campaign_id=campaign.id,
                    lead_id=lead.id,
                    step=0,
                    status="waiting",
                    next_at=max(start + timedelta(minutes=first), now),
                    stage_at_start=lead.stage,
                    reason=None,
                    proof=None,
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_nothing(index_elements=["campaign_id", "lead_id"])
                .returning(LeadWhatsAppCampaignLead.id)
            )
            joined += made.first() is not None
    return joined


async def _replied_since(db: AsyncSession, lead: Lead, since: datetime) -> bool:
    wa = cloud.wa_id(lead.phone)
    found = await db.scalar(
        select(func.count())
        .select_from(LeadWhatsAppMessage)
        .where(
            LeadWhatsAppMessage.tenant_id == lead.tenant_id,
            LeadWhatsAppMessage.direction == "in",
            (LeadWhatsAppMessage.lead_id == lead.id) | (LeadWhatsAppMessage.wa_id == (wa or "-")),
            func.coalesce(LeadWhatsAppMessage.meta_time, LeadWhatsAppMessage.created_at) > since,
        )
    )
    return bool(found)


def _system(
    db: AsyncSession, campaign: LeadWhatsAppCampaign, number: LeadWhatsAppNumber, now: datetime
) -> LeadDesk:
    return LeadDesk(
        db,
        Viewer(
            person_id=number.connected_by_person_id,
            tenant_id=campaign.tenant_id,
            role="system",
            name="WhatsApp",
        ),
        now=now,
    )


async def send_due(
    db: AsyncSession,
    cfg: cloud.WhatsAppConfig,
    api: cloud.Cloud,
    *,
    now: datetime,
    store: Any = None,
) -> dict[str, int]:
    """Send what is due, at each campaign's pace; stop whoever replied, moved stage, said
    STOP or left; end a broadcast once nobody is waiting."""
    out = {"sent": 0, "failed": 0, "stopped": 0, "ended": 0}
    budget = SEND_LIMIT_PER_TICK
    campaigns = (
        await db.scalars(select(LeadWhatsAppCampaign).where(LeadWhatsAppCampaign.status == "live"))
    ).all()
    for campaign in campaigns:
        if budget <= 0:
            break
        number = await db.get(LeadWhatsAppNumber, campaign.number_id)
        if number is None or number.status != "active":
            continue
        pace = max(1, -(-campaign.per_minute * TICK_SECONDS // 60))
        rows = (
            await db.scalars(
                select(LeadWhatsAppCampaignLead)
                .where(
                    LeadWhatsAppCampaignLead.campaign_id == campaign.id,
                    LeadWhatsAppCampaignLead.status == "waiting",
                    LeadWhatsAppCampaignLead.next_at <= now,
                )
                .order_by(LeadWhatsAppCampaignLead.next_at)
                .limit(min(pace, budget))
                .with_for_update(skip_locked=True)
            )
        ).all()
        business = await inbox.business_name(db, number) if rows else ""
        rules = inbox.number_config(number)["first_reply"]
        for row in rows:
            budget -= 1
            lead = await db.get(Lead, row.lead_id)
            reason = await _stop_reason(db, campaign, row, lead, rules, now=now)
            if reason:
                row.status, row.reason, row.next_at, row.updated_at = (
                    "skipped" if reason in ("no_yes", "no_whatsapp") else "stopped",
                    reason,
                    None,
                    now,
                )
                out["stopped"] += 1
                continue
            assert lead is not None
            if row.proof is None:
                _, row.proof = await _proof(db, lead, rules, now=now)
                if row.proof is None and (campaign.audience or {}).get("agreed_at"):
                    row.proof = {
                        "how": "A manager confirmed people who reach you agreed to WhatsApp",
                        "at": str((campaign.audience or {}).get("agreed_at")),
                        "by": (campaign.audience or {}).get("agreed_by"),
                    }
            step = (campaign.steps or [])[row.step]
            desk = _system(db, campaign, number, now)
            # The outreach limits (v1.95): an automation waits on a warning too, so a lead the
            # guard holds waits (or is skipped when waiting can't help), with the reason
            # (outreach.py). Only once the workspace saved its limits: until then they show.
            held, limits, _ = await outreach.check_lead(
                db, campaign.tenant_id, lead, "whatsapp", "automation", now
            )
            if held.verdict != "ok" and (limits.saved or held.opted_out):
                wait = held.quiet_until or held.next_ok_at
                if wait is not None and not held.opted_out and wait <= now + LONGEST:
                    # Waiting helps (sending hours, a day or week limit, a rest): it waits.
                    row.next_at, row.reason, row.updated_at = wait, OUTREACH_LIMIT, now
                else:
                    row.status, row.reason, row.next_at, row.updated_at = (
                        "skipped",
                        OUTREACH_LIMIT,
                        None,
                        now,
                    )
                out["stopped"] += 1
                continue
            if row.reason == OUTREACH_LIMIT:
                row.reason = None
            try:
                message = await inbox.send(
                    desk,
                    cfg,
                    api,
                    lead.id,
                    command_id=uuid5(row.id, f"step-{row.step}"),
                    number_id=number.id,
                    body=None,
                    template=step["template"],
                    language=step["language"],
                    values=fill_values(step.get("values") or [], lead, business),
                    auto="drip" if campaign.kind == "sequence" else "broadcast",
                    media_id=UUID(step["media_id"]) if step.get("media_id") else None,
                    store=store,
                    campaign_id=campaign.id,
                    campaign_step=row.step,
                )
            except DeskError as error:
                row.status, row.reason, row.next_at, row.updated_at = (
                    "failed",
                    "refused",
                    None,
                    now,
                )
                log.warning("whatsapp campaign %s step not sent: %s", campaign.id, error)
                out["failed"] += 1
                continue
            row.last_message_id = message.id
            row.updated_at = now
            if message.status == "failed":
                row.status, row.reason, row.next_at = (
                    "failed",
                    (message.error_code or "")[:32],
                    None,
                )
                out["failed"] += 1
                continue
            out["sent"] += 1
            nxt = row.step + 1
            if nxt < len(campaign.steps or []):
                gap = int(campaign.steps[nxt].get("after_minutes") or 0) - int(
                    step.get("after_minutes") or 0
                )
                row.step, row.next_at = nxt, now + timedelta(minutes=gap)
            else:
                row.status, row.next_at = "done", None
        if campaign.kind == "broadcast":
            waiting = await db.scalar(
                select(func.count())
                .select_from(LeadWhatsAppCampaignLead)
                .where(
                    LeadWhatsAppCampaignLead.campaign_id == campaign.id,
                    LeadWhatsAppCampaignLead.status == "waiting",
                )
            )
            if not waiting:
                campaign.status, campaign.ended_at, campaign.updated_at = "ended", now, now
                out["ended"] += 1
    await db.flush()
    return out


async def _stop_reason(
    db: AsyncSession,
    campaign: LeadWhatsAppCampaign,
    row: LeadWhatsAppCampaignLead,
    lead: Lead | None,
    rules: Mapping[str, Any],
    *,
    now: datetime,
) -> str | None:
    if lead is None or lead.binned_at is not None or lead.tenant_id != campaign.tenant_id:
        return "gone"
    if await inbox.said_no(db, lead):
        return "said_stop"
    if cloud.wa_id(lead.phone) is None:
        return "no_whatsapp"
    if campaign.kind == "sequence":
        if lead.stage != row.stage_at_start:
            return "stage"
        if await _replied_since(db, lead, row.created_at):
            return "replied"
        if not (campaign.audience or {}).get("agreed_at"):
            agreed, _ = await inbox.opt_in_state(db, lead, rules)
            if not agreed:
                return "no_yes"
    return None


# ----- the numbers ---------------------------------------------------------------------------


_COUNTS = """
    SELECT {group}
      count(*) FILTER (WHERE m.status <> 'failed') AS sent,
      count(*) FILTER (WHERE m.status IN ('delivered', 'read')) AS delivered,
      count(*) FILTER (WHERE m.status = 'read') AS read,
      count(*) FILTER (WHERE m.status = 'failed') AS failed,
      count(DISTINCT m.lead_id) FILTER (
        WHERE m.status <> 'failed' AND EXISTS (
          SELECT 1 FROM lead_desk_whatsapp_messages i
          WHERE i.tenant_id = m.tenant_id AND i.number_id = m.number_id
            AND i.wa_id = m.wa_id AND i.direction = 'in'
            AND COALESCE(i.meta_time, i.created_at) > m.created_at)
      ) AS replied,
      count(DISTINCT m.lead_id) FILTER (
        WHERE m.status <> 'failed' AND EXISTS (
          SELECT 1 FROM lead_desk_leads l
          WHERE l.tenant_id = m.tenant_id AND l.id = m.lead_id AND l.stage = 'won')
      ) AS won
    FROM lead_desk_whatsapp_messages m
    LEFT JOIN lead_desk_whatsapp_campaign_messages c ON c.message_id = m.id
    WHERE m.tenant_id = :tenant AND m.direction = 'out' AND {where}
    {group_by}
"""
COUNTED: Final[tuple[str, ...]] = ("sent", "delivered", "read", "failed", "replied", "won")


async def numbers(db: AsyncSession, campaign: LeadWhatsAppCampaign) -> dict[str, Any]:
    """One campaign's numbers: who is on it and where they are, and what its messages did."""
    people = {
        status: int(count)
        for status, count in (
            await db.execute(
                select(LeadWhatsAppCampaignLead.status, func.count())
                .where(LeadWhatsAppCampaignLead.campaign_id == campaign.id)
                .group_by(LeadWhatsAppCampaignLead.status)
            )
        ).all()
    }
    reasons = {
        str(reason): int(count)
        for reason, count in (
            await db.execute(
                select(LeadWhatsAppCampaignLead.reason, func.count())
                .where(
                    LeadWhatsAppCampaignLead.campaign_id == campaign.id,
                    LeadWhatsAppCampaignLead.reason.is_not(None),
                )
                .group_by(LeadWhatsAppCampaignLead.reason)
            )
        ).all()
    }
    query = _COUNTS.format(group="", where="c.campaign_id = :campaign", group_by="")
    row = (
        await db.execute(text(query), {"tenant": campaign.tenant_id, "campaign": campaign.id})
    ).one()
    counts = {key: int(getattr(row, key) or 0) for key in COUNTED}
    return {"people": people, "reasons": reasons, "messages": counts}


async def overview(db: AsyncSession, tenant_id: UUID, *, since: datetime) -> list[dict[str, Any]]:
    """Every message sent since a date, by what sent it (a person, the first reply, a
    sequence, a broadcast...), its campaign and its template: sent, delivered, read,
    failed, replied and won."""
    query = _COUNTS.format(
        group="m.auto, c.campaign_id, m.template_name,",
        where="m.created_at >= :since",
        group_by="GROUP BY m.auto, c.campaign_id, m.template_name",
    )
    out = [
        {
            "sentBy": row.auto or "person",
            "campaignId": row.campaign_id,
            "template": row.template_name,
            **{key: int(getattr(row, key) or 0) for key in COUNTED},
        }
        for row in (await db.execute(text(query), {"tenant": tenant_id, "since": since})).all()
    ]
    out.sort(key=lambda item: -item["sent"])
    return out
