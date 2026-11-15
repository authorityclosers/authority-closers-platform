#!/usr/bin/env python3
"""Set up a test or sandbox workspace for an API call upload (owner-approved data change).

Orchestrator, 15 Nov 2026 (Luna on staging, step 7): one of Dipak's gold calls goes in through
the API (``sx upload``) on staging, in a sandbox or fictional workspace, never a customer's.
The workspace needs its API-upload terms on and a ``recordings:write`` key, and the key must
reach a root-only file without anyone typing or seeing it.

- ``status`` (read only): the workspace's tier and whether it allows API keys and
  ``recordings:write``, the API-upload terms (``key_upload.terms``) for the upload terms in
  force, its live keys, and each member's role, contact profile and AI level (emails masked).
- ``terms``: the workspace's API-upload terms accepted (``key_upload.record_terms``, the same
  event the Developers switch writes) in the name of ``--maker-email``, an owner or admin
  there, plus ``conversation.api_upload_terms_data_change`` naming the approver and the issue.
  Already on: nothing changes.
- ``mint-key``: a ``recordings:write`` key (30 days) made by ``--maker-email``
  (``integrations.keys.create``, audited as ``integration.api_key_created`` with the approval).
  With ``--apply`` the key itself, and nothing else, goes to standard output, for the caller
  to pipe into a root-only file; everything else goes to standard error. A dry run prints no
  key. Refused unless the workspace's plan allows API keys and ``recordings:write``. Run again
  while that maker's live key of this name exists, it makes none (``already_minted``) and
  prints no key (release PR #623 review, 15 Nov 2026): a key can't be shown twice.

Refused for any workspace whose name doesn't say it is a test, sandbox or fictional one.
Owner-approved data change (AGENTS.md): dry run by default, one transaction, idempotent for
the terms, audited with the approver and the issue. The upload terms in force come from the
running API (``/v1/conversation/acquisition/upload-policy``) unless given.

In staging or production, inside the deployed API container:

    docker exec -i ac-application-staging-api-1 python - --environment staging \\
      --tenant <workspace id> --maker-email <owner or admin> \\
      --approver "<approver>" --issue <reference> --reason "<their words>" \\
      status|terms|mint-key [--apply] < scripts/data-changes/api-upload-proof-setup.py

    ... mint-key --apply < ... | sudo sh -c 'umask 077; f=/root/<file>; cat > "$f.new";
          if [ -s "$f.new" ]; then mv "$f.new" "$f"; else rm -f "$f.new"; fi'

(an empty answer, such as ``already_minted`` or a refusal, never replaces the file).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select

ACTIONS = ("status", "terms", "mint-key")
SCOPE = "recordings:write"
KEY_DAYS = 30
TEST_NAME = re.compile(r"^test\b|sandbox|fictional", re.IGNORECASE)
POLICY_PATH = "/v1/conversation/acquisition/upload-policy"


class Refused(RuntimeError):
    """A stable, content-free reason the change was not made."""


class _DryRun(Exception):
    pass


@dataclass(frozen=True)
class Command:
    action: str
    environment: str
    tenant_id: UUID
    maker_email: str
    apply: bool = False
    approver: str | None = None
    issue: str | None = None
    reason: str | None = None
    upload_policy_sha256: str | None = None
    key_name: str = "API upload proof (data change)"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="api-upload-proof-setup", allow_abbrev=False)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--allow-production", action="store_true")
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--maker-email", required=True)
    parser.add_argument("--approver")
    parser.add_argument("--issue")
    parser.add_argument("--reason")
    parser.add_argument("--upload-policy-sha256")
    parser.add_argument("--key-name", default="API upload proof (data change)")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("action", choices=ACTIONS)
    return parser


def command_from(args: argparse.Namespace) -> Command:
    try:
        tenant_id = UUID(args.tenant)
    except ValueError:
        raise Refused("tenant_must_be_a_workspace_id") from None
    policy = args.upload_policy_sha256
    if policy is not None and re.fullmatch(r"[0-9a-f]{64}", policy) is None:
        raise Refused("upload_policy_sha256_must_be_64_hex")
    command = Command(
        action=args.action,
        environment=args.environment,
        tenant_id=tenant_id,
        maker_email=args.maker_email.strip().casefold(),
        apply=bool(args.apply) and args.action != "status",
        approver=args.approver,
        issue=args.issue,
        reason=args.reason,
        upload_policy_sha256=policy,
        key_name=args.key_name,
    )
    if command.action != "status":
        if not command.approver or not command.issue:
            raise Refused("approver_and_issue_are_required")
        if not command.reason or not 10 <= len(command.reason.strip()) <= 300:
            raise Refused("reason_must_be_10_to_300_characters")
    return command


def _mask(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    name, domain = email.split("@", 1)
    return name[:2] + "***@" + domain


async def _workspace(db: Any, command: Command) -> tuple[Any, Any, str]:
    from ac_platform.identity.models import Person
    from ac_platform.tenancy.models import Membership, Organisation, Tenant

    tenant = await db.get(Tenant, command.tenant_id)
    organisation = await db.scalar(
        select(Organisation.tenant_id).where(Organisation.tenant_id == command.tenant_id)
    )
    if tenant is None or organisation is None:
        raise Refused("no_such_organisation")
    if tenant.status != "active":
        raise Refused("the_workspace_is_not_active")
    if TEST_NAME.search(tenant.name or "") is None:
        raise Refused("not_a_test_sandbox_or_fictional_workspace")
    people = list(
        await db.scalars(select(Person).where(Person.email.ilike(command.maker_email)).limit(2))
    )
    if len(people) != 1:
        raise Refused("exactly_one_person_must_match_the_maker_email")
    seat = await db.scalar(
        select(Membership).where(
            Membership.tenant_id == command.tenant_id,
            Membership.person_id == people[0].id,
            Membership.status == "active",
            Membership.ended_at.is_(None),
        )
    )
    if seat is None or seat.role not in {"owner", "admin"}:
        raise Refused("the_maker_must_be_an_owner_or_admin_there")
    return tenant, people[0], seat.role


async def execute(
    db: Any, command: Command, *, billing_enabled: bool, now: datetime | None = None
) -> dict[str, Any]:
    from ac_platform.audit.service import AuditRepository
    from ac_platform.call_ai import auto_consent
    from ac_platform.conversation_intelligence import key_upload
    from ac_platform.identity.models import Person
    from ac_platform.identity.sales_xray_profile import (
        SalesXrayProfileError,
        require_sales_xray_profile_complete,
    )
    from ac_platform.integrations import keys, tiers
    from ac_platform.integrations.models import IntegrationApiKey
    from ac_platform.tenancy.models import Membership

    now = now or datetime.now(UTC)
    tenant, maker, role = await _workspace(db, command)
    if command.upload_policy_sha256 is None:
        raise Refused("the_upload_terms_in_force_are_unknown")
    policy = command.upload_policy_sha256
    platform = await tiers.read_platform(db)
    tier = await tiers.workspace_tier(
        db,
        platform,
        billing_enabled=billing_enabled,
        tenant_id=tenant.id,
        person_id=maker.id,
        personal=False,
        now=now,
    )
    terms = await key_upload.terms(db, tenant.id, policy, command.environment)
    live = [
        key
        for key in await db.scalars(
            select(IntegrationApiKey).where(
                IntegrationApiKey.tenant_id == tenant.id, IntegrationApiKey.revoked_at.is_(None)
            )
        )
        if SCOPE in (key.scopes or []) and (key.expires_at is None or key.expires_at > now)
    ]
    result: dict[str, Any] = {
        "workspace": tenant.name,
        "tier": tier.key,
        "api_keys_allowed": tier.api_keys,
        "recordings_write_allowed": tier.allows(SCOPE),
        "terms": terms.state,
        "upload_policy_sha256": policy,
        "recordings_write_keys": len(live),
        "action": command.action,
    }
    if command.action == "status":
        members = []
        for seat, person in (
            await db.execute(
                select(Membership, Person)
                .join(Person, Person.id == Membership.person_id)
                .where(
                    Membership.tenant_id == tenant.id,
                    Membership.status == "active",
                    Membership.ended_at.is_(None),
                    Membership.role != "processing",
                )
                .order_by(Membership.role)
            )
        ).all():
            try:
                await require_sales_xray_profile_complete(db, person_id=person.id)
                complete = True
            except SalesXrayProfileError:
                complete = False
            members.append(
                {
                    "email": _mask(person.email),
                    "person_id": str(person.id),
                    "role": seat.role,
                    "profile_complete": complete,
                    "ai_level": await auto_consent.level(db, tenant.id, person.id),
                }
            )
        return {**result, "members": members, "status": "read_only"}
    approval = {
        "approver": command.approver,
        "issue": command.issue,
        "reason": command.reason,
        "script": "scripts/data-changes/api-upload-proof-setup.py",
    }
    if command.action == "terms":
        if terms.state == "on":
            return {**result, "status": "already_on"}
        try:
            event = await key_upload.record_terms(
                db,
                tenant_id=tenant.id,
                person_id=maker.id,
                session_id=None,
                role=role,
                decision="granted",
                environment=command.environment,
                policy_sha256=key_upload.notice()["policy_sha256"],
                upload_policy_sha256=policy,
                now=now,
            )
        except Exception as error:  # noqa: BLE001 - the domain's own refusal, content-free
            raise Refused(f"terms_refused_{type(error).__name__}") from None
        await AuditRepository(db).append(
            tenant_id=tenant.id,
            actor_person_id=maker.id,
            actor_type="data_change",
            action="conversation.api_upload_terms_data_change",
            resource_type=key_upload.TERMS_RESOURCE,
            resource_id=str(tenant.id),
            payload={**approval, "terms_event_id": str(event)},
            reason=command.reason,
            now=now,
        )
        after = await key_upload.terms(db, tenant.id, policy, command.environment)
        return {**result, "terms_after": after.state, "status": "applied"}
    if not tier.api_keys or not tier.allows(SCOPE):
        raise Refused("the_plan_does_not_allow_recordings_write_keys")
    mine = [
        key for key in live if key.name == command.key_name and key.created_by_person_id == maker.id
    ]
    if mine:
        # A key is shown once, when it is made; this one exists already.
        return {
            **result,
            "key_id": str(mine[0].id),
            "key_prefix": mine[0].prefix,
            "expires_at": mine[0].expires_at,
            "status": "already_minted",
        }
    key, view = await db.run_sync(
        lambda sync: keys.create(
            sync.connection(),
            tenant_id=tenant.id,
            person_id=maker.id,
            name=command.key_name,
            scopes=[SCOPE],
            expires_days=KEY_DAYS,
            environment=command.environment,
            now=now,
        )
    )
    await AuditRepository(db).append(
        tenant_id=tenant.id,
        actor_person_id=maker.id,
        actor_type="data_change",
        action="integration.api_key_created",
        resource_type="integration_api_key",
        resource_id=view["id"],
        payload={
            "name": view["name"],
            "prefix": view["prefix"],
            "scopes": view["scopes"],
            "expires_at": view["expires_at"],
            **approval,
        },
        reason=command.reason,
        now=now,
    )
    return {
        **result,
        "key_id": view["id"],
        "key_prefix": view["prefix"],
        "expires_at": view["expires_at"],
        "status": "applied",
        "_key": key,
    }


def _policy_in_force(settings: Any) -> str:
    """The upload terms' hash the running API serves (this container's own)."""
    host = settings.sales_xray_app_url.host if settings.sales_xray_app_url else None
    if not host:
        raise Refused("no_sales_xray_host_configured")
    request = urllib.request.Request(  # noqa: S310 - the container's own API, fixed path
        f"http://127.0.0.1:8000{POLICY_PATH}", headers={"Host": host}
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as answer:  # noqa: S310
            value = json.loads(answer.read())["policy_sha256"]
    except Exception:  # noqa: BLE001 - say what is missing, never the body
        raise Refused("the_upload_terms_in_force_are_unreadable") from None
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise Refused("the_upload_terms_in_force_are_unreadable")
    return value


async def _run(command: Command, settings: Any) -> dict[str, Any]:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(settings.database_url, pool_pre_ping=True, hide_parameters=True)
    result: dict[str, Any] = {}
    try:
        async with async_sessionmaker(engine, expire_on_commit=False, autoflush=False)() as db:
            try:
                async with db.begin():
                    result = await execute(db, command, billing_enabled=settings.billing_enabled)
                    if not command.apply or result["status"] != "applied":
                        result.pop("_key", None)
                        raise _DryRun
            except _DryRun:
                if result.get("status") == "applied":
                    result["status"] = "dry_run"
        return result
    finally:
        await engine.dispose()


def main(
    argv: list[str] | None = None,
    runner: Callable[..., Coroutine[Any, Any, dict[str, Any]]] | None = None,
) -> int:
    try:
        args = _parser().parse_args(argv)
        command = command_from(args)
        from ac_platform.application.asyncio_runtime import run_async
        from ac_platform.application.release_identity import require_baked_release_id
        from ac_platform.application.settings import Settings

        settings = Settings(_env_file=None)
        if command.environment != settings.environment:
            raise Refused("environment_must_match_the_container_settings")
        if command.environment == "production" and not args.allow_production:
            raise Refused("production_requires_allow_production")
        if command.environment in {"staging", "production"}:
            require_baked_release_id(settings.release_id)
        if command.upload_policy_sha256 is None:
            command = replace(command, upload_policy_sha256=_policy_in_force(settings))
        result = run_async((runner or _run)(command, settings))
    except Refused as refused:
        print(f"data change refused: {refused}", file=sys.stderr)
        return 2
    except (Exception, KeyboardInterrupt) as error:
        # Settings and driver failures can contain secrets; name the type only.
        print(f"data change failed: {type(error).__name__}", file=sys.stderr)
        return 2
    key = result.pop("_key", None)
    if command.action == "mint-key":
        # Standard output carries a new key and nothing else, for a pipe into a root-only
        # file; the summary (and an already-minted answer) goes to standard error.
        print(json.dumps(result, sort_keys=True, default=str, indent=2), file=sys.stderr)
        if key is not None:
            sys.stdout.write(key + "\n")
        return 0
    print(json.dumps(result, sort_keys=True, default=str, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
