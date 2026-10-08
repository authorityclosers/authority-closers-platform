"""Explicit prospect storage; callers own the transaction, HTTP writes live elsewhere."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Select, and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.audit.service import AuditRepository
from ac_platform.conversation_intelligence.acquisition_library import _account_library_query
from ac_platform.conversation_intelligence.acquisition_models import ConversationAcquisitionUsage
from ac_platform.conversation_intelligence.application import (
    ConversationConflict,
    ConversationDenied,
    ConversationError,
    ConversationNotFound,
    utc,
)
from ac_platform.conversation_intelligence.guest_models import ConversationGuestSubmission
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership, SubmissionScope
from ac_platform.conversation_intelligence.inference import binding_for, verified_checkpoint
from ac_platform.conversation_intelligence.models import (
    ConversationCheckpoint,
    ConversationRecording,
)
from ac_platform.conversation_intelligence.prospect_fact_contract import ProspectFactValidationError
from ac_platform.conversation_intelligence.prospect_fields import validate_evidence, validate_fields
from ac_platform.conversation_intelligence.prospect_models import (
    ConversationProspect,
    ConversationProspectFieldRevision,
    ConversationProspectMembership,
)
from ac_platform.conversation_intelligence.sensitive_segment_models import (
    ConversationSensitiveSegmentMark,
)
from ac_platform.conversation_intelligence.sensitive_segments import (
    WITHHELD_MARKER,
    grams,
    withheld_plan,
    withhold,
)
from ac_platform.conversation_intelligence.sensitive_segments_store import _effective_statement
from ac_platform.kernel.authz import ActorContext


def validated_tags(value: object) -> list[str]:
    if (
        not isinstance(value, list)
        or len(value) > 10
        or any(
            not isinstance(tag, str) or not 1 <= len(tag) <= 40 or not tag.strip() for tag in value
        )
    ):
        raise ValueError("Supply valid prospect tags.")
    tags = [tag.strip() for tag in value]
    if len(set(tags)) != len(tags):
        raise ValueError("Supply distinct prospect tags.")
    return tags


@dataclass(frozen=True)
class ProspectQueries:
    """Authorized SQL building blocks for bounded API pages/aggregates.

    Aggregate only ``memberships``. It contains active links to retained Calls
    visible to this reader. ``prospects`` also includes creator/owner name-only
    rows. Neither query grants access to audio, reports or mutation.
    """

    prospects: Select[tuple[ConversationProspect]]
    memberships: Select[tuple[ConversationProspectMembership]]


class ProspectStore:
    def __init__(self, ownership: GuestOwnership) -> None:
        self.ownership = ownership
        self.database: AsyncSession = ownership.database

    async def queries(self, actor: ActorContext) -> ProspectQueries:
        now = await self.ownership.sessions._admit()
        await self.ownership.sessions._owner(None, actor, now, shared_identity_locks=True)
        if actor.tenant_id != self.ownership.tenant_id:
            raise ConversationDenied("Select the same workspace as this prospect library.")
        every_owner = await self.ownership.organisation_call_reader(actor)
        usage, member, prospect = (
            ConversationAcquisitionUsage,
            ConversationProspectMembership,
            ConversationProspect,
        )
        visible_calls = _account_library_query(
            actor, now, every_owner=every_owner
        ).with_only_columns(usage.submission_id)
        memberships = select(member).where(
            member.tenant_id == actor.tenant_id,
            member.ended_at.is_(None),
            member.submission_id.in_(visible_calls),
        )
        prospects = select(prospect).where(
            prospect.tenant_id == actor.tenant_id,
            or_(
                prospect.created_by_person_id == actor.person_id,
                prospect.owner_person_id == actor.person_id,
                prospect.id.in_(memberships.with_only_columns(member.prospect_id)),
            ),
        )
        return ProspectQueries(prospects, memberships)

    async def read(self, actor: ActorContext, prospect_id: UUID) -> ConversationProspect:
        query = (await self.queries(actor)).prospects
        row = await self.database.scalar(query.where(ConversationProspect.id == prospect_id))
        if row is None:
            raise ConversationNotFound("This prospect is unavailable.")
        return row

    async def read_memberships(
        self, actor: ActorContext, prospect_id: UUID, *, limit: int = 100
    ) -> Sequence[ConversationProspectMembership]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ConversationError("Read between 1 and 100 call memberships.")
        query = (await self.queries(actor)).memberships
        member = ConversationProspectMembership
        return (
            await self.database.scalars(
                query.where(member.prospect_id == prospect_id)
                .order_by(member.created_at.desc(), member.id.desc())
                .limit(limit)
            )
        ).all()

    async def edit_name(
        self, actor: ActorContext, prospect_id: UUID, *, display_name: str, expected_revision: int
    ) -> ConversationProspect:
        if (
            not isinstance(display_name, str)
            or not 1 <= len(display_name) <= 160
            or not display_name.strip()
            or type(expected_revision) is not int
            or expected_revision < 1
        ):
            raise ConversationError("Supply a valid prospect name and revision.")
        query = (await self.queries(actor)).prospects
        row = await self.database.scalar(
            query.where(
                ConversationProspect.id == prospect_id,
                ConversationProspect.owner_person_id == actor.person_id,
            )
            .with_for_update(of=ConversationProspect)
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise ConversationNotFound("This prospect is unavailable.")
        if row.revision != expected_revision:
            raise ConversationConflict("The prospect changed. Reload before saving again.")
        name = display_name.strip()
        if row.display_name == name:
            return row
        previous_revision = row.revision
        now = utc(self.ownership.clock())
        row.display_name, row.revision, row.updated_at = name, previous_revision + 1, now
        await self._append_fields(
            row, {"name": {"kind": "text", "text": name}}, actor=actor, now=now
        )
        await self.database.flush()
        await self._audit(
            actor,
            row.id,
            "name_changed",
            {
                "field": "display_name",
                "previous_revision": str(previous_revision),
                "current_revision": str(row.revision),
            },
            now,
        )
        return row

    async def edit_fields(
        self, actor: ActorContext, prospect_id: UUID, *, fields: object, expected_revision: int
    ) -> ConversationProspect:
        try:
            values = validate_fields(fields)
        except ProspectFactValidationError:
            raise ConversationError("Supply valid prospect fields.") from None
        if type(expected_revision) is not int or expected_revision < 1:
            raise ConversationError("Supply a valid prospect revision.")
        row = await self._field_target(actor, prospect_id)
        if row.revision != expected_revision:
            raise ConversationConflict("The prospect changed. Reload before saving again.")
        latest = await self._latest_fields(row, basis="person")
        changed = {
            key: value
            for key, value in values.items()
            if key not in latest or latest[key].value != value
        }
        if not changed:
            return row
        before, now = row.revision, utc(self.ownership.clock())
        row.revision, row.updated_at = before + 1, now
        await self._append_fields(row, changed, actor=actor, now=now)
        if "name" in changed:
            row.display_name = str(changed["name"]["text"])
        await self.database.flush()
        await self._audit(
            actor,
            row.id,
            "fields_changed",
            {
                "field_count": str(len(changed)),
                "previous_revision": str(before),
                "current_revision": str(row.revision),
            },
            now,
        )
        return row

    async def _field_target(self, actor: ActorContext, prospect_id: UUID) -> ConversationProspect:
        query = (await self.queries(actor)).prospects
        row = await self.database.scalar(
            query.where(
                ConversationProspect.id == prospect_id,
                ConversationProspect.owner_person_id == actor.person_id,
            )
            .with_for_update(of=ConversationProspect)
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise ConversationNotFound("This prospect is unavailable.")
        return row

    async def _latest_fields(
        self, row: ConversationProspect, *, basis: str | None = None
    ) -> dict[str, ConversationProspectFieldRevision]:
        field = ConversationProspectFieldRevision
        ranked = select(
            field.id,
            func.row_number()
            .over(partition_by=field.field_key, order_by=field.revision.desc())
            .label("rank"),
        ).where(field.tenant_id == row.tenant_id, field.entity_id == row.id)
        if basis:
            ranked = ranked.where(field.basis == basis)
        ranked_rows = ranked.subquery()
        rows = (
            await self.database.scalars(
                select(field)
                .join(ranked_rows, ranked_rows.c.id == field.id)
                .where(ranked_rows.c.rank == 1)
            )
        ).all()
        return {r.field_key: r for r in rows}

    async def _append_fields(
        self,
        row: ConversationProspect,
        values: dict[str, dict[str, Any]],
        *,
        actor: ActorContext | None,
        now: datetime,
        submission_id: UUID | None = None,
        evidence: dict[str, dict[str, Any]] | None = None,
        extractor_revision: str | None = None,
    ) -> None:
        latest = await self._latest_fields(row)
        self.database.add_all(
            [
                ConversationProspectFieldRevision(
                    id=uuid4(),
                    tenant_id=row.tenant_id,
                    entity_id=row.id,
                    field_key=key,
                    revision=row.revision,
                    value=value,
                    basis="person" if actor else "heard_in_call",
                    state="confirmed" if actor else "detected",
                    created_by_person_id=actor.person_id if actor else None,
                    created_at=now,
                    supersedes_id=latest[key].id if key in latest else None,
                    submission_id=submission_id,
                    evidence=evidence[key] if evidence else None,
                    extractor_revision=extractor_revision,
                )
                for key, value in values.items()
            ]
        )
        await self.database.flush()

    async def record_detected(
        self,
        actor: ActorContext,
        prospect_id: UUID,
        *,
        submission_id: UUID,
        fields: object,
        evidence: dict[str, Any],
        extractor_revision: str,
    ) -> ConversationProspect:
        """Caller owns the transaction; no extraction/provider activation here.

        Hold the source fence before the prospect row, like call linking. Every
        detection is source-verified, including detections behind a person lock.
        """
        try:
            values = validate_fields(fields, detected=True)
            if (
                not isinstance(evidence, dict)
                or set(evidence) != set(values)
                or not isinstance(extractor_revision, str)
                or not 1 <= len(extractor_revision.strip()) <= 160
            ):
                raise ProspectFactValidationError("invalid_detection")
            refs = {key: validate_evidence(value) for key, value in evidence.items()}
        except (ProspectFactValidationError, TypeError):
            raise ConversationError("Supply supported detected prospect fields.") from None
        scope = await self._write_scope(actor, submission_id, read_only=True)
        member = await self._active(scope)
        if member is None or member.prospect_id != prospect_id:
            raise ConversationNotFound("This prospect is unavailable.")
        recording = await self.database.get(ConversationRecording, scope.recording_id)
        assert recording is not None
        sources = await self._field_sources([recording])
        if any(
            not self._supported_field(value, refs[key], sources.get(recording.id, []))
            for key, value in values.items()
        ):
            raise ConversationError("Supply supported detected prospect fields.")
        row = await self._field_target(actor, prospect_id)
        latest = await self._latest_fields(row, basis="heard_in_call")
        changed = {
            key: value
            for key, value in values.items()
            if key not in latest
            or (
                latest[key].value,
                latest[key].evidence,
                latest[key].submission_id,
                latest[key].extractor_revision,
            )
            != (value, refs[key], submission_id, extractor_revision)
        }
        if not changed:
            return row
        before, now = row.revision, utc(self.ownership.clock())
        row.revision, row.updated_at = before + 1, now
        await self._append_fields(
            row,
            changed,
            actor=None,
            now=now,
            submission_id=submission_id,
            evidence=refs,
            extractor_revision=extractor_revision,
        )
        await self.database.flush()
        await self._audit(
            actor,
            row.id,
            "fields_detected",
            {
                "field_count": str(len(changed)),
                "previous_revision": str(before),
                "current_revision": str(row.revision),
            },
            now,
        )
        return row

    async def field_rows(
        self, actor: ActorContext, ids: list[UUID], scope: ProspectQueries
    ) -> Sequence[ConversationProspectFieldRevision]:
        """Four batch reads, independent of the number of fields or prospects.

        Detected rows require an active, readable source; the source lock and
        recheck prevent content surviving an erasure/read race. Five recent
        detections per field are enough for the bounded disagreement panel.
        """
        field, link, usage, recording = (
            ConversationProspectFieldRevision,
            ConversationGuestSubmission,
            ConversationAcquisitionUsage,
            ConversationRecording,
        )
        visible = scope.memberships.subquery()
        source = (
            select(visible.c.submission_id)
            .where(visible.c.prospect_id == field.entity_id)
            .correlate(field)
        )
        eligible = and_(
            field.tenant_id == actor.tenant_id,
            field.entity_id.in_(ids),
            field.entity_id.in_(scope.prospects.with_only_columns(ConversationProspect.id)),
            or_(field.basis == "person", field.submission_id.in_(source)),
        )
        locked = (
            await self.database.execute(
                select(link.submission_id, recording)
                .join(
                    link,
                    and_(link.recording_id == recording.id, link.tenant_id == recording.tenant_id),
                )
                .where(
                    link.submission_id.in_(
                        select(field.submission_id).where(eligible, field.basis == "heard_in_call")
                    )
                )
                .with_for_update(of=recording, read=True)
                .execution_options(populate_existing=True)
            )
        ).all()
        recordings = [r for _, r in locked]
        ranked = (
            select(
                field.id,
                func.row_number()
                .over(
                    partition_by=(field.entity_id, field.field_key, field.basis),
                    order_by=(
                        case((field.basis == "person", None), else_=usage.created_at).desc(),
                        field.revision.desc(),
                    ),
                )
                .label("rank"),
            )
            .outerjoin(
                usage,
                and_(
                    usage.tenant_id == field.tenant_id, usage.submission_id == field.submission_id
                ),
            )
            .where(eligible)
            .subquery()
        )
        rows = (
            await self.database.scalars(
                select(field)
                .join(ranked, ranked.c.id == field.id)
                .where(
                    or_(
                        and_(field.basis == "person", ranked.c.rank == 1),
                        and_(field.basis == "heard_in_call", ranked.c.rank <= 5),
                    )
                )
                .order_by(field.entity_id, field.field_key, field.basis.desc(), ranked.c.rank)
            )
        ).all()
        sources = await self._field_sources(recordings)
        by_submission = {submission: r.id for submission, r in locked}
        return [
            r
            for r in rows
            if r.basis == "person"
            or (
                r.submission_id is not None
                and r.submission_id in by_submission
                and self._supported_field(
                    r.value, r.evidence or {}, sources.get(by_submission[r.submission_id], [])
                )
            )
        ]

    async def _field_sources(
        self, recordings: Sequence[ConversationRecording]
    ) -> dict[UUID, list[tuple[dict[str, Any], Any]]]:
        checkpoints = (
            await self.database.scalars(
                select(ConversationCheckpoint)
                .where(
                    ConversationCheckpoint.recording_id.in_([r.id for r in recordings]),
                    ConversationCheckpoint.stage == "C2",
                    ConversationCheckpoint.erased_at.is_(None),
                )
                .order_by(
                    ConversationCheckpoint.created_at.desc(), ConversationCheckpoint.id.desc()
                )
            )
        ).all()
        revisions = [r.payload.get("revision") for r in checkpoints if r.payload]
        mark = ConversationSensitiveSegmentMark
        marks = (
            await self.database.scalars(
                _effective_statement(
                    or_(
                        mark.recording_id.in_([r.id for r in recordings]),
                        mark.transcript_revision.in_(revisions),
                    )
                )
            )
        ).all()
        result: dict[UUID, list[tuple[dict[str, Any], Any]]] = {}
        for recording in recordings:
            texts = {
                r.payload["revision"]: {
                    s["id"]: s.get("text", "") for s in r.payload.get("segments", [])
                }
                for r in checkpoints
                if r.recording_id == recording.id and r.payload
            }
            for checkpoint in checkpoints:
                if checkpoint.recording_id != recording.id or not checkpoint.payload:
                    continue
                try:
                    verified_checkpoint(checkpoint, binding_for(recording))
                except ConversationError:
                    continue
                segments = {s["id"]: s for s in checkpoint.payload.get("segments", [])}
                effective = [
                    m
                    for m in marks
                    if m.recording_id == recording.id
                    or m.transcript_revision == checkpoint.payload.get("revision")
                ]
                plan = withheld_plan(
                    [(key, s.get("text", "")) for key, s in segments.items()],
                    {
                        m.segment_id
                        for m in effective
                        if m.transcript_revision == checkpoint.payload.get("revision")
                    },
                    {
                        g
                        for m in effective
                        for g in grams(texts.get(m.transcript_revision, {}).get(m.segment_id, ""))
                    },
                )
                result.setdefault(recording.id, []).append((segments, plan))
        return result

    @staticmethod
    def _supported_field(
        value: dict[str, Any], evidence: dict[str, Any], sources: list[tuple[dict[str, Any], Any]]
    ) -> bool:
        segment_id = evidence.get("segment_id")
        if not isinstance(segment_id, str):
            return False
        for segments, plan in sources:
            segment = segments.get(segment_id)
            if (
                segment is not None
                and evidence.get("quote")
                and evidence["quote"] in segment.get("text", "")
                and evidence.get("start_ms") == segment.get("start_ms")
                and evidence.get("end_ms") == segment.get("end_ms")
            ):
                projected = withhold({"value": value, "evidence": evidence}, plan)
                if WITHHELD_MARKER not in str(projected):
                    return True
        return False

    async def edit_tags(
        self, actor: ActorContext, prospect_id: UUID, *, tags: list[str], expected_revision: int
    ) -> ConversationProspect:
        try:
            tags = validated_tags(tags)
        except ValueError:
            raise ConversationError("Supply valid prospect tags and revision.") from None
        if type(expected_revision) is not int or expected_revision < 1:
            raise ConversationError("Supply valid prospect tags and revision.")
        query = (await self.queries(actor)).prospects
        row = await self.database.scalar(
            query.where(
                ConversationProspect.id == prospect_id,
                ConversationProspect.owner_person_id == actor.person_id,
            )
            .with_for_update(of=ConversationProspect)
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise ConversationNotFound("This prospect is unavailable.")
        if row.revision != expected_revision:
            raise ConversationConflict("The prospect changed. Reload before saving again.")
        if row.tags == tags:
            return row
        previous_revision, previous_count = row.revision, len(row.tags)
        now = utc(self.ownership.clock())
        row.tags, row.revision, row.updated_at = tags, previous_revision + 1, now
        await self.database.flush()
        await self._audit(
            actor,
            row.id,
            "tags_changed",
            {
                "field": "tags",
                "previous_revision": str(previous_revision),
                "current_revision": str(row.revision),
                "previous_tag_count": str(previous_count),
                "current_tag_count": str(len(tags)),
            },
            now,
        )
        return row

    async def _write_scope(
        self, actor: ActorContext, submission_id: UUID, *, read_only: bool = False
    ) -> SubmissionScope:
        scope = await self.ownership.require_submission_owner(
            submission_id, actor=actor, shared_identity_locks=True
        )
        if not scope.claimed_account or scope.tenant_id != actor.tenant_id:
            raise ConversationDenied("Claim this call before linking a prospect.")
        recording = await self.database.scalar(
            select(ConversationRecording)
            .where(
                ConversationRecording.id == scope.recording_id,
                ConversationRecording.tenant_id == scope.tenant_id,
            )
            .with_for_update(read=read_only)
            .execution_options(populate_existing=True)
        )
        if recording is None or recording.state not in ("awaiting_upload", "ready"):
            raise ConversationNotFound("This call is unavailable.")
        # Recheck source retention/ownership after the erasure fence is acquired.
        if (
            await self.ownership.require_submission_owner(
                submission_id, actor=actor, shared_identity_locks=True
            )
            != scope
            or await self.database.scalar(
                _account_library_query(actor, utc(self.ownership.clock())).where(
                    ConversationAcquisitionUsage.submission_id == submission_id
                )
            )
            is None
        ):
            raise ConversationNotFound("This call is unavailable.")
        return scope

    async def _active(self, scope: SubmissionScope) -> ConversationProspectMembership | None:
        member = ConversationProspectMembership
        row: ConversationProspectMembership | None = await self.database.scalar(
            select(member).where(
                member.tenant_id == scope.tenant_id,
                member.submission_id == scope.submission_id,
                member.ended_at.is_(None),
            )
        )
        return row

    async def create_from_call(
        self, actor: ActorContext, submission_id: UUID, *, display_name: str
    ) -> ConversationProspect:
        """Create a new stable ID only on an explicit person's command; no name lookup."""
        if not isinstance(display_name, str) or not 1 <= len(display_name.strip()) <= 160:
            raise ConversationError("Enter a prospect name of at most 160 characters.")
        scope = await self._write_scope(actor, submission_id)
        if await self._active(scope) is not None:
            raise ConversationConflict(
                "This call already has a prospect. Confirm a new link first."
            )
        now = utc(self.ownership.clock())
        prospect = ConversationProspect(
            id=uuid4(),
            tenant_id=scope.tenant_id,
            display_name=display_name.strip(),
            created_by_person_id=actor.person_id,
            owner_person_id=actor.person_id,
            created_at=now,
            updated_at=now,
            revision=1,
        )
        self.database.add(prospect)
        await self.database.flush()
        await self._append_fields(
            prospect,
            {"name": {"kind": "text", "text": prospect.display_name}},
            actor=actor,
            now=now,
        )
        await self._audit(actor, prospect.id, "created", {}, now)
        await self._append(actor, scope, prospect.id, now)
        return prospect

    async def confirm_link(
        self,
        actor: ActorContext,
        submission_id: UUID,
        prospect_id: UUID,
        *,
        expected_membership_id: UUID | None,
    ) -> ConversationProspectMembership:
        scope = await self._write_scope(actor, submission_id)
        prospect = await self.read(actor, prospect_id)
        if prospect.owner_person_id != actor.person_id:
            raise ConversationNotFound("This prospect is unavailable.")
        current = await self._active(scope)
        if current is not None and current.prospect_id == prospect_id:
            return current
        if (None if current is None else current.id) != expected_membership_id:
            raise ConversationConflict("The call link changed. Reload before confirming.")
        now = utc(self.ownership.clock())
        if current is not None:
            await self._end(current, "superseded", now, actor)
        return await self._append(actor, scope, prospect_id, now)

    async def unlink(
        self, actor: ActorContext, submission_id: UUID, *, expected_membership_id: UUID
    ) -> None:
        scope = await self._write_scope(actor, submission_id)
        current = await self._active(scope)
        if current is None or current.id != expected_membership_id:
            raise ConversationConflict("The call link changed. Reload before unlinking.")
        await self._end(current, "unlinked", utc(self.ownership.clock()), actor)

    async def _append(
        self, actor: ActorContext, scope: SubmissionScope, prospect_id: UUID, now: datetime
    ) -> ConversationProspectMembership:
        row = ConversationProspectMembership(
            id=uuid4(),
            tenant_id=scope.tenant_id,
            prospect_id=prospect_id,
            submission_id=scope.submission_id,
            linked_by_person_id=actor.person_id,
            created_at=now,
        )
        self.database.add(row)
        await self.database.flush()
        await self._audit(
            actor,
            prospect_id,
            "call_linked",
            {"membership_id": str(row.id), "submission_id": str(scope.submission_id)},
            now,
        )
        return row

    async def _end(
        self, row: ConversationProspectMembership, reason: str, now: datetime, actor: ActorContext
    ) -> None:
        await end_membership(self.database, row, reason, now, actor)

    async def _audit(
        self,
        actor: ActorContext,
        prospect_id: UUID,
        action: str,
        payload: dict[str, str],
        now: datetime,
    ) -> None:
        await AuditRepository(self.database).append(
            tenant_id=self.ownership.tenant_id,
            actor_person_id=actor.person_id,
            session_id=actor.session_id,
            action=f"conversation.prospect_{action}",
            resource_type="conversation_prospect",
            resource_id=prospect_id,
            payload=payload,
            now=now,
        )


async def end_membership(
    database: AsyncSession,
    row: ConversationProspectMembership,
    reason: str,
    now: datetime,
    actor: ActorContext | None = None,
) -> None:
    row.ended_at, row.ended_reason = now, reason
    row.ended_by_person_id = None if actor is None else actor.person_id
    await database.flush()
    await AuditRepository(database).append(
        tenant_id=row.tenant_id,
        actor_person_id=None if actor is None else actor.person_id,
        actor_type="system" if actor is None else "person",
        session_id=None if actor is None else actor.session_id,
        action="conversation.prospect_call_ended",
        resource_type="conversation_prospect",
        resource_id=row.prospect_id,
        payload={
            "membership_id": str(row.id),
            "submission_id": str(row.submission_id),
            "reason": reason,
        },
        now=now,
    )


async def end_prospect_memberships_for_recording(
    database: AsyncSession, *, tenant_id: UUID, recording_id: UUID, now: datetime
) -> None:
    """Called under the canonical recording erasure lock; keeps non-content history."""
    submission_ids = select(ConversationGuestSubmission.submission_id).where(
        ConversationGuestSubmission.tenant_id == tenant_id,
        ConversationGuestSubmission.recording_id == recording_id,
    )
    member = ConversationProspectMembership
    rows = (
        await database.scalars(
            select(member)
            .where(
                member.tenant_id == tenant_id,
                member.submission_id.in_(submission_ids),
                member.ended_at.is_(None),
            )
            .order_by(member.id)
        )
    ).all()
    for row in rows:
        await end_membership(database, row, "source_erasure", now)
