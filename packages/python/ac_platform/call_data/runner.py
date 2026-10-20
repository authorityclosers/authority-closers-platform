"""The fast pipeline runner: every new call's transcript becomes typed objects in seconds.

Owner direction (19 Oct 2026): a salesperson calls, the call is transcribed,
facts are extracted at once and the lead is filled; uncertain facts wait for
the salesperson's one-at-a-time confirmation.

How it runs:
- one runner per database (a session advisory lock); ``--loop`` polls every few
  seconds for C2 transcripts saved after ``--not-before`` (automatic mode never
  backfills); our own canary and QA calls are skipped;
- each call is admitted (consent, retention, erasure, newest transcript), then a
  'running' row is committed before the provider is called, so a crash or
  timeout still counts as a paid attempt; at most two attempts per transcript;
- the answer is validated (quotes copied from the transcript, never the model),
  and in one transaction the admission is checked again and the outcome row,
  objects, decisions and lead fills are saved;
- the Admin settings choose the model, switch the pipeline off and set a daily
  rupee cap (list-price estimate); the provider key lives only in the
  ``infisical run`` child this command re-executes itself into;
- before every call the environment's AI spend guard is asked too (``ai_spend``,
  owner 20 Oct 2026): development's background AI is off until switched on, the
  deep pipeline never runs by itself there and backfills never run there; a
  backfill needs its own cap; sandbox and load-test organisations are skipped.

    python -m ac_platform.call_data.runner \\
        --service-config /etc/authority-closers/development/service-live.json \\
        --database-url-file /etc/authority-closers/development/database-url-live \\
        --not-before 2026-10-19T00:00:00+00:00 --loop --apply

Nothing printed contains transcript text, quotes, prompts, answers or lead values.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

INNER = "--inner"
AUTOMATIC = "automatic:call-data"
OPERATOR = "operator:call-data"
BACKFILL = "operator:call-data-backfill"
RUN_LOCK = "ac.call_data.fast"
_PROVIDER = "gemini"
LASTING_REFUSALS = frozenset({"permission_inactive", "account_inactive", "attempts_exhausted"})


def _arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="call_data.runner")
    parser.add_argument("--service-config", required=True, type=Path)
    parser.add_argument("--database-url-file", required=True, type=Path)
    parser.add_argument(
        "--not-before",
        type=datetime.fromisoformat,
        required=True,
        help="only transcripts saved after this moment (new calls only)",
    )
    parser.add_argument("--recent-hours", type=int, default=48)
    parser.add_argument("--recording", type=UUID, help="operator mode: this one call")
    parser.add_argument(
        "--force",
        action="store_true",
        help="operator mode: read this call again even if it was read (new run, supersedes)",
    )
    parser.add_argument("--limit", type=int, default=5, help="calls per pass")
    parser.add_argument(
        "--pipeline",
        choices=("fast", "deep", "both"),
        default="both",
        help="which pipelines a pass runs (deep only reads calls the fast pipeline finished)",
    )
    parser.add_argument(
        "--backfill",
        action="store_true",
        help="operator: read stored older calls once (no loop; up to a year back, up to 200)",
    )
    parser.add_argument("--loop", action="store_true", help="keep polling")
    parser.add_argument("--interval", type=float, default=4.0, help="seconds between passes")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--token-file", type=Path)
    parser.add_argument("--infisical", type=Path)
    parser.add_argument(INNER, action="store_true", help=argparse.SUPPRESS)
    arguments = parser.parse_args(argv)
    if arguments.not_before.tzinfo is None:
        parser.error("--not-before needs a time zone, e.g. 2026-10-19T00:00:00+00:00")
    if not 1 <= arguments.limit <= (200 if arguments.backfill else 20):
        parser.error("--limit must be 1-20 (1-200 with --backfill)")
    if not 1 <= arguments.recent_hours <= (8760 if arguments.backfill else 720):
        parser.error("--recent-hours must be 1-720 (up to 8760 with --backfill)")
    if arguments.backfill and arguments.loop:
        parser.error("--backfill runs once, never in the loop")
    if not 1.0 <= arguments.interval <= 300.0:
        parser.error("--interval must be 1-300 seconds")
    if arguments.force and (arguments.loop or not (arguments.recording or arguments.backfill)):
        parser.error("--force is for one call (--recording) or a --backfill, never the loop")
    return arguments


def _provider_config(config: Path) -> dict[str, Any]:
    service = json.loads(config.read_text())
    for provider in service.get("providers") or []:
        if provider.get("provider_id") == _PROVIDER:
            return dict(provider)
    raise SystemExit("call_data_provider_missing")


def _reexec_inside_infisical(argv: list[str], arguments: argparse.Namespace) -> None:
    """The same launch as the pointer review: the key exists only in the child."""
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
        "ac_platform.call_data.runner",
        *argv,
        INNER,
    ]
    os.execvpe(command[0], command, environment)  # noqa: S606 - fixed argv, no shell


def _prompt_sha256(model: str, system: str, user: str) -> str:
    return hashlib.sha256(
        json.dumps([model, system, user], ensure_ascii=False).encode()
    ).hexdigest()


def process_call(
    sessions: Any,
    call: Any,
    *,
    settings: dict[str, Any],
    apply: bool,
    trigger: str,
    created_by: str,
    model_client: Any,
    test_sources: set[str],
) -> dict[str, Any]:
    """Admit, extract, validate and save one call. Returns a content-free log line."""
    from ac_platform.call_data import engine, extraction, policy, taxonomy
    from ac_platform.call_data.provider import ProviderFailure
    from ac_platform.call_data.settings import cost_inr

    fast = settings["fast"]
    model = str(fast["model"])
    line: dict[str, Any] = {"recording": str(call.recording_id)}
    with sessions() as session, session.begin():
        connection = session.connection()
        engine.load(connection, call)
        now = datetime.now(UTC)
        refusal = engine.admission_refusal(connection, call, now) or engine.attempt_refusal(
            connection, call, "fast", now
        )
        if refusal:
            if apply and refusal in LASTING_REFUSALS:
                # Recorded once, so later passes do not pick this transcript again.
                engine.skip_run(
                    connection,
                    call,
                    reason=refusal,
                    pipeline="fast",
                    trigger=trigger,
                    created_by=created_by,
                    now=now,
                )
            line["skipped"] = refusal
            return line
        if call.source_sha256 in test_sources:
            if apply:
                engine.skip_run(
                    connection,
                    call,
                    reason="test_call",
                    pipeline="fast",
                    trigger=trigger,
                    created_by=created_by,
                    now=now,
                )
            line["skipped"] = "test_call"
            return line
        minutes = (call.duration_ms or 0) / 60000
        segments = [s for s in call.segments if s.id not in call.withheld]
        reason = None
        if minutes > fast["max_call_minutes"]:
            reason = "call_too_long"
        elif sum(len(s.text) for s in segments) < 40:
            reason = "no_conversation"
        if reason:
            if apply:
                engine.skip_run(
                    connection,
                    call,
                    reason=reason,
                    pipeline="fast",
                    trigger=trigger,
                    created_by=created_by,
                    now=now,
                )
            line["skipped"] = reason
            return line
        system, user = extraction.build_prompt(
            segments, types=taxonomy.FAST_TYPES, call_date=call.call_date()
        )
        digest = _prompt_sha256(model, system, user)
        line["segments"] = len(segments)
        if not apply:
            line["dry_run"] = True
            line["prompt_chars"] = len(system) + len(user)
            return line
        started = engine.start_run(
            connection,
            call,
            pipeline="fast",
            model=model,
            trigger=trigger,
            prompt_sha256=digest,
            created_by=created_by,
            now=now,
        )
    # The start is committed: from here on this attempt counts as paid.
    clock = time.monotonic()
    usage: dict[str, Any] | None = None
    outcome, reason = "failed", "runner_error"
    counts: dict[str, Any] = {}
    try:
        answer = model_client.generate_json(
            model=model,
            system=system,
            user=user,
            schema=extraction.response_schema(taxonomy.FAST_TYPES),
        )
        usage = answer.usage
        drafts, dropped = extraction.validate_response(
            answer.value, segments, types=taxonomy.FAST_TYPES, withheld=call.withheld
        )
        roles = extraction.parse_roles(answer.value, segments)
        with sessions() as session, session.begin():
            connection = session.connection()
            now = datetime.now(UTC)
            refusal = engine.admission_refusal(connection, call, now)
            if refusal:
                outcome, reason = "skipped", f"refused_{refusal}"
            else:
                lead = (
                    engine.lead_state(connection, call.tenant_id, call.lead_id)
                    if call.lead_id
                    else None
                )
                plans = policy.plan(
                    drafts,
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
                    pipeline="fast",
                    model=model,
                    trigger=trigger,
                    usage=usage,
                    cost_inr=cost_inr(
                        model, usage.get("promptTokenCount"), usage.get("candidatesTokenCount")
                    ),
                    duration_ms=round((time.monotonic() - clock) * 1000),
                    counts={"roles": roles, "dropped": dropped, "facts": len(drafts)},
                    created_by=created_by,
                    now=now,
                )
                counts = engine.save_objects(
                    connection,
                    call,
                    finished,
                    drafts,
                    plans,
                    lead=lead,
                    pipeline="fast",
                    pipeline_version=engine.FAST_VERSION,
                    now=now,
                )
                outcome, reason = "succeeded", None
    except ProviderFailure as failure:
        outcome, reason, usage = "failed", failure.outcome, failure.usage or usage
    finally:
        if outcome != "succeeded":
            # If this write fails too, the 'running' row without an outcome stays an
            # uncertain attempt, counted as spent and as a failure.
            with sessions() as session, session.begin():
                engine.finish_run(
                    session.connection(),
                    call,
                    started,
                    state=outcome,
                    reason=reason,
                    pipeline="fast",
                    model=model,
                    trigger=trigger,
                    usage=usage,
                    cost_inr=cost_inr(
                        model,
                        (usage or {}).get("promptTokenCount"),
                        (usage or {}).get("candidatesTokenCount"),
                    ),
                    duration_ms=round((time.monotonic() - clock) * 1000),
                    counts=None,
                    created_by=created_by,
                    now=datetime.now(UTC),
                )
    line["outcome"] = outcome if reason is None else f"{outcome}:{reason}"
    line.update(counts)
    if usage:
        line["tokens"] = [usage.get("promptTokenCount"), usage.get("candidatesTokenCount")]
    line["ms"] = round((time.monotonic() - clock) * 1000)
    return line


def run_pass(
    sessions: Any,
    arguments: argparse.Namespace,
    model_client: Any,
    *,
    created_by: str,
    storage_root: Path | None = None,
    spend_environment: str | None = None,
) -> list[dict[str, Any]]:
    """One pass. ``spend_environment`` turns the AI spend guard on (the real runner
    always passes it; tests with a fake model may leave it out)."""
    from ac_platform.ai_spend import guard as spend_guard
    from ac_platform.call_data import engine
    from ac_platform.call_data.deep_runner import process_deep_call

    pipelines = ("fast", "deep") if arguments.pipeline == "both" else (arguments.pipeline,)
    trigger = "backfill" if arguments.backfill else "operator" if arguments.recording else "auto"

    def refused(connection: Any, pipeline: str) -> dict[str, Any] | None:
        if spend_environment is None:
            return None
        refusal = spend_guard.check(
            connection, f"call_data_{pipeline}", environment=spend_environment, trigger=trigger
        )
        return None if refusal is None else refusal.line()

    lines: list[dict[str, Any]] = []
    for pipeline in pipelines:
        with sessions() as session:
            connection = session.connection()
            settings, _ = engine.read_settings(connection)
            if not settings[pipeline]["enabled"]:
                lines.append({"stopped": f"{pipeline}_pipeline_off"})
                continue
            now = datetime.now(UTC)
            spent = engine.spent_today(connection, pipeline, now)
            if spent >= settings[pipeline]["daily_cap_inr"]:
                lines.append({"stopped": f"{pipeline}_daily_cap", "spent_inr": str(spent)})
                continue
            calls = engine.candidates(
                connection,
                not_before=arguments.not_before,
                hours=arguments.recent_hours,
                limit=arguments.limit,
                pipeline=pipeline,
                recording_id=arguments.recording,
                include_done=bool(arguments.force),
            )
            test_sources = engine.test_source_shas(connection) if calls else set()
            if calls and spend_environment is not None:
                skipped = spend_guard.skipped_tenants(connection, spend_environment)
                calls = [call for call in calls if call.tenant_id not in skipped]
            stop = refused(connection, pipeline) if calls else None
            if stop is not None:
                lines.append(stop)
                continue
        for call in calls:
            if pipeline == "fast":
                line = process_call(
                    sessions,
                    call,
                    settings=settings,
                    apply=arguments.apply,
                    trigger=trigger,
                    created_by=created_by,
                    model_client=model_client,
                    test_sources=test_sources,
                )
            else:
                line = process_deep_call(
                    sessions,
                    call,
                    settings=settings,
                    apply=arguments.apply,
                    trigger=trigger,
                    created_by=created_by,
                    model_client=model_client,
                    test_sources=test_sources,
                    storage_root=storage_root,
                )
            lines.append(line)
            with sessions() as session:
                spent = engine.spent_today(session.connection(), pipeline, datetime.now(UTC))
                stop = refused(session.connection(), pipeline)
            if spent >= settings[pipeline]["daily_cap_inr"]:
                lines.append({"stopped": f"{pipeline}_daily_cap", "spent_inr": str(spent)})
                break
            if stop is not None:
                lines.append(stop)
                break
    return lines


def _inner(arguments: argparse.Namespace, model_client: Any = None) -> int:
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    from ac_platform.call_data.provider import Gemini

    client = model_client or Gemini()
    if arguments.apply and model_client is None and not client.ready:
        raise SystemExit("call_data_credential_missing")
    url = arguments.database_url_file.read_text().strip()
    database = create_engine(url.replace("+asyncpg", "+psycopg"), pool_pre_ping=True)
    sessions = sessionmaker(database, expire_on_commit=False)
    created_by = BACKFILL if arguments.backfill else OPERATOR if arguments.recording else AUTOMATIC
    service = json.loads(arguments.service_config.read_text())
    root = service.get("sales_xray_storage_root")
    storage_root = Path(root) if isinstance(root, str) and root else None
    # A real model is always behind the AI spend guard (owner, 20 Oct 2026).
    spend_environment = None
    if model_client is None:
        from ac_platform.ai_spend import guard as spend_guard
        from ac_platform.ai_spend.policy import SettingsError

        try:
            spend_environment = spend_guard.service_environment(service)
        except SettingsError:
            raise SystemExit("call_data_environment_missing") from None
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
                    storage_root=storage_root,
                    spend_environment=spend_environment,
                ):
                    stop = line.get("stopped")
                    if stop is not None:
                        # A pipeline switched off or at its cap is said once, not every pass.
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


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    arguments = _arguments(raw)
    if arguments.inner or not arguments.apply:
        return _inner(arguments)
    _reexec_inside_infisical([item for item in raw if item != INNER], arguments)
    return 0  # pragma: no cover - execvpe replaces this process


if __name__ == "__main__":
    raise SystemExit(main())
