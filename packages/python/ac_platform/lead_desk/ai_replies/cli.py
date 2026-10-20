"""The AI replies runner: asks the model for the replies the API queued.

The same launch as the call data engine (``call_data.runner``): started with the
worker's service config, it re-executes itself inside ``infisical run`` with that
config's provider launcher, so the provider key exists in this child process only.
It never sends a message and holds no Meta secret: it reads queued rows of
``lead_desk_ai_replies``, asks the model (with no transaction open) and writes the
outcome; the API sends the drafted automatic replies and alerts sellers on hand-offs.

Each pass, by this environment's Admin settings:

- switched off: nothing is asked (one ``{"stopped": "lead_desk_ai_off"}`` line);
- at the cap: automatic replies wait ("waiting"), suggestions stop ("paused"), and
  one ``{"stopped": "lead_desk_ai_cap", ...}`` line lets the launcher alert the owner
  once per period (``infra/application/scripts/ac-lead-desk-ai``);
- otherwise: what waited for budget is queued again, and up to ``--limit`` queued rows
  are answered, the cap checked again after each.

One runner per database (a session advisory lock); a row it was answering when it
stopped is asked again when it starts. Without ``--apply`` it only says where things
stand. Lines carry ids, outcomes and counts only, never a message or a prompt.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final
from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.lead_desk.ai_replies import admin_settings, registry, service
from ac_platform.lead_desk.models import Lead, LeadAiReply

INNER: Final[str] = "--inner"
RUN_LOCK: Final[str] = "ac.lead_desk.ai_replies"
PROVIDER: Final[str] = "gemini"
THINKING: Final[str] = "thinking"  # the reason on a row being answered now


def _arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="lead_desk.ai_replies.cli")
    parser.add_argument("--service-config", required=True, type=Path)
    parser.add_argument("--database-url-file", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=10, help="replies per pass")
    parser.add_argument("--loop", action="store_true", help="keep polling")
    parser.add_argument("--interval", type=float, default=3.0, help="seconds between passes")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--token-file", type=Path)
    parser.add_argument("--infisical", type=Path)
    parser.add_argument(INNER, action="store_true", help=argparse.SUPPRESS)
    arguments = parser.parse_args(argv)
    if not 1 <= arguments.limit <= 50:
        parser.error("--limit must be 1-50")
    if not 1.0 <= arguments.interval <= 300.0:
        parser.error("--interval must be 1-300 seconds")
    return arguments


def _provider_config(config: Path) -> dict[str, Any]:
    service_config = json.loads(config.read_text())
    for provider in service_config.get("providers") or []:
        if provider.get("provider_id") == PROVIDER:
            return dict(provider)
    raise SystemExit("lead_desk_ai_provider_missing")


def _reexec_inside_infisical(argv: list[str], arguments: argparse.Namespace) -> None:
    """The call data engine's launch: the key exists only in the child."""
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
        "ac_platform.lead_desk.ai_replies.cli",
        *argv,
        INNER,
    ]
    os.execvpe(command[0], command, environment)  # noqa: S606 - fixed argv, no shell


ModelFactory = Callable[[dict[str, Any]], service.Model]


async def thinking_pass(
    sessions: async_sessionmaker[AsyncSession],
    model_for: ModelFactory,
    *,
    now: datetime,
    limit: int = 10,
    spend_environment: str | None = None,
) -> list[dict[str, Any]]:
    """One pass: the switch, the cap, then the queued replies.

    ``spend_environment`` also asks the environment's AI spend guard (owner, 20 Oct
    2026); at its cap replies wait for budget exactly as at this feature's own cap."""
    from ac_platform.ai_spend import guard as spend_guard

    async def refused(db: AsyncSession) -> dict[str, Any] | None:
        if spend_environment is None:
            return None
        refusal = await spend_guard.check_async(
            db, "lead_desk_ai", environment=spend_environment, trigger="person", now=now
        )
        return None if refusal is None else refusal.line()

    async with sessions() as db, db.begin():
        config, _ = await admin_settings.read(db)
        if not config["enabled"]:
            return [{"stopped": "lead_desk_ai_off"}]
        if await admin_settings.capped(db, config, now):
            return [await _wait_for_budget(db, config, now)]
        stop = await refused(db)
        if stop is not None:
            return [{**await _wait_for_budget(db, config, now), **stop}]
        # Under the cap: what waited for budget is asked again.
        await db.execute(
            update(LeadAiReply)
            .where(LeadAiReply.outcome == "waiting")
            .values(outcome="queued", reason=None)
        )
        claimed = list(
            (
                await db.scalars(
                    select(LeadAiReply.id)
                    .where(LeadAiReply.outcome == "queued", LeadAiReply.reason.is_(None))
                    .order_by(LeadAiReply.created_at)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        if claimed:
            await db.execute(
                update(LeadAiReply).where(LeadAiReply.id.in_(claimed)).values(reason=THINKING)
            )
    model = model_for(config)
    lines: list[dict[str, Any]] = []
    for reply_id in claimed:
        lines.append(await _answer(sessions, model, reply_id, now=now))
        async with sessions() as db:
            if await admin_settings.capped(db, config, now):
                async with db.begin():
                    lines.append(await _wait_for_budget(db, config, now))
                break
            stop = await refused(db)
            if stop is not None:
                async with db.begin():
                    lines.append({**await _wait_for_budget(db, config, now), **stop})
                break
    return lines


async def _wait_for_budget(
    db: AsyncSession, config: dict[str, Any], now: datetime
) -> dict[str, Any]:
    """At the cap: automatic replies wait for budget, suggestions stop."""
    held = await db.execute(
        update(LeadAiReply)
        .where(LeadAiReply.outcome == "queued", LeadAiReply.mode == "auto")
        .values(outcome="waiting", reason="budget")
    )
    stopped = await db.execute(
        update(LeadAiReply)
        .where(LeadAiReply.outcome == "queued", LeadAiReply.mode != "auto")
        .values(outcome="paused", reason="budget", settled_at=now)
    )
    spent = await admin_settings.spent(db, config, now)
    return {
        "stopped": "lead_desk_ai_cap",
        "spent_inr": f"{spent:.2f}",
        "cap_inr": str(config["cap_inr"]),
        "period": config["period"],
        "period_key": admin_settings.period_key(str(config["period"]), now),
        "waiting": int(getattr(held, "rowcount", 0) or 0),
        "suggestions_stopped": int(getattr(stopped, "rowcount", 0) or 0),
    }


async def _answer(
    sessions: async_sessionmaker[AsyncSession],
    model: service.Model,
    reply_id: UUID,
    *,
    now: datetime,
) -> dict[str, Any]:
    async with sessions() as db:
        row = await db.get(LeadAiReply, reply_id)
        if row is None:
            return {"reply": str(reply_id), "outcome": "gone"}
        ready = await service.prepare_row(db, row, now=now)
        mode = row.mode
    late = None if ready is None or mode != "auto" else service.gone_by(row, ready)
    if ready is None:
        result = service.Outcome("failed", "lead_gone")
    elif late is not None:
        result = service.Outcome("failed", late)
    else:
        result = await service.think(model, ready)
    async with sessions() as db, db.begin():
        row = await db.get(LeadAiReply, reply_id, with_for_update=True)
        if row is None:
            return {"reply": str(reply_id), "outcome": "gone"}
        if ready is not None:
            service.apply(row, ready, result, now=now)
        else:
            row.outcome, row.reason = result.outcome, result.reason
        if result.outcome == "opted_out" and ready is not None and row.lead_id is not None:
            lead = await db.get(Lead, row.lead_id, with_for_update=True)
            if lead is not None:
                await service.record_stop(service.system_desk(db, lead, now), lead, row.channel)
        # A suggestion (or a try) is final here; an automatic reply waits for the API to
        # send it or to alert the seller.
        if mode != "auto" or result.outcome in ("failed", "opted_out", "paused"):
            row.settled_at = now
    return {"reply": str(reply_id), "mode": mode, "outcome": result.outcome}


async def _run(
    arguments: argparse.Namespace,
    model_for: ModelFactory,
    *,
    spend_environment: str | None = None,
) -> int:
    url = arguments.database_url_file.read_text().strip()
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    # psycopg's async driver, as the API's own engine (``db.session``).
    database = create_async_engine(url.replace("+asyncpg", "+psycopg"), pool_pre_ping=True)
    sessions = async_sessionmaker(database, expire_on_commit=False)
    try:
        async with database.connect() as lock:
            if arguments.apply:
                held = await lock.scalar(
                    text("SELECT pg_try_advisory_lock(hashtextextended(:key, 0))"),
                    {"key": RUN_LOCK},
                )
                await lock.commit()
                if not held:
                    print(json.dumps({"stopped": "another_runner"}), flush=True)
                    return 0
            if not arguments.apply:
                print(json.dumps(await status(sessions, now=datetime.now(UTC))), flush=True)
                return 0
            async with sessions() as db, db.begin():
                # What this runner was answering when it last stopped is asked again.
                await db.execute(
                    update(LeadAiReply)
                    .where(LeadAiReply.outcome == "queued", LeadAiReply.reason == THINKING)
                    .values(reason=None)
                )
            print(json.dumps({"started": "lead-desk-ai", "apply": True}), flush=True)
            said: set[str] = set()
            while True:
                stops: set[str] = set()
                for line in await thinking_pass(
                    sessions,
                    model_for,
                    now=datetime.now(UTC),
                    limit=arguments.limit,
                    spend_environment=spend_environment,
                ):
                    stop = line.get("stopped")
                    if stop is not None:
                        # Off or at the cap is said once, not every pass.
                        stops.add(str(stop))
                        if stop not in said:
                            print(json.dumps(line), flush=True)
                        continue
                    print(json.dumps(line), flush=True)
                said = stops
                if not arguments.loop:
                    return 0
                await asyncio.sleep(arguments.interval)
    finally:
        await database.dispose()


async def status(sessions: async_sessionmaker[AsyncSession], *, now: datetime) -> dict[str, Any]:
    """Where things stand, for a dry run: the switch, the spend and the queue."""
    async with sessions() as db:
        config, revision = await admin_settings.read(db)
        counts = await admin_settings.queue(db)
        spent = await admin_settings.spent(db, config, now)
    return {
        "dry_run": "lead-desk-ai",
        "enabled": config["enabled"],
        "revision": revision,
        "provider": config["provider"],
        "model": config["model"],
        "cap_inr": str(config["cap_inr"]),
        "period": config["period"],
        "spent_inr": f"{spent:.2f}",
        "queued": int(counts.get("queued", 0)),
        "waiting": int(counts.get("waiting", 0)),
    }


def _inner(arguments: argparse.Namespace) -> int:
    from ac_platform.ai_spend import guard as spend_guard
    from ac_platform.ai_spend.policy import SettingsError
    from ac_platform.call_data.provider import Gemini

    if arguments.apply and not Gemini().ready:
        raise SystemExit("lead_desk_ai_credential_missing")
    try:
        spend_environment = spend_guard.service_environment(
            json.loads(arguments.service_config.read_text())
        )
    except SettingsError:
        raise SystemExit("lead_desk_ai_environment_missing") from None
    return asyncio.run(
        _run(
            arguments,
            lambda config: registry.ProviderModel(config),
            spend_environment=spend_environment,
        )
    )


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    arguments = _arguments(raw)
    if arguments.inner or not arguments.apply:
        return _inner(arguments)
    _reexec_inside_infisical([item for item in raw if item != INNER], arguments)
    return 0  # not reached: the process is replaced


if __name__ == "__main__":
    raise SystemExit(main())
