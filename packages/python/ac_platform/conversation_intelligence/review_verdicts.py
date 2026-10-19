"""Review 2.0: reviewers judge the analysis, never the report (admin revamp, 19 Oct 2026).

Design: docs/design/review-2-20261019.md. A pipeline is a versioned list of
primitives (sample, show, ask, reconcile, measure); this module stores answers
("verdicts") about analysis targets and serves pipelines and a call's verdicts.

- Reviewers are the standing gold reviewers (``conversation_gold_reviewers``, the
  only designation); revoking one ends their access here too. Admin requests come
  from the operations workspace.
- The AI digest is computed here from the call object judged, by the call data
  engine's recipe (type and value only: wording, confidence, basis and evidence
  never void a verdict), so a verdict stays bound to the claim it judged.
- Answers never write to call objects, their decisions or Lead Desk fields.
- Append-only: a changed answer supersedes the old row; call erasure empties answers.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import exists, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from ac_platform.audit.service import AuditRepository
from ac_platform.conversation_intelligence.application import (
    ConversationConflict,
    ConversationDenied,
    ConversationError,
    ConversationNotFound,
)
from ac_platform.conversation_intelligence.coaching_points import coaching_points
from ac_platform.conversation_intelligence.gold_review_models import GoldReviewer
from ac_platform.conversation_intelligence.models import (
    ConversationRecording,
    ConversationReportDraft,
)
from ac_platform.conversation_intelligence.review_models import ReviewPipeline, ReviewVerdict
from ac_platform.conversation_intelligence.synthetic_import_models import (
    ConversationSandboxOrganisation,
)
from ac_platform.kernel.authz import ActorContext
from ac_platform.organisations.workspace_kinds import classify_workspaces

SAVED_ACTION = "review.verdict_saved"
PIPELINE_SCHEMA = "ac.review-pipeline/1"
TARGET_KINDS = ("object", "fact", "segment", "voice", "coaching")
QUESTION_KINDS = ("verdict", "pick", "correct", "scale")
# Objects, facts and coaching points now. Segments need the engine's span-aware
# digest and their object ids in its reads (after v0.66); voice follows.
SUPPORTED_TARGETS = ("object", "fact", "coaching")
MAX_TEXT = 2000

# The pipelines Review 2.0 starts with. A saved version with the same key replaces
# its default; the newest saved version of a key is the active one.
DEFAULT_PIPELINES: dict[str, dict[str, Any]] = {
    "analysis-sales": {
        "kind": "analysis",
        "title": "Analysis: sales",
        "definition": {
            "schema": PIPELINE_SCHEMA,
            "targets": ["object", "fact"],
            "sample": {"order": "newest", "limit": 20},
            "show": ["evidence", "transcript_window"],
            "questions": [
                {
                    "key": "correct",
                    "kind": "verdict",
                    "label": "Is this right?",
                    "options": ["correct", "wrong", "unsure"],
                },
                {
                    "key": "fix",
                    "kind": "correct",
                    "label": "What should it say?",
                    "when": {"correct": "wrong"},
                },
            ],
            "reconcile": {"reviewers": 2},
            "measure": ["agreement_by_type", "agreement_by_pipeline_version"],
        },
    },
    # Coaching is reviewed apart from the analysis, in coaching terms (owner, 19 Oct).
    "coaching": {
        "kind": "coaching",
        "title": "Coaching",
        "definition": {
            "schema": PIPELINE_SCHEMA,
            "targets": ["coaching"],
            "sample": {"order": "newest", "limit": 20},
            "show": ["coaching_point", "evidence"],
            "questions": [
                {
                    "key": "true",
                    "kind": "verdict",
                    "label": "True for this call?",
                    "options": ["true", "false", "unsure"],
                },
                {"key": "useful", "kind": "scale", "label": "How useful for this rep?"},
                {
                    "key": "fix",
                    "kind": "correct",
                    "label": "What should the coaching say?",
                    "when": {"true": "false"},
                },
            ],
            "reconcile": {"reviewers": 2},
            "measure": ["agreement_by_point_kind", "usefulness"],
        },
    },
}


def utc_now() -> datetime:
    return datetime.now(UTC)


def value_digest(type_key: str, value: Any) -> str:
    """The claim a verdict judges, by the call data engine's recipe: type and value.

    Display is made from value, so a wording change never voids a verdict that is
    still right; nor do confidence, basis or evidence. Stored when the verdict is
    written: after erasure the value is gone and cannot be hashed again.
    """
    body = json.dumps(
        {"type": type_key, "value": value},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def validate_answer(question: dict[str, Any], answer: Any) -> dict[str, Any]:
    """One answer, shaped by its question's kind; never trusts the client's shape."""
    if not isinstance(answer, dict):
        raise ConversationError("An answer must be an object.")
    kind = question.get("kind")
    options = [str(option) for option in question.get("options", [])]
    if kind in ("verdict", "pick"):
        value = answer.get("value")
        if not isinstance(value, str) or value not in options:
            raise ConversationError(f"Choose one of: {', '.join(options)}.")
        return {"value": value}
    if kind == "scale":
        value = answer.get("value")
        if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 5:
            raise ConversationError("Choose a number from 1 to 5.")
        return {"value": value}
    if kind == "correct":
        text = answer.get("text")
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
            raise ConversationError(f"Write the correction (1 to {MAX_TEXT} characters).")
        return {"text": text.strip()}
    raise ConversationError("This question cannot be answered yet.")


def verdict_view(row: ReviewVerdict, reviewer_id: UUID) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "pipeline": {"key": row.pipeline_key, "version": row.pipeline_version},
        "target": {"kind": row.target_kind, "ref": row.target_ref},
        "question": row.question_key,
        "answer": row.answer,
        "ai_sha256": row.ai_sha256,
        "mine": row.reviewer_id == reviewer_id,
        "reviewer_id": str(row.reviewer_id),
        "supersedes_id": str(row.supersedes_id) if row.supersedes_id else None,
        "created_at": row.created_at.isoformat(),
        "erased": row.erased_at is not None,
    }


async def erase_review_verdicts_for_recording(
    database: Any, recording_id: UUID, now: datetime
) -> int:
    """Called in the canonical call-erasure transaction, every superseded answer included."""
    result = await database.execute(
        update(ReviewVerdict)
        .where(ReviewVerdict.recording_id == recording_id, ReviewVerdict.erased_at.is_(None))
        .values(answer=None, erased_at=now)
    )
    return int(result.rowcount or 0)


class ReviewVerdicts:
    def __init__(
        self,
        database: AsyncSession,
        operations_tenant_id: UUID,
        personal_tenant_id: UUID | None = None,
    ) -> None:
        self.database = database
        self.operations_tenant_id = operations_tenant_id
        self.personal_tenant_id = personal_tenant_id

    async def admit(self, actor: ActorContext) -> None:
        """A standing gold reviewer, working in the operations workspace."""
        if actor.tenant_id != self.operations_tenant_id:
            raise ConversationDenied("Review needs the AC operations workspace.")
        reviewer = await self.database.get(GoldReviewer, actor.person_id)
        if reviewer is None or reviewer.revoked_at is not None:
            raise ConversationDenied("Only designated gold reviewers can review the analysis.")

    async def pipelines(self) -> dict[str, dict[str, Any]]:
        """Each pipeline key's active version: the newest saved one, else its default."""
        active: dict[str, dict[str, Any]] = {
            key: {"key": key, "version": 1, "saved": False, **pipeline}
            for key, pipeline in DEFAULT_PIPELINES.items()
        }
        rows = (
            await self.database.scalars(
                select(ReviewPipeline).order_by(ReviewPipeline.key, ReviewPipeline.version)
            )
        ).all()
        for row in rows:
            active[row.key] = {
                "key": row.key,
                "version": row.version,
                "saved": True,
                "kind": row.kind,
                "title": row.title,
                "definition": row.definition,
            }
        return active

    async def list_pipelines(self, actor: ActorContext) -> dict[str, Any]:
        await self.admit(actor)
        return {"pipelines": list((await self.pipelines()).values())}

    async def _recording(self, recording_id: UUID) -> ConversationRecording:
        recording = await self.database.get(ConversationRecording, recording_id)
        if recording is None or recording.deleted_at is not None:
            raise ConversationNotFound("Call not found.")
        return recording

    async def _current(self, recording_id: UUID) -> list[ReviewVerdict]:
        rows = (
            await self.database.scalars(
                select(ReviewVerdict)
                .where(ReviewVerdict.recording_id == recording_id)
                .order_by(ReviewVerdict.created_at, ReviewVerdict.id)
            )
        ).all()
        replaced = {row.supersedes_id for row in rows if row.supersedes_id is not None}
        return [row for row in rows if row.id not in replaced]

    async def call(self, actor: ActorContext, recording_id: UUID) -> dict[str, Any]:
        """The active pipelines and every reviewer's current answers for one call."""
        await self.admit(actor)
        await self._recording(recording_id)
        return {
            "pipelines": list((await self.pipelines()).values()),
            "verdicts": [
                verdict_view(row, actor.person_id) for row in await self._current(recording_id)
            ],
        }

    async def queue(
        self,
        actor: ActorContext,
        *,
        pipeline_key: str = "analysis-sales",
        limit: int | None = None,
        include_sandbox: bool = False,
        include_done: bool = False,
    ) -> dict[str, Any]:
        """The pipeline's sample: calls with current analysis items, newest first.

        Each call says how many items it has, how many this reviewer answered and how
        many other reviewers answered. Calls this reviewer finished drop out unless
        asked for; the fictional sandbox stays out unless asked for.
        """
        from ac_platform.call_data.models import CallObject

        await self.admit(actor)
        pipeline = (await self.pipelines()).get(pipeline_key)
        if pipeline is None:
            raise ConversationNotFound("No such review pipeline.")
        sample = pipeline["definition"].get("sample", {})
        size = max(1, min(int(limit or sample.get("limit") or 20), 100))
        successor = aliased(CallObject)
        current = (
            select(
                CallObject.recording_id,
                func.count().label("items"),
                func.max(CallObject.created_at).label("analysed_at"),
            )
            .join(ConversationRecording, ConversationRecording.id == CallObject.recording_id)
            .where(
                CallObject.type_key != "conversation.segment",
                CallObject.retracted.is_(False),
                CallObject.erased_at.is_(None),
                ~exists().where(successor.supersedes_id == CallObject.id),
                ConversationRecording.deleted_at.is_(None),
            )
            .group_by(CallObject.recording_id)
        )
        if not include_sandbox:
            current = current.where(
                ~ConversationRecording.tenant_id.in_(
                    select(ConversationSandboxOrganisation.tenant_id)
                )
            )
        rows = (
            await self.database.execute(
                current.order_by(func.max(CallObject.created_at).desc()).limit(size * 4)
            )
        ).all()
        ids = [row.recording_id for row in rows]
        answered: dict[UUID, int] = {}
        others: dict[UUID, int] = {}
        if ids:
            mine_rows = await self.database.execute(
                select(
                    ReviewVerdict.recording_id, func.count(func.distinct(ReviewVerdict.target_ref))
                )
                .where(
                    ReviewVerdict.recording_id.in_(ids),
                    ReviewVerdict.reviewer_id == actor.person_id,
                    ReviewVerdict.pipeline_key == pipeline_key,
                    ReviewVerdict.erased_at.is_(None),
                )
                .group_by(ReviewVerdict.recording_id)
            )
            answered = {recording: int(count) for recording, count in mine_rows.all()}
            other_rows = await self.database.execute(
                select(
                    ReviewVerdict.recording_id, func.count(func.distinct(ReviewVerdict.reviewer_id))
                )
                .where(
                    ReviewVerdict.recording_id.in_(ids),
                    ReviewVerdict.reviewer_id != actor.person_id,
                    ReviewVerdict.pipeline_key == pipeline_key,
                    ReviewVerdict.erased_at.is_(None),
                )
                .group_by(ReviewVerdict.recording_id)
            )
            others = {recording: int(count) for recording, count in other_rows.all()}
        recordings = {
            row.id: row
            for row in (
                await self.database.scalars(
                    select(ConversationRecording).where(ConversationRecording.id.in_(ids))
                )
            ).all()
        }
        workspaces = await classify_workspaces(
            self.database,
            operations_tenant_id=self.operations_tenant_id,
            personal_tenant_id=self.personal_tenant_id,
            tenant_ids={recording.tenant_id for recording in recordings.values()},
        )
        items = []
        for row in rows:
            done = answered.get(row.recording_id, 0)
            if done >= row.items and not include_done:
                continue
            recording = recordings[row.recording_id]
            workspace = workspaces.get(recording.tenant_id)
            items.append(
                {
                    "recording_id": str(row.recording_id),
                    "uploaded_at": recording.created_at.isoformat(),
                    "analysed_at": row.analysed_at.isoformat(),
                    "organisation": {
                        "id": str(recording.tenant_id),
                        "name": workspace.name if workspace else "Unknown organisation",
                        "kind": workspace.kind if workspace else "other",
                    },
                    "items": int(row.items),
                    "answered": done,
                    "others": others.get(row.recording_id, 0),
                }
            )
            if len(items) >= size:
                break
        return {
            "pipeline": {
                "key": pipeline_key,
                "version": pipeline["version"],
                "title": pipeline["title"],
            },
            "items": items,
        }

    async def _report_points(self, recording_id: UUID, run_id: UUID) -> list[dict[str, str]]:
        """The coaching points of one analysis run's saved report (none once erased)."""
        draft = await self.database.scalar(
            select(ConversationReportDraft)
            .where(
                ConversationReportDraft.run_id == run_id,
                ConversationReportDraft.recording_id == recording_id,
                ConversationReportDraft.erased_at.is_(None),
            )
            .order_by(ConversationReportDraft.created_at.desc())
            .limit(1)
        )
        if draft is None or draft.payload is None:
            raise ConversationNotFound("This analysis has no saved coaching.")
        return coaching_points(draft.payload)

    async def coaching(
        self, actor: ActorContext, recording_id: UUID, run_id: UUID
    ) -> dict[str, Any]:
        """One run's coaching as points to judge, apart from the report's layout."""
        await self.admit(actor)
        await self._recording(recording_id)
        points = await self._report_points(recording_id, run_id)
        return {
            "run_id": str(run_id),
            "points": [{**point, "ref": f"{run_id}:{point['key']}"} for point in points],
        }

    async def _target_digest(self, recording_id: UUID, kind: str, ref: str) -> str:
        from ac_platform.call_data.models import CallObject

        if kind not in SUPPORTED_TARGETS:
            raise ConversationError("This kind of target cannot be reviewed yet.")
        if kind == "coaching":
            run_text, _, key = ref.partition(":")
            try:
                run_id = UUID(run_text)
            except ValueError:
                raise ConversationError("Name the analysis run and coaching point.") from None
            point = next(
                (
                    item
                    for item in await self._report_points(recording_id, run_id)
                    if item["key"] == key
                ),
                None,
            )
            if point is None:
                raise ConversationNotFound("That coaching point is not in this analysis.")
            return value_digest(
                f"coaching.{point['kind']}", {"title": point["title"], "text": point["text"]}
            )
        try:
            object_id = UUID(ref)
        except ValueError:
            raise ConversationError("Name the call object being judged.") from None
        found = await self.database.get(CallObject, object_id)
        if found is None or found.recording_id != recording_id or found.erased_at is not None:
            raise ConversationNotFound("That analysis item is not part of this call.")
        is_segment = found.type_key == "conversation.segment"
        if (kind == "segment") != is_segment:
            raise ConversationError("That item is not a " + kind + ".")
        return value_digest(found.type_key, found.value)

    async def save(
        self,
        actor: ActorContext,
        recording_id: UUID,
        *,
        pipeline_key: str,
        target_kind: str,
        target_ref: str,
        question_key: str,
        answer: Any,
        request_key: str,
    ) -> dict[str, Any]:
        """One reviewer's answer to one question about one target (append-only, audited)."""
        await self.admit(actor)
        recording = await self._recording(recording_id)
        existing = await self.database.scalar(
            select(ReviewVerdict).where(
                ReviewVerdict.reviewer_id == actor.person_id,
                ReviewVerdict.request_key == request_key,
            )
        )
        if existing is not None:
            if (
                existing.recording_id != recording_id
                or existing.target_ref != target_ref
                or existing.question_key != question_key
            ):
                raise ConversationConflict("That request key was used for another answer.")
            return verdict_view(existing, actor.person_id)
        pipeline = (await self.pipelines()).get(pipeline_key)
        if pipeline is None:
            raise ConversationNotFound("No such review pipeline.")
        definition = pipeline["definition"]
        if target_kind not in definition.get("targets", []):
            raise ConversationError("This pipeline does not judge that kind of target.")
        question = next(
            (item for item in definition.get("questions", []) if item.get("key") == question_key),
            None,
        )
        if question is None:
            raise ConversationError("This pipeline has no such question.")
        clean = validate_answer(question, answer)
        digest = await self._target_digest(recording_id, target_kind, target_ref)
        previous = next(
            (
                row
                for row in reversed(await self._current(recording_id))
                if row.reviewer_id == actor.person_id
                and row.target_kind == target_kind
                and row.target_ref == target_ref
                and row.question_key == question_key
            ),
            None,
        )
        now = utc_now()
        row = ReviewVerdict(
            id=uuid4(),
            pipeline_key=pipeline_key,
            pipeline_version=int(pipeline["version"]),
            recording_id=recording_id,
            tenant_id=recording.tenant_id,
            reviewer_id=actor.person_id,
            target_kind=target_kind,
            target_ref=target_ref,
            question_key=question_key,
            ai_sha256=digest,
            answer=clean,
            supersedes_id=previous.id if previous is not None else None,
            request_key=request_key,
            created_at=now,
        )
        self.database.add(row)
        await self.database.flush()
        await AuditRepository(self.database).append_for_actor(
            actor,
            action=SAVED_ACTION,
            resource_type="review_verdict",
            resource_id=row.id,
            payload={
                "schema": "ac.review-verdict/1",
                "recording_id": str(recording_id),
                "pipeline": {"key": pipeline_key, "version": row.pipeline_version},
                "target": {"kind": target_kind, "ref": target_ref},
                "question": question_key,
                # Choices only: a written correction is call content and stays out.
                "value": clean.get("value") if "value" in clean else None,
                "supersedes_id": str(row.supersedes_id) if row.supersedes_id else None,
            },
        )
        return verdict_view(row, actor.person_id)
