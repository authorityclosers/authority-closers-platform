"""One pass inside the sealed plan, slice B2: what its C4 request answered, published.

Owner, 21 Oct 2026: "call data written in production". When a call's plan ran C4 as the
one-pass request (``one_pass.stage``), that one read already holds the call's deep call
data and its 27-pointer review. The pointer review's own background job (every
environment, production included) publishes them once the call's report is saved,
instead of reading the transcript again:

- ``c4_read``: the one-pass C4 task behind a report draft (draft run -> C5 task -> its
  complete-facts checkpoint -> the single C4 chunk with the one-pass recipe); ``answer``
  reads that task's saved, receipt-bound provider response from storage;
- ``publish``: the answer mapped by the publishing contracts (``analysis.map_publish``):
  the pointer review, parsed against the report's own transcript and withheld segments,
  saved through the review's own admission; the call data saved as the call's deep call
  data run through the deep pipeline's own merge (call objects, prospect facts, lead
  fills), with the deep pipeline's audio measurements. No tokens or rupees here: the read
  was paid once, as the plan's C4 stage.
- ``one_pass_plans``: recordings whose newest plan runs one pass, so the call data
  engine's deep read (development and staging) leaves them to this.

A review part that does not parse is left to today's pointer review (one more Gemini
read), so nothing is lost. Nothing logged contains transcript text or answers.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final
from uuid import UUID

from sqlalchemy import select, text

from ac_platform.one_pass import markers

PUBLISHER: Final = "automatic:one-pass-plan"
# Today's plans only: a report is published from its own plan's read.
_COMPLETE_FACTS: Final = "ac.sales-xray.complete-facts/1"


@dataclass(frozen=True, slots=True)
class Read:
    """The one-pass C4 task behind a report: where its answer is, and how to check it."""

    tenant_id: UUID
    recording_id: UUID
    run_id: UUID
    input_sha256: str
    response_sha256: str
    provider: str
    model: str


def c4_read(connection: Any, report: Mapping[str, Any]) -> Read | None:
    """The one-pass C4 read behind this report draft, or None (today's fact chunks, an
    erased or incomplete chain, or anything that does not check out)."""
    from ac_platform.conversation_intelligence.models import (
        ConversationCheckpoint,
        ConversationInferenceTask,
    )
    from ac_platform.outbox.models import Job

    c5 = connection.execute(
        select(ConversationCheckpoint.manifest)
        .join(
            ConversationInferenceTask,
            ConversationInferenceTask.checkpoint_id == ConversationCheckpoint.id,
        )
        .where(
            ConversationInferenceTask.run_id == report["run_id"],
            ConversationInferenceTask.stage == "C5",
            ConversationInferenceTask.state == "completed",
            ConversationInferenceTask.erased_at.is_(None),
            ConversationCheckpoint.recording_id == report["recording_id"],
            ConversationCheckpoint.erased_at.is_(None),
        )
    ).scalar()
    parents = c5.get("parents") if isinstance(c5, Mapping) else None
    digest = next(
        (
            parent[1]
            for parent in parents or []
            if isinstance(parent, list | tuple) and len(parent) == 2 and parent[0] == "C4"
        ),
        None,
    )
    if not isinstance(digest, str):
        return None
    aggregate = connection.execute(
        select(ConversationCheckpoint.payload).where(
            ConversationCheckpoint.recording_id == report["recording_id"],
            ConversationCheckpoint.stage == "C4",
            ConversationCheckpoint.manifest_sha256 == digest,
            ConversationCheckpoint.erased_at.is_(None),
        )
    ).scalar()
    chunks = aggregate.get("chunks") if isinstance(aggregate, Mapping) else None
    if (
        not isinstance(aggregate, Mapping)
        or aggregate.get("schema") != _COMPLETE_FACTS
        or not isinstance(chunks, list)
        or len(chunks) != 1
        or not isinstance(chunks[0], Mapping)
    ):
        return None
    try:
        chunk_id = UUID(str(chunks[0].get("id")))
    except ValueError:
        return None
    row = connection.execute(
        select(
            ConversationCheckpoint.manifest,
            ConversationInferenceTask.run_id,
            ConversationInferenceTask.job_id,
            ConversationInferenceTask.input_sha256,
            ConversationInferenceTask.tenant_id,
        )
        .join(
            ConversationInferenceTask,
            ConversationInferenceTask.checkpoint_id == ConversationCheckpoint.id,
        )
        .where(
            ConversationCheckpoint.id == chunk_id,
            ConversationCheckpoint.recording_id == report["recording_id"],
            ConversationCheckpoint.erased_at.is_(None),
            ConversationInferenceTask.stage == "C4",
            ConversationInferenceTask.state == "completed",
            ConversationInferenceTask.erased_at.is_(None),
        )
    ).first()
    if row is None or not isinstance(row.manifest, Mapping):
        return None
    if row.manifest.get("revision") != markers.RECIPE:
        return None
    receipt = connection.execute(select(Job.provider_receipt).where(Job.id == row.job_id)).scalar()
    if not isinstance(receipt, Mapping):
        return None
    response, provider, model = (
        receipt.get("response_sha256"),
        receipt.get("provider"),
        receipt.get("model"),
    )
    if (
        not isinstance(response, str)
        or len(response) != 64
        or receipt.get("raw_blob_id") != str(row.run_id)
        or not isinstance(provider, str)
        or not isinstance(model, str)
        or (provider, model) not in markers.ROUTES
    ):
        return None
    return Read(
        tenant_id=row.tenant_id,
        recording_id=report["recording_id"],
        run_id=row.run_id,
        input_sha256=str(row.input_sha256),
        response_sha256=response,
        provider=provider,
        model=model,
    )


def answer(storage_root: Path, read: Read) -> dict[str, Any] | None:
    """The read's answer, from its saved provider response (checked against the receipt's
    digest before the first byte is used); None when it can't be read or decoded."""
    from ac_platform.conversation_intelligence.gemini_tasks import (
        GeminiTaskError,
        decode_gemini_object,
    )
    from ac_platform.conversation_intelligence.storage import (
        ObjectKey,
        ObjectKind,
        PrivateLocalRecordingStorage,
        StorageError,
    )

    key = ObjectKey(read.tenant_id, read.recording_id, read.run_id, ObjectKind.PROVIDER_RESPONSE)
    try:
        raw = b"".join(
            PrivateLocalRecordingStorage(storage_root).iter_bytes(
                key, expected_sha256=read.response_sha256
            )
        )
        response = json.loads(raw)
        if read.provider != "gemini" or not isinstance(response, dict):
            return None
        return decode_gemini_object(response)
    except (StorageError, OSError, ValueError, GeminiTaskError):
        return None


def _call(connection: Any, report: Mapping[str, Any]) -> Any:
    """The call data engine's view of this call, at the report's own transcript."""
    from ac_platform.call_data import engine
    from ac_platform.one_pass import store

    calls = store.candidates(
        connection,
        not_before=datetime(2000, 1, 1, tzinfo=UTC),
        hours=24 * 3650,
        limit=1,
        recording_id=report["recording_id"],
        include_done=True,
    )
    if not calls or calls[0].transcript_revision != report["transcript_revision"]:
        return None
    return engine.load(connection, calls[0])


def _deep_saved(connection: Any, recording_id: UUID, revision: str) -> bool:
    from ac_platform.call_data.models import CallDataRun

    return (
        connection.execute(
            select(CallDataRun.id).where(
                CallDataRun.recording_id == recording_id,
                CallDataRun.pipeline == "deep",
                CallDataRun.transcript_revision == revision,
                CallDataRun.state == "succeeded",
            )
        ).first()
        is not None
    )


def _reviewed(connection: Any, report: Mapping[str, Any]) -> bool:
    from ac_platform.conversation_intelligence.pointer_review_models import (
        ConversationPointerReview,
    )

    return (
        connection.execute(
            select(ConversationPointerReview.id).where(
                ConversationPointerReview.run_id == report["run_id"],
                ConversationPointerReview.source_sha256 == report["source_sha256"],
                ConversationPointerReview.transcript_revision == report["transcript_revision"],
                ConversationPointerReview.erased_at.is_(None),
            )
        ).first()
        is not None
    )


def publish(
    connection: Any,
    *,
    report: Mapping[str, Any],
    read: Read,
    answer: Mapping[str, Any],
    segments: list[dict[str, Any]],
    withheld: set[str],
    storage_root: Path | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Save this read's pointer review and deep call data for the report's call, in the
    caller's transaction. Returns a content-free line: ``review`` is ``published``,
    ``refused`` (admission said no) or ``unusable:<code>`` (left to today's review)."""
    from ac_platform.call_data import engine
    from ac_platform.call_data.deep_runner import _frames, measured
    from ac_platform.conversation_intelligence import pointer_review
    from ac_platform.one_pass import analysis
    from ac_platform.one_pass.publish import _save_deep

    now = now or datetime.now(UTC)
    line: dict[str, Any] = {"one_pass": str(read.run_id)}
    transcript = {"segments": segments}
    published = analysis.map_publish(answer, transcript, withheld=frozenset(withheld))
    review = published.outputs.get("pointer_review")
    if _reviewed(connection, report):
        line["review"] = "already_saved"
    elif review is None:
        line["review"] = "unusable:" + str(published.checks.get("pointer_review"))[:48]
    else:
        saved = pointer_review.save_review(
            connection,
            report=dict(report),
            review=review,
            prompt_digest=read.input_sha256,
            usage={},  # paid once, as the plan's C4 stage
            created_by=PUBLISHER,
            now=now,
        )
        line["review"] = "published" if saved is not None else "refused"
    call = _call(connection, report)
    if call is None or not published.drafts:
        line["call_data"] = "none" if call is not None else "no_call"
        return line
    if engine.admission_refusal(connection, call, now) is not None:
        line["call_data"] = "refused"
        return line
    if _deep_saved(connection, call.recording_id, call.transcript_revision):
        line["call_data"] = "already_saved"
        return line
    inputs = engine.audio_inputs(connection, call)
    frames = _frames(call, inputs, storage_root)
    line["call_data"] = _save_deep(
        connection,
        call,
        published,
        voice=measured(call, published.roles, inputs, frames),
        audio="frames" if frames is not None else "timings",
        one_pass_run=read.run_id,
        trigger="auto",
        now=now,
        created_by=PUBLISHER,
    )
    return line


def one_pass_plans(connection: Any, recording_ids: Iterable[UUID]) -> set[UUID]:
    """Recordings whose newest processing plan runs C4 as the one-pass request: their deep
    call data comes from that read (``publish``), not from another engine read."""
    ids = list(dict.fromkeys(recording_ids))
    if not ids:
        return set()
    rows = connection.execute(
        text(
            """
            SELECT DISTINCT ON (recording_id) recording_id,
                   manifest -> 'stages' -> 1 ->> 'recipe_revision' AS c4_recipe
            FROM conversation_processing_plans
            WHERE recording_id = ANY(:ids) AND created_at > :since
            ORDER BY recording_id, created_at DESC
            """
        ),
        {"ids": ids, "since": datetime.now(UTC) - timedelta(days=30)},
    ).mappings()
    return {row["recording_id"] for row in rows if row["c4_recipe"] == markers.RECIPE}
