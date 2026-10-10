"""Tentative literal-detail matches; only a person's command establishes a link."""

from typing import Any
from uuid import UUID

from sqlalchemy import and_, select

from ac_platform.conversation_intelligence.acquisition_library import _account_library_query
from ac_platform.conversation_intelligence.acquisition_models import ConversationAcquisitionUsage
from ac_platform.conversation_intelligence.application import utc
from ac_platform.conversation_intelligence.guest_models import ConversationGuestSubmission
from ac_platform.conversation_intelligence.models import ConversationRecording
from ac_platform.conversation_intelligence.prospect_library import ProspectLibrary
from ac_platform.conversation_intelligence.prospect_models import ConversationProspect
from ac_platform.conversation_intelligence.prospect_store import ProspectStore
from ac_platform.conversation_intelligence.sensitive_segments import WITHHELD_MARKER
from ac_platform.kernel.authz import ActorContext

SCHEMA = "ac.sales-xray.prospect-link/1"
PAGE_SIZE = 100


def membership_json(row: Any) -> dict[str, str] | None:
    return (
        None if row is None else {"membership_id": str(row.id), "prospect_id": str(row.prospect_id)}
    )


def _facts(snapshot: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (fact["key"], " ".join(fact["text"].casefold().split())): fact
        for fact in snapshot.get("facts", [])
        if fact["text"].strip()
        and fact["text"] != WITHHELD_MARKER
        and all(ref["quote"] != WITHHELD_MARKER for ref in fact["evidence"])
    }


def _reference(snapshot: dict[str, Any], submission: UUID, fact: dict[str, Any]) -> dict[str, Any]:
    return {
        "submission_id": str(submission),
        **{
            key: snapshot[key]
            for key in (
                "snapshot_id",
                "snapshot_kind",
                "source_revision",
                "source_sha256",
                "run_id",
                "transcript_revision",
            )
        },
        "evidence": fact["evidence"],
    }


async def suggestions(
    store: ProspectStore, actor: ActorContext, submission_id: UUID, *, offset: int = 0
) -> dict[str, Any]:
    scope = await store._write_scope(actor, submission_id, read_only=True)
    current = await store._active(scope)
    linked = await store.read(actor, current.prospect_id) if current else None
    authorized = await store.queries(actor)
    members = authorized.memberships.subquery()
    own_calls = _account_library_query(actor, utc(store.ownership.clock())).with_only_columns(
        ConversationAcquisitionUsage.submission_id
    )
    usage, link, recording, prospect = (
        ConversationAcquisitionUsage,
        ConversationGuestSubmission,
        ConversationRecording,
        ConversationProspect,
    )
    query = (
        select(prospect, usage.submission_id, usage.created_at, recording)
        .select_from(members)
        .join(
            prospect,
            and_(prospect.id == members.c.prospect_id, prospect.tenant_id == members.c.tenant_id),
        )
        .join(
            link,
            and_(
                link.submission_id == members.c.submission_id, link.tenant_id == members.c.tenant_id
            ),
        )
        .join(usage, usage.id == link.usage_id)
        .join(recording, recording.id == link.recording_id)
        .where(
            prospect.owner_person_id == actor.person_id,
            usage.submission_id.in_(own_calls),
            usage.submission_id != submission_id,
        )
        .order_by(usage.created_at.desc(), usage.submission_id.desc())
        .offset(offset)
        .limit(PAGE_SIZE + 1)
    )
    # Shared recording fences serialize privacy erasure. Recheck retained scope
    # after waiting and only project recordings for which a fence was acquired.
    locked = (await store.database.execute(query.with_for_update(of=recording, read=True))).all()
    rows = (
        await store.database.execute(
            query.where(usage.submission_id.in_([row[1] for row in locked])).offset(0)
        )
    ).all()
    source = await store.database.get(ConversationRecording, scope.recording_id)
    assert source is not None  # _write_scope holds and verifies this row
    snapshots = await ProspectLibrary(store)._snapshots(
        [source, *(row[3] for row in rows[:PAGE_SIZE])], include_facts=True
    )
    source_snapshot = snapshots.get(source.id, {})
    source_facts = _facts(source_snapshot)
    matches = {}
    for row, submission, created, rec in rows[:PAGE_SIZE]:
        if row.id in matches or (current is not None and row.id == current.prospect_id):
            continue
        previous = snapshots.get(rec.id, {})
        previous_facts = _facts(previous)
        shared = sorted(source_facts.keys() & previous_facts.keys())
        if shared:
            matches[row.id] = {
                "prospect_id": str(row.id),
                "name": row.display_name,
                "previous_call_at": created.isoformat(),
                "kind": "shared_stated_details",
                "confirmed": False,
                "details": [
                    {
                        "key": key[0],
                        "text": source_facts[key]["text"],
                        "current": _reference(source_snapshot, submission_id, source_facts[key]),
                        "previous": _reference(previous, submission, previous_facts[key]),
                    }
                    for key in shared
                ],
            }
    return {
        "schema": SCHEMA,
        "submission_id": str(submission_id),
        "membership": membership_json(current),
        "linked_prospect": {
            "name": linked.display_name,
            "origin": linked.origin,
            "confirmed_at": linked.confirmed_at.isoformat() if linked.confirmed_at else None,
            "revision": linked.revision,
        }
        if linked
        else None,
        "suggestions": list(matches.values()),
        "next_offset": offset + PAGE_SIZE if len(rows) > PAGE_SIZE else None,
    }
