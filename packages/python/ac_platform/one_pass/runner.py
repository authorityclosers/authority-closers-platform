"""The one-pass runner: beside today's pipeline, the same call read the Google-only way.

When this environment's analysis pipeline is ``both`` (Admin → Providers), every new
call that today's pipeline transcribed is also read by the one-pass pipeline:

1. its stored audio, as mono 32 kbps MP3, is transcribed by Gemini 3.1 Flash-Lite into
   the C2 transcript contract (standard or Flex, as set);
2. that transcript is read once by Gemini 3.8 Flash, writing C4 facts, the C5 report
   and coaching, the pointer review, call objects and prospect facts in one answer,
   each checked by its own stage's validator;
3. both results stay side by side (``one_pass_runs`` next to today's tables); people
   keep seeing today's. Admin → Providers → One-pass compare shows the difference.

Like the call data engine: one runner per database (advisory lock); automatic passes
read only transcripts saved in the last two hours and never backfill; each call is
admitted (consent, retention, erasure, newest transcript) before and again after the
provider calls; a 'running' row is committed first, so a crash still counts as a paid
attempt; at most two attempts per transcript. Before every call the AI spend guard is
asked (feature ``one_pass``: its cap starts at ₹0, raising it in Admin → AI spend is the
recorded approval; development's background AI must be switched on).

    python -m ac_platform.one_pass.runner \\
        --service-config /etc/authority-closers/development/service-live.json \\
        --database-url-file /etc/authority-closers/development/database-url-live \\
        --not-before 2026-10-21T00:00:00+00:00 --loop --apply

``--bench DIR`` reads the research's fictional benchmark calls instead (never a real
call): their MP3s go through Google AI Studio by OpenRouter with the research's key,
results are stored as benchmark rows beside the research's classic results. Run it
inside ``ac-infisical-run`` with the bench folder (/sales-xray-bench).

Nothing printed contains transcript text, audio, prompts or answers.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final
from uuid import UUID

INNER: Final = "--inner"
AUTOMATIC: Final = "automatic:one-pass"
OPERATOR: Final = "operator:one-pass"
BENCH: Final = "operator:one-pass-bench"
RUN_LOCK: Final = "ac.one_pass"
FEATURE: Final = "one_pass"
_PROVIDER: Final = "gemini"
LASTING_REFUSALS: Final = frozenset(
    {"permission_inactive", "account_inactive", "attempts_exhausted"}
)


def _arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="one_pass.runner")
    parser.add_argument("--service-config", type=Path)
    parser.add_argument("--database-url-file", required=True, type=Path)
    parser.add_argument("--not-before", type=datetime.fromisoformat)
    parser.add_argument("--recent-hours", type=int, default=2)
    parser.add_argument("--recording", type=UUID, help="operator mode: this one call")
    parser.add_argument("--force", action="store_true", help="operator: read this call again")
    parser.add_argument("--limit", type=int, default=3, help="calls per pass")
    parser.add_argument("--loop", action="store_true", help="keep polling")
    parser.add_argument("--interval", type=float, default=10.0, help="seconds between passes")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--token-file", type=Path)
    parser.add_argument("--infisical", type=Path)
    parser.add_argument("--bench", type=Path, help="the research folder (fictional calls only)")
    parser.add_argument("--calls", default="", help="benchmark call ids, comma separated")
    parser.add_argument(
        "--classic-only", action="store_true", help="bench: import the classic side only"
    )
    parser.add_argument(
        "--classic-again",
        action="store_true",
        help="bench: import the classic side again (a newer row; the newest is compared)",
    )
    parser.add_argument(INNER, action="store_true", help=argparse.SUPPRESS)
    arguments = parser.parse_args(argv)
    if arguments.bench is None:
        if arguments.service_config is None or arguments.not_before is None:
            parser.error("--service-config and --not-before are needed for real calls")
        if arguments.not_before.tzinfo is None:
            parser.error("--not-before needs a time zone, e.g. 2026-10-21T00:00:00+00:00")
    elif arguments.loop or arguments.recording:
        parser.error("--bench runs the fictional set once; no --loop or --recording")
    if not 1 <= arguments.limit <= 20:
        parser.error("--limit must be 1-20")
    if not 1 <= arguments.recent_hours <= 720:
        parser.error("--recent-hours must be 1-720")
    if not 1.0 <= arguments.interval <= 300.0:
        parser.error("--interval must be 1-300 seconds")
    if arguments.force and (arguments.loop or not arguments.recording):
        parser.error("--force is for one call (--recording), never the loop")
    return arguments


def _provider_config(config: Path) -> dict[str, Any]:
    service = json.loads(config.read_text())
    for provider in service.get("providers") or []:
        if provider.get("provider_id") == _PROVIDER:
            return dict(provider)
    raise SystemExit("one_pass_provider_missing")


def _reexec_inside_infisical(argv: list[str], arguments: argparse.Namespace) -> None:
    """The same launch as the call data engine: the key exists only in the child."""
    provider = _provider_config(arguments.service_config)
    token_file = arguments.token_file or Path(provider["token_file_ref"])
    token = token_file.read_text().strip()
    if token.startswith("INFISICAL_TOKEN="):
        token = token[len("INFISICAL_TOKEN=") :]
    environment = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "HOME", "LANG", "PYTHONPATH", "PYTHONUNBUFFERED"}
    }
    environment["INFISICAL_TOKEN"] = token
    command = [
        str(arguments.infisical or provider["executable"]),
        "run",
        "--include-imports=false",
        "--expand=false",
        "--silent",
        "--telemetry=false",
        "--log-level=error",
        "--projectId",
        str(provider["project_ref"]),
        "--env",
        str(provider["environment_ref"]),
        "--path",
        str(provider["secret_path_ref"]),
        "--",
        sys.executable,
        "-m",
        "ac_platform.one_pass.runner",
        *argv,
        INNER,
    ]
    os.execvpe(command[0], command, environment)  # noqa: S606 - fixed argv, no shell


def read_call(
    transport: Any,
    *,
    audio: bytes,
    mime: str,
    source_sha256: str,
    duration_ms: int | None,
    call_date: str,
    settings: dict[str, Any],
    outcome: Any,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    """Both stages for one call, filling ``outcome`` as they go (so a failure keeps what
    was measured and spent). Raises ``OnePassFailure`` with a fixed code."""
    from ac_platform.one_pass import analysis, pricing, transcription
    from ac_platform.one_pass import settings as choices

    started = clock()
    outcome.audio_ms = duration_ms
    tier = settings["transcription_tier"]
    heard = transport.generate(
        model=choices.TRANSCRIPTION_MODEL,
        request=transcription.request(audio, mime, duration_ms),
        tier=tier,
    )
    paid_tier = "standard" if heard.tier_used != "flex" else "flex"
    outcome.transcription_tier = heard.tier_used
    outcome.transcription_input_tokens = heard.usage.prompt
    outcome.transcription_output_tokens = heard.usage.billed_output
    outcome.transcription_cost_inr = pricing.cost_inr(
        choices.TRANSCRIPTION_MODEL, heard.usage, tier=paid_tier
    )
    outcome.transcription_ms = heard.ms
    usage: dict[str, Any] = {
        "transcription": {
            **heard.usage.as_dict(),
            "tier": heard.tier_used,
            "attempts": heard.attempts,
            "transport": transport.name,
            "standard_inr": float(
                pricing.cost_inr(choices.TRANSCRIPTION_MODEL, heard.usage, tier="standard")
            ),
            "flex_inr": float(
                pricing.cost_inr(choices.TRANSCRIPTION_MODEL, heard.usage, tier="flex")
            ),
        }
    }
    outcome.usage = usage
    transcript, dropped = transcription.to_transcript(
        heard.data,
        source_sha256=source_sha256,
        duration_ms=duration_ms,
        response_sha256=heard.response_sha256,
        model=choices.TRANSCRIPTION_MODEL,
    )
    outcome.transcript = transcript
    if outcome.audio_ms is None:
        outcome.audio_ms = int(transcript["duration_ms"])
    usage["transcription"]["segments"] = len(transcript["segments"])
    usage["transcription"]["dropped"] = dropped
    tier = settings["analysis_tier"]
    request = analysis.request(transcript, call_date=call_date)
    answered = transport.generate(model=choices.ANALYSIS_MODEL, request=request, tier=tier)
    paid_tier = "standard" if answered.tier_used != "flex" else "flex"
    outcome.analysis_tier = answered.tier_used
    outcome.analysis_input_tokens = answered.usage.prompt
    outcome.analysis_output_tokens = answered.usage.billed_output
    outcome.analysis_cached_tokens = answered.usage.cached
    outcome.analysis_cost_inr = pricing.cost_inr(
        choices.ANALYSIS_MODEL, answered.usage, tier=paid_tier
    )
    outcome.analysis_ms = answered.ms
    usage["analysis"] = {
        **answered.usage.as_dict(),
        "tier": answered.tier_used,
        "attempts": answered.attempts,
        "schema_mode": answered.schema_mode,
        "transport": transport.name,
        "prompt_sha256": analysis.prompt_sha256(choices.ANALYSIS_MODEL, request),
        "standard_inr": float(
            pricing.cost_inr(choices.ANALYSIS_MODEL, answered.usage, tier="standard")
        ),
        "flex_inr": float(pricing.cost_inr(choices.ANALYSIS_MODEL, answered.usage, tier="flex")),
    }
    outputs, checks = analysis.map_outputs(answered.data, transcript)
    outcome.outputs = outputs
    outcome.checks = checks
    outcome.duration_ms = round((clock() - started) * 1000)
    outcome.state, outcome.reason = "succeeded", None


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
    storage_root: Path | None,
    audio_reader: Callable[[Any, Any], tuple[bytes, str]] | None = None,
) -> dict[str, Any]:
    """Admit, read and save one real call. Returns a content-free log line."""
    from ac_platform.call_data import engine
    from ac_platform.conversation_intelligence.storage import StorageError
    from ac_platform.one_pass import settings as choices
    from ac_platform.one_pass import store
    from ac_platform.one_pass.gemini import OnePassFailure

    models = {"transcription": choices.TRANSCRIPTION_MODEL, "analysis": choices.ANALYSIS_MODEL}
    mode = settings["mode"]
    line: dict[str, Any] = {"recording": str(call.recording_id)}
    with sessions() as session, session.begin():
        connection = session.connection()
        engine.load(connection, call)
        subject = store.Subject.of(call)
        now = datetime.now(UTC)
        refusal = engine.admission_refusal(connection, call, now) or store.attempt_refusal(
            connection, call, now
        )
        skip = None
        if refusal is None:
            minutes = (call.duration_ms or 0) / 60000
            if call.source_sha256 in test_sources:
                skip = "test_call"
            elif minutes > settings["max_call_minutes"]:
                skip = "call_too_long"
            elif sum(len(s.text) for s in call.segments) < 40:
                skip = "no_conversation"
            elif call.withheld:
                # Marks name today's segments; they can't be carried to a new transcript.
                skip = "sensitive_segments_marked"
            elif not call.source_sha256:
                skip = "source_unknown"
        key = None
        if refusal is None and skip is None and audio_reader is None:
            try:
                key = store.source_key(connection, call)
            except StorageError:
                skip = "audio_missing"
        if refusal or skip:
            reason = str(refusal or skip)
            if apply and (skip or refusal in LASTING_REFUSALS):
                store.skip_run(
                    connection,
                    subject,
                    reason=reason,
                    trigger=trigger,
                    mode=mode,
                    created_by=created_by,
                    now=now,
                )
            line["skipped"] = reason
            return line
        if not apply:
            line["dry_run"] = True
            return line
        started = store.start_run(
            connection,
            subject,
            trigger=trigger,
            mode=mode,
            settings=settings,
            models=models,
            created_by=created_by,
            now=now,
        )
    # The start is committed: from here on this attempt counts as paid.
    outcome = store.Outcome()
    try:
        if audio_reader is not None:
            audio, mime = audio_reader(call, storage_root)
        else:
            if storage_root is None:
                raise OnePassFailure("storage_root_missing")
            try:
                source = store.read_audio(storage_root, key, str(call.source_sha256))
                audio, mime = store.to_mp3(source), "audio/mpeg"
            except (StorageError, ValueError):
                raise OnePassFailure("audio_unreadable") from None
        read_call(
            transport,
            audio=audio,
            mime=mime,
            source_sha256=str(call.source_sha256),
            duration_ms=call.duration_ms,
            call_date=call.call_date(),
            settings=settings,
            outcome=outcome,
        )
    except OnePassFailure as failure:
        outcome.state, outcome.reason = "failed", failure.outcome
    with sessions() as session, session.begin():
        connection = session.connection()
        now = datetime.now(UTC)
        refusal = engine.admission_refusal(connection, call, now)
        if refusal and outcome.state == "succeeded":
            # Erased, revoked or replaced meanwhile: keep the numbers, never the content.
            outcome.state, outcome.reason = "skipped", f"refused_{refusal}"
            outcome.transcript = outcome.outputs = None
        store.finish_run(
            connection,
            subject,
            started,
            outcome,
            trigger=trigger,
            mode=mode,
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


def run_pass(
    sessions: Any,
    arguments: argparse.Namespace,
    transport: Any,
    *,
    created_by: str,
    environment: str,
    storage_root: Path | None = None,
    guard: bool = True,
    audio_reader: Callable[[Any, Any], tuple[bytes, str]] | None = None,
) -> list[dict[str, Any]]:
    """One pass over new calls; stops at the mode switch and the AI spend guard."""
    from ac_platform.ai_spend import guard as spend_guard
    from ac_platform.call_data import engine
    from ac_platform.one_pass import settings as choices
    from ac_platform.one_pass import store

    trigger = "operator" if arguments.recording else "auto"
    hours = (
        min(arguments.recent_hours, store.AUTO_FRESH_HOURS)
        if trigger == "auto"
        else (arguments.recent_hours)
    )
    with sessions() as session:
        connection = session.connection()
        settings, _ = choices.read(connection, environment)
        if settings["mode"] == "classic":
            return [{"stopped": "pipeline_classic"}]
        calls = store.candidates(
            connection,
            not_before=arguments.not_before,
            hours=hours,
            limit=arguments.limit,
            recording_id=arguments.recording,
            include_done=bool(arguments.force),
        )
        test_sources = engine.test_source_shas(connection) if calls else set()
        if calls and guard:
            skipped = spend_guard.skipped_tenants(connection, environment)
            calls = [call for call in calls if call.tenant_id not in skipped]
            refusal = spend_guard.check(
                connection, FEATURE, environment=environment, trigger=trigger
            )
            if refusal is not None:
                return [refusal.line()]
    lines: list[dict[str, Any]] = []
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
                storage_root=storage_root,
                audio_reader=audio_reader,
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
    return lines


def _database(arguments: argparse.Namespace) -> tuple[Any, Any]:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    url = arguments.database_url_file.read_text().strip()
    database = create_engine(url.replace("+asyncpg", "+psycopg"), pool_pre_ping=True)
    return database, sessionmaker(database, expire_on_commit=False)


def _inner(arguments: argparse.Namespace, transport: Any = None) -> int:
    from sqlalchemy import text

    from ac_platform.ai_spend import guard as spend_guard
    from ac_platform.ai_spend.policy import SettingsError
    from ac_platform.one_pass.gemini import GoogleGemini

    client = transport or GoogleGemini()
    if arguments.apply and transport is None and not client.ready:
        raise SystemExit("one_pass_credential_missing")
    service = json.loads(arguments.service_config.read_text())
    root = service.get("sales_xray_storage_root")
    storage_root = Path(root) if isinstance(root, str) and root else None
    try:
        environment = spend_guard.service_environment(service)
    except SettingsError:
        raise SystemExit("one_pass_environment_missing") from None
    created_by = OPERATOR if arguments.recording else AUTOMATIC
    database, sessions = _database(arguments)
    try:
        with database.connect() as lock:
            if arguments.apply:
                held = lock.scalar(
                    text("SELECT pg_try_advisory_lock(hashtextextended(:key, 0))"),
                    {"key": RUN_LOCK},
                )
                lock.commit()
                if not held:
                    print(json.dumps({"stopped": "another_runner"}), flush=True)
                    return 0
            print(json.dumps({"started": created_by, "apply": arguments.apply}), flush=True)
            said: set[str] = set()
            while True:
                stops: set[str] = set()
                for line in run_pass(
                    sessions,
                    arguments,
                    client,
                    created_by=created_by,
                    environment=environment,
                    storage_root=storage_root,
                ):
                    stop = line.get("stopped")
                    if stop is not None:
                        stops.add(str(stop))
                        if stop not in said:
                            print(json.dumps(line), flush=True)
                        continue
                    if line.get("skipped") != "in_flight":
                        print(json.dumps(line), flush=True)
                said = stops
                if not arguments.loop:
                    return 0
                time.sleep(arguments.interval)
    finally:
        database.dispose()


def _bench(arguments: argparse.Namespace) -> int:
    from ac_platform.one_pass import bench

    database, sessions = _database(arguments)
    try:
        calls = [item for item in arguments.calls.split(",") if item.strip()]
        for line in bench.run(
            sessions,
            arguments.bench,
            calls=calls or None,
            apply=arguments.apply,
            classic_only=arguments.classic_only,
            classic_again=arguments.classic_again,
            created_by=BENCH,
        ):
            print(json.dumps(line), flush=True)
    finally:
        database.dispose()
    return 0


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    arguments = _arguments(raw)
    if arguments.bench is not None:
        return _bench(arguments)
    if arguments.inner or not arguments.apply:
        return _inner(arguments)
    _reexec_inside_infisical([item for item in raw if item != INNER], arguments)
    return 0  # pragma: no cover - execvpe replaces this process


if __name__ == "__main__":
    raise SystemExit(main())
