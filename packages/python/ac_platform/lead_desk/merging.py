"""Merging two leads that are one person, and undoing it (owner, 25 Oct 2026; design:
docs/product/lead-desk/duplicates.md, sections 3 and 4). The rules are pure, in ``dupes``;
this applies them in one transaction.

A merge:
- keeps the lead with the most human work (then the earliest received), unless the
  manager says which;
- moves the other lead's history, meetings, tasks, messages, AI drafts and calls to it,
  each keeping its own actor and time. Where both leads have an open meeting, the other
  lead's is cancelled first, so one stays open. Open tasks written twice become one;
- fills the kept lead's empty contact fields from the other (its phone too, when the kept
  lead has none);
- keeps the furthest stage, and closes the other lead as Junk, "Merged into another lead":
  the bookkeeping moves (source "merge") are never progress, a conversion, a partner
  event or a seller's work;
- gives the lead to the seller who worked on either in the last 14 days; with two, the
  manager's choice or the most recent; with none, the earliest assignee. Others who worked
  on it get a "worked before" line;
- marks the other lead "merged into" the kept one: it is kept, and opening it leads there;
- records every moved row, so an unmerge within 30 days puts them all back.
Nothing is sent to a lead, an ad platform or a partner. Audit events throughout.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID, uuid5

from sqlalchemy import delete, func, or_, select, update

from ac_platform.audit.service import append_audit_event
from ac_platform.call_data.models import CallObject, CallObjectDecision
from ac_platform.lead_desk import dupes
from ac_platform.lead_desk import meetings as meeting_rows
from ac_platform.lead_desk.contracts import MergeLeads, MergeView, UndoMerge
from ac_platform.lead_desk.errors import DeskError
from ac_platform.lead_desk.journey import model as journeys
from ac_platform.lead_desk.models import (
    Lead,
    LeadAiReply,
    LeadDuplicateDecision,
    LeadDuplicatePair,
    LeadEvent,
    LeadMeeting,
    LeadMerge,
    LeadSocialMessage,
    LeadTask,
    LeadWhatsAppMessage,
)
from ac_platform.lead_desk.vocabulary import MERGED_DUPLICATE

if TYPE_CHECKING:
    from ac_platform.lead_desk.store import LeadDesk

UNDO_FOR: Final = timedelta(days=30)
# The rows that are the lead's story, moved with it. Ad conversions, partner events, SLA
# records and read marks stay with the lead they were made for: a merge sends nothing.
MOVED: Final[tuple[tuple[str, Any], ...]] = (
    ("events", LeadEvent),
    ("meetings", LeadMeeting),
    ("tasks", LeadTask),
    ("whatsapp", LeadWhatsAppMessage),
    ("social", LeadSocialMessage),
    ("ai_replies", LeadAiReply),
    ("calls", CallObject),
    ("call_decisions", CallObjectDecision),
)
# A person's own work on a lead.
HUMAN: Final = ("call", "result", "note", "message", "email", "task", "stage", "meeting")
FILLED: Final = ("email", "company", "city", "language", "interest")


async def _side(desk: LeadDesk, lead: Lead) -> dupes.Side:
    work = (
        await desk.db.execute(
            select(LeadEvent.actor_person_id, func.count(), func.max(LeadEvent.created_at))
            .where(
                LeadEvent.tenant_id == desk.tenant_id,
                LeadEvent.lead_id == lead.id,
                LeadEvent.actor_person_id.is_not(None),
                LeadEvent.kind.in_(HUMAN),
            )
            .group_by(LeadEvent.actor_person_id)
        )
    ).all()
    journey = await desk._labels(journeys.pipeline_of(lead))
    stage = journey.resolve(lead.stage, lead.step)
    return dupes.Side(
        lead_id=lead.id,
        human_activity=sum(int(count) for _, count, _ in work),
        received_at=lead.created_at,
        owner=lead.owner_person_id,
        assigned_at=lead.assigned_at,
        milestone=stage.milestone if stage is not None else "lead",
        touched=tuple((person, at) for person, _, at in work if person is not None),
    )


def _place(journey: journeys.Journey, other: journeys.Journey, lead: Lead) -> journeys.Stage | None:
    """In ``journey``, the stage that says what ``lead``'s stage in ``other`` says."""
    theirs = other.resolve(lead.stage, lead.step)
    if theirs is None:
        return None
    if journey.pipeline == other.pipeline:
        return theirs
    live = [stage for stage in journey.stages if not stage.archived]
    return next(
        (stage for stage in live if stage.milestone == theirs.milestone),
        next((stage for stage in live if stage.kind == theirs.kind), None),
    )


def _owner_words(why: str, name: str | None, by: str, others: list[str]) -> str:
    also = f"; {', '.join(others)} also worked on it" if others else ""
    if why == "active":
        return f"Kept with {name}: worked on it in the last 14 days"
    if why == "asked":
        return f"Kept with {name}, who worked on it last{also}"
    if why == "chosen":
        return f"Given to {name} by {by} on merging{also}"
    if why == "first":
        return f"Kept with {name}: the first to have it"
    return "Nobody worked on these leads lately; it stays as it was"


async def _view(desk: LeadDesk, row: LeadMerge) -> MergeView:
    names = await desk._names([row.owner_person_id])
    kept = await desk.db.get(Lead, row.survivor_lead_id)
    gone = await desk.db.get(Lead, row.merged_lead_id)
    others = [UUID(item) for item in row.moved.get("also_worked", [])]
    other_names = await desk._names(others)
    return MergeView(
        merge_id=row.id,
        kept_lead_id=row.survivor_lead_id,
        kept_name=kept.name if kept is not None else "",
        merged_lead_id=row.merged_lead_id,
        merged_name=gone.name if gone is not None else "",
        owner_person_id=row.owner_person_id,
        owner_name=names.get(row.owner_person_id) if row.owner_person_id else None,
        owner_reason=row.owner_reason,
        owner_why=str(row.moved.get("owner_why", "")),
        also_worked=tuple(other_names[person] for person in others if person in other_names),
        moved={
            key: len(value)
            for key, value in row.moved.items()
            if isinstance(value, list) and key in {name for name, _ in MOVED}
        },
        created_at=row.created_at,
        undo_until=row.created_at + UNDO_FOR,
        undone_at=row.undone_at,
    )


async def merge(desk: LeadDesk, command: MergeLeads) -> MergeView:
    """Merge two leads that are one person; see the module's notes."""
    desk._require_manager()
    done = await desk.db.scalar(
        select(LeadMerge).where(
            LeadMerge.tenant_id == desk.tenant_id, LeadMerge.command_id == command.command_id
        )
    )
    if done is not None:
        return await _view(desk, done)
    first_id, second_id = sorted(set(command.lead_ids))
    if first_id == second_id:
        raise DeskError(422, "Choose two different leads.")
    if command.keep is not None and command.keep not in (first_id, second_id):
        raise DeskError(422, "Keep one of the two leads.")
    # Locked in one order, so two merges never wait on each other.
    leads = {lead_id: await desk._lead(lead_id, lock=True) for lead_id in (first_id, second_id)}
    if any(lead.merged_into_id is not None for lead in leads.values()):
        raise DeskError(409, "One of these leads was merged already. Open the lead it went into.")
    sides = {lead_id: await _side(desk, lead) for lead_id, lead in leads.items()}
    kept_side, gone_side = dupes.survivor(sides[first_id], sides[second_id])
    if command.keep is not None and command.keep != kept_side.lead_id:
        kept_side, gone_side = gone_side, kept_side
    if command.owner_person_id is not None:
        await desk._require_seller(command.owner_person_id)
    choice = dupes.owner_after(kept_side, gone_side, desk.now, chosen=command.owner_person_id)
    if command.owner_person_id is not None and choice.why != "chosen":
        choice = dupes.OwnerChoice(command.owner_person_id, "chosen", choice.others)
    kept, gone = leads[kept_side.lead_id], leads[gone_side.lead_id]
    merge_id = uuid5(command.command_id, "merge")
    moved: dict[str, Any] = {"owner_why": choice.why}

    # One open meeting per lead: the other lead's is cancelled, and moves as history.
    kept_open = await meeting_rows.open_meeting(desk.db, desk.tenant_id, kept.id, lock=True)
    gone_open = await meeting_rows.open_meeting(desk.db, desk.tenant_id, gone.id, lock=True)
    if kept_open is not None and gone_open is not None:
        meeting_rows.close(
            desk,
            gone,
            gone_open,
            "cancelled",
            note=f"Merged into {kept.name}, whose meeting stays",
            command_id=uuid5(command.command_id, "meeting"),
        )
        moved["meetings_cancelled"] = [str(gone_open.id)]
        await desk.db.flush()
    for key, model in MOVED:
        ids = list(
            (
                await desk.db.scalars(
                    select(model.id).where(
                        model.tenant_id == desk.tenant_id, model.lead_id == gone.id
                    )
                )
            ).all()
        )
        if ids:
            await desk.db.execute(update(model).where(model.id.in_(ids)).values(lead_id=kept.id))
            moved[key] = [str(item) for item in ids]
    await desk.db.flush()

    # Open tasks written twice become one: the kept lead's own stays.
    from_gone = set(moved.get("tasks", []))
    open_tasks = (
        await desk.db.scalars(
            select(LeadTask).where(
                LeadTask.tenant_id == desk.tenant_id,
                LeadTask.lead_id == kept.id,
                LeadTask.status == "open",
            )
        )
    ).all()
    seen: set[tuple[str, str]] = set()
    cancelled: list[str] = []
    for task in sorted(open_tasks, key=lambda t: (str(t.id) in from_gone, t.starts_at, str(t.id))):
        same = dupes.task_key(task.title, task.starts_at)
        if same in seen:
            task.status = "cancelled"
            cancelled.append(str(task.id))
        else:
            seen.add(same)
    if cancelled:
        moved["tasks_cancelled"] = cancelled

    # The kept lead's empty contact fields, from the other.
    filled: dict[str, str] = {}
    for name in FILLED:
        value = getattr(gone, name)
        if value and not getattr(kept, name):
            setattr(kept, name, value)
            filled[name] = value
    if gone.phone and not kept.phone:
        phone, gone.phone = gone.phone, None
        await desk.db.flush()
        kept.phone = phone
        filled["phone"] = phone
    if kept.next_action_at is None and gone.next_action_at is not None:
        kept.next_action_at = gone.next_action_at
        filled["next_action_at"] = gone.next_action_at.isoformat()
    if filled:
        moved["filled"] = filled

    # The furthest stage is kept; the other lead closes as merged.
    kept_journey = await desk._labels(journeys.pipeline_of(kept))
    gone_journey = await desk._labels(journeys.pipeline_of(gone))
    moved["kept_stage"] = [kept.stage, kept.step, kept.outcome_reason]
    moved["gone_stage"] = [gone.stage, gone.step, gone.outcome_reason]
    if dupes.furthest(kept_side, gone_side) is gone_side:
        target = _place(kept_journey, gone_journey, gone)
        now_at = kept_journey.resolve(kept.stage, kept.step)
        if target is not None and (now_at is None or now_at.key != target.key):
            desk.to_stage(
                kept,
                kept_journey,
                target,
                note=f"Merged with {gone.name}: its stage was further",
                command_id=uuid5(command.command_id, "kept-stage"),
                source="merge",
                via="api",
                outcome_reason=gone.outcome_reason if target.kind in ("lost", "junk") else None,
            )
    junk = gone_journey.resolve("junk", None)
    current = gone_journey.resolve(gone.stage, gone.step)
    if junk is not None and (current is None or current.key != junk.key):
        desk.to_stage(
            gone,
            gone_journey,
            junk,
            note=f"Merged into {kept.name}",
            command_id=uuid5(command.command_id, "gone-stage"),
            source="merge",
            via="api",
            outcome_reason=MERGED_DUPLICATE,
        )
    elif junk is None:
        gone.stage, gone.step, gone.outcome_reason = "junk", None, MERGED_DUPLICATE
        gone.stage_at = desk.now

    # Who has it now, and why, in one line.
    people = [choice.person_id, *choice.others] if choice.person_id else list(choice.others)
    names = await desk._names(people)
    others = [names[person] for person in choice.others if person in names]
    reason = _owner_words(
        choice.why,
        names.get(choice.person_id) if choice.person_id else None,
        desk.viewer.name,
        others,
    )
    moved["also_worked"] = [str(person) for person in choice.others]
    if choice.person_id is not None and choice.person_id != kept.owner_person_id:
        moved["kept_owner"] = str(kept.owner_person_id) if kept.owner_person_id else None
        await desk._set_owner(
            kept,
            choice.person_id,
            reason,
            "merge",
            actor=desk.viewer.person_id,
            kind="reassigned",
            command_id=uuid5(command.command_id, "owner"),
        )

    gone.merged_into_id, gone.merged_at = kept.id, desk.now
    for lead in (kept, gone):
        lead.revision += 1
        lead.updated_at = desk.now
    desk._event(
        kept,
        "edited",
        {
            "merged_from": str(gone.id),
            "merged_name": gone.name,
            "merge": str(merge_id),
            "owner_reason": reason,
            "worked_before": moved["also_worked"],
            "reason_text": f"Merged with {gone.name}",
        },
        actor=desk.viewer.person_id,
        command_id=uuid5(command.command_id, "kept"),
    )
    desk._event(
        gone,
        "edited",
        {
            "merged_into": str(kept.id),
            "merged_name": kept.name,
            "merge": str(merge_id),
            "reason_text": f"Merged into {kept.name}",
        },
        actor=desk.viewer.person_id,
        command_id=uuid5(command.command_id, "gone"),
    )
    # The pair is decided; the lead merged away pairs with nobody now.
    await desk.db.execute(
        delete(LeadDuplicatePair).where(
            LeadDuplicatePair.tenant_id == desk.tenant_id,
            or_(
                LeadDuplicatePair.first_lead_id == gone.id,
                LeadDuplicatePair.second_lead_id == gone.id,
            ),
        )
    )
    row = LeadMerge(
        id=merge_id,
        tenant_id=desk.tenant_id,
        survivor_lead_id=kept.id,
        merged_lead_id=gone.id,
        owner_person_id=choice.person_id,
        owner_reason=reason[:300],
        moved=moved,
        decided_by_person_id=desk.viewer.person_id,
        command_id=command.command_id,
        created_at=desk.now,
    )
    desk.db.add(row)
    desk.db.add(
        LeadDuplicateDecision(
            id=uuid5(command.command_id, "decision"),
            tenant_id=desk.tenant_id,
            first_lead_id=first_id,
            second_lead_id=second_id,
            decision="merged",
            merge_id=merge_id,
            decided_by_person_id=desk.viewer.person_id,
            decided_at=desk.now,
        )
    )
    await desk.db.flush()
    await append_audit_event(
        desk.db,
        tenant_id=desk.tenant_id,
        actor_person_id=desk.viewer.person_id,
        actor_type="person",
        action="lead_desk.leads_merged",
        resource_type="lead",
        resource_id=kept.id,
        request_id=str(command.command_id),
        reason="Two leads were one person",
        payload={
            "merge_id": str(merge_id),
            "kept": str(kept.id),
            "merged": str(gone.id),
            "owner_why": choice.why,
            "moved": {key: len(value) for key, value in moved.items() if isinstance(value, list)},
        },
    )
    return await _view(desk, row)


async def unmerge(desk: LeadDesk, merge_id: UUID, command: UndoMerge) -> MergeView:
    """Put a merge back within 30 days: every moved row returns, and what the merge changed
    on the kept lead is undone where nobody has changed it since."""
    desk._require_manager()
    row = await desk.db.scalar(
        select(LeadMerge)
        .where(LeadMerge.tenant_id == desk.tenant_id, LeadMerge.id == merge_id)
        .with_for_update()
    )
    if row is None:
        raise DeskError(404, "This merge isn't here.")
    if row.undone_at is not None:
        return await _view(desk, row)
    if desk.now - row.created_at > UNDO_FOR:
        raise DeskError(409, "A merge can be undone for 30 days, and this one is older.")
    kept = await desk._lead(row.survivor_lead_id, lock=True)
    gone = await desk._lead(row.merged_lead_id, lock=True)
    moved = dict(row.moved)
    for key, model in MOVED:
        ids = [UUID(item) for item in moved.get(key, [])]
        if ids:
            await desk.db.execute(
                update(model)
                .where(
                    model.tenant_id == desk.tenant_id, model.id.in_(ids), model.lead_id == kept.id
                )
                .values(lead_id=gone.id)
            )
    await desk.db.flush()
    for task_id in moved.get("tasks_cancelled", []):
        task = await desk.db.get(LeadTask, UUID(task_id))
        if task is not None and task.status == "cancelled":
            task.status = "open"
    for meeting_id in moved.get("meetings_cancelled", []):
        meeting = await desk.db.get(LeadMeeting, UUID(meeting_id))
        if meeting is not None and meeting.status == "cancelled":
            meeting.status, meeting.closed_at = "scheduled", None
            meeting.revision += 1
            meeting.updated_at = desk.now
    filled = dict(moved.get("filled", {}))
    for name in FILLED:
        if name in filled and getattr(kept, name) == filled[name]:
            setattr(kept, name, None)
    if "phone" in filled and kept.phone == filled["phone"]:
        kept.phone = None
        await desk.db.flush()
        gone.phone = filled["phone"]
    if (
        "next_action_at" in filled
        and kept.next_action_at is not None
        and kept.next_action_at.isoformat() == filled["next_action_at"]
    ):
        kept.next_action_at = None

    async def back(lead: Lead, was: list[Any], label: str) -> None:
        journey = await desk._labels(journeys.pipeline_of(lead))
        stage, step, reason = was
        target = journey.resolve(stage, step)
        current = journey.resolve(lead.stage, lead.step)
        if target is not None and (current is None or current.key != target.key):
            desk.to_stage(
                lead,
                journey,
                target,
                note="The merge was undone",
                command_id=uuid5(command.command_id, label),
                source="merge",
                via="api",
                outcome_reason=reason if target.kind in ("lost", "junk") else None,
            )

    await back(gone, moved["gone_stage"], "gone-stage")
    # The kept lead goes back only if the merge moved it and nobody moved it since.
    merge_moves = await desk.db.scalar(
        select(func.count()).where(
            LeadEvent.tenant_id == desk.tenant_id,
            LeadEvent.lead_id == kept.id,
            LeadEvent.command_id == uuid5(row.command_id, "kept-stage"),
        )
    )
    later_moves = await desk.db.scalar(
        select(func.count()).where(
            LeadEvent.tenant_id == desk.tenant_id,
            LeadEvent.lead_id == kept.id,
            LeadEvent.kind.in_(("stage", "result")),
            LeadEvent.created_at > row.created_at + timedelta(seconds=1),
        )
    )
    if merge_moves and not later_moves:
        await back(kept, moved["kept_stage"], "kept-stage")
    if "kept_owner" in moved and kept.owner_person_id == row.owner_person_id:
        before = UUID(moved["kept_owner"]) if moved["kept_owner"] else None
        await desk._set_owner(
            kept,
            before,
            "Back to who had it before the merge",
            "merge",
            actor=desk.viewer.person_id,
            kind="reassigned",
            command_id=uuid5(command.command_id, "owner"),
        )
    gone.merged_into_id, gone.merged_at = None, None
    for lead, words in ((kept, f"Unmerged from {gone.name}"), (gone, f"Unmerged from {kept.name}")):
        lead.revision += 1
        lead.updated_at = desk.now
        desk._event(
            lead,
            "edited",
            {"unmerged": str(row.id), "reason_text": words},
            actor=desk.viewer.person_id,
            command_id=uuid5(command.command_id, f"event:{lead.id}"),
        )
    row.undone_at, row.undone_by_person_id = desk.now, desk.viewer.person_id
    first_id, second_id = sorted((kept.id, gone.id))
    desk.db.add(
        LeadDuplicateDecision(
            id=uuid5(command.command_id, "decision"),
            tenant_id=desk.tenant_id,
            first_lead_id=first_id,
            second_lead_id=second_id,
            decision="unmerged",
            merge_id=row.id,
            decided_by_person_id=desk.viewer.person_id,
            decided_at=desk.now,
        )
    )
    await desk.db.flush()
    await append_audit_event(
        desk.db,
        tenant_id=desk.tenant_id,
        actor_person_id=desk.viewer.person_id,
        actor_type="person",
        action="lead_desk.leads_unmerged",
        resource_type="lead",
        resource_id=kept.id,
        request_id=str(command.command_id),
        reason="A merge was undone",
        payload={"merge_id": str(row.id), "kept": str(kept.id), "merged": str(gone.id)},
    )
    return await _view(desk, row)


def moved_counts(rows: list[LeadMerge]) -> dict[str, int]:
    """How many rows the merges moved, by kind (Admin metric)."""
    total: dict[str, int] = defaultdict(int)
    for row in rows:
        for key, value in row.moved.items():
            if isinstance(value, list):
                total[key] += len(value)
    return dict(total)
