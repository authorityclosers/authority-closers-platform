#!/usr/bin/env python3
"""Review checkpoint 2026-10-21: close the unjudged gold assignments, cancel their Pulse subtasks.

The owner's approval, 21 Oct 2026 (relayed by the orchestrator), verbatim, is ``APPROVAL``
below. The coaching lead saved no review in the app; the owner wants a clean start from this
checkpoint. Owner-approved data change (AGENTS.md): dry run by default, before and after
printed, one transaction per part and environment, idempotent, audited with the approver and
the approval. Nothing is deleted.

Two parts:

- ``sales-xray``, inside the deployed API container of an environment. Each listed gold
  assignment that is still open with no saved line is revoked through Admin's own revoke
  (``ConversationReviewService.revoke``: a revocation row and its receipt), then one audit
  event ``review.checkpoint_reset`` names the approver, the approval and the ids closed and
  skipped. The assignments, their links and history stay. The gold reviewer designation
  stays, so new calls are assigned to him as before. Acts as the AC control account named by
  ``--control-email``, through its newest current Admin session in the operations workspace.

      docker exec -i ac-application-production-api-1 python - \\
        --environment production --allow-production --control-email <control account> \\
        --issue <AUT issue> sales-xray [--apply] \\
        < scripts/data-changes/review-checkpoint-reset-20261021.py

- ``pulse``, on the host as root, as ac-pulse-gold-bridge runs (production only). The
  subtasks the bridge made for the production assignments (found by the review link in
  their notes, as the bridge finds them) are moved to cancelled with the reason, after a
  Pulse backup. The parent task stays. The bridge's state marks them cancelled, so it never
  touches them again.

      sudo python3 scripts/data-changes/review-checkpoint-reset-20261021.py \\
        --environment production --allow-production --issue <AUT issue> pulse [--apply]

Order: development, then production (database snapshot first; the dry run shown first).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import subprocess
import sys
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any, Final
from uuid import UUID

APPROVER: Final = "Suyash Kulkarni (owner, relayed by the orchestrator)"
APPROVAL: Final = (
    "approve data change: close the 61 unjudged gold assignments and cancel their 61 Pulse "
    'subtasks on production, and close the 35 dev assignments, reason "checkpoint 2026-10-21 '
    'reset" (records and audit kept; Dipak stays the reviewer for new calls)'
)
REASON: Final = "checkpoint 2026-10-21 reset"
DATA_CHANGE: Final = "scripts/data-changes/review-checkpoint-reset-20261021.py"
OPERATOR: Final = "claude-laptop:review-checkpoint-reset-20261021"
ACTION: Final = "review.checkpoint_reset"
KEY_PREFIX: Final = "checkpoint-2026-10-21"

# Read 21 Oct 2026 (read-only): every gold assignment of each environment, none judged.
ASSIGNMENTS: Final[dict[str, tuple[str, ...]]] = {
    "production": (
        "4065b268-35d8-4e4e-9891-cd7ff2a1d4c4",
        "50da0c52-f636-43a9-aa98-1893c752ecfe",
        "c9dc5efb-4415-4c92-84fa-9b42789ed7f7",
        "e8eb3aeb-4928-464f-9919-e3e0d8a0ed91",
        "4bad6dd5-ecce-4a52-82b0-4cf74b27c74a",
        "5723a27b-276a-41a1-82d1-ee79612e2fcc",
        "d0fd66d2-ea3f-48ce-bd91-a859ad3ae38c",
        "71ec4e0c-a853-4e89-9d4f-187bff3302c2",
        "1a943510-f3c5-42ea-9ff5-a45fd9bfd8bf",
        "138de7c1-6712-4148-9220-d5907315cf1d",
        "09e1e554-f9be-4161-b4ee-2e5f0b572f07",
        "afeed8bb-4b6a-4500-a4f5-933644ef5a62",
        "065578a5-9f54-4faf-a6e2-d3e28ca8c5e4",
        "e96ed3b0-303f-4b1e-8cab-5ca3196058cd",
        "16e9eb22-0186-4e8b-9d09-9cdb18a4d344",
        "d4d2ab28-ece8-4998-9fac-a108c7898b6e",
        "31524c58-0bac-4d73-aa08-665e419b3d7f",
        "5a1da359-ce25-443b-9ce2-b3afc203b6ee",
        "084e5e33-7d5e-4ea9-8755-5f92ad4107d1",
        "2fc83d2a-0722-4381-9b9d-a783a854600f",
        "3efa3dfa-cbcd-4c72-9adf-442cc0b3934b",
        "2a76620a-58a2-4eb7-b12f-9a915398c7df",
        "ba5d00eb-6e59-4219-8b82-a544266696d1",
        "4b9ad4ad-881d-482d-a803-de0485356004",
        "f1f19674-7fc8-42ba-b623-5bce70ed52b4",
        "feaf9f5a-4b33-45d2-b388-fef6b1385368",
        "c319e16c-d7e8-4e3f-8ab2-5d4edd5a6fe1",
        "ba78b721-373a-4f9c-b175-a00f88e70471",
        "896c262e-96b2-476d-967a-7536a2400e09",
        "bf845f78-b76d-4407-bcec-d05c0fc333e7",
        "e1aaf408-cdca-4b10-8e21-91dbe85d9df1",
        "be315ed7-9282-48cc-9c2a-49630e5ecefd",
        "ec63e3fa-53be-498a-9266-85f20dd2a3c3",
        "083242b0-9521-4b53-a5c7-160384e1add6",
        "aeb97f3f-00a2-4167-b892-3dc690cf1aef",
        "1fe79c11-9f8e-4439-b20a-f564b44828d1",
        "69d5cb81-c4e0-4f97-8d6d-672f43cecf50",
        "13056a30-7f51-4a00-af11-bf658df261f8",
        "32d1ac1a-ab42-435d-856e-d23f2b4e3714",
        "07c53802-ba1a-432f-8694-3cbf8f9a2d8b",
        "fac90c8f-77a2-4b62-ba8c-d64816d6caf9",
        "fe888d8b-2522-4f1c-a919-2e664a3e78f4",
        "ef05f2f5-8506-4570-8df9-c778352a5f82",
        "08cc612d-e92e-483b-a3e2-ebbc83e62eb7",
        "7ab47818-abb7-4002-bd81-e36b459b0d3e",
        "191d9c74-de43-4de7-a118-8ec82577c7eb",
        "dae10dc9-aa31-467b-9e82-cf73ea1dd1c7",
        "7e6bc180-93db-4628-b14a-808f89cde626",
        "c9546909-6701-4513-ae8e-4d509631d928",
        "a92d80be-88d6-4ce1-b3db-7a11d370e125",
        "aa1ac8ef-bda7-47d7-a505-40fbbd1a9c35",
        "a0bbc092-7764-4132-a8ac-51dbc7de540d",
        "6e624a45-aeb4-4cf9-9807-53e3b374c099",
        "240829a6-c1fe-4fd3-884f-ff7cada72b09",
        "c737f78c-7262-4611-8ea9-560c7e895cc6",
        "25e9eb1a-2cb2-49fb-b469-c15ff95f89b4",
        "8ebfc32c-6332-4998-bb39-23e32fdf4697",
        "adcb12c3-fdb8-499d-baaa-b55b2e86c46a",
        "e7f2c01b-83cd-4721-a440-364678c74231",
        "999976c9-ab44-4dfd-bbb6-aca5af7d5e30",
        "2c428af6-4cf0-48a4-a29a-f015e8b91f44",
    ),
    "development": (
        "8fb3205f-99db-434b-ab32-534f76f88e3a",
        "59356a40-5f6c-4db1-80c5-62cec415baa4",
        "83184053-d290-4919-8b9c-8a9cf848ca32",
        "72515188-37a0-42fb-a892-6ca9230f8469",
        "5f2db0bc-61e4-47e2-84e8-7106f73496c0",
        "e270d356-5407-4d04-8fce-b0b9b5fab07b",
        "ece49a53-08d5-47c7-8400-0ff95d902fa1",
        "1a5b72f7-8b1c-4b24-8cf9-f4e3629ed1fe",
        "cb1a9c8c-c9ab-4693-9957-d8c9491f77a0",
        "d36210df-4bfd-46b5-81ad-a6f89ee1e2a2",
        "27f79d5f-86cd-4bd1-aa7b-f1a6f34f338e",
        "83dd01ca-ceeb-46d2-a91f-d01303abfc28",
        "8cdd27a8-07e6-4a92-b8a2-d7a70a46508f",
        "2653c74e-8fd4-4c43-bd13-add6d2ad3d4a",
        "0cd07524-9443-40e9-af5e-2dfd5e7afd35",
        "d2ee3573-f467-45d9-bc3d-1a2185614b5e",
        "e6226f48-4059-4eab-9430-76b43354c2b3",
        "97af409c-8466-4ce6-97be-48cac40220aa",
        "2e011e5e-e490-4693-be28-2be533df6cbe",
        "4d27e3f1-eec7-4c36-b111-9579b545799e",
        "713cc6cb-bbe1-46a1-9f2e-5709d1580026",
        "6aaff09c-6fc5-49c6-bcfb-bc80212a7536",
        "02d7313a-817e-4a7b-9f78-30dce2c5259b",
        "f2339229-d6f2-4186-a5f7-7516ed295e8e",
        "bd311ee7-27ee-4afe-b888-1e9475ab515e",
        "5eb2e271-c99e-4db5-87f2-91aee0c08959",
        "de43d109-8158-4ff8-b4e3-dd982a669959",
        "da7e7f38-3006-4b94-a007-fe2a1ae83bbb",
        "390e5884-c280-4801-ad07-b8bb1f75c6d9",
        "e0e2bd52-2915-49f4-a395-3d8020b435d2",
        "a44b5389-06e7-4a00-94b3-548ca7373689",
        "1d431e2d-320d-4b8f-9fe5-aa7c52d30a06",
        "6568723e-0129-4c7b-9cab-d68c345abc26",
        "c9041f92-70c0-4d98-a275-9f8ee851460f",
        "345c62cc-ea4b-46c8-9b9f-49cb9fd90afe",
    ),
}

# Pulse (production), as ac-pulse-gold-bridge reaches it.
KIT: Final = "/srv/authority-closers/pulse/kit"
PULSE_ENV: Final = "/etc/pulse/pulse.env"
BACKUPS: Final = pathlib.Path("/srv/authority-closers/pulse/backups")
BRIDGE_STATE: Final = pathlib.Path("/var/lib/ac-pulse-gold-bridge/bridged.json")
ADMIN: Final = "https://admin.authorityclosers.com"
PULSE_ACTOR: Final = "review-checkpoint-reset-20261021 (owner approval, 21 Oct 2026)"
PULSE_NOTE: Final = (
    "Closed at the review checkpoint 2026-10-21 (owner's approval): this call's review is "
    "retired; new calls arrive as new tasks."
)


class Refused(RuntimeError):
    """A stable, content-free reason the change was not made."""


class _DryRun(Exception):
    """Unwinds the transaction after a dry run."""


@dataclass(frozen=True)
class Command:
    environment: str
    issue: str
    control_email: str = ""
    apply: bool = False
    ids: tuple[str, ...] = field(default=())


def environment_of(name: str) -> str:
    value = name.strip().lower()
    if value in {"development", "development-live", "dev", "test"}:
        return "development"
    if value in {"staging", "production"}:
        return value
    raise Refused("unknown_environment")


def assignment_ids(environment: str) -> tuple[str, ...]:
    return ASSIGNMENTS.get(environment_of(environment), ())


# ---------- sales-xray ----------


async def _actor(database: Any, email: str, operations_tenant_id: UUID) -> Any:
    """The control account's newest current Admin session in the operations workspace."""
    from sqlalchemy import select

    from ac_platform.conversation_intelligence.provider_admin import CONTROL_ACCOUNTS
    from ac_platform.identity.models import Person
    from ac_platform.identity.models import Session as IdentitySession
    from ac_platform.kernel.authz import ActorContext

    wanted = email.strip().casefold()
    if wanted not in CONTROL_ACCOUNTS:
        raise Refused("control_email_is_not_a_provider_control_account")
    people = list(await database.scalars(select(Person).where(Person.email.ilike(wanted)).limit(2)))
    if len(people) != 1:
        raise Refused("exactly_one_person_must_match_the_control_email")
    session = await database.scalar(
        select(IdentitySession)
        .where(
            IdentitySession.person_id == people[0].id,
            IdentitySession.revoked_at.is_(None),
            IdentitySession.expires_at > dt.datetime.now(dt.UTC),
            IdentitySession.selected_tenant_id == operations_tenant_id,
        )
        .order_by(IdentitySession.created_at.desc())
        .limit(1)
    )
    if session is None:
        raise Refused("no_current_admin_session_sign_in_to_admin_once")
    return ActorContext(
        person_id=people[0].id,
        session_id=session.id,
        tenant_id=operations_tenant_id,
        permissions=frozenset({"admin_surface"}),
    )


async def states(database: Any, ids: tuple[str, ...], now: dt.datetime) -> dict[str, str]:
    """Each listed assignment: open, revoked, judged, expired or not_gold."""
    from sqlalchemy import func, select

    from ac_platform.conversation_intelligence.gold_review_models import GoldAssignment, GoldRow
    from ac_platform.conversation_intelligence.models import (
        ConversationReviewAssignment,
        ConversationReviewRevocation,
    )

    found: dict[str, str] = {}
    for identifier in ids:
        key = UUID(identifier)
        if await database.get(GoldAssignment, key) is None:
            found[identifier] = "not_gold"
        elif await database.get(ConversationReviewRevocation, key) is not None:
            found[identifier] = "revoked"
        elif await database.scalar(
            select(func.count())
            .select_from(GoldRow)
            .where(GoldRow.assignment_id == key, GoldRow.erased_at.is_(None))
        ):
            found[identifier] = "judged"
        else:
            row = await database.get(ConversationReviewAssignment, key)
            expires = row.expires_at if row is not None else None
            if expires is not None and expires.tzinfo is None:
                expires = expires.replace(tzinfo=dt.UTC)
            found[identifier] = "expired" if expires is not None and expires <= now else "open"
    return found


def _count(found: dict[str, str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for state in found.values():
        counts[state] = counts.get(state, 0) + 1
    return dict(sorted(counts.items()))


async def close(
    database: Any,
    command: Command,
    *,
    operations_tenant_id: UUID,
    actor: Any = None,
) -> dict[str, Any]:
    """Revoke the listed open assignments in the caller's transaction (commit only with --apply)."""
    from ac_platform.audit.service import AuditRepository
    from ac_platform.conversation_intelligence.application import ConversationApplication
    from ac_platform.conversation_intelligence.review_service import ConversationReviewService

    ids = command.ids or assignment_ids(command.environment)
    if not ids:
        raise Refused("no_assignments_listed_for_this_environment")
    if actor is None:
        actor = await _actor(database, command.control_email, operations_tenant_id)
    now = dt.datetime.now(dt.UTC)
    before = await states(database, ids, now)
    service = ConversationReviewService(
        ConversationApplication(database), operations_tenant_id=operations_tenant_id
    )
    closed = [identifier for identifier in ids if before[identifier] == "open"]
    for identifier in closed:
        await service.revoke(actor, UUID(identifier), f"{KEY_PREFIX}:{identifier}")
    after = await states(database, ids, now)
    result: dict[str, Any] = {
        "part": "sales-xray",
        "environment": environment_of(command.environment),
        "listed": len(ids),
        "before": _count(before),
        "after": _count(after),
        "closed": len(closed),
    }
    if not closed:
        return {**result, "status": "no_op"}
    if not command.apply:
        return {**result, "status": "dry_run"}
    await AuditRepository(database).append_for_actor(
        actor,
        action=ACTION,
        resource_type="conversation_gold_assignments",
        resource_id=KEY_PREFIX,
        payload={
            "reason": REASON,
            "closed": closed,
            "skipped": {k: v for k, v in before.items() if v != "open"},
            "approval": {
                "approver": APPROVER,
                "approval": APPROVAL,
                "issue": command.issue,
                "data_change": DATA_CHANGE,
                "operator": OPERATOR,
            },
        },
        reason=REASON,
    )
    return {**result, "status": "applied"}


async def _run(command: Command, settings: Any) -> dict[str, Any]:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(settings.database_url, pool_pre_ping=True, hide_parameters=True)
    result: dict[str, Any] = {}
    try:
        async with async_sessionmaker(engine, expire_on_commit=False, autoflush=False)() as db:
            try:
                async with db.begin():
                    result = await close(
                        db, command, operations_tenant_id=settings.operations_tenant_id
                    )
                    if result["status"] != "applied":
                        raise _DryRun
            except _DryRun:
                pass
        return result
    finally:
        await engine.dispose()


# ---------- pulse ----------


def markers(ids: tuple[str, ...]) -> list[str]:
    """The review link the bridge puts in each subtask's notes (its marker)."""
    return [f"{ADMIN}/reviewer/review/{identifier}" for identifier in ids]


PULSE_SQL: Final = """
begin;
set local role pulse_owner;
select org_id as org from pulse.install limit 1 \\gset
select set_config('pulse.org_id', :'org', true) \\g /dev/null
select person_id as me from pulse.people_profile
 where org_id = :'org' and username = 'suyash' \\gset
select set_config('pulse.viewer_id', :'me', true) \\g /dev/null
select set_config('pulse.actor_account', :'actor', true) \\g /dev/null
select 'before', t.status, count(*) from pulse.task t
 where t.deleted_at is null and t.parent_id is not null
   and exists (select 1 from jsonb_array_elements_text(:'markers'::jsonb) m
                where position(m in coalesce(t.notes, '')) > 0)
 group by t.status order by t.status;
select 'cancelled', count(pulse.task_move(t.id, 'cancelled', :'note')) from pulse.task t
 where t.deleted_at is null and t.parent_id is not null
   and exists (select 1 from jsonb_array_elements_text(:'markers'::jsonb) m
                where position(m in coalesce(t.notes, '')) > 0)
   and t.status not in ('done', 'cancelled');
select 'after', t.status, count(*) from pulse.task t
 where t.deleted_at is null and t.parent_id is not null
   and exists (select 1 from jsonb_array_elements_text(:'markers'::jsonb) m
                where position(m in coalesce(t.notes, '')) > 0)
 group by t.status order by t.status;
"""


def pulse_sql(apply: bool) -> str:
    return PULSE_SQL + ("commit;\n" if apply else "rollback;\n")


def _pulse_psql(sql: str, variables: dict[str, str]) -> str:
    args = [
        "docker",
        "compose",
        "--env-file",
        PULSE_ENV,
        "exec",
        "-T",
        "postgres",
        "psql",
        "-U",
        "pulse_admin",
        "-d",
        "pulse",
        "-At",
        "-F",
        "\t",
        "-v",
        "ON_ERROR_STOP=1",
    ]
    for key, value in variables.items():
        args += ["-v", f"{key}={value}"]
    # Fixed argv, no shell, as ac-pulse-gold-bridge runs it.
    out = subprocess.run(  # noqa: S603
        args, cwd=KIT, input=sql, capture_output=True, text=True, check=False
    )
    if out.returncode:
        raise Refused("pulse_psql_failed")
    return out.stdout


def _pulse_backup(now: dt.datetime) -> str:
    backup = BACKUPS / f"pulse-{now:%Y%m%dT%H%M%SZ}-before-review-checkpoint-reset.sql.gz"
    with backup.open("wb") as handle:
        dump = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
            [  # noqa: S607 - the host's docker, as the bridge uses it
                "docker",
                "compose",
                "--env-file",
                PULSE_ENV,
                "exec",
                "-T",
                "postgres",
                "pg_dump",
                "-U",
                "pulse_admin",
                "-d",
                "pulse",
                "--no-owner",
                "--no-privileges",
            ],
            cwd=KIT,
            stdout=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
        )
        subprocess.run(["gzip", "-6"], stdin=dump.stdout, stdout=handle, check=True)  # noqa: S607
        if dump.wait():
            raise Refused("pulse_backup_failed")
    return backup.name


def run_pulse(command: Command) -> dict[str, Any]:
    if environment_of(command.environment) != "production":
        raise Refused("pulse_subtasks_exist_on_production_only")
    ids = command.ids or assignment_ids("production")
    now = dt.datetime.now(dt.UTC)
    result: dict[str, Any] = {"part": "pulse", "listed": len(ids)}
    if command.apply:
        result["backup"] = _pulse_backup(now)
    out = _pulse_psql(
        pulse_sql(command.apply),
        {"actor": PULSE_ACTOR, "note": PULSE_NOTE, "markers": json.dumps(markers(ids))},
    )
    for line in out.splitlines():
        cells = line.split("\t")
        if cells[0] in ("before", "after") and len(cells) == 3:
            result.setdefault(cells[0], {})[cells[1]] = int(cells[2])
        elif cells[0] == "cancelled" and len(cells) == 2:
            result["cancelled"] = int(cells[1])
    result["status"] = "applied" if command.apply else "dry_run"
    if command.apply and BRIDGE_STATE.exists():
        state = json.loads(BRIDGE_STATE.read_text())
        for identifier in ids:
            if identifier in state:
                state[identifier] = "cancelled"
        BRIDGE_STATE.write_text(json.dumps(state, indent=1, sort_keys=True))
        result["bridge_state_cancelled"] = sum(1 for i in ids if state.get(i) == "cancelled")
    return result


# ---------- cli ----------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="review-checkpoint-reset-20261021", allow_abbrev=False)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--allow-production", action="store_true")
    parser.add_argument("--control-email", default="")
    parser.add_argument("--issue", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("part", choices=("sales-xray", "pulse"))
    return parser


def main(
    argv: list[str] | None = None,
    runner: Callable[..., Coroutine[Any, Any, dict[str, Any]]] | None = None,
) -> int:
    try:
        args = _parser().parse_args(argv)
        environment = environment_of(args.environment)
        if environment == "production" and not args.allow_production:
            raise Refused("production_requires_allow_production")
        if not 1 <= len(args.issue.strip()) <= 120:
            raise Refused("issue_is_required")
        command = Command(
            environment=environment,
            issue=args.issue.strip(),
            control_email=args.control_email,
            apply=bool(args.apply),
        )
        if args.part == "pulse":
            result = run_pulse(command)
        else:
            from ac_platform.application.asyncio_runtime import run_async
            from ac_platform.application.release_identity import require_baked_release_id
            from ac_platform.application.settings import Settings

            settings = Settings(_env_file=None)
            if environment_of(settings.environment) != environment:
                raise Refused("environment_must_match_the_container_settings")
            if settings.operations_tenant_id is None:
                raise Refused("an_explicit_operations_tenant_is_required")
            if environment in {"staging", "production"}:
                require_baked_release_id(settings.release_id)
            result = run_async((runner or _run)(command, settings))
    except Refused as refused:
        print(f"data change refused: {refused}", file=sys.stderr)
        return 2
    except (Exception, KeyboardInterrupt) as error:
        # Settings and driver failures can contain secrets; name the type only.
        print(f"data change failed: {type(error).__name__}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, default=str, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
