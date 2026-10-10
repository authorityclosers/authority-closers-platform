#!/usr/bin/env python3
"""Preview/apply an exact owner-approved staging organisation change (AUT-1694).

Approval and snapshot references record independently verified authority. They
do not grant it. Run only as the named operator, outside any release.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import NoReturn
from uuid import UUID, uuid5

from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.application.asyncio_runtime import run_async
from ac_platform.application.release_identity import require_baked_release_id
from ac_platform.application.settings import Settings
from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import append_audit_event
from ac_platform.conversation_intelligence.application import ConversationApplication
from ac_platform.conversation_intelligence.guest_models import ConversationGuestSubmission
from ac_platform.conversation_intelligence.models import ConversationRecording
from ac_platform.conversation_intelligence.processing_actor import ProcessingActor
from ac_platform.identity.models import Person
from ac_platform.identity.services import normalize_email
from ac_platform.kernel.errors import DomainError
from ac_platform.organisations.invitations import active_pending_invites
from ac_platform.organisations.service import OrganisationCommandError, OrganisationService
from ac_platform.tenancy.models import Membership, Organisation, Tenant


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise OrganisationCommandError("invalid arguments; use --help")


class ResultDeliveryError(RuntimeError):
    """The transaction committed, but its JSON receipt could not be delivered."""


def _reference(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}", value):
        raise ValueError("a reference ID without credentials or personal data is required")
    return value


def _target(value: str) -> UUID | str:
    return normalize_email(value).lower() if "@" in value else UUID(value)


def _parser() -> argparse.ArgumentParser:
    parser = SafeParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("action", choices=("add-members", "remove-members", "delete-recordings"))
    parser.add_argument("--environment", choices=("staging",), required=True)
    parser.add_argument("--tenant-id", type=UUID, required=True)
    parser.add_argument("--actor-person-id", type=UUID, required=True)
    parser.add_argument("--target", type=_target, action="append", required=True)
    parser.add_argument("--command-id", type=UUID, action="append", required=True)
    for name in ("approver", "issue-reference", "operator-reference"):
        parser.add_argument(f"--{name}", type=_reference, required=True)
    parser.add_argument("--run-reference", type=UUID, required=True)
    parser.add_argument("--snapshot-reference", type=_reference)
    parser.add_argument("--apply", action="store_true")
    return parser


def _settings(args: argparse.Namespace) -> Settings:
    if args.environment != "staging" or os.getenv("AC_ENVIRONMENT") != "staging":
        raise OrganisationCommandError("this tool requires the staging runtime")
    if not os.getenv("AC_DATABASE_URL", "").strip():
        raise OrganisationCommandError("an injected database URL is required")
    settings = Settings(_env_file=None)
    if settings.environment != "staging":
        raise OrganisationCommandError("this tool requires the staging runtime")
    require_baked_release_id(settings.release_id)
    if settings.operations_tenant_id is None or settings.public_learner_tenant_id is None:
        raise OrganisationCommandError("protected tenant IDs must be configured")
    return settings


def _reason(args: argparse.Namespace) -> str:
    return json.dumps(
        {
            "tool": "AUT-1694",
            "environment": "staging",
            "approver": args.approver,
            "issue": args.issue_reference,
            "operator": args.operator_reference,
            "run": str(args.run_reference),
        },
        sort_keys=True,
    )


def _mask(target: UUID | str) -> str:
    return (
        str(target) if isinstance(target, UUID) else f"{target[:1]}***@{target.rsplit('@', 1)[1]}"
    )


def _member(row: Membership | None) -> dict[str, object] | None:
    return (
        None
        if row is None
        else {"role": row.role, "status": row.status, "ended": row.ended_at is not None}
    )


async def _person(database: AsyncSession, target: UUID | str, *, lock: bool) -> Person | None:
    query = select(Person).where(
        Person.id == target if isinstance(target, UUID) else func.lower(Person.email) == target
    )
    if lock:
        query = query.with_for_update(read=True, nowait=True)
    rows = list(await database.scalars(query))
    if len(rows) > 1:
        raise OrganisationCommandError("ambiguous person; use the exact approved UUID")
    return rows[0] if rows else None


async def _membership_change(
    database: AsyncSession,
    service: OrganisationService,
    args: argparse.Namespace,
    target: UUID | str,
    command_id: UUID,
    person: Person | None,
) -> dict[str, object]:
    membership = (
        await database.get(Membership, (args.tenant_id, person.id)) if person is not None else None
    )
    if membership is not None and membership.role == "owner":
        raise OrganisationCommandError("owner target refused")
    before = _member(membership)
    result: dict[str, object] = {
        "person_id": str(person.id) if person else None,
        "before": before,
        "after": before,
    }
    if args.action == "remove-members":
        if membership is None or (membership.status != "active" and membership.ended_at):
            return {**result, "status": "already_absent"}
        result.update(
            status="eligible", after={"role": membership.role, "status": "inactive", "ended": True}
        )
        if args.apply:
            await service.remove_member(
                args.tenant_id,
                membership.person_id,
                command_id,
                actor_person_id=args.actor_person_id,
                operator_reference=args.operator_reference,
            )
        return result
    if person is not None and person.status != "active":
        return {**result, "status": "skipped_inactive_person"}
    if membership is not None and membership.status == "active" and membership.ended_at is None:
        return {**result, "status": "already_member"}
    verified = (
        person is not None and person.email_verified_at is not None and person.email is not None
    )
    if verified:
        result.update(
            status="eligible", after={"role": "member", "status": "active", "ended": False}
        )
        if args.apply:
            assert person is not None
            await service.add_member(
                args.tenant_id,
                person.id,
                "member",
                command_id,
                actor_person_id=args.actor_person_id,
                operator_reference=args.operator_reference,
                reason=_reason(args),
            )
        return result
    assert isinstance(target, str)
    pending = next(
        (
            row
            for row in await active_pending_invites(database, tenant_id=args.tenant_id)
            if row.email_normalized.lower() == target
        ),
        None,
    )
    if pending is not None:
        return {**result, "status": "already_invited", "invite_id": str(pending.id)}
    result.update(status="eligible_invite", after={"status": "invited", "role": "member"})
    if args.apply:
        invited = await service.request_member(
            args.tenant_id,
            target,
            "member",
            command_id,
            actor_person_id=args.actor_person_id,
            operator_reference=args.operator_reference,
            operator_auto_join=True,
        )
        result["invite_id"] = invited["invite_id"]
    return result


async def _delete_recording(
    database: AsyncSession, args: argparse.Namespace, recording_id: UUID, command_id: UUID
) -> dict[str, object]:
    query = select(ConversationRecording).where(ConversationRecording.id == recording_id)
    if args.apply:
        query = query.with_for_update().execution_options(populate_existing=True)
    recording = await database.scalar(query)
    if recording is None:
        return {"status": "already_absent", "before": None, "after": None}
    if recording.tenant_id != args.tenant_id:
        raise OrganisationCommandError("recording tenant differs from approved tenant")
    before = {"state": recording.state, "generation": recording.generation}
    if recording.state in {"deleting", "deleted"}:
        return {"status": "already_deleted", "before": before, "after": before}
    link = await database.scalar(
        select(ConversationGuestSubmission).where(
            ConversationGuestSubmission.recording_id == recording.id,
            ConversationGuestSubmission.tenant_id == recording.tenant_id,
            ConversationGuestSubmission.person_id == recording.person_id,
            ConversationGuestSubmission.source_sha256 == recording.source_sha256,
        )
    )
    if link is None:
        raise OrganisationCommandError("canonical Sales Xray submission binding required")
    after = {"state": "deleting", "generation": recording.generation + 1}
    if args.apply:
        # The recorded exact owner approval authorizes this operator port.
        # ProcessingActor scopes only the canonical deletion receipt, as in
        # GuestOwnership.request_deletion; no human session/lease is fabricated.
        application = ConversationApplication(database)
        await application._request_owned_deletion(
            ProcessingActor(link.person_id, link.tenant_id, link.processing_lease_id),
            recording,
            key=str(command_id),
            now=application.clock(),
        )
    return {"status": "eligible", "before": before, "after": after}


async def _batch(
    database: AsyncSession, settings: Settings, args: argparse.Namespace
) -> dict[str, object]:
    if settings.operations_tenant_id is None or settings.public_learner_tenant_id is None:
        raise OrganisationCommandError("protected tenant IDs must be configured")
    if args.apply and args.snapshot_reference is None:
        raise OrganisationCommandError("a recorded staging snapshot is required before apply")
    if (
        not args.target
        or len(args.target) != len(args.command_id)
        or len(set(args.target)) != len(args.target)
        or len(set(args.command_id)) != len(args.command_id)
        or len(args.target) > 50
        or args.action == "add-members"
        and any(not isinstance(t, str) for t in args.target)
        or args.action == "delete-recordings"
        and any(not isinstance(t, UUID) for t in args.target)
    ):
        raise OrganisationCommandError("unique exact targets and command IDs required (maximum 50)")
    deleting = args.action == "delete-recordings"
    personal = args.tenant_id == settings.public_learner_tenant_id
    if args.tenant_id == settings.operations_tenant_id or personal and not deleting:
        raise OrganisationCommandError("protected tenant refused")
    if not (personal and deleting):
        query = select(Organisation).where(Organisation.tenant_id == args.tenant_id)
        if args.apply:
            query = query.with_for_update()
        if await database.scalar(query) is None:
            raise OrganisationCommandError("registered organisation required")
    tenant_query = select(Tenant).where(Tenant.id == args.tenant_id)
    if args.apply:
        tenant_query = tenant_query.with_for_update(read=True, nowait=True)
    tenant = await database.scalar(tenant_query)
    if tenant is None or tenant.status != "active":
        raise OrganisationCommandError("active tenant required")
    actor = await _person(database, args.actor_person_id, lock=args.apply)
    if actor is None or actor.status != "active" or actor.email_verified_at is None:
        raise OrganisationCommandError("named active verified operator person required")
    owners = list(
        await database.scalars(
            select(Membership).where(
                Membership.tenant_id == args.tenant_id,
                Membership.role == "owner",
                Membership.status == "active",
                Membership.ended_at.is_(None),
            )
        )
    )
    if not deleting and len(owners) != 1:
        raise OrganisationCommandError("exactly one active owner required")
    service = OrganisationService(
        database,
        operations_tenant_id=settings.operations_tenant_id,
        public_learner_tenant_id=settings.public_learner_tenant_id,
    )
    reason = _reason(args)
    resolved: set[UUID] = set()
    rows: list[dict[str, object]] = []
    for target, command_id in zip(args.target, args.command_id, strict=True):
        intent = {
            "action": args.action,
            "target": str(target),
            "actor_person_id": str(args.actor_person_id),
        }
        prior = await database.scalar(
            select(AuditEvent).where(AuditEvent.request_id == str(command_id)).limit(1)
        )
        if prior is not None:
            if (
                prior.tenant_id != args.tenant_id
                or prior.action != "organisation.staging_admin_applied"
                or prior.payload.get("intent") != intent
                or prior.reason != reason
            ):
                raise OrganisationCommandError("command ID has different intent or attribution")
            rows.append(
                {
                    "target": _mask(target),
                    "command_id": str(command_id),
                    "status": "replayed",
                    "applied_result": prior.payload["result"],
                }
            )
            continue
        child = uuid5(command_id, "canonical-app-command")
        if args.action == "delete-recordings":
            assert isinstance(target, UUID)
            result = await _delete_recording(database, args, target, child)
        else:
            person = await _person(database, target, lock=args.apply)
            if person is not None:
                if person.id in resolved:
                    raise OrganisationCommandError("targets resolve to the same person")
                resolved.add(person.id)
            result = await _membership_change(database, service, args, target, child, person)
        if args.apply and result["status"] in {"eligible", "eligible_invite"}:
            result["status"] = "applied"
            await append_audit_event(
                database,
                tenant_id=args.tenant_id,
                actor_person_id=args.actor_person_id,
                actor_type="operator",
                action="organisation.staging_admin_applied",
                resource_type="conversation_recording"
                if args.action == "delete-recordings"
                else "organisation_invite"
                if result.get("invite_id")
                else "organisation_membership",
                resource_id=target
                if isinstance(target, UUID)
                else result.get("person_id") or result.get("invite_id"),
                request_id=str(command_id),
                reason=reason,
                payload={
                    "intent": intent,
                    "result": result,
                    "snapshot_reference": args.snapshot_reference,
                    "canonical_command_id": str(child),
                },
            )
        rows.append({"target": _mask(target), "command_id": str(command_id), **result})
    return {
        "environment": "staging",
        "release_id": settings.release_id,
        "tenant_id": str(args.tenant_id),
        "action": args.action,
        "mode": "apply" if args.apply else "dry_run",
        "attribution": json.loads(reason),
        "snapshot_reference": args.snapshot_reference,
        "targets": rows,
    }


async def _run(args: argparse.Namespace) -> int:
    settings = _settings(args)
    engine = create_async_engine(
        settings.database_url, pool_pre_ping=True, echo=False, hide_parameters=True
    )
    committed = False
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        async with sessions() as database, database.begin():
            if not args.apply:
                await database.execute(text("SET TRANSACTION READ ONLY"))
            output = await _batch(database, settings, args)
        committed = True
        try:
            print(json.dumps(output, sort_keys=True), flush=True)
        except OSError as error:
            raise ResultDeliveryError from error
        return 0
    finally:
        try:
            await engine.dispose()
        except Exception as error:
            if committed:
                raise ResultDeliveryError from error
            raise


def main(argv: list[str] | None = None) -> int:
    try:
        return run_async(_run(_parser().parse_args(argv)))
    except ResultDeliveryError:
        print(
            "transaction completed but receipt delivery failed; read back the recorded command IDs",
            file=sys.stderr,
        )
        return 3
    except (ValueError, RuntimeError, OSError, SQLAlchemyError, DomainError):
        print(
            "organisation admin command refused or failed; no batch changes committed",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
