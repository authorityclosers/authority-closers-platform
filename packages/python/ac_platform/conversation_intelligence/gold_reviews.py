"""Exact-version reviewer workspace and gold saves; never publishes a rep score."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select, update

from ac_platform.identity.models import Person
from ac_platform.identity.services import normalize_email
from ac_platform.kernel.authz import ActorContext

from . import brain4
from .application import (
    ConversationConflict,
    ConversationDenied,
    ConversationError,
    ConversationNotFound,
)
from .checkpoints import content_hash
from .gold_review_contracts import (
    DIMENSION_PREFIX,
    MAX_MOMENTS,
    MOMENT_PREFIX,
    GoldSave,
    target_kind,
)
from .gold_review_models import GoldAssignment, GoldReviewer, GoldRow
from .models import ConversationReviewRevocation
from .pointer_review_models import ConversationPointerReview
from .review_service import ConversationReviewService
from .sensitive_segments import withhold
from .sensitive_segments_store import withheld_plan_for

# Blind Brain 4.0 mode (orchestrator, 21 Oct 2026): the reviewer rates the 18 dimensions
# before Brain 4.0's ratings are shown (AC-SVAL-01 section 8.1), then marks which of his
# correction moments Brain 4.0's coaching caught.
BLIND = "brain4_blind"
DIMENSION_TARGETS = tuple(f"{DIMENSION_PREFIX}{d}" for d in brain4.DIMENSION_IDS)
MOMENT_TARGETS = frozenset(f"{MOMENT_PREFIX}{n:02d}" for n in range(1, MAX_MOMENTS + 1))
LINES = 29


def line_count(mode: str) -> int:
    """How many saves finish a call in this mode (moments are optional)."""
    return len(DIMENSION_TARGETS) if mode == BLIND else LINES


def current_heads(rows: Any) -> dict[str, GoldRow]:
    """The newest save per target of one assignment (a re-save supersedes the one before)."""
    superseded = {row.supersedes_id for row in rows if row.supersedes_id}
    return {row.target: row for row in rows if row.id not in superseded}


def blind_rated(heads: dict[str, Any]) -> int:
    return sum(1 for target in heads if target in DIMENSION_TARGETS)


def blind_payload(intent: GoldSave, *, revealed: bool, head: GoldRow | None) -> dict[str, Any]:
    """A dimension rating (always blind: it locks once Brain 4.0's are shown) or a moment,
    blind when written before the reveal and unchanged since."""
    payload: dict[str, Any] = {"mode": BLIND}
    if intent.seconds is not None:
        payload["seconds"] = intent.seconds
    if intent.opinion:
        payload["opinion"] = intent.opinion
    if target_kind(intent.target) == "dimension":
        payload["blind"] = True
        if intent.rating is not None:
            payload["rating"] = intent.rating
        else:
            payload["skip"] = intent.skip
        return payload
    moment = intent.moment
    if moment is None:  # the contract requires it; kept for the type checker
        raise ConversationError("A moment needs its time and kind.")
    content = {"at_ms": moment.at_ms, "kind": moment.kind, "dimension": moment.dimension}
    before = head.payload if head is not None and isinstance(head.payload, dict) else {}
    earlier = before.get("moment")
    same = (
        isinstance(earlier, dict)
        and {key: earlier.get(key) for key in content} == content
        and (before.get("opinion") or "") == intent.opinion
    )
    payload["blind"] = not revealed or bool(same and before.get("blind") is True)
    payload["moment"] = {**content, "caught": moment.caught, "removed": moment.removed}
    return payload


async def brain4_read(database: Any, review: ConversationPointerReview) -> dict[str, Any] | None:
    """Brain 4.0's read of the reviewed call: the review's own block, else the shadow read
    of exactly the same run, source and transcript revision."""
    block = (review.payload or {}).get("brain4")
    if isinstance(block, dict):
        return block
    from .brain4_shadow import latest

    return await latest(
        database,
        {
            "recording_id": review.recording_id,
            "run_id": review.run_id,
            "source_sha256": review.source_sha256,
            "transcript_revision": review.transcript_revision,
        },
    )


def reveal(read: dict[str, Any] | None) -> dict[str, Any]:
    """What the reviewer sees after rating blind: Brain 4.0's rating, what it saw, its
    coaching and the lines it cites, per dimension. Beta, never official."""
    if read is None:
        return {"status": "not_read_yet", "dimensions": []}
    keys = (
        "id",
        "rating",
        "applicability",
        "confidence",
        "observed",
        "coaching",
        "evidence",
        "ethics_gate",
    )
    return {
        "status": "read",
        "label": brain4.STATUS,
        "version": read.get("version"),
        "call_type": read.get("call_type"),
        "dimensions": [
            {key: item.get(key) for key in keys}
            for item in read.get("dimensions") or []
            if isinstance(item, dict) and item.get("id") in brain4.LABELS
        ],
    }


def ai_lines(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """29 reviewable lines, with coaching tied back to each numbered pointer."""
    pointers = payload.get("pointers")
    if not isinstance(pointers, list) or len(pointers) != 27:
        raise ConversationConflict("This AI review does not have all 27 pointers.")
    if any(
        not isinstance(p, dict)
        or not isinstance(p.get("id"), str)
        or not 1 <= len(p["id"]) <= 96
        or p.get("number") != number
        or not isinstance(p.get("label"), str)
        for number, p in enumerate(pointers, 1)
    ):
        raise ConversationConflict("This saved AI review needs repair before you can judge it.")
    rows = [
        {"target": str(p["id"]), "label": f"{p['number']}. {p['label']}", "ai": p} for p in pointers
    ]
    if len({row["target"] for row in rows}) != 27:
        raise ConversationConflict("This AI review has repeated pointers.")
    rows += [
        {
            "target": "final_call_outcome",
            "label": "Final Call Outcome",
            "ai": payload.get("outcome"),
        },
        {
            "target": "coaching",
            "label": "Coaching",
            "ai": [
                {
                    "pointer": p["label"],
                    "tips": p.get("how_to_improve", []),
                    "topic": p.get("training_topic"),
                }
                for p in pointers
                if p.get("how_to_improve") or p.get("training_topic")
            ],
        },
    ]
    return rows


def gold_payload(intent: GoldSave, ai_payload: dict[str, Any]) -> dict[str, Any]:
    """The judgement plus the AI status/score it judged (never quotes), for the metrics."""
    payload: dict[str, Any] = {
        "verdict": intent.verdict,
        "score": intent.score,
        "opinion": intent.opinion,
    }
    if intent.status is not None:
        payload["status"] = intent.status
    if intent.reasons:
        payload["reasons"] = list(intent.reasons)
    if intent.skip is not None:
        payload["skip"] = intent.skip
    if intent.seconds is not None:
        payload["seconds"] = intent.seconds
    pointers = ai_payload.get("pointers")
    ai = next(
        (
            p
            for p in (pointers if isinstance(pointers, list) else [])
            if isinstance(p, dict) and p.get("id") == intent.target
        ),
        None,
    )
    if ai is not None:
        payload["ai"] = {
            "status": ai["status"] if isinstance(ai.get("status"), str) else None,
            "score": ai["score"] if type(ai.get("score")) is int else None,
        }
    return payload


def call_context(evidence: Any) -> dict[str, Any]:
    """What the reviewer needs to place the call: when, how long, and the AI's summary."""
    draft = evidence.draft.payload if isinstance(evidence.draft.payload, dict) else {}
    segments = evidence.transcript.get("segments") or []
    ends = [s.get("end_ms") for s in segments if isinstance(s, dict)]
    summary = draft.get("summary")
    return {
        "recorded_at": evidence.recording.created_at.isoformat(),
        "duration_ms": max((e for e in ends if type(e) is int), default=None),
        "summary": summary[:600] if isinstance(summary, str) else None,
        "verdict": draft.get("verdict") if isinstance(draft.get("verdict"), str) else None,
    }


def row_view(row: GoldRow) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "assignment_id": str(row.assignment_id),
        "call": {"recording_id": str(row.recording_id)},
        "review_id": str(row.review_id),
        "reviewer_id": str(row.reviewer_id),
        "target": row.target,
        "ai_sha256": row.ai_sha256,
        "value": row.payload,
        "supersedes_id": str(row.supersedes_id) if row.supersedes_id else None,
        "created_at": row.created_at.isoformat(),
        "erased": row.erased_at is not None,
    }


async def erase_gold_reviews_for_recording(database: Any, recording_id: UUID, now: datetime) -> int:
    """Called in the canonical call-erasure transaction, including every superseded save."""
    result = await database.execute(
        update(GoldRow)
        .where(GoldRow.recording_id == recording_id, GoldRow.erased_at.is_(None))
        .values(payload=None, erased_at=now)
    )
    return int(result.rowcount or 0)


async def gold_assignment_state(database: Any, assignment_id: UUID) -> str | None:
    link = await database.get(GoldAssignment, assignment_id)
    if link is None:
        return None
    q = select(func.count(func.distinct(GoldRow.target))).where(
        GoldRow.assignment_id == assignment_id, GoldRow.erased_at.is_(None)
    )
    if link.mode == BLIND:
        q = q.where(GoldRow.target.in_(DIMENSION_TARGETS))
    count = int(await database.scalar(q) or 0)
    if count >= line_count(link.mode):
        return "submitted"
    return "in_progress" if count else "assigned"


class GoldReviews:
    def __init__(self, reviews: ConversationReviewService):
        self.reviews = reviews
        self.database = reviews.database

    async def reviewers(self, actor: ActorContext) -> dict[str, Any]:
        await self.reviews._admin(actor)
        rows = (
            await self.database.execute(
                select(GoldReviewer, Person)
                .join(Person, Person.id == GoldReviewer.person_id)
                .order_by(GoldReviewer.created_at.desc())
            )
        ).all()
        return {
            "items": [
                {
                    "person_id": str(r.person_id),
                    "email": p.email,
                    "active": r.revoked_at is None,
                    "verified": p.email_verified_at is not None,
                }
                for r, p in rows
            ]
        }

    async def designate(self, actor: ActorContext, email: str, active: bool) -> dict[str, Any]:
        now = await self.reviews._admin(actor)
        person = await self.database.scalar(
            select(Person)
            .where(func.lower(Person.email) == normalize_email(email).casefold())
            .with_for_update()
        )
        if person is None:
            raise ConversationNotFound(
                "This person has no AC identity. Invite them through reviewer access first."
            )
        if person.status != "active":
            raise ConversationDenied("This reviewer identity is unavailable.")
        row = await self.database.get(GoldReviewer, person.id, with_for_update=True)
        before = row is not None and row.revoked_at is None
        if row is None and active:
            row = GoldReviewer(person_id=person.id, designated_by=actor.person_id, created_at=now)
            self.database.add(row)
        elif row is not None:
            row.revoked_at = None if active else now
            if active:
                row.designated_by = actor.person_id
        if not active:
            ids = (
                await self.database.scalars(
                    select(GoldAssignment.assignment_id).where(
                        GoldAssignment.reviewer_id == person.id
                    )
                )
            ).all()
            for identifier in ids:
                if await self.database.get(ConversationReviewRevocation, identifier) is None:
                    self.database.add(
                        ConversationReviewRevocation(
                            assignment_id=identifier, person_id=actor.person_id, created_at=now
                        )
                    )
        if before != active:
            await self.reviews._review_audit(
                actor,
                tenant_id=self.reviews.operations_tenant_id,
                action="gold_reviewer_designated" if active else "gold_reviewer_removed",
                resource_type="conversation_gold_reviewer",
                resource_id=person.id,
                intent={"person_id": str(person.id), "active": active},
                now=now,
            )
        await self.database.flush()
        return {
            "person_id": str(person.id),
            "email": person.email,
            "before": before,
            "active": active,
        }

    async def _admit(
        self, actor: ActorContext, assignment_id: UUID
    ) -> tuple[Any, Any, Any, datetime]:
        row, _, evidence, now = await self.reviews._admit(actor, assignment_id)
        link = await self.database.scalar(
            select(GoldAssignment)
            .where(
                GoldAssignment.assignment_id == row.id,
                GoldAssignment.reviewer_id == actor.person_id,
                GoldAssignment.recording_id == evidence.recording.id,
            )
            .with_for_update()
        )
        designation = await self.database.get(GoldReviewer, actor.person_id, with_for_update=True)
        if link is None:
            raise ConversationNotFound("This assignment uses the existing feedback form.")
        if designation is None or designation.revoked_at is not None:
            raise ConversationDenied("Your gold reviewer access has ended.")
        return row, link, evidence, now

    async def _review(
        self, evidence: Any, review_id: UUID | None = None
    ) -> ConversationPointerReview:
        q = select(ConversationPointerReview).where(
            ConversationPointerReview.tenant_id == evidence.recording.tenant_id,
            ConversationPointerReview.recording_id == evidence.recording.id,
            ConversationPointerReview.run_id == evidence.run.id,
            ConversationPointerReview.report_draft_id == evidence.draft.id,
            ConversationPointerReview.source_sha256 == evidence.recording.source_sha256,
            ConversationPointerReview.transcript_revision == evidence.transcript["revision"],
            ConversationPointerReview.version == "pointer-review/1",
            ConversationPointerReview.erased_at.is_(None),
        )
        if review_id is not None:
            q = q.where(ConversationPointerReview.id == review_id)
        row = await self.database.scalar(
            q.order_by(
                ConversationPointerReview.created_at.desc(), ConversationPointerReview.id.desc()
            )
            .limit(1)
            .with_for_update(read=True)
        )
        if row is None or row.payload is None or content_hash(row.payload) != row.payload_sha256:
            raise ConversationConflict(
                "This saved AI review is unavailable. Reload the assignment."
            )
        return row

    async def get(self, actor: ActorContext, assignment_id: UUID) -> dict[str, Any]:
        _, link, evidence, _ = await self._admit(actor, assignment_id)
        review = await self._review(evidence)
        plan = await withheld_plan_for(
            self.database,
            recording_id=evidence.recording.id,
            served_revisions=(review.transcript_revision,),
        )
        history = (
            await self.database.scalars(
                select(GoldRow)
                .where(GoldRow.assignment_id == assignment_id, GoldRow.erased_at.is_(None))
                .order_by(GoldRow.created_at, GoldRow.id)
            )
        ).all()
        superseded = {r.supersedes_id for r in history if r.supersedes_id}
        if link.mode == BLIND:
            return withhold(await self._blind_view(review, evidence, history, assignment_id), plan)
        return withhold(
            {
                "review_id": str(review.id),
                "version": review.version,
                "review_status": "ai_draft_not_dipak_reviewed",
                "ai_sha256": review.payload_sha256,
                "call": {
                    "recording_id": str(review.recording_id),
                    "run_id": str(review.run_id),
                    "source_sha256": review.source_sha256,
                    "transcript_revision": review.transcript_revision,
                },
                "lines": ai_lines(review.payload or {}),
                "saved": [row_view(r) for r in history if r.id not in superseded],
                "history_count": len(history),
                "audio_source_url": f"/v1/reviewer/review-assignments/{assignment_id}/source",
                "transcript": evidence.transcript,
                "context": call_context(evidence),
            },
            plan,
        )

    async def _blind_view(
        self, review: ConversationPointerReview, evidence: Any, history: Any, assignment_id: UUID
    ) -> dict[str, Any]:
        """The blind workspace: the call, the rubric's words and his own saves. Brain 4.0's
        ratings, and the AI's summary and verdict, appear only after all 18 are rated."""
        heads = current_heads(history)
        revealed = blind_rated(heads) >= len(DIMENSION_TARGETS)
        superseded = {r.supersedes_id for r in history if r.supersedes_id}
        return {
            "mode": BLIND,
            "review_id": str(review.id),
            "version": review.version,
            "review_status": "blind_brain4_rating",
            "call": {
                "recording_id": str(review.recording_id),
                "run_id": str(review.run_id),
                "source_sha256": review.source_sha256,
                "transcript_revision": review.transcript_revision,
            },
            "lines": [],
            "dimensions": list(brain4.guide()),
            "saved": [row_view(r) for r in history if r.id not in superseded],
            "history_count": len(history),
            "audio_source_url": f"/v1/reviewer/review-assignments/{assignment_id}/source",
            "transcript": evidence.transcript,
            "context": {**call_context(evidence), "summary": None, "verdict": None},
            "revealed": revealed,
            "brain4": reveal(await brain4_read(self.database, review)) if revealed else None,
        }

    async def save(
        self, actor: ActorContext, assignment_id: UUID, intent: GoldSave, key: str
    ) -> dict[str, Any]:
        if not key or len(key) > 128:
            raise ConversationError("A save key is required.")
        _, link, evidence, now = await self._admit(actor, assignment_id)
        review = await self._review(evidence, intent.review_id)
        fingerprint = content_hash(intent.model_dump(mode="json"))
        previous_request = await self.database.scalar(
            select(GoldRow).where(
                GoldRow.assignment_id == assignment_id, GoldRow.request_key == key
            )
        )
        if previous_request is not None:
            if previous_request.request_sha256 != fingerprint:
                raise ConversationConflict("This save key belongs to different feedback.")
            return row_view(previous_request)
        kind = target_kind(intent.target)
        if link.mode == BLIND:
            if intent.target not in (*DIMENSION_TARGETS, *MOMENT_TARGETS):
                raise ConversationError(
                    "This call is rated blind: choose a Brain 4.0 dimension or a moment."
                )
        else:
            targets = {line["target"] for line in ai_lines(review.payload or {})}
            if kind != "line" or intent.target not in targets:
                raise ConversationError("Choose a line from this saved report.")
        # Locking the canonical gold assignment serializes concurrent saves. The
        # predecessor check prevents a second browser tab overwriting unseen work.
        rows = (
            await self.database.scalars(
                select(GoldRow).where(
                    GoldRow.assignment_id == assignment_id, GoldRow.target == intent.target
                )
            )
        ).all()
        superseded = {r.supersedes_id for r in rows if r.supersedes_id}
        head = next((r for r in rows if r.id not in superseded), None)
        if intent.supersedes_id != (head.id if head else None):
            raise ConversationConflict("This line was saved elsewhere. Reload before saving again.")
        if link.mode == BLIND:
            everything = (
                await self.database.scalars(
                    select(GoldRow).where(
                        GoldRow.assignment_id == assignment_id, GoldRow.erased_at.is_(None)
                    )
                )
            ).all()
            revealed = blind_rated(current_heads(everything)) >= len(DIMENSION_TARGETS)
            if kind == "dimension" and revealed:
                raise ConversationConflict(
                    "Your blind ratings are locked once Brain 4.0's ratings are shown."
                )
            if kind == "moment" and not revealed and intent.moment and intent.moment.caught:
                raise ConversationError("Mark what Brain 4.0 caught after its read is shown.")
            payload = blind_payload(intent, revealed=revealed, head=head)
        else:
            payload = gold_payload(intent, review.payload or {})
        row = GoldRow(
            id=uuid4(),
            assignment_id=assignment_id,
            recording_id=review.recording_id,
            review_id=review.id,
            reviewer_id=actor.person_id,
            target=intent.target,
            ai_sha256=review.payload_sha256,
            payload=payload,
            supersedes_id=intent.supersedes_id,
            request_key=key,
            request_sha256=fingerprint,
            created_at=now,
        )
        self.database.add(row)
        await self.database.flush()
        await self.reviews._review_audit(
            actor,
            tenant_id=evidence.recording.tenant_id,
            action="gold_line_saved",
            resource_type="conversation_gold_row",
            resource_id=row.id,
            intent={
                "review_id": str(review.id),
                "target": intent.target,
                "request_sha256": fingerprint,
            },
            now=now,
        )
        return row_view(row)

    async def evaluation(self, actor: ActorContext) -> dict[str, Any]:
        """Brain 4.0 and today's pointer review against the gold set (brain4_eval).

        Counts, labels and scores only: never a reviewer's note or the call's words.
        """
        now = await self.reviews._admin(actor)
        from .brain4_eval import evaluate, load
        from .gold_review_job import checkpoint_progress

        result = evaluate(await load(self.database), now=now)
        # How far the gold checkpoint's chosen sample is (counts only).
        result["sample"] = await checkpoint_progress(
            self.database, self.reviews.operations_tenant_id
        )
        return result

    async def rows(self, actor: ActorContext) -> dict[str, Any]:
        now = await self.reviews._admin(actor)
        rows = (
            await self.database.scalars(
                select(GoldRow).order_by(GoldRow.created_at.desc(), GoldRow.id.desc()).limit(200)
            )
        ).all()
        # The dataset view applies the current privacy marks even to old opinions.
        result = []
        sources: dict[UUID, Any] = {}
        reviewers: dict[UUID, Any] = {}
        for row in rows:
            if row.review_id not in sources:
                review = await self.database.get(ConversationPointerReview, row.review_id)
                try:
                    if review is None or review.erased_at is not None:
                        raise ConversationNotFound("The call was erased.")
                    evidence = await self.reviews._evidence(
                        review.run_id, now, report_id=review.report_draft_id
                    )
                    bound = await self._review(evidence, review.id)
                    plan = await withheld_plan_for(
                        self.database,
                        recording_id=row.recording_id,
                        served_revisions=(bound.transcript_revision,),
                    )
                    sources[row.review_id] = (
                        {line["target"]: line["ai"] for line in ai_lines(bound.payload or {})},
                        plan,
                        bound.payload_sha256,
                    )
                except (ConversationDenied, ConversationNotFound, ConversationConflict):
                    sources[row.review_id] = None
            source = sources[row.review_id]
            view = row_view(row)
            if source is None:
                view["value"] = None
                view["ai_value"] = None
            else:
                ai, plan, digest = source
                view["ai_value"] = ai.get(row.target) if digest == row.ai_sha256 else None
                view = withhold(view, plan)
            if row.reviewer_id not in reviewers:
                person = await self.database.get(Person, row.reviewer_id)
                reviewers[row.reviewer_id] = person.email if person else None
            view["reviewer_email"] = reviewers[row.reviewer_id]
            result.append(view)
        return {"items": result}
