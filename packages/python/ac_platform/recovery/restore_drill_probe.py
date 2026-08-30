"""Application-image probe for an isolated PostgreSQL restore drill.

This module is intentionally not a general database administration CLI.  It
accepts one database URL from the environment, validates that the host, role,
and database share a generated restore-drill token, and requires an explicit
acknowledgement before opening the connection.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import json
import os
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from types import SimpleNamespace
from uuid import UUID, uuid4

from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.kernel.authz import ActorContext
from ac_platform.outbox import (
    RecoveryStateRepository,
    mark_database_restore,
    reconcile_operations,
)
from ac_platform.providers import DeliveryReceipt
from ac_platform.worker import (
    ENROLLMENT_WELCOME_JOB,
    AllowlistedDispatcher,
    DurableWorker,
    PreparedDispatch,
    WorkerNotReadyError,
)

DATABASE_URL_ENV = "AC_RESTORE_DRILL_DATABASE_URL"
ACKNOWLEDGEMENT_ENV = "AC_RESTORE_DRILL_ACKNOWLEDGE"
ACKNOWLEDGEMENT_VALUE = "isolated-disposable-restore-drill-v1"
MAX_RELEASE_SET_SIZE = 100
TOKEN_PATTERN = r"(?P<token>[0-9a-f]{12})"  # noqa: S105 - identity regex, not a secret
HOST_PATTERN = re.compile(rf"^ac-restore-drill-{TOKEN_PATTERN}$")
DATABASE_PATTERN = re.compile(rf"^ac_restore_drill_{TOKEN_PATTERN}$")
ROLE_PATTERN = re.compile(rf"^ac_restore_owner_{TOKEN_PATTERN}$")


class ProbeError(RuntimeError):
    """A safe, bounded failure from the recovery probe boundary."""


@dataclass(frozen=True, slots=True)
class ProbeTarget:
    """A URL proven to name one generated disposable restore target."""

    url: URL
    token: str


@dataclass(frozen=True, slots=True)
class ReconciliationSelection:
    job_ids: tuple[UUID, ...]
    outbox_event_ids: tuple[UUID, ...]
    actor_person_id: UUID
    tenant_id: UUID
    reason: str


def validate_probe_target(raw_url: str | None, acknowledgement: str | None) -> ProbeTarget:
    """Reject every URL except the generated, token-matched drill identity."""

    if acknowledgement != ACKNOWLEDGEMENT_VALUE:
        raise ProbeError("explicit isolated restore-drill acknowledgement is required")
    if raw_url is None or not raw_url.strip():
        raise ProbeError("restore-drill database URL is required")
    try:
        url = make_url(raw_url)
    except ArgumentError as error:
        raise ProbeError("restore-drill database URL is invalid") from error
    if url.drivername != "postgresql+psycopg":
        raise ProbeError("restore-drill database driver is not allowed")
    if url.port != 5432 or url.query:
        raise ProbeError("restore-drill database endpoint is not canonical")
    if url.password is None or not url.password:
        raise ProbeError("restore-drill database password is required")
    host_match = HOST_PATTERN.fullmatch(url.host or "")
    database_match = DATABASE_PATTERN.fullmatch(url.database or "")
    role_match = ROLE_PATTERN.fullmatch(url.username or "")
    if host_match is None or database_match is None or role_match is None:
        raise ProbeError("database endpoint is not an isolated restore-drill identity")
    tokens = {
        host_match.group("token"),
        database_match.group("token"),
        role_match.group("token"),
    }
    if len(tokens) != 1:
        raise ProbeError("restore-drill database identities do not share one token")
    return ProbeTarget(url=url, token=tokens.pop())


def _selection_from_args(args: argparse.Namespace) -> ReconciliationSelection:
    job_ids = tuple(args.job_id or ())
    event_ids = tuple(args.outbox_event_id or ())
    if not job_ids and not event_ids:
        raise ProbeError("selected reconciliation requires at least one record")
    if len(job_ids) + len(event_ids) > MAX_RELEASE_SET_SIZE:
        raise ProbeError("selected reconciliation exceeds the bounded set size")
    if len(set(job_ids)) != len(job_ids) or len(set(event_ids)) != len(event_ids):
        raise ProbeError("selected reconciliation contains duplicate IDs")
    if not args.acknowledge_selected_reconciliation:
        raise ProbeError("selected reconciliation acknowledgement is required")
    reason = args.reason.strip()
    if not reason or len(reason) > 500:
        raise ProbeError("selected reconciliation reason is invalid")
    return ReconciliationSelection(
        job_ids=job_ids,
        outbox_event_ids=event_ids,
        actor_person_id=args.actor_person_id,
        tenant_id=args.tenant_id,
        reason=reason,
    )


async def mark_and_prove(target: ProbeTarget, *, reason: str) -> dict[str, object]:
    """Use the sanctioned marker, then prove the held worker calls no provider."""

    normalized_reason = reason.strip()
    if not normalized_reason or len(normalized_reason) > 500:
        raise ProbeError("restore marker reason is invalid")
    engine = create_async_engine(target.url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    provider_calls = 0

    async def provider_must_not_be_called(_prepared: PreparedDispatch) -> DeliveryReceipt:
        nonlocal provider_calls
        provider_calls += 1
        raise ProbeError("provider dispatch was attempted while restore hold was active")

    try:
        async with sessions() as session, session.begin():
            state, held_outbox, held_jobs = await mark_database_restore(
                session,
                reason=normalized_reason,
            )
            marker = {
                "generation": state.generation,
                "status": state.status,
                "held_outbox": held_outbox,
                "held_jobs": held_jobs,
            }

        worker = DurableWorker(
            sessions,
            dispatcher=AllowlistedDispatcher({ENROLLMENT_WELCOME_JOB: provider_must_not_be_called}),
            settings=SimpleNamespace(external_side_effects_hold=False),
            poll_interval=0,
        )
        ready = await worker.prepare()
        run_once_rejected = False
        try:
            await worker.run_once()
        except WorkerNotReadyError:
            run_once_rejected = True
        if ready or not run_once_rejected or provider_calls != 0:
            raise ProbeError("worker recovery hold proof failed")
        return {
            "action": "mark-and-prove",
            "restore_marker": marker,
            "worker_hold_proof": {
                "worker_ready": ready,
                "run_once_rejected": run_once_rejected,
                "provider_calls": provider_calls,
            },
        }
    finally:
        await engine.dispose()


async def reconcile_selected(
    target: ProbeTarget,
    selection: ReconciliationSelection,
) -> dict[str, object]:
    """Release only the explicitly selected held set through repository policy."""

    engine = create_async_engine(target.url, pool_pre_ping=True)
    sessions: async_sessionmaker[AsyncSession] = async_sessionmaker(
        engine,
        expire_on_commit=False,
    )
    try:
        actor = ActorContext(
            person_id=selection.actor_person_id,
            session_id=uuid4(),
            tenant_id=selection.tenant_id,
            permissions=frozenset({"recovery_reconcile"}),
        )
        async with sessions() as session, session.begin():
            events, jobs = await reconcile_operations(
                session,
                outbox_event_ids=selection.outbox_event_ids,
                job_ids=selection.job_ids,
                actor=actor,
                reason=selection.reason,
            )
            state = await RecoveryStateRepository(session).get()
            if state is None:
                raise ProbeError("durable recovery state is missing after reconciliation")
            recovery = {"generation": state.generation, "status": state.status}
        return {
            "action": "reconcile-selected",
            "job_ids": [str(job.id) for job in jobs],
            "outbox_event_ids": [str(event.id) for event in events],
            "recovery_state": recovery,
        }
    finally:
        await engine.dispose()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    marker = actions.add_parser("mark-and-prove")
    marker.add_argument("--reason", required=True)

    reconcile = actions.add_parser("reconcile-selected")
    reconcile.add_argument("--job-id", action="append", type=UUID)
    reconcile.add_argument("--outbox-event-id", action="append", type=UUID)
    reconcile.add_argument("--actor-person-id", required=True, type=UUID)
    reconcile.add_argument("--tenant-id", required=True, type=UUID)
    reconcile.add_argument("--reason", required=True)
    reconcile.add_argument("--acknowledge-selected-reconciliation", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        target = validate_probe_target(
            os.getenv(DATABASE_URL_ENV),
            os.getenv(ACKNOWLEDGEMENT_ENV),
        )
        # Worker/SQL libraries may log to standard streams.  Discard those
        # streams so the container emits exactly one fixed-shape safe JSON line.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            if args.action == "mark-and-prove":
                result = asyncio.run(mark_and_prove(target, reason=args.reason))
            else:
                selection = _selection_from_args(args)
                result = asyncio.run(reconcile_selected(target, selection))
        print(json.dumps(result, separators=(",", ":"), sort_keys=True))
        return 0
    except ProbeError as error:
        print(f"restore drill probe failed closed: {error}", file=sys.stderr)
        return 2
    except Exception as error:  # pragma: no cover - live dependency failure
        print(
            f"restore drill probe failed closed: unexpected {type(error).__name__}",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
