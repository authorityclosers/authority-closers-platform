"""One deep-pipeline read of one call (v0.64): whole-call facts, segment labels, audio.

Same admission and paid-attempt rules as the fast pipeline: admitted before the
first model call and again in the saving transaction; a committed 'running' row
counts as paid. Content-free log lines only.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ac_platform.call_data import audio, classifier, deep, engine, extraction, taxonomy
from ac_platform.call_data.provider import ProviderFailure
from ac_platform.call_data.settings import cost_inr
from ac_platform.call_data.values import CallValueError, display, validate_value


def _digest(*parts: str) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()


def _frames(call: engine.Call, inputs: engine.AudioInputs, storage_root: Path | None) -> Any:
    """The audio check's 10 ms frames for this call, or None when they can't be read."""
    if storage_root is None or inputs.blob_id is None or inputs.feature_sha256 is None:
        return None
    from ac_platform.conversation_intelligence.storage import (
        ObjectKey,
        ObjectKind,
        PrivateLocalRecordingStorage,
    )

    try:
        storage = PrivateLocalRecordingStorage(storage_root)
        key = ObjectKey(
            call.tenant_id, call.recording_id, inputs.blob_id, ObjectKind.SIGNAL_FEATURES
        )
        blob = b"".join(storage.iter_bytes(key, expected_sha256=inputs.feature_sha256))
        _rate, rows = audio.frames(blob)
        return list(rows)
    except Exception:  # noqa: BLE001 - audio is best effort; timings still measure the call
        return None


def measured(
    call: engine.Call, roles: dict[str, str], inputs: engine.AudioInputs, frames: Any
) -> list[Any]:
    segments = [s for s in call.segments if s.id not in call.withheld]
    value = audio.features(
        segments,
        roles=roles,
        duration_ms=call.duration_ms or (max((s.end_ms for s in segments), default=0)),
        display_dbfs=inputs.display_dbfs,
        frame_rows=frames,
    )
    drafts = []
    audio_type = taxonomy.TYPES["audio.features"]
    try:
        checked = validate_value(audio_type, value)
        drafts.append(deep.measured_draft(audio_type.key, checked, display(audio_type, checked)))
    except CallValueError:
        pass
    ratio = audio.talk_ratio(value)
    ratio_type = taxonomy.TYPES["conversation.talk_ratio"]
    if ratio is not None:
        try:
            checked = validate_value(ratio_type, ratio)
            drafts.append(
                deep.measured_draft(ratio_type.key, checked, display(ratio_type, checked))
            )
        except CallValueError:
            pass
    return drafts


def process_deep_call(
    sessions: Any,
    call: engine.Call,
    *,
    settings: dict[str, Any],
    apply: bool,
    trigger: str,
    created_by: str,
    model_client: Any,
    test_sources: set[str],
    storage_root: Path | None,
) -> dict[str, Any]:
    config = settings["deep"]
    model = str(config["model"])
    line: dict[str, Any] = {"recording": str(call.recording_id), "pipeline": "deep"}
    with sessions() as session, session.begin():
        connection = session.connection()
        engine.load(connection, call)
        now = datetime.now(UTC)
        refusal = engine.admission_refusal(connection, call, now) or engine.attempt_refusal(
            connection, call, "deep", now
        )
        segments = [s for s in call.segments if s.id not in call.withheld]
        reason = refusal
        if reason is None and call.source_sha256 in test_sources:
            reason = "test_call"
        elif reason is None and (call.duration_ms or 0) / 60000 > config["max_call_minutes"]:
            reason = "call_too_long"
        elif reason is None and sum(len(s.text) for s in segments) < 40:
            reason = "no_conversation"
        if reason:
            if apply and reason not in (
                "in_flight",
                "call_missing",
                "call_erased",
                "call_not_ready",
            ):
                engine.skip_run(
                    connection,
                    call,
                    reason=reason,
                    pipeline="deep",
                    trigger=trigger,
                    created_by=created_by,
                    now=now,
                    version=deep.DEEP_VERSION,
                )
            line["skipped"] = reason
            return line
        system, user = extraction.build_prompt(
            segments, types=taxonomy.DEEP_EXTRACT_TYPES, call_date=call.call_date()
        )
        line["segments"] = len(segments)
        if not apply:
            line["dry_run"] = True
            line["chunks"] = len(classifier.chunks(segments))
            return line
        inputs = engine.audio_inputs(connection, call)
        started = engine.start_run(
            connection,
            call,
            pipeline="deep",
            model=model,
            trigger=trigger,
            prompt_sha256=_digest(model, system, user),
            created_by=created_by,
            now=now,
            version=deep.DEEP_VERSION,
        )
    clock = time.monotonic()
    usage = {"promptTokenCount": 0, "candidatesTokenCount": 0}
    outcome: str = "failed"
    why: str | None = "runner_error"
    counts: dict[str, Any] = {}

    def spend(answer: Any) -> None:
        for key in usage:
            usage[key] += int(answer.usage.get(key) or 0)

    try:
        answer = model_client.generate_json(
            model=model,
            system=system,
            user=user,
            schema=extraction.response_schema(taxonomy.DEEP_EXTRACT_TYPES),
        )
        spend(answer)
        facts, dropped = extraction.validate_response(
            answer.value, segments, types=taxonomy.DEEP_EXTRACT_TYPES, withheld=call.withheld
        )
        roles = extraction.parse_roles(answer.value, segments)
        labels = []
        for start, end in classifier.chunks(segments):
            chunk_system, chunk_user = classifier.build_prompt(segments, start, end, roles=roles)
            labelled = model_client.generate_json(
                model=model,
                system=chunk_system,
                user=chunk_user,
                schema=classifier.response_schema(),
            )
            spend(labelled)
            drafts, label_dropped = classifier.validate_labels(
                labelled.value, segments, start, end, withheld=call.withheld
            )
            labels.extend(drafts)
            for code, n in label_dropped.items():
                dropped[f"label_{code}"] = dropped.get(f"label_{code}", 0) + n
        frames = _frames(call, inputs, storage_root)
        voice = measured(call, roles, inputs, frames)
        with sessions() as session, session.begin():
            connection = session.connection()
            now = datetime.now(UTC)
            refusal = engine.admission_refusal(connection, call, now)
            if refusal:
                outcome, why = "skipped", f"refused_{refusal}"
            else:
                lead = (
                    engine.lead_state(connection, call.tenant_id, call.lead_id)
                    if call.lead_id
                    else None
                )
                merge = deep.plan_merge(
                    [*facts, *labels, *voice],
                    deep.load_current(connection, call.recording_id),
                    lead=lead.columns if lead else None,
                    auto_filled=lead.auto_filled if lead else {},
                    rejected=lead.rejected if lead else frozenset(),
                )
                finished = engine.finish_run(
                    connection,
                    call,
                    started,
                    state="succeeded",
                    reason=None,
                    pipeline="deep",
                    model=model,
                    trigger=trigger,
                    usage=usage,
                    cost_inr=cost_inr(
                        model, usage["promptTokenCount"], usage["candidatesTokenCount"]
                    ),
                    duration_ms=round((time.monotonic() - clock) * 1000),
                    counts={
                        "roles": roles,
                        "dropped": dropped,
                        "facts": len(facts),
                        "segments_labelled": len(labels),
                        "audio": "frames" if frames is not None else "timings",
                    },
                    created_by=created_by,
                    now=now,
                    version=deep.DEEP_VERSION,
                )
                counts = deep.save(connection, call, finished, merge, lead=lead, now=now)
                outcome, why = "succeeded", None
    except ProviderFailure as failure:
        outcome, why = "failed", failure.outcome
        if failure.usage:
            for key in usage:
                usage[key] += int(failure.usage.get(key) or 0)
    finally:
        if outcome != "succeeded":
            with sessions() as session, session.begin():
                engine.finish_run(
                    session.connection(),
                    call,
                    started,
                    state=outcome,
                    reason=why,
                    pipeline="deep",
                    model=model,
                    trigger=trigger,
                    usage=usage,
                    cost_inr=cost_inr(
                        model, usage["promptTokenCount"], usage["candidatesTokenCount"]
                    ),
                    duration_ms=round((time.monotonic() - clock) * 1000),
                    counts=None,
                    created_by=created_by,
                    now=datetime.now(UTC),
                    version=deep.DEEP_VERSION,
                )
    line["outcome"] = outcome if why is None else f"{outcome}:{why}"
    line.update(counts)
    line["tokens"] = [usage["promptTokenCount"], usage["candidatesTokenCount"]]
    line["ms"] = round((time.monotonic() - clock) * 1000)
    return line
