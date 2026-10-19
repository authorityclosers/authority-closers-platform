"""Partner webhooks runner and operator commands (``sx.analysis_completed.v1``).

    python -m ac_platform.partner_events.cli \\
        --service-config /etc/authority-closers/development/service-live.json \\
        --database-url-file /etc/authority-closers/development/database-url-live \\
        [--token-file ...] [--infisical ...] [--app-url ...] <command>

Commands (every change is a dry run without ``--apply``):

- ``run [--apply] [--seconds 55] [--interval 5]``: for about a minute, loop
  quote facts -> enqueue -> deliver -> erasure sweep. A dry run makes one pass
  and changes nothing (no provider call, no send). Reports are read a page at
  a time, oldest first; a waiting report is counted and paged past. A report
  that will never be sent gets a final row with a reason; one that aged out of
  the recent window is recorded and the owner is alerted (counts and short
  ids only), like a dead letter.
- ``register-endpoint --tenant --url --secret-ref [--secret-ref-next]
  --events analysis.completed [--facts-profile wiselife-quote-v1] [--supersede]
  --reason --operator-reference [--apply]``
- ``disable-endpoint --endpoint-id --reason --operator-reference [--apply]``
- ``list``: endpoints with masked URLs and event counts.
- ``replay --event-id --reason --operator-reference [--apply]``: dead letter
  back to pending.
- ``test-event --endpoint-id [--apply]``: one signed fictional ``sx.test.v1``
  event, so a partner can check signing without customer data.

``run --apply`` and ``test-event --apply`` re-run themselves inside
``infisical run`` with the Gemini provider's secret path, so ``GEMINI_API_KEY``
and the ``AC_PARTNER_WEBHOOK_SECRET__*`` values exist only in the child's
environment. Nothing here prints payloads, transcript text, full URLs or
secret values.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

INNER = "--inner"
MODULE = "ac_platform.partner_events.cli"
_PROVIDER = "gemini"
MAX_PAGES = 10  # pages of reports read per pass, so waiting reports never hold newer ones
AGE_OUT_LIMIT = 50  # aged-out reports recorded per page; up to MAX_PAGES pages per run


def _bounded(low: int, high: int) -> Callable[[str], int]:
    def parse(value: str) -> int:
        number = int(value)
        if not low <= number <= high:
            raise argparse.ArgumentTypeError(f"must be {low}-{high}")
        return number

    return parse


def _arguments(argv: list[str]) -> argparse.Namespace:
    from ac_platform.partner_events.endpoints import EVENTS
    from ac_platform.partner_events.quote_facts import PROFILES

    parser = argparse.ArgumentParser(prog="partner_events")
    parser.add_argument("--service-config", required=True, type=Path)
    parser.add_argument("--database-url-file", required=True, type=Path)
    # Outside the worker's mount namespace the identity token and Infisical
    # live at their host paths (the worker bind-mounts them read-only).
    parser.add_argument("--token-file", type=Path)
    parser.add_argument("--infisical", type=Path)
    parser.add_argument("--app-url", help="Sales X-Ray web origin for analysis_url")
    parser.add_argument(INNER, action="store_true", help=argparse.SUPPRESS)
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="quote facts, enqueue, deliver, erasure sweep")
    run.add_argument("--apply", action="store_true")
    run.add_argument("--seconds", type=_bounded(1, 600), default=55)
    run.add_argument("--interval", type=_bounded(1, 60), default=5)
    run.add_argument("--limit", type=_bounded(1, 50), default=10, help="reports per pass")
    run.add_argument("--daily-cap", type=_bounded(1, 2000), default=300)
    run.add_argument("--recent-hours", type=_bounded(1, 168), default=72)

    register = commands.add_parser("register-endpoint")
    register.add_argument("--tenant", required=True, type=UUID)
    register.add_argument("--url", required=True)
    register.add_argument("--secret-ref", required=True)
    register.add_argument("--secret-ref-next")
    register.add_argument("--events", required=True, nargs="+", choices=EVENTS)
    register.add_argument("--facts-profile", choices=sorted(PROFILES))
    register.add_argument("--supersede", action="store_true")
    register.add_argument("--reason", required=True)
    register.add_argument("--operator-reference", required=True)
    register.add_argument("--apply", action="store_true")

    disable = commands.add_parser("disable-endpoint")
    disable.add_argument("--endpoint-id", required=True, type=UUID)
    disable.add_argument("--reason", required=True)
    disable.add_argument("--operator-reference", required=True)
    disable.add_argument("--apply", action="store_true")

    commands.add_parser("list")

    replay = commands.add_parser("replay")
    replay.add_argument("--event-id", required=True, type=UUID)
    replay.add_argument("--reason", required=True)
    replay.add_argument("--operator-reference", required=True)
    replay.add_argument("--apply", action="store_true")

    test = commands.add_parser("test-event")
    test.add_argument("--endpoint-id", required=True, type=UUID)
    test.add_argument("--apply", action="store_true")
    return parser.parse_args(argv)


def _service(config: Path) -> dict[str, Any]:
    value = json.loads(config.read_text())
    if not isinstance(value, dict):
        raise SystemExit("partner_events_service_config_invalid")
    return value


def _environment(service: dict[str, Any]) -> str:
    environment = service.get("environment")
    if not isinstance(environment, str) or not environment:
        raise SystemExit("partner_events_environment_missing")
    return environment


def _app_url(arguments: argparse.Namespace, environment: str) -> str:
    from ac_platform.conversation_intelligence.account_smoke import ORIGINS

    return str(arguments.app_url or ORIGINS.get(environment) or "http://localhost:3000").rstrip("/")


def _needs_secrets(arguments: argparse.Namespace) -> bool:
    return arguments.command in {"run", "test-event"} and bool(arguments.apply)


def _reexec_inside_infisical(argv: list[str], arguments: argparse.Namespace) -> None:
    service = _service(arguments.service_config)
    provider = next(
        (
            dict(item)
            for item in service.get("providers") or []
            if item.get("provider_id") == _PROVIDER
        ),
        None,
    )
    if provider is None:
        raise SystemExit("partner_events_provider_missing")
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
        MODULE,
        INNER,
        *argv,
    ]
    os.execvpe(command[0], command, environment)  # noqa: S606 - fixed argv, no shell


def _call_gemini_for(model_id: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def call(body: dict[str, Any]) -> dict[str, Any]:
        import httpx

        from ac_platform.partner_events.pipeline import ProviderFailure

        key = os.environ.get("GEMINI_API_KEY", "")
        if not key:
            raise SystemExit("partner_events_credential_missing")
        try:
            response = httpx.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent",
                headers={"x-goog-api-key": key, "content-type": "application/json"},
                json=body,
                timeout=httpx.Timeout(120.0, connect=20.0),
            )
        except httpx.TimeoutException:
            raise ProviderFailure("timeout") from None
        except httpx.HTTPError:
            raise ProviderFailure("transport_error") from None
        if response.status_code != 200:
            raise ProviderFailure(f"provider_http_{response.status_code}")
        try:
            return dict(response.json())
        except ValueError:
            raise ProviderFailure("unreadable_response") from None

    return call


def _now() -> datetime:
    return datetime.now(UTC)


def _print(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, default=str), flush=True)


async def _gemini_needed(sessions: Any) -> bool:
    from sqlalchemy import select

    from ac_platform.partner_events.models import PartnerWebhookEndpoint

    async with sessions() as session:
        found = await session.scalar(
            select(PartnerWebhookEndpoint.id)
            .where(
                PartnerWebhookEndpoint.status == "active",
                PartnerWebhookEndpoint.facts_profile.is_not(None),
            )
            .limit(1)
        )
    return found is not None


def _waiting(line: dict[str, Any]) -> bool:
    """A report that is not ready yet (an attempt in flight, the daily cap, a call not
    ready): it repeats every pass, so it is counted, not logged."""
    if {"final", "error", "facts_attempt", "revision", "event"} & set(line):
        return False
    return "facts_wait" in line or "enqueue_refused" in line


async def _settle(
    sessions: Any,
    candidate: Any,
    arguments: argparse.Namespace,
    *,
    app_url: str,
    call_provider: Callable[[dict[str, Any]], dict[str, Any]] | None,
    clock: Callable[[], datetime],
    totals: dict[str, int],
) -> dict[str, Any]:
    """Quote facts and enqueue for one report, or its final row; the line to log."""
    from ac_platform.partner_events import pipeline
    from ac_platform.partner_events.quote_facts import load_profile

    line: dict[str, Any] = {"submission": str(candidate.submission_id)}
    try:
        reason = candidate.skip
        if reason is None:
            provider = call_provider or _call_gemini_for(
                load_profile(candidate.facts_profile).model_id
                if candidate.facts_profile
                else "none"
            )
            extraction, detail = await pipeline.extract(
                sessions,
                candidate,
                apply=arguments.apply,
                daily_cap=arguments.daily_cap,
                call_provider=provider,
                clock=clock,
            )
            line.update(detail)
            if extraction is not None and arguments.apply:
                line.update(
                    await pipeline.enqueue(
                        sessions, candidate, extraction, app_url=app_url, clock=clock
                    )
                )
                totals["enqueued"] += "revision" in line
            elif extraction is not None:
                line["would_enqueue"] = extraction.status
            reason = pipeline.final_refusal(line)
        if reason is not None:
            if arguments.apply:
                line.update(await pipeline.record_final(sessions, candidate, reason, clock=clock))
                totals["final"] += "final" in line
            else:
                line["would_record"] = reason
    except Exception as error:  # one call's failure never stops the others
        line["error"] = type(error).__name__
        totals["errors"] += 1
    return line


async def _age_out(
    sessions: Any,
    arguments: argparse.Namespace,
    *,
    environment: str,
    tests: set[str],
    clock: Callable[[], datetime],
    totals: dict[str, int],
) -> None:
    """Reports that left the recent window without an event row: recorded, owner alerted.

    A backlog is recorded a page at a time (up to ``MAX_PAGES`` pages of
    ``AGE_OUT_LIMIT``) and alerts once per run with the total, not once a
    minute per page.
    """
    from ac_platform.partner_events import pipeline
    from ac_platform.partner_events.delivery import notify_owner

    recorded = 0
    short_ids: set[str] = set()
    for _ in range(MAX_PAGES):
        async with sessions() as session:
            old = await pipeline.aged_out(
                session,
                now=clock(),
                recent_hours=arguments.recent_hours,
                limit=AGE_OUT_LIMIT,
                tests=tests,
            )
        if not old:
            break
        if not arguments.apply:
            _print({"would_age_out": len(old)})
            return
        page = 0
        for candidate in old:
            line = await pipeline.record_final(sessions, candidate, pipeline.AGED_OUT, clock=clock)
            if "final" in line:
                page += 1
                short_ids.add(str(candidate.endpoint_id)[:8])
        recorded += page
        if not page or len(old) < AGE_OUT_LIMIT:
            break  # the backlog is done, or another runner is recording it
    totals["aged_out"] += recorded
    if not recorded:
        return
    endpoints = sorted(short_ids)
    text = (
        f"Sales X-Ray partner webhooks ({environment}): {recorded} report(s) aged out after "
        f"{arguments.recent_hours} h without an event (endpoint {', '.join(endpoints)}). "
        "Recorded as dropped (aged_out); check the runner and the daily cap."
    )
    _print(
        {
            "alert": "reports_aged_out",
            "count": recorded,
            "endpoints": endpoints,
            "notified": await asyncio.to_thread(notify_owner, text),
        }
    )


async def _one_pass(
    sessions: Any,
    arguments: argparse.Namespace,
    *,
    environment: str,
    app_url: str,
    client: Any,
    call_provider: Callable[[dict[str, Any]], dict[str, Any]] | None,
    clock: Callable[[], datetime],
    deadline: float,
    totals: dict[str, int],
    cache: dict[str, Any],
) -> bool:
    """One extract -> enqueue -> deliver -> sweep pass; False when no endpoint is active.

    Reports are read a page at a time; waiting reports and failures do not use
    up the pass's ``--limit``, so the pass pages past them (at most
    ``MAX_PAGES`` pages). Our own test sources are filtered in the query
    (looked up once per run).
    """
    from ac_platform.partner_events import pipeline
    from ac_platform.partner_events.delivery import deliver_one, erasure_sweep

    async with sessions() as session:
        active = await pipeline.active_endpoints(session)
        if active and "tests" not in cache:
            cache["tests"] = set(await pipeline.test_sources(session))
    tests: set[str] = cache.get("tests", set())
    if active:
        after: tuple[datetime, UUID] | None = None
        acted = 0
        for _ in range(MAX_PAGES):
            async with sessions() as session:
                page = await pipeline.candidates(
                    session,
                    now=clock(),
                    recent_hours=arguments.recent_hours,
                    limit=arguments.limit,
                    tests=tests,
                    after=after,
                )
            for candidate in page:
                after = (candidate.created_at, candidate.draft_id)
                line = await _settle(
                    sessions,
                    candidate,
                    arguments,
                    app_url=app_url,
                    call_provider=call_provider,
                    clock=clock,
                    totals=totals,
                )
                if arguments.apply and _waiting(line):
                    totals["waiting"] += 1
                    continue
                _print(line)
                acted += "error" not in line
            if len(page) < arguments.limit or acted >= arguments.limit:
                break
            if time.monotonic() >= deadline:
                break
        if not cache.get("aged_checked"):
            cache["aged_checked"] = True  # once per run (about a minute)
            try:
                await _age_out(
                    sessions,
                    arguments,
                    environment=environment,
                    tests=tests,
                    clock=clock,
                    totals=totals,
                )
            except Exception as error:  # never stops delivery
                totals["errors"] += 1
                _print({"age_out_error": type(error).__name__})
    if not arguments.apply:
        from sqlalchemy import func, select

        from ac_platform.partner_events.models import PartnerWebhookEvent

        async with sessions() as session:
            due = await session.scalar(
                select(func.count())
                .select_from(PartnerWebhookEvent)
                .where(
                    PartnerWebhookEvent.status == "pending",
                    PartnerWebhookEvent.next_attempt_at <= clock(),
                )
            )
        _print({"due_events": int(due or 0), "apply": False})
        return bool(active)
    while active and time.monotonic() < deadline:
        delivered = await deliver_one(sessions, client, environment=environment, clock=clock)
        if delivered is None:
            break
        totals["attempts"] += 1
        totals["delivered"] += delivered.get("status") == "delivered"
        totals["dropped"] += "dropped" in delivered
        totals["dead_letters"] += delivered.get("status") == "dead_letter"
        _print(delivered)
    async with sessions() as session, session.begin():
        swept = await erasure_sweep(session, clock())
    if any(swept.values()):
        _print(swept)
    # The sweep runs even with no active endpoint, so erased calls are emptied regardless.
    return bool(active)


async def _run(
    sessions: Any,
    engine: Any,
    arguments: argparse.Namespace,
    *,
    environment: str,
    app_url: str,
    call_provider: Callable[[dict[str, Any]], dict[str, Any]] | None,
    client: Any,
    clock: Callable[[], datetime],
) -> int:
    from ac_platform.partner_events.delivery import http_client, release_run_lock, try_run_lock

    if (
        arguments.apply
        and call_provider is None
        and not os.environ.get("GEMINI_API_KEY")
        and await _gemini_needed(sessions)
    ):
        # Checked before any claim, so a missing key never records an attempt.
        _print({"stopped": "partner_events_credential_missing"})
        return 2
    totals = dict.fromkeys(
        (
            "passes",
            "enqueued",
            "final",
            "aged_out",
            "attempts",
            "delivered",
            "dropped",
            "dead_letters",
            "errors",
            "waiting",
        ),
        0,
    )
    cache: dict[str, Any] = {}
    deadline = time.monotonic() + arguments.seconds
    own_client = client is None and arguments.apply
    client = client or (http_client() if arguments.apply else None)
    try:
        async with engine.connect() as lock:
            if arguments.apply and not await try_run_lock(lock):
                _print({"stopped": "another_runner"})
                return 0
            try:
                while True:
                    active = await _one_pass(
                        sessions,
                        arguments,
                        environment=environment,
                        app_url=app_url,
                        client=client,
                        call_provider=call_provider,
                        clock=clock,
                        deadline=deadline,
                        totals=totals,
                        cache=cache,
                    )
                    totals["passes"] += 1
                    if not active:
                        _print({"endpoints": 0})
                        break
                    if not arguments.apply or time.monotonic() + arguments.interval >= deadline:
                        break
                    await asyncio.sleep(arguments.interval)
            finally:
                if arguments.apply:
                    await release_run_lock(lock)
    finally:
        if own_client:
            await client.aclose()
    if any(value for key, value in totals.items() if key != "passes"):
        _print({"totals": totals, "apply": arguments.apply})
    return 1 if totals["errors"] else 0


async def _test_event(
    sessions: Any,
    arguments: argparse.Namespace,
    *,
    environment: str,
    client: Any,
    clock: Callable[[], datetime],
) -> int:
    from ac_platform.partner_events.delivery import (
        http_client,
        mask_url,
        post,
        read_secrets,
        url_allowed,
    )
    from ac_platform.partner_events.endpoints import fictional_test_body, record_test_event
    from ac_platform.partner_events.models import PartnerWebhookEndpoint
    from ac_platform.partner_events.payload import body_bytes

    async with sessions() as session:
        endpoint = await session.get(PartnerWebhookEndpoint, arguments.endpoint_id)
    if endpoint is None or endpoint.status != "active":
        _print({"error": "endpoint_not_active"})
        return 2
    body = fictional_test_body(endpoint.tenant_id, clock())
    raw = body_bytes(body)
    summary = {
        "endpoint": mask_url(endpoint.url),
        "event_id": body["event_id"],
        "bytes": len(raw),
        "secret_ref": endpoint.secret_ref,
        "secret_ref_next": endpoint.secret_ref_next,
        "apply": arguments.apply,
    }
    if not url_allowed(endpoint.url, environment):
        _print({**summary, "error": "url_refused"})
        return 2
    if not arguments.apply:
        _print(summary)
        return 0
    secrets = read_secrets(endpoint.secret_ref, endpoint.secret_ref_next)
    if secrets is None:
        _print({**summary, "error": "secret_missing"})
        return 2
    if endpoint.secret_ref_next and len(secrets) == 1:
        summary["rotation"] = "next_not_set"  # signed with the current secret only
    own_client = client is None
    client = client or http_client()
    try:
        outcome = await post(
            client,
            url=endpoint.url,
            event_id=body["event_id"],
            event_type="test",
            body=raw,
            secrets=secrets,
            environment=environment,
        )
    finally:
        if own_client:
            await client.aclose()
    async with sessions() as session, session.begin():
        await record_test_event(
            session,
            endpoint=endpoint,
            event_id=body["event_id"],
            http_status=outcome.http_status,
            error_code=outcome.error_code,
            duration_ms=outcome.duration_ms,
            now=clock(),
        )
    _print(
        {
            **summary,
            "http_status": outcome.http_status,
            "error": outcome.error_code,
            "duration_ms": outcome.duration_ms,
        }
    )
    return 0 if outcome.delivered else 1


async def _inner_async(
    arguments: argparse.Namespace,
    *,
    call_provider: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    client: Any = None,
    clock: Callable[[], datetime] = _now,
) -> int:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from ac_platform.partner_events import endpoints

    environment = _environment(_service(arguments.service_config))
    app_url = _app_url(arguments, environment)
    url = arguments.database_url_file.read_text().strip()
    engine = create_async_engine(url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        if arguments.command == "run":
            return await _run(
                sessions,
                engine,
                arguments,
                environment=environment,
                app_url=app_url,
                call_provider=call_provider,
                client=client,
                clock=clock,
            )
        if arguments.command == "test-event":
            return await _test_event(
                sessions, arguments, environment=environment, client=client, clock=clock
            )
        async with sessions() as session, session.begin():
            if arguments.command == "list":
                _print({"endpoints": await endpoints.list_endpoints(session)})
                return 0
            if arguments.command == "register-endpoint":
                result = await endpoints.register(
                    session,
                    tenant_id=arguments.tenant,
                    url=arguments.url,
                    secret_ref=arguments.secret_ref,
                    secret_ref_next=arguments.secret_ref_next,
                    events=list(arguments.events),
                    facts_profile=arguments.facts_profile,
                    reason=arguments.reason,
                    operator_reference=arguments.operator_reference,
                    supersede=arguments.supersede,
                    apply=arguments.apply,
                    environment=environment,
                    now=clock(),
                )
            elif arguments.command == "disable-endpoint":
                result = await endpoints.disable(
                    session,
                    endpoint_id=arguments.endpoint_id,
                    reason=arguments.reason,
                    operator_reference=arguments.operator_reference,
                    apply=arguments.apply,
                    now=clock(),
                )
            else:
                result = await endpoints.replay(
                    session,
                    event_id=arguments.event_id,
                    reason=arguments.reason,
                    operator_reference=arguments.operator_reference,
                    apply=arguments.apply,
                    now=clock(),
                )
            _print(result)
            return 0
    except endpoints.EndpointError as error:
        _print({"error": str(error)})
        return 2
    finally:
        await engine.dispose()


async def _preflight_async(
    arguments: argparse.Namespace, clock: Callable[[], datetime] = _now
) -> bool:
    """Before fetching any secret: True when an endpoint is active.

    With none, ``run --apply`` needs no key: it only empties erased calls'
    payloads and stops, so an idle environment never calls Infisical.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from ac_platform.partner_events.delivery import erasure_sweep
    from ac_platform.partner_events.pipeline import active_endpoints

    engine = create_async_engine(arguments.database_url_file.read_text().strip())
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sessions() as session:
            if await active_endpoints(session):
                return True
        async with sessions() as session, session.begin():
            swept = await erasure_sweep(session, clock())
        if any(swept.values()):
            _print(swept)
        _print({"endpoints": 0})
        return False
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    arguments = _arguments(raw)
    if arguments.inner or not _needs_secrets(arguments):
        return asyncio.run(_inner_async(arguments))
    if arguments.command == "run" and not asyncio.run(_preflight_async(arguments)):
        return 0
    _reexec_inside_infisical([item for item in raw if item != INNER], arguments)
    return 0  # pragma: no cover - execvpe replaces this process


if __name__ == "__main__":
    raise SystemExit(main())
