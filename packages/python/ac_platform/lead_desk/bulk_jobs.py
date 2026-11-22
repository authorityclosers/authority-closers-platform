"""Bulk changes on a frozen selection, with Undo (owner, 16 Nov 2026: "reorganizing,
reassigning … managing the leads at a higher level"; 02-management-findings-and-spec.md §4,
M3 and §6; docs/product/lead-desk/lead-management-api.md §2).

One request names the leads by id, or by the list's own filter ("all 522 matching"), which is
frozen when the request arrives: the leads matching then are the selection, whatever comes in
after. Owners, admins and sales managers give them to someone (or the lead rules), move them to
one stage or pipeline, archive them, or (owners and admins) move them to the Bin or restore
them. Each lead changes exactly as its own action would (store.bulk, shelf.move), with its own
history line, so the lead's history shows the bulk change; that line also keeps what the lead
was before (``bulk_before``).

The job is one audit event (``lead_desk.bulk_job.applied``, resource id = the command id): ids,
counts and each changed lead's revision after the change, never a name or a word. It is the
job's idempotency record and the action history. For ``UNDO_MINUTES`` the job can be undone:
every lead not changed since (same revision) goes back to its ``bulk_before``; one changed
since is left as it is and counted. The undo is a new history line per lead and one more audit
event; nothing is deleted or overwritten.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Final, cast
from uuid import UUID, uuid5

from sqlalchemy import select, update

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import AuditRepository
from ac_platform.lead_desk import shelf, tags
from ac_platform.lead_desk.contracts import (
    BulkFailure,
    BulkJob,
    BulkJobCommand,
    BulkJobs,
    BulkLeads,
    BulkUndone,
    LeadFilter,
)
from ac_platform.lead_desk.errors import DeskError
from ac_platform.lead_desk.journey.transitions import UNDONE_RESULT
from ac_platform.lead_desk.models import Lead, LeadConversion, LeadEvent, LeadMetaConversion
from ac_platform.partner_events.models import PartnerLeadEvent

if TYPE_CHECKING:
    from ac_platform.lead_desk.store import LeadDesk

MAX_LEADS: Final = 2000
UNDO_MINUTES: Final = 30
RESOURCE: Final = "lead_desk.bulk_job"
APPLIED: Final = "lead_desk.bulk_job.applied"
UNDONE: Final = "lead_desk.bulk_job.undone"
BEFORE: Final = "bulk_before"
JOB: Final = "bulk_job"
SHELF_ACTIONS: Final = frozenset({"archive", "bin", "restore_archive", "restore_bin"})
# Tags (migration 0165, tags.py): a lead's revision stays, so Undo reverses exactly what the
# job changed on each lead, whatever else changed since.
TAG_ACTIONS: Final = frozenset({"tag", "untag"})
# What each lead's snapshot keeps (the lead's own fields; its history holds them).
_FIELDS: Final = (
    "owner_person_id",
    "assigned_at",
    "owner_reason",
    "stage",
    "step",
    "stage_at",
    "next_action_at",
    "next_action_note",
    "outcome_reason",
    "pipeline_key",
    "archived_at",
    "archived_by_person_id",
    "binned_at",
    "binned_by_person_id",
)
_TIMES: Final = frozenset({"assigned_at", "stage_at", "next_action_at", "archived_at", "binned_at"})
_IDS: Final = frozenset({"owner_person_id", "archived_by_person_id", "binned_by_person_id"})


def _snapshot(lead: Lead) -> dict[str, Any]:
    out: dict[str, Any] = {"revision": lead.revision}
    for name in _FIELDS:
        value = getattr(lead, name)
        out[name] = (
            value.isoformat()
            if isinstance(value, datetime)
            else str(value)
            if isinstance(value, UUID)
            else value
        )
    return out


def _value(name: str, raw: Any) -> Any:
    if raw is None:
        return None
    if name in _TIMES:
        return datetime.fromisoformat(raw)
    if name in _IDS:
        return UUID(raw)
    return raw


def _one(job_id: UUID, lead_id: UUID) -> UUID:
    """The per-lead command id store.bulk gives each lead's change."""
    return uuid5(job_id, str(lead_id))


def _shelf_command(job_id: UUID) -> UUID:
    return uuid5(job_id, "shelf")


def _shelf_one(job_id: UUID, lead_id: UUID) -> UUID:
    return uuid5(_shelf_command(job_id), f"shelf:{lead_id}")


def _filter_record(selection: LeadFilter) -> dict[str, Any]:
    """The filter as the audit keeps it: a search's words are never kept, only that there was
    one."""
    record = selection.model_dump(mode="json", exclude_none=True, exclude_defaults=True)
    if "search" in record:
        record["search"] = True
    return record


async def _audit(desk: LeadDesk, resource_id: str, action: str) -> AuditEvent | None:
    event: AuditEvent | None = await desk.db.scalar(
        select(AuditEvent).where(
            AuditEvent.tenant_id == desk.tenant_id,
            AuditEvent.resource_type == RESOURCE,
            AuditEvent.resource_id == resource_id,
            AuditEvent.action == action,
        )
    )
    return event


async def _words(desk: LeadDesk, payload: Mapping[str, Any]) -> str:
    action = payload.get("action")
    changed = int(payload.get("changed", 0))
    leads = f"{changed} lead{'' if changed == 1 else 's'}"
    if action == "assign":
        person = payload.get("person_id")
        return (
            f"{leads} given to {await desk._name(UUID(person))}"
            if person
            else f"{leads} given out by the lead rules"
        )
    if action == "stage":
        return f"{leads} moved to {payload.get('step_label') or payload.get('step')}"
    if action == "pipeline":
        return f"{leads} moved to the {payload.get('pipeline_label') or payload.get('pipeline')}"
    if action in TAG_ACTIONS:
        names = ", ".join(str(name) for name in payload.get("tag_names", ()))
        return f"{leads} tagged {names}" if action == "tag" else f"{names} taken off {leads}"
    return f"{leads} {shelf.EVENT_WORDS[action].lower()}" if action in shelf.EVENT_WORDS else leads


async def _view(desk: LeadDesk, event: AuditEvent, undone: AuditEvent | None) -> BulkJob:
    payload = event.payload
    return BulkJob(
        job_id=UUID(event.resource_id or ""),
        action=payload["action"],
        selection=payload.get("selection", {}).get("kind", "ids"),
        selected=int(payload.get("selected", 0)),
        changed=int(payload.get("changed", 0)),
        unchanged=int(payload.get("unchanged", 0)),
        not_found=int(payload.get("not_found", 0)),
        failed=tuple(
            BulkFailure(reason=str(reason), count=int(count))
            for reason, count in payload.get("failed", {}).items()
        ),
        lead_ids=tuple(UUID(lead_id) for lead_id, _ in payload.get("leads", ())),
        words=await _words(desk, payload),
        by_person_id=event.actor_person_id,
        at=event.occurred_at,
        undo_until=datetime.fromisoformat(payload["undo_until"]),
        undoable=undone is None
        and desk.now < datetime.fromisoformat(payload["undo_until"])
        and int(payload.get("changed", 0)) > 0,
        undone_at=undone.occurred_at if undone is not None else None,
    )


def _allowed(desk: LeadDesk, action: str) -> None:
    if action in SHELF_ACTIONS:
        shelf.allowed(desk, action)  # type: ignore[arg-type]
    elif not desk.viewer.can_manage:
        raise DeskError(403, "Only owners, admins and managers change many leads at once.")


async def _selection(desk: LeadDesk, command: BulkJobCommand) -> list[UUID]:
    if (command.lead_ids is None) == (command.filter is None):
        raise DeskError(422, "Choose the leads, or the list they are in.")
    if command.lead_ids is not None:
        return list(dict.fromkeys(command.lead_ids))
    assert command.filter is not None
    chosen = command.filter
    page = await desk.leads(
        scope=chosen.scope,
        stage=chosen.stage,
        search=chosen.search,
        tag=chosen.tag,
        offset=0,
        test_only=chosen.test,
        older_only=chosen.older,
        owner=chosen.owner,
        pipeline=chosen.pipeline,
        source=chosen.source,
        due=chosen.due,
        contact=chosen.contact,
        created=chosen.created,
        duplicates=chosen.duplicates,
        side=chosen.side,
        view=chosen.view,
        step=chosen.step,
        when=chosen.when,
        since=chosen.since,
        until=chosen.until,
        shelf=chosen.shelf,
        freeze=MAX_LEADS,
    )
    if page.total > MAX_LEADS:
        raise DeskError(422, f"{page.total:,} leads match. Up to {MAX_LEADS:,} at a time.")
    if command.expected_total is not None and command.expected_total != page.total:
        raise DeskError(
            409, f"The list changed: {page.total:,} leads match now. Check and try again."
        )
    if not desk.frozen_ids:
        raise DeskError(422, "No leads match this list.")
    return list(desk.frozen_ids)


async def run(desk: LeadDesk, command: BulkJobCommand) -> BulkJob:
    """Apply one bulk change to a frozen selection, in the request's one transaction."""
    _allowed(desk, command.action)
    job_id = command.command_id
    done = await _audit(desk, str(job_id), APPLIED)
    if done is not None:
        return await _view(desk, done, await _audit(desk, f"undo:{job_id}", UNDONE))
    wanted = await _selection(desk, command)
    if len(wanted) > MAX_LEADS:
        raise DeskError(422, f"Up to {MAX_LEADS:,} leads at a time.")
    shelved = command.action in SHELF_ACTIONS
    tagged = command.action in TAG_ACTIONS
    chosen_tags = await tags.known(desk, command.tag_ids) if tagged else []
    if tagged and not chosen_tags:
        raise DeskError(422, "Choose a tag.")
    # Lock what this person may change, in id order; a lead in the Bin only for a restore.
    scope = [desk._visible(), Lead.id.in_(wanted)]
    if command.action != "restore_bin":
        scope.append(Lead.binned_at.is_(None))
    leads = list(
        await desk.db.scalars(select(Lead).where(*scope).order_by(Lead.id).with_for_update())
    )
    # A twin request (a second tap, a retry) may have finished while this one waited for the
    # locks: its job, never a second APPLIED event (as shelf.move does; PR 637 review).
    done = await _audit(desk, str(job_id), APPLIED)
    if done is not None:
        return await _view(desk, done, await _audit(desk, f"undo:{job_id}", UNDONE))
    before = {lead.id: _snapshot(lead) for lead in leads}
    failed: dict[str, int] = {}
    extra: dict[str, Any] = {}
    tag_changes: dict[UUID, Any] = {}
    if tagged:
        # A lead that would pass 10 tags stays as it is and is counted as "couldn't change".
        full: set[UUID] = set()
        tag_changes = await tags.apply(
            desk,
            leads,
            add=chosen_tags if command.action == "tag" else (),
            remove=chosen_tags if command.action == "untag" else (),
            command_id=job_id,
            actor=desk.viewer.person_id,
            extra={JOB: str(job_id)},
            over="skip",
            full=full,
        )
        if full:
            failed[tags.FULL_REASON] = len(full)
        one = _one
        extra["tag_ids"] = [str(tag.id) for tag in chosen_tags]
        extra["tag_names"] = [tag.name for tag in chosen_tags]
    elif shelved:
        if leads:
            await shelf.move(
                desk,
                command.action,  # type: ignore[arg-type]
                _shelf_command(job_id),
                [lead.id for lead in leads],
                via="bulk",
            )
        one = _shelf_one
    else:
        result = await desk.bulk(
            BulkLeads.model_construct(
                command_id=job_id,
                lead_ids=tuple(lead.id for lead in leads),
                action=cast(Any, command.action),
                person_id=command.person_id,
                step=command.step,
                pipeline=command.pipeline,
                outcome_reason=command.outcome_reason,
                reason_note=command.reason_note,
                next_action_at=command.next_action_at,
            )
        )
        if "not moved: " in result.words:
            for part in result.words.split(". "):
                count, _, reason = part.partition(" not moved: ")
                if reason and count.strip().isdigit():
                    failed[reason.rstrip(".")] = int(count)
        one = _one
        if command.action == "stage" and command.step:
            extra["step"] = command.step
            for lead in leads:
                if lead.revision > before[lead.id]["revision"]:
                    extra["step_label"] = desk._stage_label(lead)
                    break
        if command.action == "pipeline" and command.pipeline:
            extra["pipeline"] = command.pipeline
            extra["pipeline_label"] = (await desk._pipeline(command.pipeline)).name
        if command.action == "assign" and command.person_id is not None:
            extra["person_id"] = str(command.person_id)
    changed = (
        [lead for lead in leads if lead.id in tag_changes]
        if tagged
        else [lead for lead in leads if lead.revision > before[lead.id]["revision"]]
    )
    # Each changed lead's own history line keeps what it was before (for Undo).
    await desk.db.flush()
    events = {
        event.lead_id: event
        for event in await desk.db.scalars(
            select(LeadEvent).where(
                LeadEvent.tenant_id == desk.tenant_id,
                LeadEvent.command_id.in_([one(job_id, lead.id) for lead in changed]),
            )
        )
    }
    for lead in changed:
        event = events.get(lead.id)
        if event is not None:
            event.data = {**event.data, JOB: str(job_id), BEFORE: before[lead.id]}
    order = {lead_id: index for index, lead_id in enumerate(wanted)}
    changed.sort(key=lambda lead: order.get(lead.id, 0))
    payload: dict[str, Any] = {
        "action": command.action,
        "selection": (
            {"kind": "filter", "filter": _filter_record(command.filter)}
            if command.filter is not None
            else {"kind": "ids"}
        ),
        "selected": len(wanted),
        "changed": len(changed),
        "unchanged": len(leads) - len(changed),
        "not_found": len(wanted) - len(leads),
        "failed": failed,
        # Each changed lead and its revision right after: Undo touches only leads still there.
        "leads": [[str(lead.id), lead.revision] for lead in changed],
        "undo_until": (desk.now + timedelta(minutes=UNDO_MINUTES)).isoformat(),
        **extra,
    }
    record = await AuditRepository(desk.db).append(
        tenant_id=desk.tenant_id,
        actor_person_id=desk.viewer.person_id,
        session_id=desk.viewer.session_id,
        action=APPLIED,
        resource_type=RESOURCE,
        resource_id=str(job_id),
        payload=payload,
        reason="Bulk change in Leads",
        now=desk.now,
    )
    await desk.db.flush()
    return await _view(desk, record, None)


async def _drop_sends(desk: LeadDesk, event_ids: Sequence[UUID]) -> None:
    """Stage news the undone move queued and nobody sent yet is dropped, never sent."""
    if not event_ids:
        return
    for model in (LeadConversion, LeadMetaConversion, PartnerLeadEvent):
        await desk.db.execute(
            update(model)
            .where(
                model.tenant_id == desk.tenant_id,
                model.source_event_id.in_(list(event_ids)),
                model.status == "pending",
            )
            .values(status="dropped", last_error_code="undone")
            .execution_options(synchronize_session=False)
        )


async def undo(desk: LeadDesk, job_id: UUID) -> BulkUndone:
    """Put a bulk change back for every lead not changed since, within ``UNDO_MINUTES``."""
    job = await _audit(desk, str(job_id), APPLIED)
    if job is None:
        raise DeskError(404, "This change isn't here.")
    _allowed(desk, job.payload["action"])
    resource = f"undo:{job_id}"
    earlier = await _audit(desk, resource, UNDONE)
    if earlier is not None:
        return BulkUndone(**{k: earlier.payload[k] for k in ("restored", "skipped")}, job_id=job_id)
    if desk.now >= datetime.fromisoformat(job.payload["undo_until"]):
        raise DeskError(409, f"Undo was open for {UNDO_MINUTES} minutes; it has closed.")
    action = job.payload["action"]
    after = {UUID(lead_id): int(revision) for lead_id, revision in job.payload.get("leads", ())}
    leads = list(
        await desk.db.scalars(
            select(Lead)
            .where(desk._visible(), Lead.id.in_(list(after)))
            .order_by(Lead.id)
            .with_for_update()
        )
    )
    # Taken again in case a twin undo finished while this one waited for the locks.
    earlier = await _audit(desk, resource, UNDONE)
    if earlier is not None:
        return BulkUndone(**{k: earlier.payload[k] for k in ("restored", "skipped")}, job_id=job_id)
    one = _shelf_one if action in SHELF_ACTIONS else _one
    if action in TAG_ACTIONS:
        return await _undo_tags(desk, job_id, resource, leads, len(after))
    marks = {
        event.lead_id: event
        for event in await desk.db.scalars(
            select(LeadEvent).where(
                LeadEvent.tenant_id == desk.tenant_id,
                LeadEvent.command_id.in_([one(job_id, lead_id) for lead_id in after]),
            )
        )
    }
    restored: list[UUID] = []
    undone_events: list[UUID] = []
    for lead in leads:
        mark = marks.get(lead.id)
        was = mark.data.get(BEFORE) if mark is not None else None
        if lead.revision != after[lead.id] or not isinstance(was, dict) or mark is None:
            continue  # Changed since: left as it is.
        again = uuid5(job_id, f"undo:{lead.id}")
        if action == "assign":
            previous = _value("owner_person_id", was.get("owner_person_id"))
            await desk._set_owner(
                lead,
                previous,
                f"Undone by {desk.viewer.name}",
                "undo",
                actor=desk.viewer.person_id,
                kind="reassigned",
                command_id=again,
            )
            lead.assigned_at = _value("assigned_at", was.get("assigned_at"))
            lead.owner_reason = was.get("owner_reason")
        else:
            moved_from = lead.stage
            names = (
                ("archived_at", "archived_by_person_id", "binned_at", "binned_by_person_id")
                if action in SHELF_ACTIONS
                else (
                    "stage",
                    "step",
                    "stage_at",
                    "next_action_at",
                    "next_action_note",
                    "outcome_reason",
                    "pipeline_key",
                )
            )
            for name in names:
                if name == "stage" and was.get(name) is None:
                    continue
                setattr(lead, name, _value(name, was.get(name)))
            lead.revision += 1
            lead.updated_at = desk.now
            data: dict[str, Any] = {
                "undo_of": str(mark.id),
                UNDONE_RESULT: str(mark.id),
                JOB: str(job_id),
                "reason_text": f"Bulk change undone by {desk.viewer.name}",
            }
            if action in SHELF_ACTIONS:
                data.update(changed=["shelf"], shelf=f"undo_{action}")
            else:
                data.update(
                    changed=["stage"],
                    stage=lead.stage,
                    from_stage=moved_from,
                    step=lead.step,
                    follow_up_at=lead.next_action_at.isoformat() if lead.next_action_at else None,
                )
                undone_events.append(mark.id)
            desk._event(lead, "edited", data, actor=desk.viewer.person_id, command_id=again)
        restored.append(lead.id)
    await _drop_sends(desk, undone_events)
    result = {"restored": len(restored), "skipped": len(after) - len(restored)}
    await AuditRepository(desk.db).append(
        tenant_id=desk.tenant_id,
        actor_person_id=desk.viewer.person_id,
        session_id=desk.viewer.session_id,
        action=UNDONE,
        resource_type=RESOURCE,
        resource_id=resource,
        payload={**result, "job_id": str(job_id), "lead_ids": [str(i) for i in restored]},
        reason="Bulk change undone in Leads",
        now=desk.now,
    )
    await desk.db.flush()
    return BulkUndone(job_id=job_id, **result)


async def _undo_tags(
    desk: LeadDesk, job_id: UUID, resource: str, leads: Sequence[Lead], total: int
) -> BulkUndone:
    """Take off the tags the job added (still on) and put back the ones it took off (unless
    deleted since), lead by lead from each lead's own history line."""
    marks = {
        event.lead_id: event
        for event in await desk.db.scalars(
            select(LeadEvent).where(
                LeadEvent.tenant_id == desk.tenant_id,
                LeadEvent.command_id.in_([_one(job_id, lead.id) for lead in leads]),
            )
        )
    }

    def ids(event: LeadEvent, key: str) -> tuple[UUID, ...]:
        items = event.data.get(key)
        return tuple(UUID(item["id"]) for item in items) if isinstance(items, list) else ()

    plans: dict[tuple[tuple[UUID, ...], tuple[UUID, ...]], list[Lead]] = {}
    wanted: set[UUID] = set()
    for lead in leads:
        mark = marks.get(lead.id)
        if mark is None:
            continue
        key = (ids(mark, "tags_removed"), ids(mark, "tags_added"))
        plans.setdefault(key, []).append(lead)
        wanted.update(key[0] + key[1])
    found = await tags.present(desk, wanted)
    restored: set[UUID] = set()
    for (put_back, take_off), group in plans.items():
        done = await tags.apply(
            desk,
            group,
            add=[found[tag_id] for tag_id in put_back if tag_id in found],
            remove=[found[tag_id] for tag_id in take_off if tag_id in found],
            command_id=uuid5(job_id, "undo"),
            actor=desk.viewer.person_id,
            extra={JOB: str(job_id), "undo_of": str(job_id)},
            # A lead that has 10 tags since keeps them: it counts as skipped.
            over="skip",
        )
        restored.update(done)
    result = {"restored": len(restored), "skipped": total - len(restored)}
    await AuditRepository(desk.db).append(
        tenant_id=desk.tenant_id,
        actor_person_id=desk.viewer.person_id,
        session_id=desk.viewer.session_id,
        action=UNDONE,
        resource_type=RESOURCE,
        resource_id=resource,
        payload={**result, "job_id": str(job_id), "lead_ids": [str(i) for i in restored]},
        reason="Bulk change undone in Leads",
        now=desk.now,
    )
    await desk.db.flush()
    return BulkUndone(job_id=job_id, **result)


async def history(desk: LeadDesk, limit: int = 20) -> BulkJobs:
    """The workspace's recent bulk changes, newest first (owners, admins and managers)."""
    if not desk.viewer.can_manage:
        raise DeskError(403, "Only owners, admins and managers see bulk changes.")
    jobs = (
        await desk.db.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.tenant_id == desk.tenant_id,
                AuditEvent.resource_type == RESOURCE,
                AuditEvent.action == APPLIED,
            )
            .order_by(AuditEvent.sequence_no.desc())
            .limit(max(1, min(limit, 50)))
        )
    ).all()
    undone = {
        (event.resource_id or "").removeprefix("undo:"): event
        for event in await desk.db.scalars(
            select(AuditEvent).where(
                AuditEvent.tenant_id == desk.tenant_id,
                AuditEvent.resource_type == RESOURCE,
                AuditEvent.action == UNDONE,
                AuditEvent.resource_id.in_([f"undo:{job.resource_id}" for job in jobs]),
            )
        )
    }
    return BulkJobs(
        jobs=tuple([await _view(desk, job, undone.get(job.resource_id or "")) for job in jobs])
    )


async def one_job(desk: LeadDesk, job_id: UUID) -> BulkJob:
    if not desk.viewer.can_manage:
        raise DeskError(403, "Only owners, admins and managers see bulk changes.")
    job = await _audit(desk, str(job_id), APPLIED)
    if job is None:
        raise DeskError(404, "This change isn't here.")
    return await _view(desk, job, await _audit(desk, f"undo:{job_id}", UNDONE))
