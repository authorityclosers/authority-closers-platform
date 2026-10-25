"""Bring in older Meta leads: everything Meta still keeps for a Page (90 days).

Connecting a Page files its last week at once. The rest of what Meta keeps comes in
the background: each step reads a few pages of one form's leads, files them through
``LeadDesk.ingest`` exactly like the webhook and the pull, and keeps its place (the
form and Meta's cursor) in the source's config. A step runs when a manager asks
("Bring in older leads") and then once a minute in the puller until every form is
read. The Meta lead id is the source reference, so a lead already here is "known"
and changes nothing: running it twice adds nothing. A Meta lead whose person is already
a lead made at or after the form was sent (imported from a sheet or a file of Meta's
leads first) is "linked": a note on that lead keeps the Meta lead id and source, and
nothing else changes. New leads then go through the duplicate engine at once
(``duplicate_intake``): a certain pair is merged, any other waits for review.

State, under ``config["backfill"]``:
``{"state": "running" | "done" | "blocked", "since": epoch, "forms": [form ids],
"form": index, "after": cursor | None, "created": n, "linked": n, "seen": n,
"started_at": epoch,
"finished_at": epoch | None, "error": text | None}``. "blocked" means Meta refused in
a way only the customer can fix (Leads Access Manager, a lost connection); asking
again starts over.

A step reads from Meta first (``read``, no database) and then files what it read
(``apply``, in a short transaction), so no lock waits on Meta. A slice is applied only
to the backfill it was read for, from the place it was read from.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Protocol
from uuid import UUID, uuid5

from sqlalchemy import select

from ac_platform.lead_desk import duplicate_intake
from ac_platform.lead_desk.capture import extract
from ac_platform.lead_desk.connectors import meta
from ac_platform.lead_desk.models import Lead, LeadEvent, LeadSource
from ac_platform.lead_desk.store import LeadDesk

KEY: Final[str] = "backfill"
STEP_LEADS: Final[int] = 300  # leads read in one step (one request, or one puller tick)
_STOPS: Final[frozenset[str]] = frozenset({"token", "permission", "lead_access"})


class _Graph(Protocol):
    async def forms(self, page_id: str, page_token: str) -> list[dict[str, str]]: ...

    async def leads_page(
        self, form_id: str, page_token: str, *, since: int, after: str | None = None
    ) -> tuple[list[dict[str, Any]], str | None]: ...


def state(config: Mapping[str, Any]) -> dict[str, Any] | None:
    value = config.get(KEY)
    return dict(value) if isinstance(value, Mapping) else None


def running(config: Mapping[str, Any]) -> bool:
    current = state(config)
    return current is not None and current.get("state") == "running"


def begin(config: Mapping[str, Any], *, form_ids: list[str], now: int) -> dict[str, Any]:
    """The source config with a fresh backfill over the last 90 days of these forms."""
    return {
        **config,
        KEY: {
            "state": "running",
            "since": now - meta.BACKFILL_DAYS * 86400,
            "forms": [str(form) for form in form_ids][: meta.MAX_FORMS],
            "form": 0,
            "after": None,
            "created": 0,
            "linked": 0,
            "seen": 0,
            "started_at": now,
            "finished_at": None,
            "error": None,
        },
    }


def remember_forms(config: Mapping[str, Any], forms: list[dict[str, str]]) -> dict[str, Any]:
    """Keep the Page's forms (id, name, status), so the page can say which are covered."""
    return {
        **config,
        "form_list": [
            {"id": form["id"], "name": form["name"], "status": form.get("status", "")}
            for form in forms[: meta.MAX_FORMS]
        ],
    }


def submitted_at(lead: Mapping[str, Any]) -> datetime | None:
    """When the person sent Meta's form (``created_time``, e.g. 2026-09-01T10:00:00+0000)."""
    raw = lead.get("created_time")
    if not isinstance(raw, str):
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%dT%H:%M:%S%z")
    except ValueError:
        return None


async def earlier_lead(
    desk: LeadDesk, record: Mapping[str, Any], ref: str, sent: datetime
) -> Lead | None:
    """The lead this Meta lead's person already is, when it was made at or after they sent
    the form: the same enquiry, brought in first some other way (a sheet or a file of
    Meta's leads). The phone decides when a lead has it; else the email (a sheet may hold
    another number for the same person). Owner's demo
    prep, 25 Oct 2026: AC's own Page holds 100 leads its team had already imported, and
    filing them as repeats would reset every follow-up to now and reopen Lost leads. A
    form sent after the lead was made is a real repeat, and this Meta lead filed as its
    own lead is left to intake ("known")."""
    _, config = await desk.settings()
    found = extract(record, None, default_country=config["default_country"])
    lead: Lead | None = None
    for same in (
        Lead.phone == found.phone if found.phone else None,
        Lead.email == found.email if found.email else None,
    ):
        if same is None:
            continue
        lead = await desk.db.scalar(
            select(Lead)
            .where(Lead.tenant_id == desk.tenant_id, same)
            .order_by(Lead.created_at)
            .limit(1)
        )
        if lead is not None:
            break
    if lead is None or lead.created_at < sent or (lead.source, lead.source_ref) == ("meta", ref):
        return None
    # A lead merged into another: the link goes to the lead it went into.
    return await desk._live(lead)


async def link(desk: LeadDesk, source: LeadSource, lead: Lead, ref: str, sent: datetime) -> str:
    """Keep the Meta lead id and source on the lead, once, as a note from the desk; the
    lead itself is left as it is (no follow-up reset, no reopening, no "asked again")."""
    command = uuid5(desk.tenant_id, f"meta-link:{ref}")
    seen = await desk.db.scalar(
        select(LeadEvent.id).where(
            LeadEvent.tenant_id == desk.tenant_id, LeadEvent.command_id == command
        )
    )
    if seen is not None:
        return "known"
    desk._event(
        lead,
        "note",
        {
            "note": f"Also on {source.label}: their form was sent before this lead was "
            "added, so it is the same enquiry. Linked; nothing else changed.",
            "source": "meta",
            "source_label": source.label,
            "source_ref": ref,
            "submitted_at": sent.isoformat(),
            "linked": True,
        },
        actor=None,
        command_id=command,
    )
    return "linked"


async def file_lead(
    desk: LeadDesk,
    source: LeadSource,
    lead: Mapping[str, Any],
    *,
    page_name: str,
    made: list[UUID] | None = None,
) -> str:
    """One Meta lead into the CRM, like the webhook and the pull; returns the outcome.
    A lead Meta's testing tools made is test data, so it stays out of partner sends,
    SLA reports and lead stages sent back to the ad platforms like any test lead. A form
    sent before its person's lead was made is "linked" to that lead (``earlier_lead``).
    A new lead's id is added to ``made``, for the duplicate engine after the batch."""
    record = meta.lead_record(lead, page_name=page_name)
    ref = str(lead.get("id") or "")[:200] or None
    test = meta.is_test_lead(lead)
    sent = submitted_at(lead)
    if ref is not None and sent is not None and not test:
        earlier = await earlier_lead(desk, record, ref, sent)
        if earlier is not None:
            return await link(desk, source, earlier, ref, sent)
    filed, outcome = await desk.ingest(
        record,
        source="meta",
        source_label=source.label,
        source_ref=ref,
        actor=None,
        test_data=test,
    )
    if outcome == "created" and filed is not None and made is not None:
        made.append(filed.id)
    if outcome in {"created", "repeat"}:
        source.received = int(source.received or 0) + 1
        source.last_received_at = desk.now
    return outcome


@dataclass(frozen=True, slots=True)
class Slice:
    """One step's reading from Meta: the leads, where it started and where it got to."""

    started_at: int
    from_form: int
    from_after: str | None
    leads: list[dict[str, Any]]
    form: int
    after: str | None
    error: meta.MetaError | None = None


async def read(
    config: Mapping[str, Any],
    graph: _Graph,
    cfg: meta.MetaConfig,
    *,
    now: int,
    budget: int = STEP_LEADS,
) -> Slice | None:
    """Read up to ``budget`` older leads from Meta (a page is read whole); no database.
    None when no backfill is running. A refusal ends the slice with what was read."""
    current = state(config)
    if current is None or current.get("state") != "running":
        return None
    forms = [str(form) for form in current.get("forms") or []]
    start = int(current.get("form") or 0)
    first = current.get("after") if isinstance(current.get("after"), str) else None
    since = int(current.get("since") or now - meta.BACKFILL_DAYS * 86400)
    index, after = start, first
    leads: list[dict[str, Any]] = []
    error: meta.MetaError | None = None
    try:
        page_id = str(config.get("page_id") or "")
        token = meta.unseal(cfg.token_key, config["token"], page_id=page_id)
        while index < len(forms) and len(leads) < budget:
            rows, after = await graph.leads_page(forms[index], token, since=since, after=after)
            leads.extend(rows)
            if after is None:
                index, after = index + 1, None
    except meta.MetaError as refused:
        error = refused
    return Slice(int(current.get("started_at") or 0), start, first, leads, index, after, error)


async def apply(desk: LeadDesk, source: LeadSource, piece: Slice, *, now: int) -> int:
    """File one slice and move the backfill on, in the caller's transaction. A backfill
    started again, or moved on by another step meanwhile, is left alone."""
    config = dict(source.config or {})
    current = state(config)
    if (
        current is None
        or current.get("state") != "running"
        or int(current.get("started_at") or 0) != piece.started_at
        or int(current.get("form") or 0) != piece.from_form
        or (current.get("after") if isinstance(current.get("after"), str) else None)
        != piece.from_after
    ):
        return 0
    page_name = str(config.get("page_name") or "")
    created = linked = 0
    made: list[UUID] = []
    for lead in piece.leads:
        outcome = await file_lead(desk, source, lead, page_name=page_name, made=made)
        created += outcome == "created"
        linked += outcome == "linked"
    await duplicate_intake.after_intake(desk, made)
    current.update(
        form=piece.form,
        after=piece.after,
        created=int(current.get("created") or 0) + created,
        linked=int(current.get("linked") or 0) + linked,
        seen=int(current.get("seen") or 0) + len(piece.leads),
        error=str(piece.error) if piece.error is not None else None,
    )
    if piece.error is not None and piece.error.kind in _STOPS:
        current.update(state="blocked", finished_at=now)
    if current["state"] == "running" and piece.form >= len(current.get("forms") or []):
        current.update(state="done", finished_at=now, after=None)
    config[KEY] = current
    source.config = config
    return created


async def step(
    desk: LeadDesk,
    source: LeadSource,
    graph: _Graph,
    cfg: meta.MetaConfig,
    *,
    now: int,
    budget: int = STEP_LEADS,
) -> int:
    """Read up to ``budget`` older leads and file them; returns how many were new."""
    piece = await read(source.config or {}, graph, cfg, now=now, budget=budget)
    if piece is None:
        return 0
    return await apply(desk, source, piece, now=now)
