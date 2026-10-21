"""The one-pass runner's database side: find calls, record attempts, read the audio.

Synchronous SQLAlchemy; every function takes an open connection and leaves commit to
the caller. Calls are found and admitted exactly as the call data engine finds and
admits them (``call_data.engine``): ready, permitted, active, newest transcript.
Nothing here logs or returns transcript text or audio.
"""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Final
from uuid import UUID, uuid4

from sqlalchemy import insert, select, text, update

from ac_platform.call_data.engine import Call
from ac_platform.one_pass.models import OnePassRun

VERSION: Final = "one-pass/1"
IN_FLIGHT: Final = timedelta(minutes=30)  # Flex may queue for up to 15 minutes per stage
MAX_ATTEMPTS: Final = 2
# Automatic passes read only fresh transcripts (owner, 20 Oct 2026: nothing old runs or
# charges by itself); a call not read by then is never read automatically.
AUTO_FRESH_HOURS: Final = 2
FFMPEG: Final = "/usr/bin/ffmpeg"
NICE: Final = "/usr/bin/nice"

_CANDIDATES: Final = """
SELECT cp.tenant_id, cp.recording_id, cp.person_id AS principal_id, cp.id AS checkpoint_id,
       cp.payload ->> 'revision' AS transcript_revision,
       cp.payload ->> 'source_sha256' AS source_sha256,
       cp.payload ->> 'duration_ms' AS duration_ms,
       c.created_at
FROM conversation_checkpoints cp
JOIN conversation_recordings c ON c.id = cp.recording_id AND c.tenant_id = cp.tenant_id
WHERE cp.stage = 'C2' AND cp.erased_at IS NULL AND json_typeof(cp.payload) = 'object'
  AND cp.created_at > :not_before
  AND cp.created_at > :horizon
  AND c.state = 'ready' AND c.deleted_at IS NULL
  AND cp.created_at = (
    SELECT max(n.created_at) FROM conversation_checkpoints n
    WHERE n.recording_id = cp.recording_id AND n.stage = 'C2' AND n.erased_at IS NULL
  )
  {done}
  {only}
ORDER BY cp.created_at DESC
LIMIT :limit
"""
_NOT_DONE: Final = """AND NOT EXISTS (
    SELECT 1 FROM one_pass_runs r
    WHERE r.recording_id = cp.recording_id AND r.source = 'call'
      AND r.transcript_revision = cp.payload ->> 'revision'
      AND r.state IN ('succeeded', 'skipped')
  )"""


def candidates(
    connection: Any,
    *,
    not_before: datetime,
    hours: int,
    limit: int,
    recording_id: UUID | None = None,
    include_done: bool = False,
) -> list[Call]:
    """Calls whose newest classic transcript has no finished one-pass run yet."""
    query = _CANDIDATES.format(
        done="" if include_done else _NOT_DONE,
        only="AND cp.recording_id = :recording" if recording_id else "",
    )
    rows = connection.execute(
        text(query),
        {
            "not_before": not_before,
            "horizon": datetime.now(UTC) - timedelta(hours=hours),
            "limit": limit,
            "recording": recording_id,
        },
    ).mappings()
    calls = []
    for row in rows:
        if not row["transcript_revision"]:
            continue
        duration = row["duration_ms"]
        calls.append(
            Call(
                tenant_id=row["tenant_id"],
                recording_id=row["recording_id"],
                principal_id=row["principal_id"],
                checkpoint_id=row["checkpoint_id"],
                transcript_revision=str(row["transcript_revision"]),
                source_sha256=row["source_sha256"],
                duration_ms=int(duration) if duration and str(duration).isdigit() else None,
                created_at=row["created_at"],
            )
        )
    return calls


def attempt_refusal(connection: Any, call: Call, now: datetime) -> str | None:
    """'in_flight' or 'attempts_exhausted' from this transcript's earlier attempts."""
    rows = connection.execute(
        select(OnePassRun.id, OnePassRun.state, OnePassRun.supersedes_id, OnePassRun.created_at)
        .where(
            OnePassRun.recording_id == call.recording_id,
            OnePassRun.source == "call",
            OnePassRun.transcript_revision == call.transcript_revision,
        )
        .order_by(OnePassRun.created_at)
    ).all()
    outcomes = {row.supersedes_id: row.state for row in rows if row.supersedes_id is not None}
    unsaved = 0
    for row in rows:
        if row.state != "running":
            continue
        outcome = outcomes.get(row.id)
        if outcome is None and now - row.created_at < IN_FLIGHT:
            return "in_flight"
        unsaved = 0 if outcome == "succeeded" else unsaved + 1
    return "attempts_exhausted" if unsaved >= MAX_ATTEMPTS else None


@dataclass(frozen=True, slots=True)
class Subject:
    """What a run is about: a real call, or one fictional benchmark call."""

    source: str
    tenant_id: UUID | None = None
    recording_id: UUID | None = None
    bench_call: str | None = None
    submission_id: UUID | None = None
    person_id: UUID | None = None
    transcript_revision: str | None = None
    source_sha256: str | None = None

    @classmethod
    def of(cls, call: Call) -> Subject:
        return cls(
            "call",
            tenant_id=call.tenant_id,
            recording_id=call.recording_id,
            submission_id=call.submission_id,
            person_id=call.person_id,
            transcript_revision=call.transcript_revision,
            source_sha256=call.source_sha256,
        )

    def columns(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "tenant_id": self.tenant_id,
            "recording_id": self.recording_id,
            "bench_call": self.bench_call,
            "submission_id": self.submission_id,
            "person_id": self.person_id,
            "transcript_revision": self.transcript_revision,
            "source_sha256": self.source_sha256,
        }


def start_run(
    connection: Any,
    subject: Subject,
    *,
    trigger: str,
    mode: str | None,
    settings: dict[str, Any],
    models: dict[str, str],
    created_by: str,
    now: datetime,
) -> UUID:
    run_id = uuid4()
    connection.execute(
        insert(OnePassRun).values(
            id=run_id,
            **subject.columns(),
            pipeline="one_pass",
            pipeline_version=VERSION,
            state="running",
            trigger=trigger,
            mode=mode,
            transcription_model=models["transcription"],
            analysis_model=models["analysis"],
            transcription_tier=settings.get("transcription_tier"),
            analysis_tier=settings.get("analysis_tier"),
            created_by=created_by,
            created_at=now,
        )
    )
    return run_id


@dataclass(slots=True)
class Outcome:
    """Everything an attempt measured; content stays None when it failed early."""

    state: str = "failed"
    reason: str | None = "runner_error"
    audio_ms: int | None = None
    transcription_tier: str | None = None
    analysis_tier: str | None = None
    transcription_input_tokens: int | None = None
    transcription_output_tokens: int | None = None
    analysis_input_tokens: int | None = None
    analysis_output_tokens: int | None = None
    analysis_cached_tokens: int | None = None
    transcription_cost_inr: Decimal | None = None
    analysis_cost_inr: Decimal | None = None
    transcription_ms: int | None = None
    analysis_ms: int | None = None
    duration_ms: int | None = None
    usage: dict[str, Any] | None = None
    checks: dict[str, Any] | None = None
    transcript: dict[str, Any] | None = None
    outputs: dict[str, Any] | None = None

    @property
    def cost_inr(self) -> Decimal | None:
        parts = [p for p in (self.transcription_cost_inr, self.analysis_cost_inr) if p is not None]
        return sum(parts, Decimal(0)) if parts else None


def finish_run(
    connection: Any,
    subject: Subject,
    started: UUID,
    outcome: Outcome,
    *,
    trigger: str,
    mode: str | None,
    models: dict[str, str],
    created_by: str,
    now: datetime,
) -> UUID:
    run_id = uuid4()
    connection.execute(
        insert(OnePassRun).values(
            id=run_id,
            **subject.columns(),
            pipeline="one_pass",
            pipeline_version=VERSION,
            state=outcome.state,
            reason_code=(outcome.reason or None) and str(outcome.reason)[:64],
            trigger=trigger,
            mode=mode,
            transcription_model=models["transcription"],
            analysis_model=models["analysis"],
            transcription_tier=outcome.transcription_tier,
            analysis_tier=outcome.analysis_tier,
            audio_ms=outcome.audio_ms,
            transcription_input_tokens=outcome.transcription_input_tokens,
            transcription_output_tokens=outcome.transcription_output_tokens,
            analysis_input_tokens=outcome.analysis_input_tokens,
            analysis_output_tokens=outcome.analysis_output_tokens,
            analysis_cached_tokens=outcome.analysis_cached_tokens,
            transcription_cost_inr=outcome.transcription_cost_inr,
            analysis_cost_inr=outcome.analysis_cost_inr,
            cost_inr=outcome.cost_inr,
            transcription_ms=outcome.transcription_ms,
            analysis_ms=outcome.analysis_ms,
            duration_ms=outcome.duration_ms,
            usage=outcome.usage,
            checks=outcome.checks,
            transcript=outcome.transcript,
            outputs=outcome.outputs,
            supersedes_id=started,
            created_by=created_by,
            created_at=now,
        )
    )
    return run_id


def skip_run(
    connection: Any,
    subject: Subject,
    *,
    reason: str,
    trigger: str,
    mode: str | None,
    created_by: str,
    now: datetime,
) -> None:
    """A call the pipeline will not read (too long, no speech, marked sensitive): recorded
    once, no cost."""
    connection.execute(
        insert(OnePassRun).values(
            id=uuid4(),
            **subject.columns(),
            pipeline="one_pass",
            pipeline_version=VERSION,
            state="skipped",
            reason_code=reason,
            trigger=trigger,
            mode=mode,
            created_by=created_by,
            created_at=now,
        )
    )


def insert_classic_bench(
    connection: Any,
    bench_call: str,
    *,
    outcome: Outcome,
    models: dict[str, str],
    created_by: str,
    now: datetime,
) -> UUID:
    """A fictional call's classic results, imported from the research harness."""
    run_id = uuid4()
    connection.execute(
        insert(OnePassRun).values(
            id=run_id,
            source="bench",
            bench_call=bench_call,
            pipeline="classic",
            pipeline_version="classic/research-today",
            state=outcome.state,
            reason_code=outcome.reason,
            trigger="bench",
            transcription_model=models.get("transcription"),
            analysis_model=models.get("analysis"),
            transcription_tier="standard",
            analysis_tier="standard",
            audio_ms=outcome.audio_ms,
            transcription_cost_inr=outcome.transcription_cost_inr,
            analysis_cost_inr=outcome.analysis_cost_inr,
            cost_inr=outcome.cost_inr,
            analysis_input_tokens=outcome.analysis_input_tokens,
            analysis_output_tokens=outcome.analysis_output_tokens,
            transcription_ms=outcome.transcription_ms,
            analysis_ms=outcome.analysis_ms,
            duration_ms=outcome.duration_ms,
            usage=outcome.usage,
            checks=outcome.checks,
            transcript=outcome.transcript,
            outputs=outcome.outputs,
            created_by=created_by,
            created_at=now,
        )
    )
    return run_id


# ----- audio ------------------------------------------------------------------------


def source_key(connection: Any, call: Call) -> Any:
    """The call's stored source audio key (the same rule as ``resolve_source_key``)."""
    from ac_platform.conversation_intelligence.storage import (
        ObjectKey,
        ObjectKind,
        SourceAudioKey,
        StorageError,
    )

    row = connection.execute(
        text(
            """
            SELECT c.tenant_id, c.person_id, c.source_sha256,
                   r.recording_id AS referenced, r.released_at, r.tenant_id AS ref_tenant,
                   r.person_id AS ref_person, s.tenant_id AS src_tenant,
                   s.source_sha256 AS src_sha, s.deleted_at AS src_deleted
            FROM conversation_recordings c
            LEFT JOIN conversation_source_references r ON r.recording_id = c.id
            LEFT JOIN conversation_source_objects s ON s.id = r.source_object_id
            WHERE c.id = :recording
            """
        ),
        {"recording": call.recording_id},
    ).first()
    if row is None:
        raise StorageError("storage_object_missing")
    if row.referenced is None:
        return ObjectKey(
            row.tenant_id, call.recording_id, call.recording_id, ObjectKind.SOURCE_AUDIO
        )
    if (
        row.released_at is not None
        or row.ref_tenant != row.tenant_id
        or row.ref_person != row.person_id
        or row.src_tenant != row.tenant_id
        or row.src_sha != row.source_sha256
        or row.src_deleted is not None
    ):
        raise StorageError("storage_object_missing")
    return SourceAudioKey(row.src_tenant, row.src_sha)


def read_audio(storage_root: Path, key: Any, sha256: str) -> bytes:
    from ac_platform.conversation_intelligence.storage import PrivateLocalRecordingStorage

    storage = PrivateLocalRecordingStorage(storage_root)
    return b"".join(storage.iter_bytes(key, expected_sha256=sha256))


def to_mp3(source: bytes, *, ffmpeg: str = FFMPEG) -> bytes:
    """Mono 32 kbps MP3, the shape the research measured Flash-Lite on (any input format;
    calls are speech, so nothing the model needs is lost)."""
    with tempfile.TemporaryDirectory(prefix="one-pass-") as folder:
        source_path = Path(folder) / "source"
        target = Path(folder) / "call.mp3"
        source_path.write_bytes(source)
        try:
            subprocess.run(  # noqa: S603 - fixed argv, no shell, our own files
                [
                    NICE,
                    "-n",
                    "19",
                    ffmpeg,
                    "-nostdin",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(source_path),
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-b:a",
                    "32k",
                    "-f",
                    "mp3",
                    str(target),
                ],
                check=True,
                capture_output=True,
                timeout=300,
            )
        except (subprocess.SubprocessError, OSError):
            raise ValueError("audio_transcode_failed") from None
        return target.read_bytes()


# ----- erasure ------------------------------------------------------------------------


def erase_for_recording(connection: Any, recording_id: UUID, now: datetime) -> int:
    """Empty the transcript and outputs of every run on an erased call."""
    erased = connection.execute(
        update(OnePassRun)
        .where(OnePassRun.recording_id == recording_id, OnePassRun.erased_at.is_(None))
        .values(transcript=None, outputs=None, erased_at=now)
    ).rowcount
    return int(erased or 0)


async def erase_one_pass_for_recording(database: Any, recording_id: UUID, now: datetime) -> int:
    """The erasure hook ``ConversationApplication.finish_erasure`` calls (same transaction)."""
    if not await database.scalar(text("SELECT to_regclass('one_pass_runs') IS NOT NULL")):
        return 0
    erased: int = await database.run_sync(
        lambda session: erase_for_recording(session.connection(), recording_id, now)
    )
    return erased
