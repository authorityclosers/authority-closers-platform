"""One-pass results people see (analysis pipeline ``one_pass``).

Owner, 21 Oct 2026: "So at least get this on prod now!!!" (one pass on the standard tier,
the real-call trial running beside it as the safety check).

What changes for a call when this environment's analysis pipeline is ``one_pass``:

- today's C2 transcript, C4 facts and C5 report and coaching stay exactly as they are
  (C5 already sends its strict schema to Gemini directly), and so does the fast call
  data pipeline (leads fill in seconds);
- the deep call data read (whole-call facts, then per-segment labels in several more
  requests) and the AI pointer review (another read of the same transcript) become ONE
  strict Gemini 3.8 Flash request on the same saved transcript;
- its call data is saved as the call's deep call data run, through the deep pipeline's
  own merge (``created_by`` ``automatic:one-pass``), with the deep pipeline's audio
  measurements (no model); per-segment labels are not asked for (cost research, 21 Oct:
  the deep pipeline's most expensive part, and a classifier matched them only at the
  majority baseline);
- its pointer review is saved, once the call's report is saved, as the call's pointer
  review (``save_review``: the review's own admission, in the saving transaction),
  parsed again against the report's own transcript and withheld segments, its scores
  calibrated to today's review and labelled beta (``calibration``), as in the plan.

Fallback: whatever one pass does not finish (failed, refused, skipped, nothing valid, or a
review not published within an hour) is left to today's deep pipeline and pointer review.
They wait for one pass (``Handoff``) only while it is working on that call, or for at
most 15 minutes after the transcript while it has not started. Switching the pipeline
back to classic in Admin ends every wait at once.

Spend: each request goes through the AI spend guard as feature ``one_pass``; its rupees
are in ``one_pass_runs`` (the ledger's one-pass lines). The deep run and the review it
saves carry no tokens or rupees, so nothing is counted twice.

Nothing printed contains transcript text, prompts or answers.
"""

from __future__ import annotations

import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text

PUBLISH_VERSION: Final = "one-pass-publish/1"
AUTOMATIC: Final = "automatic:one-pass"
# Today's deep pipeline and pointer review wait this long for one pass to start a call.
HANDOFF_START: Final = timedelta(minutes=15)
# A read's pointer review is published if the call's report is saved within this time.
REVIEW_WINDOW: Final = timedelta(hours=1)


def _models() -> dict[str, Any]:
    from ac_platform.one_pass import settings as choices

    # Publishing reads today's saved transcript: no one-pass transcription.
    return {"transcription": None, "analysis": choices.ANALYSIS_MODEL}


def transcript_of(call: Any) -> dict[str, Any]:
    """The call's saved C2 transcript in the contract's shape (segments only)."""
    return {
        "source_sha256": call.source_sha256,
        "revision": call.transcript_revision,
        "segments": [
            {
                "id": segment.id,
                "speaker_id": segment.speaker,
                "start_ms": segment.start_ms,
                "end_ms": segment.end_ms,
                "text": segment.text,
            }
            for segment in call.segments
        ],
    }


def marked_canaries(connection: Any, recording_ids: Iterable[UUID]) -> set[UUID]:
    """Our release canary's own submissions (not a QA account's upload of the same file):
    one pass reads these, so each release's canary exercises it."""
    ids = list(recording_ids)
    if not ids:
        return set()
    rows = connection.execute(
        text(
            """
            SELECT g.recording_id FROM conversation_canary_submissions k
            JOIN conversation_guest_submissions g
              ON g.tenant_id = k.tenant_id AND g.submission_id = k.submission_id
            WHERE g.recording_id = ANY(:ids)
            """
        ),
        {"ids": ids},
    ).scalars()
    return set(rows)


def candidates(
    connection: Any,
    *,
    not_before: datetime,
    hours: int,
    limit: int,
    recording_id: UUID | None = None,
) -> list[Any]:
    """Calls the fast pipeline has finished whose deep call data is not saved and that one
    pass has not finished (one attempt here: a failure goes to today's pipeline)."""
    from ac_platform.call_data import engine

    calls = engine.candidates(
        connection,
        not_before=not_before,
        hours=hours,
        limit=limit,
        pipeline="deep",
        recording_id=recording_id,
    )
    if not calls:
        return []
    return [
        call
        for call in calls
        if not connection.scalar(
            text(
                """
                SELECT EXISTS (
                  SELECT 1 FROM one_pass_runs r
                  WHERE r.recording_id = :recording AND r.source = 'call'
                    AND r.transcript_revision = :revision AND r.state <> 'running'
                )
                """
            ),
            {"recording": call.recording_id, "revision": call.transcript_revision},
        )
    ]


@dataclass(frozen=True, slots=True)
class Handoff:
    """Today's deep pipeline and pointer review, asking whether to leave a call to one
    pass. Built only while the environment's pipeline is ``one_pass``."""

    def waits(
        self,
        connection: Any,
        recording_id: UUID,
        transcript_revision: str,
        *,
        kind: str,
        now: datetime,
    ) -> bool:
        from ac_platform.one_pass import store

        rows = connection.execute(
            text(
                """
                SELECT r.id, r.state, r.supersedes_id, r.created_at, r.checks
                FROM one_pass_runs r
                WHERE r.recording_id = :recording AND r.source = 'call'
                  AND r.transcript_revision = :revision
                ORDER BY r.created_at
                """
            ),
            {"recording": recording_id, "revision": transcript_revision},
        ).all()
        ended = {row.supersedes_id for row in rows if row.supersedes_id is not None}
        if any(
            row.state == "running"
            and row.id not in ended
            and now - row.created_at < store.IN_FLIGHT
            for row in rows
        ):
            return True
        finished = [row for row in rows if row.state != "running"]
        if not finished:
            # Not started: wait only for a call one pass will take (the fast pipeline has
            # finished its transcript) and only briefly.
            transcript_at = connection.scalar(
                text(
                    """
                    SELECT max(cp.created_at) FROM conversation_checkpoints cp
                    WHERE cp.recording_id = :recording AND cp.stage = 'C2'
                      AND cp.erased_at IS NULL AND cp.payload ->> 'revision' = :revision
                      AND EXISTS (
                        SELECT 1 FROM call_data_runs f
                        WHERE f.recording_id = cp.recording_id AND f.pipeline = 'fast'
                          AND f.transcript_revision = :revision
                          AND f.state IN ('succeeded', 'skipped')
                      )
                    """
                ),
                {"recording": recording_id, "revision": transcript_revision},
            )
            return transcript_at is not None and now - transcript_at < HANDOFF_START
        if kind == "deep":
            # One pass saved the deep run (today's deep pipeline then has nothing to do),
            # or it did not: today's runs.
            return False
        # The newest outcome decides: a read with a valid review waits for the report
        # (up to an hour); a review that could not be published is marked skipped.
        last = finished[-1]
        checks = last.checks if isinstance(last.checks, Mapping) else {}
        return (
            last.state == "succeeded"
            and checks.get("pointer_review") == "ok"
            and now - last.created_at < REVIEW_WINDOW
        )


def handoff(connection: Any, environment: str | None) -> Handoff | None:
    """The handoff when this environment publishes one-pass results, else None."""
    if environment is None:
        return None
    from ac_platform.one_pass import settings as choices

    config, _ = choices.read(connection, environment)
    return Handoff() if config["mode"] == "one_pass" else None


def process_call(
    sessions: Any,
    call: Any,
    *,
    settings: dict[str, Any],
    apply: bool,
    trigger: str,
    created_by: str,
    transport: Any,
    test_sources: set[str],
    canaries: set[UUID],
    storage_root: Path | None,
    clock: Any = time.monotonic,
) -> dict[str, Any]:
    """Admit, read and save one call's deep call data; the review waits for the report.
    Returns a content-free log line."""
    from ac_platform.call_data import engine
    from ac_platform.call_data.deep_runner import _frames, measured
    from ac_platform.one_pass import analysis, store
    from ac_platform.one_pass.gemini import OnePassFailure
    from ac_platform.one_pass.runner import LASTING_REFUSALS, analyse

    models = _models()
    line: dict[str, Any] = {"recording": str(call.recording_id), "pipeline": "one_pass"}
    with sessions() as session, session.begin():
        connection = session.connection()
        engine.load(connection, call)
        subject = store.Subject.of(call)
        now = datetime.now(UTC)
        refusal = engine.admission_refusal(connection, call, now) or store.attempt_refusal(
            connection, call, now
        )
        segments = [s for s in call.segments if s.id not in call.withheld]
        skip = None
        if refusal is None:
            if call.source_sha256 in test_sources and call.recording_id not in canaries:
                skip = "test_call"
            elif (call.duration_ms or 0) / 60000 > settings["max_call_minutes"]:
                skip = "call_too_long"
            elif sum(len(s.text) for s in segments) < 40:
                skip = "no_conversation"
        if refusal or skip:
            reason = str(refusal or skip)
            if apply and (skip or refusal in LASTING_REFUSALS):
                # Recorded once: today's deep pipeline and pointer review take the call.
                store.skip_run(
                    connection,
                    subject,
                    reason=reason,
                    trigger=trigger,
                    mode="one_pass",
                    created_by=created_by,
                    now=now,
                )
            line["skipped"] = reason
            return line
        line["segments"] = len(segments)
        if not apply:
            line["dry_run"] = True
            return line
        inputs = engine.audio_inputs(connection, call)
        started = store.start_run(
            connection,
            subject,
            trigger=trigger,
            mode="one_pass",
            settings={"analysis_tier": settings["analysis_tier"]},
            models=models,
            created_by=created_by,
            now=now,
        )
    # The start is committed: from here on this attempt counts as paid.
    began = clock()
    outcome = store.Outcome()
    outcome.audio_ms = call.duration_ms
    usage: dict[str, Any] = {}
    outcome.usage = usage
    transcript = transcript_of(call)
    published = None
    try:
        answers = analyse(
            transport,
            analysis.requests(
                transcript, call_date=call.call_date(), withheld=call.withheld, publish=True
            ),
            tier=settings["analysis_tier"],
            outcome=outcome,
            usage=usage,
        )
        published = analysis.map_publish(answers["facts"], transcript, withheld=call.withheld)
        outcome.outputs = published.outputs
        outcome.checks = dict(published.checks)
        outcome.state, outcome.reason = "succeeded", None
    except OnePassFailure as failure:
        outcome.state, outcome.reason = "failed", failure.outcome
    frames = _frames(call, inputs, storage_root) if published is not None else None
    outcome.duration_ms = round((clock() - began) * 1000)
    with sessions() as session, session.begin():
        connection = session.connection()
        now = datetime.now(UTC)
        refusal = engine.admission_refusal(connection, call, now)
        if refusal and outcome.state == "succeeded":
            # Erased, revoked or replaced meanwhile: keep the numbers, never the content.
            outcome.state, outcome.reason = "skipped", f"refused_{refusal}"
            outcome.outputs = None
        elif published is not None and outcome.checks is not None:
            if published.drafts:
                outcome.checks["deep_run"] = "saved"
                line.update(
                    _save_deep(
                        connection,
                        call,
                        published,
                        voice=measured(call, published.roles, inputs, frames),
                        audio="frames" if frames is not None else "timings",
                        one_pass_run=started,
                        trigger=trigger,
                        now=now,
                    )
                )
            else:
                outcome.checks["deep_run"] = "none_valid"
        store.finish_run(
            connection,
            subject,
            started,
            outcome,
            trigger=trigger,
            mode="one_pass",
            models=models,
            created_by=created_by,
            now=now,
        )
    line["outcome"] = (
        outcome.state if outcome.reason is None else f"{outcome.state}:{outcome.reason}"
    )
    if outcome.checks:
        line["contracts_ok"] = sum(1 for value in outcome.checks.values() if value == "ok")
    if outcome.cost_inr is not None:
        line["inr"] = float(outcome.cost_inr)
    line["ms"] = outcome.duration_ms
    return line


def _save_deep(
    connection: Any,
    call: Any,
    published: Any,
    *,
    voice: list[Any],
    audio: str,
    one_pass_run: UUID,
    trigger: str,
    now: datetime,
    created_by: str = AUTOMATIC,
) -> dict[str, Any]:
    """The call's deep call data run and objects, through the deep pipeline's own merge.
    No tokens or rupees here: the read is counted once (one_pass_runs, or the plan's C4)."""
    from ac_platform.call_data import deep, engine
    from ac_platform.one_pass import settings as choices

    lead = engine.lead_state(connection, call.tenant_id, call.lead_id) if call.lead_id else None
    merge = deep.plan_merge(
        [*published.drafts, *voice],
        deep.load_current(connection, call.recording_id),
        lead=lead.columns if lead else None,
        auto_filled=lead.auto_filled if lead else {},
        rejected=lead.rejected if lead else frozenset(),
    )
    started = engine.start_run(
        connection,
        call,
        pipeline="deep",
        model=choices.ANALYSIS_MODEL,
        trigger="auto" if trigger == "auto" else "operator",
        prompt_sha256=None,
        created_by=created_by,
        now=now,
        version=deep.DEEP_VERSION,
    )
    finished = engine.finish_run(
        connection,
        call,
        started,
        state="succeeded",
        reason=None,
        pipeline="deep",
        model=choices.ANALYSIS_MODEL,
        trigger="auto" if trigger == "auto" else "operator",
        usage=None,
        cost_inr=Decimal(0),
        duration_ms=None,
        counts={
            "roles": published.roles,
            "dropped": published.dropped,
            "facts": len(published.drafts),
            "segments_labelled": 0,
            "audio": audio,
            "one_pass_run": str(one_pass_run),
        },
        created_by=created_by,
        now=now,
        version=deep.DEEP_VERSION,
    )
    counts: dict[str, Any] = deep.save(connection, call, finished, merge, lead=lead, now=now)
    return counts


_PENDING_REVIEWS: Final = """
SELECT r.id AS one_pass_run, r.tenant_id, r.recording_id, r.source_sha256,
       r.transcript_revision, r.outputs -> 'review_raw' AS review_raw,
       r.usage -> 'analysis' -> 'requests' -> 'facts' ->> 'prompt_sha256' AS prompt_sha256,
       d.id AS draft_id, d.run_id
FROM one_pass_runs r
JOIN LATERAL (
    SELECT n.* FROM conversation_report_drafts n
    WHERE n.recording_id = r.recording_id AND n.erased_at IS NULL
    ORDER BY n.created_at DESC LIMIT 1
) d ON TRUE
WHERE r.source = 'call' AND r.mode = 'one_pass' AND r.state = 'succeeded'
  AND r.erased_at IS NULL AND r.created_at > :since
  AND r.outputs -> 'review_raw' IS NOT NULL
  AND d.source_sha256 = r.source_sha256
  AND d.payload ->> 'transcript_revision' = r.transcript_revision
  AND NOT EXISTS (
    SELECT 1 FROM one_pass_runs x
    WHERE x.recording_id = r.recording_id AND x.transcript_revision = r.transcript_revision
      AND x.state <> 'running' AND x.created_at > r.created_at
  )
  AND NOT EXISTS (
    SELECT 1 FROM conversation_pointer_reviews p
    WHERE p.run_id = d.run_id AND p.source_sha256 = d.source_sha256
      AND p.transcript_revision = r.transcript_revision
  )
ORDER BY r.created_at
LIMIT :limit
"""


def publish_reviews(
    sessions: Any, *, apply: bool, now: datetime | None = None, limit: int = 10
) -> list[dict[str, Any]]:
    """Each succeeded read whose call now has its report: its pointer review, parsed
    against that report's own transcript and withheld segments, calibrated and labelled
    beta, saved through the review's own admission. A review that no longer parses is
    left to today's review."""
    from ac_platform.conversation_intelligence import pointer_review
    from ac_platform.conversation_intelligence.pointer_review_cli import _segments, _withheld
    from ac_platform.one_pass import calibration, store

    now = now or datetime.now(UTC)
    lines: list[dict[str, Any]] = []
    with sessions() as session:
        rows = list(
            session.connection()
            .execute(text(_PENDING_REVIEWS), {"since": now - REVIEW_WINDOW, "limit": limit})
            .mappings()
        )
    for row in rows:
        line: dict[str, Any] = {"recording": str(row["recording_id"]), "review": "one_pass"}
        report = {
            "tenant_id": row["tenant_id"],
            "recording_id": row["recording_id"],
            "draft_id": row["draft_id"],
            "run_id": row["run_id"],
            "source_sha256": row["source_sha256"],
            "transcript_revision": row["transcript_revision"],
        }
        if not apply:
            line["dry_run"] = True
            lines.append(line)
            continue
        with sessions() as session, session.begin():
            connection = session.connection()
            # The pointer review's own per-call lock: one saver at a time.
            connection.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"ac.pointer_review:{row['recording_id']}"},
            )
            withheld = _withheld(connection, row["recording_id"], row["transcript_revision"])
            segments = [
                s
                for s in _segments(connection, row["draft_id"])
                if str(s.get("id")) not in withheld
            ]
            saved = None
            try:
                review = pointer_review.parse_review(dict(row["review_raw"] or {}), segments)
            except pointer_review.PointerReviewError as error:
                line["outcome"] = f"not_published:{str(error)[:48]}"
            else:
                # One pass reads 4-5 points kinder than today's review: calibrated, and
                # shown as a beta (one_pass.calibration; owner, 21 Oct 2026).
                review = calibration.calibrate(review)
                saved = pointer_review.save_review(
                    connection,
                    report=report,
                    review=review,
                    prompt_digest=str(row["prompt_sha256"] or ""),
                    usage={},  # counted once, in one_pass_runs
                    created_by=AUTOMATIC,
                    now=datetime.now(UTC),
                )
                line["outcome"] = "published" if saved is not None else "refused"
            if saved is None:
                # Marked, so today's pointer review takes the call at once.
                store.skip_run(
                    connection,
                    store.Subject(
                        "call",
                        tenant_id=row["tenant_id"],
                        recording_id=row["recording_id"],
                        transcript_revision=row["transcript_revision"],
                        source_sha256=row["source_sha256"],
                    ),
                    reason="review_not_published",
                    trigger="auto",
                    mode="one_pass",
                    created_by=AUTOMATIC,
                    now=datetime.now(UTC),
                )
        lines.append(line)
    return lines


def run_pass(
    sessions: Any,
    arguments: Any,
    transport: Any,
    *,
    settings: dict[str, Any],
    created_by: str,
    environment: str,
    storage_root: Path | None,
    guard: bool = True,
) -> list[dict[str, Any]]:
    """One publishing pass: new calls read (each behind the AI spend guard), then every
    read whose report is now saved gets its pointer review."""
    from ac_platform.ai_spend import guard as spend_guard
    from ac_platform.call_data import engine
    from ac_platform.one_pass import store
    from ac_platform.one_pass.runner import FEATURE

    trigger = "operator" if arguments.recording else "auto"
    hours = (
        min(arguments.recent_hours, store.AUTO_FRESH_HOURS)
        if trigger == "auto"
        else arguments.recent_hours
    )
    lines: list[dict[str, Any]] = []
    with sessions() as session:
        connection = session.connection()
        calls = candidates(
            connection,
            not_before=arguments.not_before,
            hours=hours,
            limit=arguments.limit,
            recording_id=arguments.recording,
        )
        test_sources = engine.test_source_shas(connection) if calls else set()
        canaries = marked_canaries(connection, [call.recording_id for call in calls])
        if calls and guard:
            if trigger == "auto":
                skipped = spend_guard.skipped_tenants(connection, environment)
                calls = [call for call in calls if call.tenant_id not in skipped]
            refusal = spend_guard.check(
                connection, FEATURE, environment=environment, trigger=trigger
            )
            if refusal is not None:
                lines.append(refusal.line())
                calls = []
    for call in calls:
        lines.append(
            process_call(
                sessions,
                call,
                settings=settings,
                apply=arguments.apply,
                trigger=trigger,
                created_by=created_by,
                transport=transport,
                test_sources=test_sources,
                canaries=canaries,
                storage_root=storage_root,
            )
        )
        if guard:
            with sessions() as session:
                refusal = spend_guard.check(
                    session.connection(), FEATURE, environment=environment, trigger=trigger
                )
            if refusal is not None:
                lines.append(refusal.line())
                break
    lines.extend(publish_reviews(sessions, apply=arguments.apply))
    return lines
