"""The fast pipeline's database side: find calls, admit them, save runs, objects and fills.

Synchronous SQLAlchemy (the runner calls these through ``run_sync``). Every
function takes an open connection and leaves commit to the caller, so one
call's objects, decisions and lead fills land in one transaction together with
the admission check that fences erasure and revocation.

Nothing here logs or returns transcript text, quotes or lead values.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import insert, select, text, update

from ac_platform.call_data import taxonomy
from ac_platform.call_data.extraction import Draft, Segment, segments_from_transcript
from ac_platform.call_data.models import (
    CallDataRun,
    CallDataSettings,
    CallObject,
    CallObjectDecision,
)
from ac_platform.call_data.policy import Plan
from ac_platform.call_data.settings import validate
from ac_platform.lead_desk.models import Lead, LeadEvent

IST = ZoneInfo("Asia/Kolkata")
FAST_VERSION = "fast/1"
IN_FLIGHT = timedelta(minutes=10)
MAX_ATTEMPTS = 2
# The lead columns the engine may write. Phone and email never come from a call.
LEAD_COLUMNS = frozenset({"name", "company", "city", "interest"})
LEAD_LIMITS = {"name": 200, "company": 200, "city": 120, "interest": 200}
PLACEHOLDER_NAMES = frozenset({"unnamed lead"})


@dataclass(slots=True)
class Call:
    tenant_id: UUID
    recording_id: UUID
    principal_id: UUID
    checkpoint_id: UUID
    transcript_revision: str
    source_sha256: str | None
    duration_ms: int | None
    created_at: datetime
    submission_id: UUID | None = None
    salesperson_id: UUID | None = None
    lead_id: UUID | None = None
    segments: list[Segment] = field(default_factory=list)
    withheld: frozenset[str] = frozenset()

    @property
    def person_id(self) -> UUID:
        return self.salesperson_id or self.principal_id

    def call_date(self) -> str:
        local = self.created_at.astimezone(IST)
        return local.strftime("%A %d %B %Y")


# ----- settings ------------------------------------------------------------------


def read_settings(connection: Any) -> tuple[dict[str, Any], int | None]:
    row = connection.execute(
        select(CallDataSettings.config, CallDataSettings.revision)
        .order_by(CallDataSettings.revision.desc())
        .limit(1)
    ).first()
    if row is None:
        return validate({}), None
    try:
        return validate(row.config), int(row.revision)
    except ValueError:
        # A row from a newer release this code cannot read: fail safe, pipelines off.
        safe = validate({})
        for pipeline in safe:
            safe[pipeline]["enabled"] = False
        return safe, int(row.revision)


def save_settings(
    connection: Any, config: dict[str, Any], *, person_id: UUID | None, now: datetime
) -> int:
    checked = validate(config)
    current = connection.scalar(
        select(CallDataSettings.revision)
        .order_by(CallDataSettings.revision.desc())
        .limit(1)
        .with_for_update()
    )
    revision = int(current or 0) + 1
    connection.execute(
        insert(CallDataSettings).values(
            id=uuid4(),
            revision=revision,
            config=checked,
            created_by_person_id=person_id,
            created_at=now,
        )
    )
    return revision


# ----- finding calls ---------------------------------------------------------------

_CANDIDATES = """
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
  {after_fast}
  {only}
ORDER BY cp.created_at DESC
LIMIT :limit
"""


_NOT_DONE = """AND NOT EXISTS (
    SELECT 1 FROM call_data_runs r
    WHERE r.recording_id = cp.recording_id AND r.pipeline = :pipeline
      AND r.transcript_revision = cp.payload ->> 'revision'
      AND r.state IN ('succeeded', 'skipped')
  )"""


_AFTER_FAST = """AND EXISTS (
    SELECT 1 FROM call_data_runs f
    WHERE f.recording_id = cp.recording_id AND f.pipeline = 'fast'
      AND f.transcript_revision = cp.payload ->> 'revision'
      AND f.state IN ('succeeded', 'skipped')
  )"""


def candidates(
    connection: Any,
    *,
    not_before: datetime,
    hours: int,
    limit: int,
    pipeline: str = "fast",
    recording_id: UUID | None = None,
    include_done: bool = False,
) -> list[Call]:
    only = "AND cp.recording_id = :recording" if recording_id else ""
    done = "" if include_done else _NOT_DONE
    after_fast = _AFTER_FAST if pipeline == "deep" else ""
    rows = connection.execute(
        text(_CANDIDATES.format(only=only, done=done, after_fast=after_fast)),
        {
            "not_before": not_before,
            "horizon": datetime.now(UTC) - timedelta(hours=hours),  # backfill: up to a year
            "pipeline": pipeline,
            "limit": limit,
            "recording": recording_id,
        },
    ).mappings()
    result = []
    for row in rows:
        if not row["transcript_revision"]:
            continue
        duration = row["duration_ms"]
        result.append(
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
    return result


def test_source_shas(connection: Any) -> set[str]:
    """Our own canary and QA smoke calls are never processed (owner, 17 Oct cost step 1)."""
    from ac_platform.conversation_intelligence.pointer_review_cli import _test_source_shas

    return _test_source_shas(connection)


def attempt_refusal(connection: Any, call: Call, pipeline: str, now: datetime) -> str | None:
    """'in_flight' or 'attempts_exhausted' from this transcript's earlier attempts."""
    rows = connection.execute(
        select(CallDataRun.id, CallDataRun.state, CallDataRun.supersedes_id, CallDataRun.created_at)
        .where(
            CallDataRun.recording_id == call.recording_id,
            CallDataRun.pipeline == pipeline,
            CallDataRun.transcript_revision == call.transcript_revision,
        )
        .order_by(CallDataRun.created_at)
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


def spent_today(connection: Any, pipeline: str, now: datetime) -> Decimal:
    """Estimated rupees in the last 24 hours; an attempt with no outcome counts as Rs 2."""
    since = now - timedelta(hours=24)
    finished = connection.scalar(
        text(
            "SELECT coalesce(sum(cost_inr), 0) FROM call_data_runs"
            " WHERE pipeline = :pipeline AND created_at > :since AND state <> 'running'"
        ),
        {"pipeline": pipeline, "since": since},
    )
    open_attempts = connection.scalar(
        text(
            "SELECT count(*) FROM call_data_runs r WHERE r.pipeline = :pipeline"
            " AND r.created_at > :since AND r.state = 'running' AND NOT EXISTS"
            " (SELECT 1 FROM call_data_runs o WHERE o.supersedes_id = r.id)"
        ),
        {"pipeline": pipeline, "since": since},
    )
    return Decimal(finished or 0) + Decimal(2) * int(open_attempts or 0)


# Owner, 20 Oct 2026: nothing old runs or charges by itself. The automatic runner
# reads only transcripts saved in the last AUTO_FRESH_HOURS; a call not read by then
# (the pipeline was off, at its cap, stopped by the spend guard or the runner was
# down) is held, and only an explicit backfill (after raising the backfill cap in
# AI spend, which is the approval) ever reads it.
AUTO_FRESH_HOURS = 2


def queue(connection: Any, pipeline: str, now: datetime, hours: int = 720) -> dict[str, Any]:
    """Calls this pipeline has not read (last 30 days): `new` ones the automatic runner
    still reads by itself, and `held` ones it never will, with the oldest held moment."""
    after_fast = _AFTER_FAST if pipeline == "deep" else ""
    row = connection.execute(
        text(
            f"""
            SELECT count(*) FILTER (WHERE cp.created_at > :fresh) AS new,
                   count(*) FILTER (WHERE cp.created_at <= :fresh) AS held,
                   min(cp.created_at) FILTER (WHERE cp.created_at <= :fresh) AS oldest_held
            FROM conversation_checkpoints cp
            JOIN conversation_recordings c ON c.id = cp.recording_id
            WHERE cp.stage = 'C2' AND cp.erased_at IS NULL
              AND json_typeof(cp.payload) = 'object' AND cp.created_at > :horizon
              AND c.state = 'ready' AND c.deleted_at IS NULL
              AND cp.created_at = (
                SELECT max(n.created_at) FROM conversation_checkpoints n
                WHERE n.recording_id = cp.recording_id AND n.stage = 'C2'
                  AND n.erased_at IS NULL
              )
              AND NOT EXISTS (
                SELECT 1 FROM call_data_runs r
                WHERE r.recording_id = cp.recording_id AND r.pipeline = :pipeline
                  AND r.transcript_revision = cp.payload ->> 'revision'
              )
              {after_fast}
            """  # noqa: S608 - fixed fragments, values bound
        ),
        {
            "pipeline": pipeline,
            "horizon": now - timedelta(hours=hours),
            "fresh": now - timedelta(hours=AUTO_FRESH_HOURS),
        },
    ).one()
    return {
        "new": int(row.new or 0),
        "held": int(row.held or 0),
        "oldest_held_at": row.oldest_held.isoformat() if row.oldest_held else None,
        "fresh_hours": AUTO_FRESH_HOURS,
    }


def waiting_for_budget(connection: Any, pipeline: str, now: datetime, hours: int = 720) -> int:
    """Calls whose newest transcript has no run of this pipeline yet (last 30 days)."""
    after_fast = _AFTER_FAST if pipeline == "deep" else ""
    return int(
        connection.scalar(
            text(
                f"""
                SELECT count(*) FROM conversation_checkpoints cp
                JOIN conversation_recordings c ON c.id = cp.recording_id
                WHERE cp.stage = 'C2' AND cp.erased_at IS NULL
                  AND json_typeof(cp.payload) = 'object' AND cp.created_at > :horizon
                  AND c.state = 'ready' AND c.deleted_at IS NULL
                  AND cp.created_at = (
                    SELECT max(n.created_at) FROM conversation_checkpoints n
                    WHERE n.recording_id = cp.recording_id AND n.stage = 'C2'
                      AND n.erased_at IS NULL
                  )
                  AND NOT EXISTS (
                    SELECT 1 FROM call_data_runs r
                    WHERE r.recording_id = cp.recording_id AND r.pipeline = :pipeline
                      AND r.transcript_revision = cp.payload ->> 'revision'
                  )
                  {after_fast}
                """  # noqa: S608 - fixed fragments, values bound
            ),
            {"pipeline": pipeline, "horizon": now - timedelta(hours=hours)},
        )
        or 0
    )


def settings_history(connection: Any, limit: int = 10) -> list[dict[str, Any]]:
    """Recent settings revisions, newest first: who, when, caps and switches."""
    rows = connection.execute(
        select(
            CallDataSettings.revision,
            CallDataSettings.config,
            CallDataSettings.created_by_person_id,
            CallDataSettings.created_at,
        )
        .order_by(CallDataSettings.revision.desc())
        .limit(limit)
    ).all()
    history = []
    for row in rows:
        config = row.config if isinstance(row.config, dict) else {}
        history.append(
            {
                "revision": row.revision,
                "by_person_id": str(row.created_by_person_id) if row.created_by_person_id else None,
                "at": row.created_at.isoformat(),
                "fast": dict(config.get("fast") or {}),
                "deep": dict(config.get("deep") or {}),
            }
        )
    return history


# ----- loading one call ------------------------------------------------------------


def load(connection: Any, call: Call) -> Call:
    """Fill in the transcript segments, withheld marks, submission, salesperson and lead."""
    payload = connection.scalar(
        text("SELECT payload FROM conversation_checkpoints WHERE id = :id AND erased_at IS NULL"),
        {"id": call.checkpoint_id},
    )
    call.segments = segments_from_transcript(payload if isinstance(payload, dict) else {})
    marks = connection.execute(
        text(
            """
            SELECT DISTINCT ON (segment_id) segment_id, action
            FROM conversation_sensitive_segment_marks
            WHERE recording_id = :recording AND transcript_revision = :revision
            ORDER BY segment_id, created_at DESC
            """
        ),
        {"recording": call.recording_id, "revision": call.transcript_revision},
    ).mappings()
    call.withheld = frozenset(str(r["segment_id"]) for r in marks if r["action"] == "mark")
    owner = connection.execute(
        text(
            """
            SELECT s.submission_id, u.person_id
            FROM conversation_guest_submissions s
            LEFT JOIN conversation_acquisition_usage u ON u.id = s.usage_id
            WHERE s.recording_id = :recording AND s.tenant_id = :tenant
            ORDER BY s.created_at DESC
            LIMIT 1
            """
        ),
        {"recording": call.recording_id, "tenant": call.tenant_id},
    ).first()
    if owner is not None:
        call.submission_id = owner.submission_id
        call.salesperson_id = owner.person_id
    if call.submission_id is not None:
        call.lead_id = lead_for_call(connection, call.tenant_id, call.submission_id)
    return call


@dataclass(slots=True)
class AudioInputs:
    display_dbfs: list[float]
    blob_id: UUID | None
    feature_sha256: str | None


def audio_inputs(connection: Any, call: Call) -> AudioInputs:
    """The audio check's waveform and feature-file reference for this call (C1)."""
    row = connection.execute(
        text(
            """
            SELECT payload, feature_blob_id FROM conversation_checkpoints
            WHERE recording_id = :recording AND stage = 'C1' AND erased_at IS NULL
            ORDER BY created_at DESC LIMIT 1
            """
        ),
        {"recording": call.recording_id},
    ).first()
    if row is None or not isinstance(row.payload, dict):
        return AudioInputs([], None, None)
    display = row.payload.get("display")
    channels = display.get("channels") if isinstance(display, dict) else None
    first = channels[0] if isinstance(channels, list) and channels else {}
    dbfs = first.get("dbfs") if isinstance(first, dict) else None
    digest = row.payload.get("feature_sha256")
    return AudioInputs(
        [float(v) for v in dbfs if isinstance(v, (int, float))] if isinstance(dbfs, list) else [],
        row.feature_blob_id,
        digest if isinstance(digest, str) else None,
    )


def lead_for_call(connection: Any, tenant_id: UUID, submission_id: UUID) -> UUID | None:
    """The Lead Desk lead this call was made or uploaded on, same workspace only."""
    lead_id: UUID | None = connection.scalar(
        text(
            """
            SELECT l.id FROM lead_desk_leads l
            WHERE l.tenant_id = :tenant AND l.id = coalesce(
              (SELECT e.lead_id FROM lead_desk_events e
               WHERE e.tenant_id = :tenant AND e.kind = 'call'
                 AND e.data ->> 'submission_id' = :submission
               ORDER BY e.created_at DESC LIMIT 1),
              (SELECT x.id FROM lead_desk_leads x
               WHERE x.tenant_id = :tenant AND x.last_submission_id = :submission_id
               ORDER BY x.updated_at DESC LIMIT 1))
            """
        ),
        {"tenant": tenant_id, "submission": str(submission_id), "submission_id": submission_id},
    )
    return lead_id


_ADMISSION = """
SELECT c.state, c.deleted_at IS NULL AS live, c.source_sha256 AS call_source,
       p.revoked_at IS NULL AND p.provider = 'local' AND p.source_sha256 = c.source_sha256
         AND p.expires_at > :now AND p.retention_until > :now
         AND length(p.permission_reference) > 0 AND length(p.retention_reference) > 0
         AS permitted,
       t.status = 'active' AND person.status = 'active'
         AND coalesce(m.status = 'active' AND m.ended_at IS NULL, false) AS active,
       (SELECT n.payload ->> 'revision' FROM conversation_checkpoints n
        WHERE n.recording_id = c.id AND n.stage = 'C2' AND n.erased_at IS NULL
        ORDER BY n.created_at DESC LIMIT 1) AS latest_revision
FROM conversation_recordings c
JOIN conversation_permissions p ON p.id = c.permission_id
JOIN tenants t ON t.id = c.tenant_id
JOIN persons person ON person.id = c.person_id
LEFT JOIN memberships m ON m.tenant_id = c.tenant_id AND m.person_id = c.person_id
WHERE c.id = :recording AND c.tenant_id = :tenant
FOR SHARE OF c, p
"""


def admission_refusal(connection: Any, call: Call, now: datetime) -> str | None:
    """Why this call may not be processed or saved now (the pointer review's checks).

    The call is ready and not being erased; its recording permission is current;
    its workspace, principal and membership are active; and this transcript is
    still the call's newest. The recording and permission rows stay locked FOR
    SHARE until the caller's transaction ends, so erasure waits for this check.
    """
    row = connection.execute(
        text(_ADMISSION),
        {"recording": call.recording_id, "tenant": call.tenant_id, "now": now},
    ).first()
    if row is None:
        return "call_missing"
    if row.state in {"deleting", "deleted"} or not row.live:
        return "call_erased"
    if row.state != "ready":
        return "call_not_ready"
    if row.latest_revision != call.transcript_revision:
        return "stale_transcript"
    if call.source_sha256 and row.call_source != call.source_sha256:
        return "stale_source"
    if not row.permitted:
        return "permission_inactive"
    if not row.active:
        return "account_inactive"
    return None


# ----- runs ------------------------------------------------------------------------


def start_run(
    connection: Any,
    call: Call,
    *,
    pipeline: str,
    model: str,
    trigger: str,
    prompt_sha256: str | None,
    created_by: str,
    now: datetime,
    version: str = FAST_VERSION,
) -> UUID:
    run_id = uuid4()
    connection.execute(
        insert(CallDataRun).values(
            id=run_id,
            tenant_id=call.tenant_id,
            recording_id=call.recording_id,
            submission_id=call.submission_id,
            person_id=call.person_id,
            pipeline=pipeline,
            pipeline_version=version,
            taxonomy_version=taxonomy.TAXONOMY_VERSION,
            state="running",
            trigger=trigger,
            transcript_revision=call.transcript_revision,
            source_sha256=call.source_sha256,
            provider="gemini",
            model_id=model,
            prompt_sha256=prompt_sha256,
            created_by=created_by,
            created_at=now,
        )
    )
    return run_id


def finish_run(
    connection: Any,
    call: Call,
    started: UUID,
    *,
    state: str,
    reason: str | None,
    pipeline: str,
    model: str | None,
    trigger: str,
    usage: dict[str, Any] | None,
    cost_inr: Decimal | None,
    duration_ms: int | None,
    counts: dict[str, Any] | None,
    created_by: str,
    now: datetime,
    version: str = FAST_VERSION,
) -> UUID:
    run_id = uuid4()
    usage = usage or {}
    connection.execute(
        insert(CallDataRun).values(
            id=run_id,
            tenant_id=call.tenant_id,
            recording_id=call.recording_id,
            submission_id=call.submission_id,
            person_id=call.person_id,
            pipeline=pipeline,
            pipeline_version=version,
            taxonomy_version=taxonomy.TAXONOMY_VERSION,
            state=state,
            reason_code=reason,
            trigger=trigger,
            transcript_revision=call.transcript_revision,
            source_sha256=call.source_sha256,
            provider="gemini" if model else None,
            model_id=model,
            input_tokens=usage.get("promptTokenCount"),
            output_tokens=usage.get("candidatesTokenCount"),
            cost_inr=cost_inr,
            duration_ms=duration_ms,
            counts=counts,
            supersedes_id=started,
            created_by=created_by,
            created_at=now,
        )
    )
    return run_id


def skip_run(
    connection: Any,
    call: Call,
    *,
    reason: str,
    pipeline: str,
    trigger: str,
    created_by: str,
    now: datetime,
    version: str = FAST_VERSION,
) -> None:
    """A call the engine will not process (too long, no speech): recorded once, no cost."""
    connection.execute(
        insert(CallDataRun).values(
            id=uuid4(),
            tenant_id=call.tenant_id,
            recording_id=call.recording_id,
            submission_id=call.submission_id,
            person_id=call.person_id,
            pipeline=pipeline,
            pipeline_version=version,
            taxonomy_version=taxonomy.TAXONOMY_VERSION,
            state="skipped",
            reason_code=reason,
            trigger=trigger,
            transcript_revision=call.transcript_revision,
            source_sha256=call.source_sha256,
            created_by=created_by,
            created_at=now,
        )
    )


# ----- the lead --------------------------------------------------------------------


@dataclass(slots=True)
class LeadState:
    id: UUID
    revision: int
    columns: dict[str, str | None]
    phone: str | None
    auto_filled: dict[str, str]
    rejected: frozenset[tuple[str, str]]


def _norm(value: str | None) -> str:
    return " ".join((value or "").casefold().split())


def lead_state(connection: Any, tenant_id: UUID, lead_id: UUID) -> LeadState | None:
    lead = connection.execute(
        select(
            Lead.id, Lead.revision, Lead.name, Lead.company, Lead.city, Lead.interest, Lead.phone
        )
        .where(Lead.id == lead_id, Lead.tenant_id == tenant_id)
        .with_for_update()
    ).first()
    if lead is None:
        return None
    name = lead.name
    if _norm(name) in PLACEHOLDER_NAMES or (lead.phone and _norm(name) == _norm(lead.phone)):
        name = None
    written = connection.execute(
        select(
            CallObjectDecision.lead_field,
            CallObjectDecision.display.label("edited"),
            CallObject.display.label("heard"),
        )
        .join(CallObject, CallObject.id == CallObjectDecision.object_id)
        .where(
            CallObjectDecision.tenant_id == tenant_id,
            CallObjectDecision.lead_id == lead_id,
            CallObjectDecision.lead_written.is_(True),
            CallObjectDecision.actor == "engine",
            CallObjectDecision.erased_at.is_(None),
        )
        .order_by(CallObjectDecision.created_at)
    ).all()
    auto_filled = {
        str(row.lead_field): str(row.edited or row.heard or "") for row in written if row.lead_field
    }
    rejected_rows = connection.execute(
        select(CallObject.type_key, CallObject.display)
        .join(CallObjectDecision, CallObjectDecision.object_id == CallObject.id)
        .where(
            CallObjectDecision.tenant_id == tenant_id,
            CallObjectDecision.lead_id == lead_id,
            CallObjectDecision.decision == "rejected",
            CallObject.erased_at.is_(None),
        )
    ).all()
    return LeadState(
        id=lead.id,
        revision=lead.revision,
        columns={
            "name": name,
            "company": lead.company,
            "city": lead.city,
            "interest": lead.interest,
        },
        phone=lead.phone,
        auto_filled=auto_filled,
        rejected=frozenset((row.type_key, _norm(row.display)) for row in rejected_rows),
    )


def write_lead(
    connection: Any,
    tenant_id: UUID,
    lead: LeadState,
    column: str,
    value: str,
    *,
    submission_id: UUID | None,
    actor_person_id: UUID | None,
    now: datetime,
) -> bool:
    """Write one lead column with the desk's revision rule and an 'edited' history row."""
    if column not in LEAD_COLUMNS:
        raise ValueError("call_data_lead_column")
    value = value.strip()[: LEAD_LIMITS[column]]
    if not value:
        return False
    result = connection.execute(
        update(Lead)
        .where(Lead.id == lead.id, Lead.tenant_id == tenant_id, Lead.revision == lead.revision)
        .values({column: value, "revision": lead.revision + 1, "updated_at": now})
    )
    if result.rowcount != 1:
        return False
    lead.revision += 1
    lead.columns[column] = value
    connection.execute(
        insert(LeadEvent).values(
            id=uuid4(),
            tenant_id=tenant_id,
            lead_id=lead.id,
            kind="edited",
            actor_person_id=actor_person_id,
            command_id=None,
            data={
                "changed": [column],
                "via": "call_data",
                "submission_id": str(submission_id) if submission_id else None,
            },
            created_at=now,
        )
    )
    return True


# ----- saving objects --------------------------------------------------------------


def current_objects(connection: Any, recording_id: UUID) -> list[Any]:
    """This call's objects that no later object supersedes (erased ones excluded)."""
    rows = connection.execute(
        select(
            CallObject.id,
            CallObject.type_key,
            CallObject.display,
            CallObject.supersedes_id,
            CallObject.retracted,
        ).where(CallObject.recording_id == recording_id, CallObject.erased_at.is_(None))
    ).all()
    successors = {row.supersedes_id for row in rows if row.supersedes_id is not None}
    return [row for row in rows if row.id not in successors]


def _identity(type_key: str, display: str | None) -> tuple[str, str]:
    kind_type = taxonomy.get(type_key)
    return (type_key, "" if kind_type is None or not kind_type.many else _norm(display))


def save_objects(
    connection: Any,
    call: Call,
    run_id: UUID,
    drafts: list[Draft],
    plans: list[Plan],
    *,
    lead: LeadState | None,
    pipeline: str,
    pipeline_version: str,
    now: datetime,
) -> dict[str, int]:
    """Insert objects and decisions, write auto-fills to the lead; counts only."""
    previous = {
        _identity(row.type_key, row.display): row.id
        for row in current_objects(connection, call.recording_id)
    }
    counts = {"objects": 0, "auto_filled": 0, "asked": 0, "lead_written": 0}
    for draft, plan in zip(drafts, plans, strict=True):
        object_id = uuid4()
        connection.execute(
            insert(CallObject).values(
                id=object_id,
                tenant_id=call.tenant_id,
                recording_id=call.recording_id,
                submission_id=call.submission_id,
                person_id=call.person_id,
                lead_id=call.lead_id,
                run_id=run_id,
                type_key=draft.type_key,
                category=draft.category,
                taxonomy_version=taxonomy.TAXONOMY_VERSION,
                value=draft.value,
                display=draft.display,
                evidence=draft.evidence,
                confidence=Decimal(str(draft.confidence)),
                basis=draft.basis,
                mentions=draft.mentions,
                pipeline=pipeline,
                pipeline_version=pipeline_version,
                transcript_revision=call.transcript_revision,
                retracted=False,
                supersedes_id=previous.pop(_identity(draft.type_key, draft.display), None),
                created_at=now,
            )
        )
        counts["objects"] += 1
        if plan.action == "keep":
            continue
        written = False
        if plan.action == "auto_fill" and plan.lead_field and lead is not None and plan.lead_value:
            written = write_lead(
                connection,
                call.tenant_id,
                lead,
                plan.lead_field,
                plan.lead_value,
                submission_id=call.submission_id,
                actor_person_id=None,
                now=now,
            )
        connection.execute(
            insert(CallObjectDecision).values(
                id=uuid4(),
                tenant_id=call.tenant_id,
                object_id=object_id,
                recording_id=call.recording_id,
                lead_id=call.lead_id,
                decision="auto_filled" if plan.action == "auto_fill" else "asked",
                actor="engine",
                person_id=None,
                question=plan.question,
                lead_field=plan.lead_field,
                lead_written=written,
                created_at=now,
            )
        )
        counts["auto_filled" if plan.action == "auto_fill" else "asked"] += 1
        counts["lead_written"] += int(written)
    return counts


# ----- erasure ---------------------------------------------------------------------


def erase_for_recording(connection: Any, recording_id: UUID, now: datetime) -> int:
    """Empty every object and decision of an erased call (superseded ones included)."""
    objects = connection.execute(
        update(CallObject)
        .where(CallObject.recording_id == recording_id, CallObject.erased_at.is_(None))
        .values(value=None, display=None, evidence=None, erased_at=now)
    ).rowcount
    connection.execute(
        update(CallObjectDecision)
        .where(
            CallObjectDecision.recording_id == recording_id, CallObjectDecision.erased_at.is_(None)
        )
        .values(value=None, display=None, erased_at=now)
    )
    return int(objects or 0)


async def erase_call_data_for_recording(database: Any, recording_id: UUID, now: datetime) -> int:
    """The erasure hook ``ConversationApplication.finish_erasure`` calls (same transaction)."""
    erased: int = await database.run_sync(
        lambda session: erase_for_recording(session.connection(), recording_id, now)
    )
    return erased
