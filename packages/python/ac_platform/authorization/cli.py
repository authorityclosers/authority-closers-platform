"""Explicit canonical capability commands; never an account-provisioning shortcut."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from typing import Any, Never
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.application.asyncio_runtime import run_async
from ac_platform.application.release_identity import require_baked_release_id
from ac_platform.application.settings import Settings
from ac_platform.authorization.application import CapabilityApplication
from ac_platform.authorization.models import (
    SUPPORTED_CAPABILITIES,
    CapabilityGrant,
    CapabilityRevocation,
)
from ac_platform.authorization.policy import CapabilityDenied, CapabilityScope
from ac_platform.identity.application import AsyncIdentityApplication
from ac_platform.identity.models import Person
from ac_platform.identity.services import normalize_email


class CliInputError(Exception):
    """Input is refused before opening any database connection."""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        # argparse normally repeats offending values, including accidental secrets.
        raise CliInputError("Invalid arguments; use --help for the explicit command contract.")


@dataclass(frozen=True)
class Command:
    action: str
    environment: str
    person_id: UUID
    expected_email: str | None
    command_id: UUID | None
    reason: str | None
    permission: str | None
    scope: CapabilityScope | None
    grant_id: UUID | None


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(description=__doc__, allow_abbrev=False)
    commands = parser.add_subparsers(dest="action", required=True)
    for action in ("inspect", "first-manager", "grant", "revoke"):
        child = commands.add_parser(action, allow_abbrev=False)
        child.add_argument("--environment", required=True)
        child.add_argument("--allow-production", action="store_true")
        child.add_argument("--person-id", type=UUID, required=True)
        child.add_argument("--expected-email", help="consistency check only; never authority")
        if action != "inspect":
            child.add_argument("--command-id", type=UUID, required=True)
            child.add_argument(
                "--reason", required=True, help="non-secret attributable change reason"
            )
        if action == "grant":
            child.add_argument(
                "--permission", choices=sorted(SUPPORTED_CAPABILITIES), required=True
            )
            child.add_argument("--scope", choices=("platform", "tenant", "program"), required=True)
            child.add_argument("--tenant-id", type=UUID)
            child.add_argument("--program-id", type=UUID)
        if action == "revoke":
            child.add_argument("--grant-id", type=UUID, required=True)
    return parser


def _command(args: argparse.Namespace) -> Command:
    environment = args.environment.strip().lower()
    if environment not in {"local", "test", "development", "staging", "production"}:
        raise CliInputError("Unsupported environment.")
    configured = os.getenv("AC_ENVIRONMENT", "").strip().lower()
    if configured and configured != environment:
        raise CliInputError("The explicit environment must match AC_ENVIRONMENT.")
    if environment == "production" and not args.allow_production:
        raise CliInputError("Production requires --allow-production.")
    if not os.getenv("AC_DATABASE_URL", "").strip():
        raise CliInputError("An explicit AC_DATABASE_URL is required.")
    reason = getattr(args, "reason", None)
    if reason is not None:
        reason = reason.strip()
        if not reason or len(reason) > 500 or any(ord(c) < 32 or ord(c) == 127 for c in reason):
            raise CliInputError("A non-secret reason of 1–500 printable characters is required.")
    email = (
        normalize_email(args.expected_email, "expected email")
        if args.expected_email is not None
        else None
    )
    scope = None
    permission = getattr(args, "permission", None)
    if args.action == "grant":
        if not isinstance(permission, str):
            raise CliInputError("An explicit permission is required.")
        scope = CapabilityScope(args.scope, args.tenant_id, args.program_id)
        scope.validate(permission)
    return Command(
        args.action,
        environment,
        args.person_id,
        email,
        getattr(args, "command_id", None),
        reason,
        permission,
        scope,
        getattr(args, "grant_id", None),
    )


def _read_terminal_token() -> str:
    if sys.platform == "win32":
        import msvcrt

        characters: list[str] = []
        while True:
            char = msvcrt.getwch()
            if char == "\x03":
                raise KeyboardInterrupt
            if char == "\r":
                return "".join(characters)
            if char == "\b":
                characters = characters[:-1]
            elif char in {"\x00", "\xe0"}:
                raise CliInputError("Unsupported hidden input.")
            elif len(characters) == 512:
                raise CliInputError("Session input exceeds the limit.")
            else:
                characters.append(char)
    else:
        import termios

        descriptor = sys.stdin.fileno()
        previous = termios.tcgetattr(descriptor)
        hidden = list(previous)
        hidden[3] &= ~termios.ECHO
        try:
            termios.tcsetattr(descriptor, termios.TCSAFLUSH, hidden)
            return sys.stdin.readline(514).removesuffix("\n").removesuffix("\r")
        finally:
            termios.tcsetattr(descriptor, termios.TCSAFLUSH, previous)


def _read_session_token() -> str:
    """Read at most 512 token characters without echo; never fall back to echoed input."""
    terminal = sys.stdin.isatty()
    if terminal:
        print("Existing session token (hidden): ", end="", file=sys.stderr, flush=True)
    try:
        token = (
            _read_terminal_token()
            if terminal
            else sys.stdin.readline(514).removesuffix("\n").removesuffix("\r")
        )
    finally:
        if terminal:
            print(file=sys.stderr)
    if re.fullmatch(r"[A-Za-z0-9_-]{43,512}", token) is None:
        raise CliInputError("A bounded canonical session token is required.")
    return token


async def _subject(database: AsyncSession, command: Command) -> Person:
    person = await database.scalar(
        select(Person)
        .where(Person.id == command.person_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if person is None:
        raise CapabilityDenied("The exact subject is unavailable.")
    if command.expected_email is not None and (
        person.email is None
        or normalize_email(person.email, "canonical email") != command.expected_email
    ):
        raise CapabilityDenied("The subject consistency check failed.")
    return person


async def execute_command(
    database: AsyncSession, settings: Settings, command: Command, token: str | None
) -> dict[str, Any]:
    """Adapter under an explicit caller transaction; no commit, output or session invention."""
    if settings.operations_tenant_id is None:
        raise CliInputError("An explicit operations tenant is required.")
    application = CapabilityApplication(
        database, operations_tenant_id=settings.operations_tenant_id
    )
    # Package-internal canonical fence MUST precede identity's Person/Session locks.
    await application._governance()
    actor = None
    if command.action != "first-manager":
        if token is None:
            raise CapabilityDenied("An existing named session is required.")
        identity = AsyncIdentityApplication(
            database, token_pepper=settings.session_token_pepper.get_secret_value()
        )
        actor = (await identity.resolve_actor(token)).actor
        await application.require(
            actor.person_id, "platform_access_manage", CapabilityScope("platform")
        )
    await _subject(database, command)
    if command.action == "inspect":
        rows = tuple(
            await database.scalars(
                select(CapabilityGrant)
                .where(CapabilityGrant.subject_person_id == command.person_id)
                .order_by(CapabilityGrant.created_at, CapabilityGrant.id)
                .limit(201)
            )
        )
        if len(rows) > 200:
            raise CliInputError(
                "Assignment history exceeds this bounded inspection; use reviewed tooling."
            )
        revoked = frozenset(
            await database.scalars(
                select(CapabilityRevocation.grant_id).where(
                    CapabilityRevocation.grant_id.in_(row.id for row in rows)
                )
            )
        )
        return {
            "person_id": str(command.person_id),
            "effective_access_evaluated": False,
            "assignments": [
                {
                    "grant_id": str(row.id),
                    "permission": row.permission,
                    "scope": row.scope_kind,
                    "tenant_id": str(row.tenant_id) if row.tenant_id else None,
                    "program_id": str(row.program_id) if row.program_id else None,
                    "revoked": row.id in revoked,
                }
                for row in rows
            ],
        }
    if command.command_id is None or command.reason is None:
        raise CliInputError("Mutation intent is incomplete.")
    if command.action == "revoke":
        if actor is None or command.grant_id is None:
            raise CliInputError("Revocation intent is incomplete.")
        grant = await database.get(CapabilityGrant, command.grant_id)
        if grant is None or grant.subject_person_id != command.person_id:
            raise CapabilityDenied("The grant does not belong to the exact subject.")
        prior = await database.get(CapabilityRevocation, command.command_id)
        revocation = await application.revoke(
            actor, command_id=command.command_id, grant_id=grant.id, reason=command.reason
        )
        return {
            "command_id": str(revocation.id),
            "grant_id": str(grant.id),
            "active": False,
            "replayed": prior is not None,
        }
    prior_grant = await database.get(CapabilityGrant, command.command_id)
    if command.action == "first-manager":
        grant = await application.bootstrap_first_manager(
            person_id=command.person_id, command_id=command.command_id, reason=command.reason
        )
    elif (
        command.action == "grant"
        and actor is not None
        and command.scope is not None
        and command.permission is not None
    ):
        grant = await application.grant(
            actor,
            command_id=command.command_id,
            subject_person_id=command.person_id,
            permission=command.permission,
            scope=command.scope,
            reason=command.reason,
        )
    else:
        raise CliInputError("Unknown command.")
    revoked_id = await database.scalar(
        select(CapabilityRevocation.id).where(CapabilityRevocation.grant_id == grant.id)
    )
    return {
        "command_id": str(grant.id),
        "grant_id": str(grant.id),
        "active": revoked_id is None,
        "replayed": prior_grant is not None,
    }


class _InspectionComplete(Exception):
    """Rollback identity last-seen updates: inspection is genuinely read-only."""


async def _run(settings: Settings, command: Command, token: str | None) -> dict[str, Any]:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True, hide_parameters=True)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as database:
            try:
                async with database.begin():
                    result = await execute_command(database, settings, command, token)
                    if command.action == "inspect":
                        raise _InspectionComplete
            except _InspectionComplete:
                pass
        return result
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    try:
        command = _command(_parser().parse_args(argv))
        settings = Settings(_env_file=None, environment=command.environment)
        if settings.operations_tenant_id is None:
            raise CliInputError("An explicit operations tenant is required.")
        if command.environment in {"staging", "production"}:
            require_baked_release_id(settings.release_id)
        token = None if command.action == "first-manager" else _read_session_token()
        result = run_async(_run(settings, command, token))
    except CliInputError as error:
        print(f"authorization refused: {error}", file=sys.stderr)
        return 2
    except (Exception, KeyboardInterrupt):
        # Settings, driver and identity failures can embed credentials or native SQL.
        # Unknown outcomes must be retried using the exact same command UUID/intent.
        print(
            "authorization refused: command failed; retain the same intent for any retry",
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


__all__ = ["main"]
