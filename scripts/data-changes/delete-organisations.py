"""Delete owner-approved organisations (owner, orchestrator chat 31 Oct 2026: "Approve delete:
both lists"). Dry run unless --apply; --read reads back. One transaction per organisation.

Approved, and nothing else (full id, and the sha256 of the approved name so names stay out of
code): on dev the four old-model sandbox organisations 114f3e0f, 349e94a3, b36c86a7 and
5505b9fb; on production the old "AC Sandbox" 67a697a5. Any other id, a changed name, an
unregistered or protected tenant, or another environment is refused before anything is read
further.

Run inside that environment's API runtime (its own code, settings and database):

    dev:        python - --environment dev [--apply | --read]          < delete-organisations.py
    production: docker exec -i ac-application-production-api-1 \
                  python - --environment production --dry-run          < delete-organisations.py

What deleting an organisation does, through the app's own rules:

- Calls: each live recording gets the app's own erasure (the conversation application's owner
  deletion, which queues DELETE_JOB); the worker removes audio and payloads and keeps the
  tombstone. While any call is still erasing, a run stops after requesting erasure: run --apply
  again once --read shows no call waiting. Nothing else changes before then.
- Leads: lead_desk.deletion.remove (the app's lead delete), then every other lead desk row of
  the organisation (sources, settings, reps, tasks, meetings, digests, devices and the rest).
- Access: pending invites revoked, memberships ended (their rows stay, since dozens of tables
  reference them), and the tenant marked deleted, so sign-in, workspace lists and Sales X-Ray
  no longer resolve it.
- Kept untouched: audit history (plus one event per run naming the approver and the time), bug
  reports, feedback and notifications (append-only; they stay valid because the tenant row
  stays), call tombstones, usage and job history, the sandbox marker and synthetic records, and
  the registry row.

Prints ids, table names and counts only; never names, emails or content.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Table, delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

APPROVER = 'Owner (Suyash Kulkarni), orchestrator chat 31 Oct 2026: "Approve delete: both lists"'
APPROVED_ON = "2026-10-31"
WORK = "organisation-delete-20261031"
ACTION_ERASE = "data_change.organisation_deletion_calls_erasing"
ACTION_DONE = "data_change.organisation_deleted"
ENVIRONMENTS = {"dev": "development", "production": "production"}
# Each approved organisation: its full id and the sha256 of its approved name.
APPROVED: dict[str, dict[UUID, str]] = {
    "development": {
        # The dev sales sandboxes' old-model copies (two each).
        UUID("114f3e0f-baf5-4b61-9ce0-6d5aa8887cd9"): (
            "580b1861e88c3294b78ac0907b953046ac323ce0ac17ca0d68a7b707eb54726f"
        ),
        UUID("349e94a3-47c6-4f42-a57d-663404fce571"): (
            "778ec1d351d11bffdd0003ebb088ebad1e4110b6f8845223715ee9474967cbdf"
        ),
        UUID("b36c86a7-b964-4d7b-840e-3dd3ae80d777"): (
            "052841cc6c4d303fb8c5c48f68741548898b518d16ba7a0f457ec536c9a1fbe9"
        ),
        UUID("5505b9fb-80d3-45b0-b0f4-9b7b9d1b0bfe"): (
            "0ebc2be0ec78c218a8115019acf61ae72aa1e013b1f72236c9be9486b7a6419c"
        ),
    },
    "production": {
        # The old AC Sandbox, never "AC Sales Sandbox" (3100ddbc) or the persona-test sandbox.
        UUID("67a697a5-99d3-493c-93f2-b372d483d354"): (
            "36a00083c08952ee0df0730401ba45da2904592a948798eb6d4e2babd2c4558a"
        ),
    },
}
LEAD_CHUNK = 500
# Lead desk rows without a tenant column, reached through their tenant-keyed parent.
CHILDREN = {
    "lead_desk_conversion_attempts": ("lead_desk_conversions", "conversion_id"),
    "lead_desk_meta_conversion_attempts": (
        "lead_desk_meta_conversions",
        "conversion_id",
    ),
}
SAFE_CODES = frozenset(
    {
        "refused_environment",
        "refused_unlisted",
        "refused_missing",
        "refused_protected",
        "refused_name",
        "refused_not_organisation",
        "refused_status",
        "refused_actor_binding",
        "refused_runtime",
    }
)


class Refused(ValueError):
    """A content-free reason nothing was changed for an organisation."""


def name_digest(name: str) -> str:
    return hashlib.sha256(name.encode()).hexdigest()


def environment_of(flag: str, runtime: str) -> str:
    """The approved list for --environment, only inside that environment's runtime."""
    environment = ENVIRONMENTS.get(flag)
    if environment is None or environment != runtime:
        raise Refused("refused_environment")
    return environment


def targets(environment: str, picks: Sequence[str] = ()) -> list[UUID]:
    """The approved ids to act on: all of them, or those whole-prefix picks name exactly."""
    approved = APPROVED.get(environment)
    if not approved:
        raise Refused("refused_environment")
    if not picks:
        return sorted(approved, key=str)
    chosen: list[UUID] = []
    for pick in picks:
        pick = pick.strip().lower()
        hits = [tenant for tenant in approved if str(tenant).startswith(pick)]
        if len(pick) < 8 or len(hits) != 1:
            raise Refused("refused_unlisted")
        if hits[0] not in chosen:
            chosen.append(hits[0])
    return chosen


def check(
    environment: str,
    tenant_id: UUID,
    *,
    name: str | None,
    registered: bool,
    protected: Iterable[UUID | None],
) -> None:
    """Refuse anything but an approved, registered organisation under its approved name."""
    approved = APPROVED.get(environment) or {}
    if tenant_id not in approved:
        raise Refused("refused_unlisted")
    if tenant_id in set(protected):
        raise Refused("refused_protected")
    if name is None:
        raise Refused("refused_missing")
    if name_digest(name) != approved[tenant_id]:
        raise Refused("refused_name")
    if not registered:
        raise Refused("refused_not_organisation")


def decide(status: str, *, live_calls: int, erasing_calls: int) -> str:
    """What --apply does next for one approved organisation."""
    if status == "deleted":
        return "already_deleted"
    if status != "active":
        raise Refused("refused_status")
    if live_calls:
        return "request_erasure"
    if erasing_calls:
        return "wait_for_erasure"
    return "finish"


def _metadata() -> Any:
    from ac_platform.db.models import model_metadata

    return model_metadata()


def tenant_tables(metadata: Any) -> list[Table]:
    """Every registered table with a tenant column, parents before children."""
    return [table for table in metadata.sorted_tables if "tenant_id" in table.c]


def lead_desk_tables(metadata: Any) -> list[Table]:
    """The organisation's lead desk tables, children before parents (FK-safe deletes)."""
    return [
        table for table in reversed(tenant_tables(metadata)) if table.name.startswith("lead_desk_")
    ]


async def counts(db: AsyncSession, tenant_id: UUID, tables: Sequence[Table]) -> dict[str, Any]:
    """Rows per table (non-zero only), calls by state and access, as counts only."""
    from ac_platform.conversation_intelligence.models import ConversationRecording
    from ac_platform.tenancy.models import Membership, OrganisationInvite

    rows: dict[str, int] = {}
    for table in tables:
        found = int(
            await db.scalar(
                select(func.count()).select_from(table).where(table.c.tenant_id == tenant_id)
            )
            or 0
        )
        if found:
            rows[table.name] = found
    states = dict(
        (
            await db.execute(
                select(ConversationRecording.state, func.count())
                .where(ConversationRecording.tenant_id == tenant_id)
                .group_by(ConversationRecording.state)
            )
        ).all()
    )
    erasing = int(states.get("deleting", 0))
    erased = int(states.get("deleted", 0))
    active_members = await db.scalar(
        select(func.count())
        .select_from(Membership)
        .where(
            Membership.tenant_id == tenant_id,
            Membership.status == "active",
            Membership.ended_at.is_(None),
        )
    )
    pending_invites = await db.scalar(
        select(func.count())
        .select_from(OrganisationInvite)
        .where(
            OrganisationInvite.tenant_id == tenant_id,
            OrganisationInvite.status == "pending",
        )
    )
    return {
        "rows": rows,
        "calls": {
            "live": sum(int(n) for n in states.values()) - erasing - erased,
            "erasing": erasing,
            "erased": erased,
        },
        "active_members": int(active_members or 0),
        "pending_invites": int(pending_invites or 0),
    }


def _chunks(values: Sequence[UUID], size: int) -> Iterable[Sequence[UUID]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


async def _request_erasure(db: AsyncSession, tenant_id: UUID) -> int:
    """The app's own owner deletion for each live call; the worker erases them."""
    from ac_platform.conversation_intelligence.application import (
        ConversationApplication,
    )
    from ac_platform.conversation_intelligence.guest_models import (
        ConversationGuestSubmission,
    )
    from ac_platform.conversation_intelligence.models import ConversationRecording
    from ac_platform.conversation_intelligence.processing_actor import ProcessingActor

    recordings = list(
        await db.scalars(
            select(ConversationRecording)
            .where(
                ConversationRecording.tenant_id == tenant_id,
                ConversationRecording.state.not_in(("deleting", "deleted")),
            )
            .order_by(ConversationRecording.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    links = {
        link.recording_id: link
        for link in await db.scalars(
            select(ConversationGuestSubmission).where(
                ConversationGuestSubmission.tenant_id == tenant_id,
                ConversationGuestSubmission.recording_id.in_([r.id for r in recordings]),
            )
        )
    }
    # Every live call must have its owner binding before the first deletion request.
    if any(recording.id not in links for recording in recordings):
        raise Refused("refused_actor_binding")
    app = ConversationApplication(db)
    for recording in recordings:
        link = links[recording.id]
        await app._request_owned_deletion(
            ProcessingActor(link.person_id, link.tenant_id, link.processing_lease_id),
            recording,
            key=f"{WORK}:{recording.id}",
            now=app.clock(),
        )
    await db.flush()
    return len(recordings)


async def _finish(
    db: AsyncSession, tenant_id: UUID, metadata: Any, now: datetime
) -> dict[str, Any]:
    """Remove the lead desk, end access and mark the tenant deleted (calls already erased)."""
    from ac_platform.lead_desk import deletion
    from ac_platform.lead_desk.models import Lead
    from ac_platform.tenancy.models import Membership, OrganisationInvite

    quiet = {"synchronize_session": False}
    lead_ids = list(
        await db.scalars(
            select(Lead.id).where(Lead.tenant_id == tenant_id).order_by(Lead.id).with_for_update()
        )
    )
    leads: dict[str, dict[str, int]] = {"removed": {}, "emptied": {}, "kept": {}}
    for chunk in _chunks(lead_ids, LEAD_CHUNK):
        removal = await deletion.remove(db, tenant_id, chunk, now)
        for part in leads:
            for key, value in getattr(removal, part).items():
                leads[part][key] = leads[part].get(key, 0) + value
    tables = metadata.tables
    for child, (parent, column) in CHILDREN.items():
        if child in tables and parent in tables:
            await db.execute(
                delete(tables[child])
                .where(
                    tables[child]
                    .c[column]
                    .in_(select(tables[parent].c.id).where(tables[parent].c.tenant_id == tenant_id))
                )
                .execution_options(**quiet)
            )
    for table in lead_desk_tables(metadata):
        await db.execute(
            delete(table).where(table.c.tenant_id == tenant_id).execution_options(**quiet)
        )
    await db.execute(
        update(OrganisationInvite)
        .where(
            OrganisationInvite.tenant_id == tenant_id,
            OrganisationInvite.status == "pending",
        )
        .values(status="revoked", closed_at=now)
        .execution_options(**quiet)
    )
    await db.execute(
        update(Membership)
        .where(
            Membership.tenant_id == tenant_id,
            Membership.status == "active",
            Membership.ended_at.is_(None),
        )
        .values(status="inactive", ended_at=now, revision=Membership.revision + 1)
        .execution_options(**quiet)
    )
    return leads


async def execute_one(
    sessions: Callable[[], Any],
    tenant_id: UUID,
    *,
    environment: str,
    mode: str,
    protected: Iterable[UUID | None],
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, Any]:
    """One organisation in one transaction. ``mode`` is dry-run, read or apply."""
    from ac_platform.audit.service import append_audit_event
    from ac_platform.tenancy.models import Organisation, Tenant

    apply = mode == "apply"
    metadata = _metadata()
    tables = tenant_tables(metadata)
    async with sessions() as db, db.begin():
        if not apply and db.get_bind().dialect.name == "postgresql":
            # A dry run and a read can't write, whatever the code below does.
            await db.execute(text("SET TRANSACTION READ ONLY"))
        statement = select(Tenant).where(Tenant.id == tenant_id)
        if apply:
            statement = statement.with_for_update()
        tenant = await db.scalar(statement.execution_options(populate_existing=True))
        registered = await db.get(Organisation, tenant_id) is not None
        check(
            environment,
            tenant_id,
            name=None if tenant is None else tenant.name,
            registered=registered,
            protected=protected,
        )
        assert tenant is not None
        before = await counts(db, tenant_id, tables)
        phase = decide(
            tenant.status,
            live_calls=before["calls"]["live"],
            erasing_calls=before["calls"]["erasing"],
        )
        result: dict[str, Any] = {
            "mode": mode,
            "tenant": str(tenant_id),
            "status": tenant.status,
            "next": phase,
            "before": before,
        }
        if not apply or phase in {"already_deleted", "wait_for_erasure"}:
            return result
        at = now()
        if phase == "request_erasure":
            result["erasure_requested"] = await _request_erasure(db, tenant_id)
            action = ACTION_ERASE
        else:
            result["leads"] = await _finish(db, tenant_id, metadata, at)
            tenant.status = "deleted"
            tenant.revision += 1
            action = ACTION_DONE
        await db.flush()
        after = await counts(db, tenant_id, tables)
        result["after"] = after
        await append_audit_event(
            db,
            tenant_id=tenant_id,
            actor_person_id=None,
            actor_type="operator",
            action=action,
            resource_type="organisation",
            resource_id=tenant_id,
            payload={
                "approved_on": APPROVED_ON,
                "applied_at": at.isoformat(),
                "before": before,
                "after": after,
            },
            reason=APPROVER,
            request_id=f"{WORK}:{tenant_id}:{phase}",
        )
        return result


async def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Delete owner-approved organisations.")
    parser.add_argument("--environment", required=True, choices=sorted(ENVIRONMENTS))
    parser.add_argument("--tenant", action="append", default=[], help="an approved id prefix")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--dry-run", action="store_true", help="the default: count, change nothing")
    modes.add_argument("--apply", action="store_true")
    modes.add_argument("--read", action="store_true", help="read back after an apply")
    args = parser.parse_args(argv)
    mode = "apply" if args.apply else "read" if args.read else "dry-run"

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from ac_platform.application.settings import get_settings

    settings = get_settings()
    environment = environment_of(args.environment, settings.environment)
    chosen = targets(environment, args.tenant)
    protected = (settings.operations_tenant_id, settings.public_learner_tenant_id)
    engine = create_async_engine(settings.database_url)
    failed = 0
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        for tenant_id in chosen:
            try:
                result = await execute_one(
                    sessions,
                    tenant_id,
                    environment=environment,
                    mode=mode,
                    protected=protected,
                )
            except Refused as refusal:
                failed += 1
                result = {
                    "mode": mode,
                    "tenant": str(tenant_id),
                    "refused": str(refusal),
                }
            print(json.dumps(result, sort_keys=True))
    finally:
        await engine.dispose()
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Refused as refusal:
        print(json.dumps({"refused": str(refusal)}))
        raise SystemExit(1) from None
    except SystemExit:
        raise
    except Exception as error:
        # Database errors can quote row values; print only the error's type.
        print(json.dumps({"refused": "refused_runtime", "error": type(error).__name__}))
        raise SystemExit(1) from None
