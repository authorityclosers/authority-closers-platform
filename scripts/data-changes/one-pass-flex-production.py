#!/usr/bin/env python3
"""Prepare, switch and switch back the Gemini Flash-Lite C2 provider configuration (Flex or
standard), from the CLI.

Owner order, 21 Oct 2026 (AUT-2177, relayed by the orchestrator): "Don't make me do this,
do this using hardcore backend commands and CLI, I need this to be live very very quick and
done properly now." His message is the approval for both production actions that Admin ->
One pass -> Transcription would otherwise take: Prepare (save the configuration as a
provider revision) and Switch (activate it once Root has sealed it). Owner order, 21 Oct
2026 (relayed): "Switch production to the standard (non-Flex) Gemini profile: about
₹0.64/min, reports in about 1 minute (add the standard prepare to the script)." Owner-
approved data change (AGENTS.md, OWNER-APPROVED DATA CHANGES): dry run by default, before
and after printed, one transaction, idempotent, audited with the approver and the issue.

``--tier flex`` (the default) is the Flex configuration (profile
``gemini-flash-lite-c2-flex``); ``--tier standard`` is the standard one (profile
``gemini-flash-lite-c2``): the same Flash-Lite C2 and Gemini 3.8 Flash C4/C5, without Flex.

It calls the same service functions as the Admin actions, nothing reimplemented:

- ``prepare``: ``c2_route.derive_configuration(classic, flex=<tier is flex>)`` from today's
  Scribe configuration, saved through ``ConversationProviderAdmin.save``, with Admin's
  audit event ``analysis_pipeline.gemini_transcription_prepared``. Prints the configuration
  digest and the provider revision Root exports for the seal (``export``, below). Already
  saved: nothing more.
- ``switch --digest D``: ``ConversationProviderAdmin.activate`` of that saved revision,
  with the owner's confirm word and his words as the reason. Refused unless D is the
  configuration of that tier derived from today's classic one AND the deployment's pinned
  approval bundle (``load_pinned_approval``, the host's sealed file) approves it. Audited
  as the Admin switch is (the ``provider_activation`` receipt, and
  ``conversation.providers.gemini_transcription_on`` when the owner's check applies:
  onto Gemini or onto Flex), plus ``conversation.providers.owner_approved_switch`` on
  every switch, carrying the approval (Flex to standard needs no owner check in Admin, so
  this is the event that names the owner there). Already active: nothing more. The pointer
  review follows: it reads the newest activation on every pass (``_active_flex``).
- ``back``: the classic (Scribe) revision activated again, the one-click fallback; no
  owner check, as in Admin. Already active: nothing more.
- ``status`` (read only: both tiers' digests, saved revisions, and whether the pinned
  approval seals each) and ``export classic|flex|standard`` (read only: the saved
  configuration's JSON, the ``--classic`` and ``--configuration`` files for
  scripts/ops/one_pass_c2_seal.py).

Who acts: the AC control account named by ``--control-email`` (one of the provider
control accounts), through its newest current Admin session in the operations workspace.
The script never reads or prints a session token; it uses that session row as the actor's
session, exactly as an Admin request would. The owner's relayed approval stands in only
for the ten-minute fresh sign-in; the confirm word and the reason still apply. No current
session: refused (sign in to Admin once; no button needed).

Run inside the deployed API container (the baked package provides ac_platform and the
container's environment the database URL, operations tenant and approval file):

    docker exec -i ac-application-production-api-1 python - \\
      --environment production --allow-production \\
      --control-email <control account> status \\
      < scripts/data-changes/one-pass-flex-production.py

    ... prepare [--tier standard] [--apply]
    ... export classic > classic-configuration.json      (Root, for the seal)
    ... export flex > gemini-flex-configuration.json
    ... export standard > gemini-standard-configuration.json
    ... switch [--tier standard] --digest <digest> [--apply]  (after Root's seal is deployed)
    ... back [--apply]                                     (the fallback)

On production: take a database snapshot before ``--apply``, show the owner the dry run.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select

APPROVER = "Suyash Kulkarni (owner, relayed)"
ISSUE = "AUT-2177"
REASON = (
    'Owner, 21 Oct 2026: "So at least get this on prod now!!!" and "Don\'t make me do this, '
    "do this using hardcore backend commands and CLI, I need this to be live very very quick "
    'and done properly now."'
)
STANDARD_REASON = (
    'Owner, 21 Oct 2026 (relayed): "Switch production to the standard (non-Flex) Gemini '
    "profile: about ₹0.64/min, reports in about 1 minute (add the standard prepare to "
    'the script)."'
)
REASONS = {"flex": REASON, "standard": STANDARD_REASON}
TIERS = ("flex", "standard")
DATA_CHANGE = "scripts/data-changes/one-pass-flex-production.py"
OPERATOR = "claude-laptop:one-pass-flex-production"
PREPARED = "analysis_pipeline.gemini_transcription_prepared"
SWITCHED = "conversation.providers.owner_approved_switch"
COMMANDS = ("status", "prepare", "switch", "back", "export")


class Refused(RuntimeError):
    """A stable, content-free reason the change was not made."""


@dataclass(frozen=True)
class Command:
    action: str
    environment: str
    control_email: str
    apply: bool = False
    digest: str | None = None
    export: str | None = None
    tier: str = "flex"
    approver: str = APPROVER
    issue: str = ISSUE
    reason: str | None = None  # the owner's words for the tier (REASONS) unless given

    @property
    def words(self) -> str:
        return self.reason or REASONS[self.tier]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="one-pass-flex-production", allow_abbrev=False)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--allow-production", action="store_true")
    parser.add_argument("--control-email", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--tier", choices=TIERS, default="flex")
    parser.add_argument("action", choices=COMMANDS)
    parser.add_argument("what", nargs="?", choices=("classic", *TIERS))
    parser.add_argument("--digest")
    return parser


def _approval(command: Command) -> dict[str, str]:
    return {
        "approver": command.approver,
        "issue": command.issue,
        "data_change": DATA_CHANGE,
        "operator": OPERATOR,
    }


async def _actor(database: Any, command: Command, operations_tenant_id: UUID) -> Any:
    """The control account's newest current Admin session in the operations workspace."""
    from ac_platform.conversation_intelligence.provider_admin import CONTROL_ACCOUNTS
    from ac_platform.identity.models import Person
    from ac_platform.identity.models import Session as IdentitySession
    from ac_platform.kernel.authz import ActorContext

    email = command.control_email.strip().casefold()
    if email not in CONTROL_ACCOUNTS:
        raise Refused("control_email_is_not_a_provider_control_account")
    people = list(await database.scalars(select(Person).where(Person.email.ilike(email)).limit(2)))
    if len(people) != 1:
        raise Refused("exactly_one_person_must_match_the_control_email")
    now = datetime.now(UTC)
    session = await database.scalar(
        select(IdentitySession)
        .where(
            IdentitySession.person_id == people[0].id,
            IdentitySession.revoked_at.is_(None),
            IdentitySession.expires_at > now,
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


async def _rows(database: Any, tenant_id: UUID) -> dict[int, Any]:
    from ac_platform.conversation_intelligence.models import ConversationProviderConfiguration

    rows = (
        await database.scalars(
            select(ConversationProviderConfiguration)
            .where(ConversationProviderConfiguration.tenant_id == tenant_id)
            .order_by(ConversationProviderConfiguration.revision.desc())
            .limit(64)
        )
    ).all()
    return {row.revision: row for row in rows}


def _transcription(row: Any) -> str | None:
    from ac_platform.conversation_intelligence.provider_registry import parse_registry_config

    try:
        config = parse_registry_config(row.configuration)
    except (TypeError, ValueError, KeyError):
        return None
    route = next((item for item in config.routes if item.task == "asr"), None)
    return None if route is None else route.provider_id


async def _state(database: Any, actor: Any, service: Any) -> dict[str, Any]:
    """Today's classic configuration, the Flex and standard ones derived from it (and their
    saved revisions, if any), and what is active."""
    from ac_platform.conversation_intelligence.provider_registry import parse_registry_config
    from ac_platform.one_pass import c2_route

    rows = await _rows(database, actor.tenant_id)
    active_id = await service._active(actor.tenant_id)
    active = (
        None
        if active_id is None
        else next((row for row in rows.values() if row.id == active_id.configuration_id), None)
    )
    classic = (
        active
        if active is not None and _transcription(active) not in (None, "gemini")
        else next(
            (
                row
                for _, row in sorted(rows.items(), reverse=True)
                if _transcription(row) not in (None, "gemini")
            ),
            None,
        )
    )
    derived = (
        {}
        if classic is None
        else {
            tier: c2_route.derive_configuration(
                parse_registry_config(classic.configuration), flex=tier == "flex"
            )
            for tier in TIERS
        }
    )
    saved = {
        tier: next(
            (
                row
                for _, row in sorted(rows.items(), reverse=True)
                if tier in derived and row.configuration_sha256 == derived[tier].digest
            ),
            None,
        )
        for tier in TIERS
    }
    return {
        "rows": rows,
        "latest_revision": max(rows) if rows else 0,
        # Each activation is its own receipt key, so back and forth always acts.
        "activation": "none" if active_id is None else str(active_id.id),
        "active": active,
        "classic": classic,
        "derived": derived,
        "saved": saved,
    }


def _summary(state: dict[str, Any]) -> dict[str, Any]:
    def row(item: Any) -> dict[str, Any] | None:
        if item is None:
            return None
        return {
            "revision": item.revision,
            "provider_revision_id": str(item.id),
            "configuration_sha256": item.configuration_sha256,
            "transcription": _transcription(item),
        }

    derived = state["derived"]
    summary: dict[str, Any] = {
        "active": row(state["active"]),
        "classic": row(state["classic"]),
        "latest_revision": state["latest_revision"],
    }
    for tier in TIERS:
        summary[f"{tier}_saved"] = row(state["saved"][tier])
        summary[f"{tier}_digest"] = derived[tier].digest if tier in derived else None
    return summary


def _sealed(state: dict[str, Any], tenant_id: UUID, bundle: Any) -> dict[str, bool]:
    """Whether the pinned approval approves each tier's derived configuration, checked as
    the activation checks it (a transient row; nothing is saved)."""
    from ac_platform.conversation_intelligence.models import ConversationProviderConfiguration
    from ac_platform.conversation_intelligence.provider_admin import ConversationProviderAdmin

    result: dict[str, bool] = {}
    for tier, derived in state["derived"].items():
        row = state["saved"][tier] or ConversationProviderConfiguration(
            tenant_id=tenant_id,
            revision=0,
            configuration=derived.as_dict(),
            configuration_sha256=derived.digest,
        )
        try:
            ConversationProviderAdmin._approved_configuration(row, bundle)
        except Exception:  # noqa: BLE001 - any refusal means: not in the sealed file
            result[tier] = False
        else:
            result[tier] = True
    return result


async def execute(
    database: Any,
    command: Command,
    *,
    operations_tenant_id: UUID,
    load_bundle: Callable[[], Any],
    clock: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """One command in the caller's transaction (the caller commits only with --apply)."""
    from ac_platform.audit.service import AuditRepository
    from ac_platform.conversation_intelligence.application import ConversationApplication
    from ac_platform.conversation_intelligence.provider_admin import (
        OWNER_CONFIRM_WORD,
        ConversationProviderAdmin,
    )

    actor = await _actor(database, command, operations_tenant_id)
    application = (
        ConversationApplication(database)
        if clock is None
        else ConversationApplication(database, clock=clock)
    )
    service = ConversationProviderAdmin(application)
    state = await _state(database, actor, service)
    before = _summary(state)
    result: dict[str, Any] = {"action": command.action, "apply": command.apply, "before": before}
    if command.action == "status":
        try:
            sealed: Any = _sealed(state, actor.tenant_id, load_bundle())
        except Exception as error:  # noqa: BLE001 - no pinned approval here: say which
            sealed = f"approval_unreadable:{type(error).__name__}"
        return {**result, "after": before, "sealed": sealed, "status": "read_only"}
    if command.action == "export":
        item = state["classic"] if command.export == "classic" else state["saved"][command.export]
        if item is None:
            raise Refused(f"no_saved_{command.export}_configuration")
        return {"export": command.export, "configuration": item.configuration}
    tier = command.tier
    if tier not in TIERS:
        raise Refused("tier_must_be_flex_or_standard")
    if state["classic"] is None or not state["derived"]:
        raise Refused("no_classic_scribe_configuration_to_start_from")
    derived, saved = state["derived"][tier], state["saved"][tier]

    if command.action == "prepare":
        if saved is not None:
            status = "no_op"
        else:
            await service.save(
                actor,
                derived.as_dict(),
                expected_revision=state["latest_revision"],
                key=f"one-pass-c2:{derived.digest}",
            )
            await AuditRepository(database).append_for_actor(
                actor,
                action=PREPARED,
                resource_type="conversation_provider_configuration",
                resource_id=derived.digest,
                payload={
                    "from_revision": state["classic"].revision,
                    "configuration_sha256": derived.digest,
                    "tier": tier,
                    "reason": command.words,
                    "approval": _approval(command),
                },
            )
            status = "applied" if command.apply else "dry_run"
    elif command.action == "switch":
        if command.digest is None or command.digest != derived.digest:
            raise Refused(f"digest_is_not_the_{tier}_configuration_derived_from_today")
        if saved is None:
            raise Refused(f"{tier}_configuration_not_prepared_run_prepare_first")
        bundle = load_bundle()
        try:
            ConversationProviderAdmin._approved_configuration(saved, bundle)
        except Exception:  # noqa: BLE001 - any refusal means: not in the sealed file
            raise Refused("the_pinned_sealed_approval_does_not_contain_this_digest") from None
        if state["active"] is not None and state["active"].id == saved.id:
            status = "no_op"
        else:
            await service.activate(
                actor,
                target_revision=saved.revision,
                expected_revision=state["latest_revision"],
                key=f"one-pass-{tier}-switch:{saved.configuration_sha256[:24]}:"
                f"{state['activation']}",
                bundle=bundle,
                confirm=OWNER_CONFIRM_WORD,
                reason=command.words,
                owner_approval=_approval(command),
            )
            # Admin's owner check (and its audit event) applies only onto Gemini or onto
            # Flex; this names the owner's approval on every switch, Flex to standard too.
            await AuditRepository(database).append_for_actor(
                actor,
                action=SWITCHED,
                resource_type="conversation_provider_configuration",
                resource_id=saved.configuration_sha256,
                payload={
                    "tier": tier,
                    "target_revision": saved.revision,
                    "configuration_sha256": saved.configuration_sha256,
                    "from_configuration_sha256": None
                    if state["active"] is None
                    else state["active"].configuration_sha256,
                    "approval_bundle_sha256": bundle.digest,
                    "reason": command.words,
                    "approval": _approval(command),
                },
            )
            status = "applied" if command.apply else "dry_run"
    elif command.action == "back":
        classic = state["classic"]
        if state["active"] is not None and state["active"].id == classic.id:
            status = "no_op"
        else:
            bundle = load_bundle()
            await service.activate(
                actor,
                target_revision=classic.revision,
                expected_revision=state["latest_revision"],
                key=f"one-pass-back-to-scribe:{classic.configuration_sha256[:24]}:"
                f"{state['activation']}",
                bundle=bundle,
            )
            status = "applied" if command.apply else "dry_run"
    else:
        raise Refused("unknown_command")
    after = _summary(await _state(database, actor, service))
    return {**result, "after": after, "status": status, "approval": _approval(command)}


class _DryRun(Exception):
    pass


async def _run(command: Command, settings: Any) -> dict[str, Any]:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from ac_platform.conversation_intelligence.hosted_runtime import load_pinned_approval

    engine = create_async_engine(settings.database_url, pool_pre_ping=True, hide_parameters=True)
    result: dict[str, Any] = {}
    try:
        async with async_sessionmaker(engine, expire_on_commit=False, autoflush=False)() as db:
            try:
                async with db.begin():
                    result = await execute(
                        db,
                        command,
                        operations_tenant_id=settings.operations_tenant_id,
                        load_bundle=lambda: load_pinned_approval(settings),
                    )
                    if not command.apply:
                        raise _DryRun
            except _DryRun:
                pass
        return result
    finally:
        await engine.dispose()


def main(
    argv: list[str] | None = None,
    runner: Callable[..., Coroutine[Any, Any, dict[str, Any]]] | None = None,
) -> int:
    try:
        args = _parser().parse_args(argv)
        if args.action == "export" and args.what is None:
            raise Refused("export_needs_classic_flex_or_standard")
        command = Command(
            action=args.action,
            environment=args.environment,
            control_email=args.control_email,
            apply=bool(args.apply) and args.action not in {"status", "export"},
            digest=args.digest,
            export=args.what,
            tier=args.tier,
        )
        from ac_platform.application.asyncio_runtime import run_async
        from ac_platform.application.release_identity import require_baked_release_id
        from ac_platform.application.settings import Settings

        settings = Settings(_env_file=None)
        if command.environment != settings.environment:
            raise Refused("environment_must_match_the_container_settings")
        if command.environment == "production" and not args.allow_production:
            raise Refused("production_requires_allow_production")
        if settings.operations_tenant_id is None:
            raise Refused("an_explicit_operations_tenant_is_required")
        if command.environment in {"staging", "production"}:
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
