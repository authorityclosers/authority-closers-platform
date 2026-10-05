"""Read-only prospect pages over explicit, authorized Calls memberships.

Call snapshots remain source-bound hypotheses. No profile, stage, promise,
readiness measure or score is inferred from their prose.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import and_, false, func, or_, select

from ac_platform.conversation_intelligence.acquisition_library import _report_columns
from ac_platform.conversation_intelligence.acquisition_models import ConversationAcquisitionUsage
from ac_platform.conversation_intelligence.application import (
    ConversationError,
    ConversationNotFound,
)
from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.guest_models import ConversationGuestSubmission
from ac_platform.conversation_intelligence.inference import binding_for, verified_checkpoint
from ac_platform.conversation_intelligence.models import (
    ConversationCheckpoint,
    ConversationRecording,
)
from ac_platform.conversation_intelligence.prospect_models import ConversationProspect
from ac_platform.conversation_intelligence.prospect_store import ProspectStore
from ac_platform.conversation_intelligence.recovery_models import ConversationRetainedC5Version
from ac_platform.conversation_intelligence.reports import ReportDraft
from ac_platform.conversation_intelligence.sensitive_segment_models import (
    ConversationSensitiveSegmentMark,
)
from ac_platform.conversation_intelligence.sensitive_segments import grams, withheld_plan, withhold
from ac_platform.conversation_intelligence.sensitive_segments_store import _effective_statement
from ac_platform.conversation_intelligence.submission_label_models import (
    ConversationSubmissionLabelRevision,
)
from ac_platform.kernel.authz import ActorContext

PAGE_SIZE = 20
SCHEMA = "ac.sales-xray.prospects/1"


def profile(row: ConversationProspect) -> dict[str, Any]:
    return {
        "prospect_id": str(row.id),
        "name": row.display_name,
        "revision": row.revision,
        "owner_person_id": str(row.owner_person_id),
        "stage": None,
        "tags": [],
        "photo_url": None,
        "contact": None,
        "fields": [],
        "buyer_intent": None,
        "next_step": None,
        "last_promise": None,
    }


class ProspectLibrary:
    def __init__(self, store: ProspectStore) -> None:
        self.store, self.database = store, store.database

    async def read(
        self,
        actor: ActorContext,
        *,
        prospect_id: UUID | None = None,
        search: str = "",
        stage: str | None = None,
        offset: int = 0,
    ) -> dict[str, Any]:
        if (
            offset < 0
            or offset > 100_000
            or len(search) > 160
            or (stage is not None and len(stage) > 160)
        ):
            raise ConversationError("Use a bounded prospect page and search.")
        scope = await self.store.queries(actor)
        visible = scope.memberships.subquery()
        usage, link, recording = (
            ConversationAcquisitionUsage,
            ConversationGuestSubmission,
            ConversationRecording,
        )
        calls = (
            select(visible.c.prospect_id, usage.created_at)
            .join(
                usage,
                and_(
                    usage.submission_id == visible.c.submission_id,
                    usage.tenant_id == visible.c.tenant_id,
                ),
            )
            .subquery()
        )
        totals = (
            select(
                calls.c.prospect_id,
                func.count().label("call_count"),
                func.max(calls.c.created_at).label("last_call"),
            )
            .group_by(calls.c.prospect_id)
            .subquery()
        )
        query = scope.prospects
        if prospect_id is not None:
            query = query.where(ConversationProspect.id == prospect_id)
        else:
            if search.strip():
                query = query.where(
                    ConversationProspect.display_name.icontains(search.strip(), autoescape=True)
                )
            # There is currently no stored stage column. This selector means
            # missing stage; all named stage filters truthfully match no rows.
            if stage is not None and stage != "__missing__":
                query = query.where(false())
        total = await self.database.scalar(select(func.count()).select_from(query.subquery()))
        selected = (
            await self.database.execute(
                query.outerjoin(totals, totals.c.prospect_id == ConversationProspect.id)
                .add_columns(func.coalesce(totals.c.call_count, 0), totals.c.last_call)
                .order_by(func.lower(ConversationProspect.display_name), ConversationProspect.id)
                .offset(0 if prospect_id is not None else offset)
                .limit(1 if prospect_id is not None else PAGE_SIZE)
            )
        ).all()
        entries = [
            {
                **profile(row),
                "call_count": count,
                "last_call": None if last is None else last.isoformat(),
            }
            for row, count, last in selected
        ]
        if prospect_id is None:
            return {
                "schema": SCHEMA,
                "prospects": entries,
                "total": total,
                "stage_filters": [],
                "next_offset": offset + PAGE_SIZE if offset + PAGE_SIZE < (total or 0) else None,
            }
        if not entries:
            raise ConversationNotFound("This prospect is unavailable.")
        has_report, plan_state = _report_columns()
        label = ConversationSubmissionLabelRevision
        last_label = (
            select(label.display_name)
            .where(label.tenant_id == link.tenant_id, label.submission_id == link.submission_id)
            .order_by(label.revision.desc())
            .limit(1)
            .correlate(link)
            .scalar_subquery()
        )
        call_query = (
            select(
                usage.submission_id,
                usage.created_at,
                usage.reserved_seconds,
                recording,
                has_report,
                plan_state,
                last_label,
            )
            .select_from(visible)
            .join(
                link,
                and_(
                    link.submission_id == visible.c.submission_id,
                    link.tenant_id == visible.c.tenant_id,
                ),
            )
            .join(usage, usage.id == link.usage_id)
            .join(recording, recording.id == link.recording_id)
            .where(visible.c.prospect_id == prospect_id)
            .order_by(usage.created_at.desc(), usage.submission_id.desc())
            .offset(offset)
            .limit(PAGE_SIZE)
        )
        # The recording is the existing report/erasure fence. Recheck retained
        # Calls scope after waiting for it, before reading any snapshot content.
        await self.database.execute(call_query.with_for_update(of=recording, read=True))
        rows = (await self.database.execute(call_query)).all()
        snapshots = await self._snapshots([row[3] for row in rows])
        history = [
            {
                "submission_id": str(submission),
                "recording_id": str(rec.id),
                "created_at": created.isoformat(),
                "duration_seconds": duration,
                "display_name": name,
                "state": "report_ready" if ready else state or rec.state,
                "has_report": bool(ready),
                "score": None,
                "call_url": f"/analysis/calls/{submission}",
                "report_url": f"/analysis/calls/{submission}" if ready else None,
                "snapshot": snapshots.get(rec.id),
            }
            for submission, created, duration, rec, ready, state, name in rows
        ]
        return {
            "schema": SCHEMA,
            "prospect": entries[0],
            "calls": history,
            "next_offset": offset + PAGE_SIZE
            if offset + PAGE_SIZE < entries[0]["call_count"]
            else None,
            "promises": [],
            "next_steps": [],
            "buyer_intent_history": [],
        }

    async def _snapshots(
        self, recordings: list[ConversationRecording], *, include_facts: bool = False
    ) -> dict[UUID, Any]:
        """Three batch reads, independent of call count; never invoke a provider.

        Use retained recovery versions or source-verified C5 checkpoints, rather
        than claiming canonical report publication from arbitrary draft rows.
        Only source notes present in the served C2 transcript are projected.
        """
        ids = [row.id for row in recordings]
        c = ConversationCheckpoint
        checkpoints = (
            await self.database.scalars(
                select(c)
                .where(c.recording_id.in_(ids), c.erased_at.is_(None), c.stage.in_(("C2", "C5")))
                .order_by(c.created_at.desc(), c.id.desc())
            )
        ).all()
        recovered = (
            await self.database.scalars(
                select(ConversationRetainedC5Version)
                .where(
                    ConversationRetainedC5Version.recording_id.in_(ids),
                    ConversationRetainedC5Version.erased_at.is_(None),
                    ConversationRetainedC5Version.payload.is_not(None),
                )
                .order_by(
                    ConversationRetainedC5Version.created_at.desc(),
                    ConversationRetainedC5Version.id.desc(),
                )
            )
        ).all()
        revisions = [
            row.payload.get("revision")
            for row in checkpoints
            if row.stage == "C2" and isinstance(row.payload, dict)
        ]
        marks = (
            await self.database.scalars(
                _effective_statement(
                    or_(
                        ConversationSensitiveSegmentMark.recording_id.in_(ids),
                        ConversationSensitiveSegmentMark.transcript_revision.in_(revisions),
                    )
                )
            )
        ).all()
        result = {}
        for recording in recordings:
            bound = []
            for checkpoint in checkpoints:
                if (
                    checkpoint.recording_id != recording.id
                    or checkpoint.tenant_id != recording.tenant_id
                    or checkpoint.person_id != recording.person_id
                ):
                    continue
                try:
                    verified_checkpoint(checkpoint, binding_for(recording))
                    bound.append(checkpoint)
                except ConversationError:
                    continue
            recovery = next(
                (
                    row
                    for row in recovered
                    if row.recording_id == recording.id
                    and row.tenant_id == recording.tenant_id
                    and row.person_id == recording.person_id
                    and row.generation == recording.generation
                    and row.source_revision == recording.source_revision
                    and row.source_sha256 == recording.source_sha256
                ),
                None,
            )
            checkpoint_source = next(
                (
                    row
                    for row in checkpoints
                    if row.recording_id == recording.id and row.stage == "C5"
                ),
                None,
            )
            source = recovery or checkpoint_source
            if source is None or not isinstance(source.payload, dict):
                continue
            if recovery is None and source not in bound:
                continue
            if recovery is not None and content_hash(source.payload) != recovery.report_sha256:
                continue
            try:
                report = ReportDraft.model_validate(source.payload)
            except ValueError:
                continue
            transcript = next(
                (
                    row.payload
                    for row in bound
                    if row.stage == "C2"
                    and row.payload is not None
                    and row.payload.get("revision") == report.transcript_revision
                ),
                None,
            )
            if transcript is None or report.source_sha256 != recording.source_sha256:
                continue
            segments = {
                s["id"]: s
                for s in transcript.get("segments", [])
                if isinstance(s, dict) and isinstance(s.get("id"), str)
            }
            overview = report.overview
            notes = (
                []
                if overview is None
                else [item.model_dump(mode="json") for item in overview.prospect_interpretations]
            )
            if any(not _supported(item["source"]["evidence"], segments) for item in notes):
                continue
            # Match the report reader's cross-revision/cross-upload withholding.
            texts = {
                row.payload["revision"]: {
                    s["id"]: s.get("text", "")
                    for s in row.payload.get("segments", [])
                    if isinstance(s, dict) and isinstance(s.get("id"), str)
                }
                for row in checkpoints
                if row.recording_id == recording.id
                and row.tenant_id == recording.tenant_id
                and row.person_id == recording.person_id
                and row.stage == "C2"
                and row.payload is not None
                and isinstance(row.payload.get("revision"), str)
            }
            effective = [
                m
                for m in marks
                if m.recording_id == recording.id
                or m.transcript_revision == report.transcript_revision
            ]
            plan = withheld_plan(
                [(key, s.get("text", "")) for key, s in segments.items()],
                {
                    m.segment_id
                    for m in effective
                    if m.transcript_revision == report.transcript_revision
                },
                {
                    g
                    for m in effective
                    for g in grams(texts.get(m.transcript_revision, {}).get(m.segment_id, ""))
                },
            )
            projected: dict[str, Any] = {
                "snapshot_id": str(source.id),
                "snapshot_kind": "retained_c5" if recovery is not None else "c5_checkpoint",
                "source_revision": recording.source_revision,
                "source_sha256": recording.source_sha256,
                "run_id": str(recovery.run_id) if recovery is not None else None,
                "transcript_revision": report.transcript_revision,
                "review_status": report.review_status,
                "interpretations": notes,
            }
            if include_facts:
                facts = []
                if report.call_map is not None:
                    roles = {s.speaker_id: s.role for s in report.call_map.speakers}
                    for fact in report.call_map.prospect_facts:
                        refs = []
                        for ref in fact.evidence:
                            segment = segments.get(ref.segment_id)
                            if (
                                segment is not None
                                and roles.get(str(segment.get("speaker_id"))) == "prospect"
                                and ref.quote
                                and ref.quote in segment.get("text", "")
                                and fact.text.strip().casefold() in ref.quote.casefold()
                            ):
                                refs.append(
                                    {
                                        "segment_id": ref.segment_id,
                                        "quote": ref.quote,
                                        "start_ms": segment["start_ms"],
                                        "end_ms": segment["end_ms"],
                                    }
                                )
                        if refs:
                            facts.append({"key": fact.key, "text": fact.text, "evidence": refs})
                projected["facts"] = facts
            result[recording.id] = withhold(projected, plan)
        return result


def _supported(evidence: list[dict[str, Any]], segments: dict[str, Any]) -> bool:
    return all(
        (segment := segments.get(ref["segment_id"])) is not None
        and isinstance(segment.get("text"), str)
        and ref["quote"] in segment["text"]
        and ref["start_ms"] == segment.get("start_ms")
        and ref["end_ms"] == segment.get("end_ms")
        for ref in evidence
    )
