"""Call review labels (AUT-1798): verdicts, notes, Dipak's gold set, data marks.

Reviewers (the Sales Xray control accounts, in the operations workspace) add
statements about a call. Each is a new, audited row; a later verdict, gold
label, data mark or review state by the same reviewer for the same thing
supersedes the earlier one. Notes accumulate. From the effective labels come
the call's review state (new, needs review, disputed, done) and an internal
view of how the AI's reports agree with the gold labels, per pillar and per
prompt version. That view is reviewer agreement for improving prompts, not an
official score (AC-SVAL), and it is never shown to reps.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import datetime
from hashlib import sha256
from typing import Annotated, Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.audit.service import AuditRepository
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationConflict,
    ConversationDenied,
    ConversationError,
    ConversationNotFound,
    utc,
)
from ac_platform.conversation_intelligence.models import (
    ConversationInferenceTask,
    ConversationPlanStageAuthorization,
    ConversationProcessingPlan,
    ConversationRecording,
    ConversationReportDraft,
    ConversationRun,
)
from ac_platform.conversation_intelligence.provider_admin import ConversationProviderAdmin
from ac_platform.conversation_intelligence.review_label_models import ConversationReviewLabel
from ac_platform.kernel.authz import ActorContext

_NAMESPACE = uuid5(NAMESPACE_URL, "https://authorityclosers.com/ns/conversation-review-label")

SKILL_IDS = (
    "human_connection_trust",
    "discovery_deep_understanding",
    "qualification",
    "problem_impact_desire",
    "solution_relevance_presentation",
    "certainty_objection_intelligence",
    "closing_decision_management",
    "communication_tonality",
)
SkillId = Literal[
    "human_connection_trust",
    "discovery_deep_understanding",
    "qualification",
    "problem_impact_desire",
    "solution_relevance_presentation",
    "certainty_objection_intelligence",
    "closing_decision_management",
    "communication_tonality",
]
SkillState = Literal[
    "strongly_demonstrated",
    "observed",
    "needs_attention",
    "insufficient_evidence",
    "not_applicable",
]
# The coaching spec's gap types (2374-2385); the root cause stays a hypothesis.
GapType = Literal[
    "knowledge",
    "recognition_judgment",
    "execution",
    "habit_recall",
    "confidence",
    "cognitive_load",
    "belief_buy_in",
    "adherence",
    "skill_dependency",
    "context_specific",
    "uncertain",
]
REVIEW_STATES = ("new", "needs_review", "disputed", "done")
Section = Annotated[
    str,
    StringConstraints(
        pattern=r"^(report|pillar|skill|coaching|transcript|speakers)(:[a-z_]{1,64})?$",
        max_length=96,
    ),
]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class VerdictValue(_Strict):
    verdict: Literal["correct", "partly", "wrong"]


class NoteValue(_Strict):
    text: Text


class GoldValue(_Strict):
    focus: SkillId | None = None
    root_cause: GapType | None = None
    root_cause_note: (
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] | None
    ) = None
    coaching: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] | None = (
        None
    )
    skill_states: dict[SkillId, SkillState] = Field(default_factory=dict)


class DataUseValue(_Strict):
    use: Literal["training", "test", "none"]


class StatusValue(_Strict):
    state: Literal["needs_review", "done"]


VALUES: dict[str, type[_Strict]] = {
    "verdict": VerdictValue,
    "note": NoteValue,
    "gold": GoldValue,
    "data_use": DataUseValue,
    "status": StatusValue,
}
SUPERSEDING_KINDS = frozenset({"verdict", "gold", "data_use", "status"})


class LabelIntent(_Strict):
    kind: Literal["verdict", "note", "gold", "data_use", "status"]
    run_id: UUID | None = None
    section: Section | None = None
    value: dict[str, Any]


def _fingerprint(intent: LabelIntent, value: dict[str, Any]) -> str:
    body = {
        "kind": intent.kind,
        "run_id": None if intent.run_id is None else str(intent.run_id),
        "section": intent.section,
        "value": value,
    }
    return sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _view(row: ConversationReviewLabel) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "kind": row.kind,
        "run_id": None if row.run_id is None else str(row.run_id),
        "section": row.section,
        "value": row.value,
        "supersedes_id": None if row.supersedes_id is None else str(row.supersedes_id),
        "actor_person_id": str(row.actor_person_id),
        "created_at": utc(row.created_at).isoformat(),
    }


def effective(rows: Iterable[ConversationReviewLabel]) -> list[ConversationReviewLabel]:
    """Labels nobody has superseded, oldest first."""

    listed = list(rows)
    superseded = {row.supersedes_id for row in listed if row.supersedes_id is not None}
    return sorted(
        (row for row in listed if row.id not in superseded),
        key=lambda row: (utc(row.created_at), str(row.id)),
    )


def review_state(rows: Iterable[ConversationReviewLabel]) -> str:
    """new, needs_review, disputed or done, from a call's effective labels."""

    current = effective(rows)
    if not current:
        return "new"
    statuses = [row for row in current if row.kind == "status"]
    if statuses and statuses[-1].value.get("state") == "done":
        return "done"
    verdicts: dict[tuple[str | None, str | None], set[str]] = defaultdict(set)
    for row in current:
        if row.kind == "verdict":
            verdicts[(None if row.run_id is None else str(row.run_id), row.section)].add(
                str(row.value.get("verdict"))
            )
    if any("wrong" in found or len(found) > 1 for found in verdicts.values()):
        return "disputed"
    return "needs_review"


class ReviewLabels:
    def __init__(
        self,
        application: ConversationApplication,
        operations_tenant_id: UUID,
        *,
        recording_tenant_ids: Sequence[UUID],
    ) -> None:
        self.application = application
        self.database: AsyncSession = application.database
        self.operations_tenant_id = operations_tenant_id
        self.recording_tenant_ids = tuple(
            item for item in dict.fromkeys(recording_tenant_ids) if item != operations_tenant_id
        )

    async def _admit(self, actor: ActorContext) -> datetime:
        if actor.tenant_id != self.operations_tenant_id:
            raise ConversationDenied("Call review requires the AC operations workspace.")
        await ConversationProviderAdmin(self.application).admit(actor)
        return utc(self.application.clock())

    async def _recording(self, recording_id: UUID, *, lock: bool = False) -> ConversationRecording:
        query = select(ConversationRecording).where(
            ConversationRecording.id == recording_id,
            ConversationRecording.tenant_id.in_(self.recording_tenant_ids),
            ConversationRecording.state != "deleted",
        )
        recording = await self.database.scalar(query.with_for_update() if lock else query)
        if recording is None:
            raise ConversationNotFound("Call not found.")
        return recording

    async def rows(
        self, recording_ids: Sequence[UUID]
    ) -> dict[UUID, list[ConversationReviewLabel]]:
        grouped: dict[UUID, list[ConversationReviewLabel]] = defaultdict(list)
        if not recording_ids:
            return grouped
        for row in (
            await self.database.scalars(
                select(ConversationReviewLabel).where(
                    ConversationReviewLabel.tenant_id.in_(self.recording_tenant_ids),
                    ConversationReviewLabel.recording_id.in_(recording_ids),
                )
            )
        ).all():
            grouped[row.recording_id].append(row)
        return grouped

    async def read(self, actor: ActorContext, recording_id: UUID) -> dict[str, Any]:
        await self._admit(actor)
        recording = await self._recording(recording_id)
        rows = (await self.rows([recording.id])).get(recording.id, [])
        return {
            "recording_id": str(recording.id),
            "review_state": review_state(rows),
            "effective": [_view(row) for row in effective(rows)],
            "history": [
                _view(row)
                for row in sorted(rows, key=lambda row: (utc(row.created_at), str(row.id)))
            ],
            "note": "Internal reviewer labels. Never an official score and never shown to reps.",
        }

    async def add(
        self, actor: ActorContext, recording_id: UUID, intent: LabelIntent, *, key: str
    ) -> dict[str, Any]:
        now = await self._admit(actor)
        key = key.strip()
        if not key or len(key) > 128:
            raise ConversationError("Idempotency-Key must be 1 to 128 characters.")
        try:
            value = (
                VALUES[intent.kind]
                .model_validate(intent.value)
                .model_dump(mode="json", exclude_none=True)
            )
        except ValidationError:
            raise ConversationError("These label details aren't valid.") from None
        if intent.kind == "verdict" and (intent.section is None or intent.run_id is None):
            raise ConversationError("A verdict names the run and the section it judges.")
        recording = await self._recording(recording_id, lock=True)
        if intent.run_id is not None:
            run = await self.database.scalar(
                select(ConversationRun).where(
                    ConversationRun.id == intent.run_id,
                    ConversationRun.recording_id == recording.id,
                    ConversationRun.tenant_id == recording.tenant_id,
                )
            )
            if run is None:
                raise ConversationNotFound("That run isn't part of this call.")
        fingerprint = _fingerprint(intent, value)
        label_id = uuid5(_NAMESPACE, f"{actor.person_id}|{key}")
        prior = await self.database.get(ConversationReviewLabel, label_id)
        if prior is not None:
            same = (
                prior.recording_id == recording.id
                and _fingerprint(
                    LabelIntent(
                        kind=prior.kind,
                        run_id=prior.run_id,
                        section=prior.section,
                        value=prior.value,
                    ),
                    prior.value,
                )
                == fingerprint
            )
            if not same:
                raise ConversationConflict(
                    "The Idempotency-Key has already been used for another label."
                )
            return _view(prior)

        supersedes: UUID | None = None
        if intent.kind in SUPERSEDING_KINDS:
            mine = [
                row
                for row in (await self.rows([recording.id])).get(recording.id, [])
                if row.kind == intent.kind
                and row.actor_person_id == actor.person_id
                and row.section == intent.section
                and (intent.kind != "verdict" or row.run_id == intent.run_id)
            ]
            current = effective(mine)
            if current:
                supersedes = current[-1].id
        audit_id = uuid4()
        await AuditRepository(self.database).append(
            event_id=audit_id,
            tenant_id=recording.tenant_id,
            actor_person_id=actor.person_id,
            session_id=actor.session_id,
            action=f"conversation.review_label.{intent.kind}",
            resource_type="conversation_review_label",
            resource_id=label_id,
            payload={
                "recording_id": str(recording.id),
                "run_id": None if intent.run_id is None else str(intent.run_id),
                "section": intent.section,
                "supersedes_id": None if supersedes is None else str(supersedes),
                "value_sha256": fingerprint,
            },
            now=now,
        )
        row = ConversationReviewLabel(
            id=label_id,
            tenant_id=recording.tenant_id,
            recording_id=recording.id,
            run_id=intent.run_id,
            kind=intent.kind,
            section=intent.section,
            value=value,
            supersedes_id=supersedes,
            actor_person_id=actor.person_id,
            audit_event_id=audit_id,
            created_at=now,
        )
        self.database.add(row)
        await self.database.flush()
        return _view(row)

    async def gold(self, actor: ActorContext) -> dict[str, Any]:
        """The gold set and how the AI's reports agree with it (internal only)."""

        await self._admit(actor)
        labels = list(
            (
                await self.database.scalars(
                    select(ConversationReviewLabel).where(
                        ConversationReviewLabel.tenant_id.in_(self.recording_tenant_ids),
                        ConversationReviewLabel.kind.in_(("gold", "verdict", "data_use")),
                    )
                )
            ).all()
        )
        current = effective(labels)
        gold_by_recording: dict[UUID, ConversationReviewLabel] = {}
        for row in current:
            if row.kind == "gold":
                gold_by_recording[row.recording_id] = row
        data_use = {
            row.recording_id: row.value.get("use") for row in current if row.kind == "data_use"
        }
        run_ids = {row.run_id for row in current if row.run_id is not None}
        prompts = await self._prompts(run_ids)
        ai_states = await self._ai_states(
            {row.run_id for row in gold_by_recording.values() if row.run_id}
        )

        skills: dict[str, list[int]] = {skill: [0, 0] for skill in SKILL_IDS}
        by_prompt: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "skills_compared": 0,
                "skills_agreed": 0,
                "correct": 0,
                "partly": 0,
                "wrong": 0,
            }
        )
        for row in gold_by_recording.values():
            states = row.value.get("skill_states") or {}
            ai = ai_states.get(row.run_id) if row.run_id else None
            if not ai:
                continue
            prompt = prompts.get(row.run_id, "unknown") if row.run_id else "unknown"
            for skill, state in states.items():
                if skill not in skills or skill not in ai:
                    continue
                skills[skill][0] += 1
                by_prompt[prompt]["skills_compared"] += 1
                if ai[skill] == state:
                    skills[skill][1] += 1
                    by_prompt[prompt]["skills_agreed"] += 1
        pillars: dict[str, dict[str, int]] = defaultdict(
            lambda: {"correct": 0, "partly": 0, "wrong": 0}
        )
        for row in current:
            if row.kind != "verdict" or row.section is None:
                continue
            verdict = str(row.value.get("verdict"))
            if verdict not in {"correct", "partly", "wrong"}:
                continue
            pillars[row.section][verdict] += 1
            prompt = prompts.get(row.run_id, "unknown") if row.run_id else "unknown"
            by_prompt[prompt][verdict] += 1
        return {
            "note": (
                "Internal reviewer agreement for improving prompts. "
                "Not an official score (AC-SVAL); never shown to reps."
            ),
            "calls": [
                {
                    "recording_id": str(row.recording_id),
                    "run_id": None if row.run_id is None else str(row.run_id),
                    "prompt_revision": prompts.get(row.run_id) if row.run_id else None,
                    "labelled_at": utc(row.created_at).isoformat(),
                    "actor_person_id": str(row.actor_person_id),
                    "value": row.value,
                    "data_use": data_use.get(row.recording_id),
                }
                for row in sorted(
                    gold_by_recording.values(), key=lambda item: utc(item.created_at), reverse=True
                )
            ],
            "data_use": {
                use: sum(1 for value in data_use.values() if value == use)
                for use in ("training", "test")
            },
            "skills": [
                {"skill": skill, "compared": counts[0], "agreed": counts[1]}
                for skill, counts in skills.items()
            ],
            "pillars": [
                {"section": section, **counts} for section, counts in sorted(pillars.items())
            ],
            "by_prompt": [
                {"prompt_revision": prompt, **counts}
                for prompt, counts in sorted(by_prompt.items())
            ],
        }

    async def _prompts(self, run_ids: Iterable[UUID | None]) -> dict[UUID, str]:
        ids = [run_id for run_id in run_ids if run_id is not None]
        if not ids:
            return {}
        rows = await self.database.execute(
            select(ConversationInferenceTask.run_id, ConversationProcessingPlan.manifest)
            .join(
                ConversationPlanStageAuthorization,
                ConversationPlanStageAuthorization.quote_id == ConversationInferenceTask.quote_id,
            )
            .join(
                ConversationProcessingPlan,
                ConversationProcessingPlan.id == ConversationPlanStageAuthorization.plan_id,
            )
            .where(
                ConversationInferenceTask.tenant_id.in_(self.recording_tenant_ids),
                ConversationInferenceTask.run_id.in_(ids),
            )
        )
        prompts: dict[UUID, str] = {}
        for run_id, manifest in rows.all():
            if isinstance(manifest, dict) and isinstance(
                manifest.get("coaching_prompt_revision"), str
            ):
                prompts[run_id] = manifest["coaching_prompt_revision"]
        return prompts

    async def _ai_states(self, run_ids: Iterable[UUID | None]) -> dict[UUID, dict[str, str]]:
        """The AI's skill states per run, from the newest saved report of each run."""

        ids = [run_id for run_id in run_ids if run_id is not None]
        if not ids:
            return {}
        drafts = (
            await self.database.scalars(
                select(ConversationReportDraft).where(
                    ConversationReportDraft.tenant_id.in_(self.recording_tenant_ids),
                    ConversationReportDraft.run_id.in_(ids),
                )
            )
        ).all()
        newest: dict[UUID, ConversationReportDraft] = {}
        for draft in drafts:
            seen = newest.get(draft.run_id)
            if seen is None or utc(draft.created_at) > utc(seen.created_at):
                newest[draft.run_id] = draft
        states: dict[UUID, dict[str, str]] = {}
        for run_id, draft in newest.items():
            payload = draft.payload if isinstance(draft.payload, dict) else {}
            found: dict[str, str] = {}
            for dimension in payload.get("dimensions") or []:
                if not isinstance(dimension, dict):
                    continue
                skill, state = dimension.get("dimension_id"), dimension.get("call_state")
                if isinstance(skill, str) and isinstance(state, str):
                    found[skill] = state
            states[run_id] = found
        return states
