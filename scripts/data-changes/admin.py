#!/usr/bin/env python3
"""The admin CLI: every base-level primitive of an organisation's sales cycle, from the back end
(owner-approved data changes; AGENTS.md "OWNER-APPROVED DATA CHANGES").

Owner, 16-17 Nov 2026 (through the orchestrator): "a hardcore admin CLI for administration of
the entire sales cycle", "every base-level primitive in CLI, MCP and API". Each command goes
through the app's own service (OrganisationService, LeadDesk, the bulk jobs, Archive and Bin,
the AI-apps switch, the file import); nothing is reimplemented where a service exists.

    admin.py <group> <command> --environment development|staging|production [options]

People (--tenant-id T):
    people list                                    members and pending invites (masked e-mails)
    people show --person-id P                      one member: role, status, open leads
    people invite --email E [--role ROLE]          a verified account joins at once; anyone
                                                   else gets the app's invitation e-mail
    people resend-invite --email E                 the pending invite is revoked and a new one
                                                   sent (the app has no resend of its own)
    people set-role --person-id P --role ROLE      admin, manager, member, viewer or finance;
                                                   never the owner's
    people transfer-owner --person-id P            P owns; the owner becomes an admin; both
                                                   are e-mailed
    people rename --person-id P --name NAME        the account's display name
    people remove-member --person-id P             the membership ends (never the owner)
    people taking-leads --person-id P --taking on|off
                                                   Team's "Taking new leads" switch: off, the
                                                   lead rules skip P (P's open leads stay)

Workspaces:
    workspaces list                                every organisation (no --tenant-id)
    workspaces show --tenant-id T                  name, owner, members, domains, switches,
                                                   lead counts
    workspaces create --name N --owner-person-id P a new organisation owned by P
    workspaces rename --tenant-id T --name N
    workspaces domains --tenant-id T --domain D [--domain D2] [--auto-join | --clear]
                                                   the verified e-mail domains, attested by
                                                   the operator (the full list each time)
    workspaces switches --tenant-id T [--paused on|off] [--note on|off] [--task ...]
                                                   [--outcome ...] [--update ...] [--stage ...]
                                                   the AI-apps switch (Organisation -> AI
                                                   apps); no flag shows it. Sales X-Ray itself
                                                   is on for every active organisation.
    workspaces lead-rules --tenant-id T [--split P=PCT ...] [--split-name N] [--no-split]
                          [--auto-reassign on|off] [--reassign-minutes N]
                          [--work-days mon-sat] [--work-start HH:MM] [--work-end HH:MM]
                          [--pause-leads on|off] [--sellers-reassign on|off]
                                                   Lead rules: a split of every new lead by
                                                   percent (the first rule; shares add up to
                                                   100), auto-reassign after N work minutes,
                                                   work days and hours (India time), and
                                                   whether sellers may give their leads to a
                                                   colleague; no flag shows them

Ask Dipak (the whole platform; no --tenant-id):
    ask-dipak videos [on|off]                      the lesson-video switch; no word shows it
                                                   and the approved videos. OFF until Dipak
                                                   and the owner approve (owner, 19 Nov 2026:
                                                   "the videos are not approved")
    ask-dipak add-video --lesson Q --src URL --poster URL --seconds N
                                                   one approved video for lesson Q (a /path or
                                                   https:// address); shown only while on
    ask-dipak remove-video --lesson Q              that lesson shows no video
Each change appends Dipak's lessons again with the new videos (ask_dipak/videos.py), so the
history stays; the app sees it at its next visit.

Leads (--tenant-id T):
    leads list [--search S] [--where-* ...] [--names] [--offset N] [--limit N]
    leads add --name N [--phone] [--email] [--company] [--city] [--note]
              [--owner-person-id P] [--side live|cold] [--pipeline KEY]
    leads assign (--lead-id L ... | --where-* ...) (--to-person-id P | --rules)
    leads reassign --person-id FROM --to-person-id TO [--where-* ...]
                                                   every lead FROM owns (or those matching)
    leads stage (--lead-id L ... | --where-* ...) --step KEY [--outcome-reason R]
                [--reason-note N] [--next-action-at ISO]
    leads archive | restore-archive | bin | restore-bin (--lead-id L ... | --where-* ...)
    leads import --input FILE.json                 import-leads-file.py's input, in this
                                                   command's transaction
Selections by filter (``--where-owner``, ``--where-unassigned``, ``--where-step``,
``--where-stage``, ``--where-side``, ``--where-search``, ``--where-source``,
``--where-pipeline``, ``--where-shelf``) are the Leads list's own filter, frozen by the bulk job
(up to 2,000); ``--expected-total`` refuses when the count changed since you looked.

Every changing command: a dry run by default, made in full inside its transaction and rolled
back, printing before and after; ``--apply`` commits once and writes one audit event
(``admin.data_change_applied``) naming the approver, the issue, the operator and the run; a
change that finds nothing to do records its receipt the same way, so a retry replays it.
``--approver`` and ``--issue`` are required. The command ID defaults to one derived from the
command and its issue, so a rerun replays and changes nothing; pass ``--command-id`` for a
fresh run of the same change. Staging and production need ``--snapshot-reference`` to apply;
production also needs ``--allow-production`` and the container's own production settings.
Reading commands (list, show, switches with no flag) run read-only and write nothing.
``--json`` prints the JSON receipt (the old flat names below always do). Prints ids, roles and
display names; e-mails masked; a lead's name only with ``--names``, never a phone or e-mail.

The first five commands keep their old flat names: transfer-owner, set-role, rename-person,
reassign-leads (= leads reassign) and remove-member.

    docker exec -i ac-application-production-api-1 python - people set-role \\
      --environment production --allow-production --tenant-id <workspace> --person-id <person> \\
      --role admin --actor-person-id <operator person> --approver <ref> --issue <ref> \\
      [--apply --snapshot-reference <ref>] < scripts/data-changes/admin.py

Usage notes: docs/product/lead-desk/admin-cli.md.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn
from uuid import UUID, uuid5

from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.application.asyncio_runtime import run_async
from ac_platform.application.release_identity import require_baked_release_id
from ac_platform.application.settings import Settings
from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import append_audit_event
from ac_platform.identity.models import Person
from ac_platform.kernel.errors import DomainError
from ac_platform.organisations.service import OrganisationCommandError, OrganisationService
from ac_platform.tenancy.models import Membership, Organisation, OrganisationDomainSetting, Tenant
from ac_platform.tenancy.roles import ASSIGNABLE_ROLES

ACTION = "admin.data_change_applied"
ENVIRONMENTS = ("development", "staging", "production")
# The first primitives' flat names (8250dba7c, v1.78) keep working.
LEGACY: dict[str, tuple[str, str]] = {
    "transfer-owner": ("people", "transfer-owner"),
    "set-role": ("people", "set-role"),
    "rename-person": ("people", "rename"),
    "reassign-leads": ("leads", "reassign"),
    "remove-member": ("people", "remove-member"),
}
COMMANDS: dict[str, tuple[str, ...]] = {
    "people": (
        "list",
        "show",
        "invite",
        "resend-invite",
        "set-role",
        "transfer-owner",
        "rename",
        "remove-member",
        "taking-leads",
    ),
    "workspaces": ("list", "show", "create", "rename", "domains", "switches", "lead-rules"),
    "leads": (
        "list",
        "add",
        "assign",
        "reassign",
        "stage",
        "archive",
        "restore-archive",
        "bin",
        "restore-bin",
        "import",
    ),
    "ask-dipak": ("videos", "add-video", "remove-video"),
}
READS = {("people", "list"), ("people", "show"), ("workspaces", "list"), ("workspaces", "show")}
READS |= {("leads", "list")}
NO_TENANT = {("workspaces", "list"), ("workspaces", "create")}
NO_TENANT |= {("ask-dipak", name) for name in ("videos", "add-video", "remove-video")}
SHELF = {"archive": "archive", "restore-archive": "restore_archive", "bin": "bin"}
SHELF["restore-bin"] = "restore_bin"
SWITCHES = ("paused", "note", "task", "outcome", "update", "stage")
# workspaces lead-rules: the options that change something (none: it reads).
LEAD_RULES = (
    "split",
    "no_split",
    "auto_reassign",
    "reassign_minutes",
    "work_days",
    "work_start",
    "work_end",
    "pause_leads",
    "sellers_reassign",
)
SPLIT_ID = "admin-split"
DAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
MAX_NAME = 200
MAX_LEADS = 2000
PAGE = 50


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise OrganisationCommandError("invalid arguments; use --help")


class ResultDeliveryError(RuntimeError):
    """The transaction committed, but its receipt could not be delivered."""


class Rehearsed(Exception):
    """A dry run's changes are rolled back by raising this inside the transaction."""

    def __init__(self, output: dict[str, object]) -> None:
        super().__init__("dry run")
        self.output = output


def _reference(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}", value):
        raise ValueError("a reference ID without credentials or personal data is required")
    return value


def _name(value: str) -> str:
    name = " ".join(value.split())
    if not 1 <= len(name) <= MAX_NAME or any(ord(c) < 0x20 or ord(c) == 0x7F for c in name):
        raise ValueError("a display name of 1 to 200 printable characters is required")
    return name


def _email(value: str) -> str:
    email = value.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) or len(email) > 320:
        raise ValueError("an e-mail address is required")
    return email


def _on_off(value: str) -> bool:
    if value not in ("on", "off"):
        raise ValueError("on or off")
    return value == "on"


def _share(value: str) -> tuple[UUID, int]:
    """``person=percent`` for a split."""
    person, _, share = value.partition("=")
    try:
        return UUID(person.strip()), int(share)
    except ValueError:
        raise argparse.ArgumentTypeError("person=percent") from None


def _days(value: str) -> tuple[int, ...]:
    """``mon-sat`` or ``mon,tue,wed``: work days, 0 for Monday."""
    words = value.lower().replace(" ", "")
    try:
        if "-" in words:
            first, last = (DAY_KEYS.index(word) for word in words.split("-", 1))
            return tuple(range(first, last + 1))
        return tuple(sorted({DAY_KEYS.index(word) for word in words.split(",")}))
    except ValueError:
        raise argparse.ArgumentTypeError("days like mon-sat or mon,tue") from None


def _clock(value: str) -> str:
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", value):
        raise argparse.ArgumentTypeError("HH:MM")
    return value


def _when(value: str) -> datetime:
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        raise ValueError("a time with its offset is required")
    return moment


def _mask(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    return f"{email[:1]}***@{email.rsplit('@', 1)[1]}"


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--environment", choices=ENVIRONMENTS, required=True)
    parser.add_argument("--allow-production", action="store_true")
    parser.add_argument("--actor-person-id", type=UUID)
    parser.add_argument("--command-id", type=UUID)
    parser.add_argument("--approver", type=_reference)
    parser.add_argument("--issue", "--issue-reference", dest="issue_reference", type=_reference)
    parser.add_argument("--operator-reference", type=_reference, default="admin-cli")
    parser.add_argument("--run-reference", type=UUID)
    parser.add_argument("--snapshot-reference", type=_reference)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")


def _where(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--lead-id", type=UUID, action="append")
    parser.add_argument("--where-owner", type=UUID)
    parser.add_argument("--where-unassigned", action="store_true")
    parser.add_argument("--where-step", type=_reference)
    parser.add_argument("--where-stage", type=_reference)
    parser.add_argument("--where-side", choices=("inbound", "cold"))
    parser.add_argument("--where-search")
    parser.add_argument("--where-source")
    parser.add_argument("--where-pipeline", type=_reference)
    parser.add_argument("--where-shelf", choices=("archived", "bin"))
    parser.add_argument("--expected-total", type=int)


def _parser() -> argparse.ArgumentParser:
    parser = SafeParser(
        description=__doc__, allow_abbrev=False, formatter_class=argparse.RawTextHelpFormatter
    )
    groups = parser.add_subparsers(dest="group", required=True, parser_class=SafeParser)
    made: dict[tuple[str, str], argparse.ArgumentParser] = {}
    for group, names in COMMANDS.items():
        commands = groups.add_parser(group, allow_abbrev=False).add_subparsers(
            dest="command", required=True, parser_class=SafeParser
        )
        for name in names:
            sub = commands.add_parser(name, allow_abbrev=False)
            _common(sub)
            if (group, name) not in NO_TENANT:
                sub.add_argument("--tenant-id", type=UUID, required=True)
            made[(group, name)] = sub
    roles = ASSIGNABLE_ROLES
    for name in ("show", "set-role", "transfer-owner", "rename", "remove-member", "taking-leads"):
        made[("people", name)].add_argument("--person-id", type=UUID, required=True)
    made[("people", "taking-leads")].add_argument("--taking", type=_on_off, required=True)
    made[("people", "set-role")].add_argument("--role", choices=roles, required=True)
    made[("people", "rename")].add_argument("--name", type=_name, required=True)
    for name in ("invite", "resend-invite"):
        made[("people", name)].add_argument("--email", type=_email, required=True)
    made[("people", "invite")].add_argument("--role", choices=roles, default="member")
    made[("workspaces", "create")].add_argument("--name", type=_name, required=True)
    made[("workspaces", "create")].add_argument("--owner-person-id", type=UUID, required=True)
    made[("workspaces", "rename")].add_argument("--name", type=_name, required=True)
    domains = made[("workspaces", "domains")]
    domains.add_argument("--domain", action="append", default=[])
    domains.add_argument("--auto-join", action="store_true")
    domains.add_argument("--clear", action="store_true")
    for switch in SWITCHES:
        made[("workspaces", "switches")].add_argument(f"--{switch}", type=_on_off)
    rules = made[("workspaces", "lead-rules")]
    rules.add_argument("--split", action="append", type=_share, default=[])
    rules.add_argument("--split-name", type=_name, default="Split by percent")
    rules.add_argument("--no-split", action="store_true")
    rules.add_argument("--auto-reassign", type=_on_off)
    rules.add_argument("--reassign-minutes", type=int)
    rules.add_argument("--work-days", type=_days)
    rules.add_argument("--work-start", type=_clock)
    rules.add_argument("--work-end", type=_clock)
    rules.add_argument("--pause-leads", type=_on_off)
    rules.add_argument("--sellers-reassign", type=_on_off)
    listing = made[("leads", "list")]
    _where(listing)
    listing.add_argument("--search")
    listing.add_argument("--names", action="store_true")
    listing.add_argument("--offset", type=int, default=0)
    listing.add_argument("--limit", type=int, default=PAGE)
    add = made[("leads", "add")]
    add.add_argument("--name", type=_name, required=True)
    for field in ("phone", "email", "company", "city", "note"):
        add.add_argument(f"--{field}")
    add.add_argument("--owner-person-id", type=UUID)
    add.add_argument("--side", choices=("live", "cold"), default="live")
    add.add_argument("--pipeline", type=_reference)
    for name in ("assign", "reassign", "stage", *SHELF):
        _where(made[("leads", name)])
    made[("leads", "assign")].add_argument("--to-person-id", type=UUID)
    made[("leads", "assign")].add_argument("--rules", action="store_true")
    made[("leads", "reassign")].add_argument(
        "--person-id", "--from-person-id", dest="person_id", type=UUID, required=True
    )
    made[("leads", "reassign")].add_argument("--to-person-id", type=UUID, required=True)
    stage = made[("leads", "stage")]
    stage.add_argument("--step", type=_reference, required=True)
    stage.add_argument("--outcome-reason", type=_reference)
    stage.add_argument("--reason-note")
    stage.add_argument("--next-action-at", type=_when)
    made[("leads", "import")].add_argument("--input", type=Path, required=True)
    made[("ask-dipak", "videos")].add_argument("state", nargs="?", choices=("on", "off"))
    for name in ("add-video", "remove-video"):
        made[("ask-dipak", name)].add_argument("--lesson", type=_reference, required=True)
    video = made[("ask-dipak", "add-video")]
    video.add_argument("--src", required=True)
    video.add_argument("--poster", required=True)
    video.add_argument("--seconds", type=int, required=True)
    return parser


def parse(argv: list[str] | None) -> argparse.Namespace:
    """The arguments, with the old flat names read as their group's command."""
    given = list(sys.argv[1:] if argv is None else argv)
    legacy = given[0] if given and given[0] in LEGACY else ""
    if legacy:
        given = [*LEGACY[legacy], *given[1:]]
    args = _parser().parse_args(given)
    args.legacy = legacy
    if legacy:
        args.json = True
    for name in ("person_id", "to_person_id", "name", "role", "email", "lead_id"):
        if not hasattr(args, name):
            setattr(args, name, None)
    return args


def _key(args: argparse.Namespace) -> tuple[str, str]:
    return (args.group, args.command)


def _writes(args: argparse.Namespace) -> bool:
    if _key(args) == ("workspaces", "switches"):
        return any(getattr(args, switch) is not None for switch in SWITCHES)
    if _key(args) == ("workspaces", "lead-rules"):
        return any(getattr(args, name) not in (None, False, []) for name in LEAD_RULES)
    if _key(args) == ("ask-dipak", "videos"):
        return args.state is not None
    return _key(args) not in READS


def _check_command(args: argparse.Namespace) -> None:
    key = _key(args)
    if key == ("leads", "reassign") and args.to_person_id == args.person_id:
        raise OrganisationCommandError("the leads already belong to that person")
    if key == ("leads", "assign") and (args.to_person_id is None) == (not args.rules):
        raise OrganisationCommandError("--to-person-id or --rules, one of them")
    if key == ("workspaces", "domains") and (
        args.clear == bool(args.domain) or (args.clear and args.auto_join)
    ):
        raise OrganisationCommandError("--domain (with --auto-join), or --clear")
    if key == ("workspaces", "lead-rules"):
        if args.split and args.no_split:
            raise OrganisationCommandError("--split or --no-split, one of them")
        if args.split and sum(share for _, share in args.split) != 100:
            raise OrganisationCommandError("the split's shares add up to 100")
        if args.reassign_minutes is not None and not 5 <= args.reassign_minutes <= 1440:
            raise OrganisationCommandError("--reassign-minutes is 5 to 1440")
    if args.group == "leads" and args.command not in ("list", "add", "import"):
        filtered = _filtered(args)
        if args.command != "reassign" and (args.lead_id is None) == (not filtered):
            raise OrganisationCommandError("--lead-id or --where-* options, one of them")
        if args.lead_id is not None and len(set(args.lead_id)) > MAX_LEADS:
            raise OrganisationCommandError("up to 2,000 leads at a time")
        if args.command == "reassign" and args.lead_id is not None:
            raise OrganisationCommandError("reassign takes --where-* options, not --lead-id")
    if not _writes(args):
        return
    if args.actor_person_id is None or args.approver is None or args.issue_reference is None:
        raise OrganisationCommandError("--actor-person-id, --approver and --issue are required")


def _filtered(args: argparse.Namespace) -> bool:
    return any(
        getattr(args, name, None)
        for name in (
            "where_owner",
            "where_unassigned",
            "where_step",
            "where_stage",
            "where_side",
            "where_search",
            "where_source",
            "where_pipeline",
            "where_shelf",
        )
    )


def _settings(args: argparse.Namespace) -> Settings:
    if args.environment == "production" and not args.allow_production:
        raise OrganisationCommandError("production needs --allow-production")
    if os.getenv("AC_ENVIRONMENT") != args.environment:
        raise OrganisationCommandError("the runtime is not the named environment")
    if not os.getenv("AC_DATABASE_URL", "").strip():
        raise OrganisationCommandError("an injected database URL is required")
    settings = Settings(_env_file=None)
    if settings.environment != args.environment:
        raise OrganisationCommandError("the runtime is not the named environment")
    if args.environment != "development":
        require_baked_release_id(settings.release_id)
    if settings.operations_tenant_id is None or settings.public_learner_tenant_id is None:
        raise OrganisationCommandError("protected tenant IDs must be configured")
    return settings


def _intent(args: argparse.Namespace) -> dict[str, Any]:
    """What the command changes: its name and every option that says what, never who."""
    skip = {
        "environment",
        "allow_production",
        "command_id",
        "approver",
        "issue_reference",
        "operator_reference",
        "run_reference",
        "snapshot_reference",
        "apply",
        "json",
        "legacy",
        "group",
        "command",
        "names",
        "input",
    }
    intent: dict[str, Any] = {"command": f"{args.group} {args.command}"}
    for name, value in sorted(vars(args).items()):
        if name in skip or value is None or value is False or value == []:
            continue
        if isinstance(value, list):
            value = sorted(str(item) for item in value)
        elif isinstance(value, tuple):  # work days: compared with the stored JSON list on replay
            value = list(value)
        elif isinstance(value, UUID | datetime | Path):
            value = str(value)
        intent[name] = value
    if args.group == "leads" and args.command == "import":
        intent["input_sha256"] = _input_digest(args.input)
    return intent


def _input_digest(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _command_id(args: argparse.Namespace, intent: dict[str, Any]) -> UUID:
    if args.command_id is not None:
        return args.command_id  # type: ignore[no-any-return]
    namespace = uuid5(UUID(int=0), f"ac-admin-cli:{args.environment}:{args.issue_reference}")
    return uuid5(namespace, json.dumps(intent, sort_keys=True))


def _reason(args: argparse.Namespace, command_id: UUID) -> str:
    return json.dumps(
        {
            "tool": "admin",
            "command": args.legacy or f"{args.group} {args.command}",
            "environment": args.environment,
            "approver": args.approver,
            "issue": args.issue_reference,
            "operator": args.operator_reference,
            "run": str(args.run_reference or command_id),
        },
        sort_keys=True,
    )


class Context:
    """One command's transaction, settings, arguments and the app command id it passes on.
    (A plain class: the script is loaded without a module entry, which dataclasses need.)"""

    def __init__(
        self,
        database: AsyncSession,
        settings: Settings,
        args: argparse.Namespace,
        child: UUID,
        service: OrganisationService,
    ) -> None:
        self.database, self.settings, self.args = database, settings, args
        self.child, self.service = child, service

    @property
    def tenant_id(self) -> UUID:
        return self.args.tenant_id  # type: ignore[no-any-return]

    def desk(self, role: str = "owner") -> Any:
        from ac_platform.lead_desk.store import LeadDesk, Viewer

        return LeadDesk(
            self.database,
            # The operator acts as a manager of the organisation, as onboarding does; each
            # lead's own history line names it.
            Viewer(
                person_id=self.args.actor_person_id or UUID(int=0),
                tenant_id=self.tenant_id,
                role=role,
                name="AC operator",
            ),
            call_mode="phone",
            now=datetime.now(UTC),
        )


Result = dict[str, object]
Handler = Callable[[Context], Awaitable[Result]]


async def _members(database: AsyncSession, tenant_id: UUID) -> dict[UUID, Membership]:
    rows = await database.scalars(
        select(Membership).where(
            Membership.tenant_id == tenant_id,
            Membership.status == "active",
            Membership.ended_at.is_(None),
            Membership.role != "processing",
        )
    )
    return {row.person_id: row for row in rows}


async def _owner(database: AsyncSession, tenant_id: UUID) -> Membership:
    owners = [row for row in (await _members(database, tenant_id)).values() if row.role == "owner"]
    if len(owners) != 1:
        raise OrganisationCommandError("exactly one active owner required")
    return owners[0]


async def _member(ctx: Context, person_id: UUID) -> tuple[Person, Membership]:
    target = (await _members(ctx.database, ctx.tenant_id)).get(person_id)
    person = await ctx.database.get(Person, person_id)
    if person is None or person.status != "active" or target is None:
        raise OrganisationCommandError("the person must be an active member of the organisation")
    return person, target


async def _open_leads(database: AsyncSession, tenant_id: UUID, person_id: UUID) -> int:
    from ac_platform.lead_desk.models import Lead

    return int(
        await database.scalar(
            select(func.count())
            .select_from(Lead)
            .where(
                Lead.tenant_id == tenant_id,
                Lead.owner_person_id == person_id,
                Lead.archived_at.is_(None),
                Lead.binned_at.is_(None),
            )
        )
        or 0
    )


# ----- people --------------------------------------------------------------------------------


async def people_list(ctx: Context) -> Result:
    from ac_platform.organisations.invitations import active_pending_invites

    rows = await ctx.database.execute(
        select(Membership, Person)
        .join(Person, Person.id == Membership.person_id)
        .where(Membership.tenant_id == ctx.tenant_id, Membership.role != "processing")
        .order_by(Membership.role, Person.display_name, Person.id)
    )
    people = [
        {
            "person_id": str(membership.person_id),
            "name": person.display_name,
            "email": _mask(person.email),
            "role": membership.role,
            "status": "ended" if membership.ended_at is not None else membership.status,
        }
        for membership, person in rows
    ]
    invites = [
        {"invite_id": str(row.id), "email": _mask(row.email_normalized), "role": row.role}
        for row in await active_pending_invites(ctx.database, tenant_id=ctx.tenant_id)
    ]
    return {"status": "read", "people": people, "pending_invites": invites}


async def people_show(ctx: Context) -> Result:
    person = await ctx.database.get(Person, ctx.args.person_id)
    membership = await ctx.database.get(Membership, (ctx.tenant_id, ctx.args.person_id))
    if person is None or membership is None:
        raise OrganisationCommandError("no such member of the organisation")
    return {
        "status": "read",
        "person": {
            "person_id": str(person.id),
            "name": person.display_name,
            "email": _mask(person.email),
            "email_verified": person.email_verified_at is not None,
            "account_status": person.status,
            "role": membership.role,
            "membership_status": "ended" if membership.ended_at is not None else membership.status,
            "open_leads": await _open_leads(ctx.database, ctx.tenant_id, person.id),
        },
    }


async def _pending(ctx: Context, email: str) -> Any:
    from ac_platform.organisations.invitations import active_pending_invites

    for row in await active_pending_invites(ctx.database, tenant_id=ctx.tenant_id):
        if row.email_normalized.lower() == email:
            return row
    return None


async def people_invite(ctx: Context) -> Result:
    args = ctx.args
    person = None
    found = list(
        await ctx.database.scalars(select(Person).where(func.lower(Person.email) == args.email))
    )
    if len(found) > 1:
        raise OrganisationCommandError("ambiguous person; resolve the account first")
    person = found[0] if found else None
    membership = await ctx.database.get(Membership, (ctx.tenant_id, person.id)) if person else None
    if membership is not None and membership.status == "active" and membership.ended_at is None:
        before = {"role": membership.role, "status": "active"}
        return {"status": "already_member", "before": before, "after": before}
    if person is not None and person.status != "active":
        raise OrganisationCommandError("that account is not active")
    if person is not None and person.email_verified_at is not None:
        await ctx.service.add_member(
            ctx.tenant_id,
            person.id,
            args.role,
            ctx.child,
            actor_person_id=args.actor_person_id,
            operator_reference=args.operator_reference,
        )
        return {
            "status": "eligible",
            "person_id": str(person.id),
            "before": None,
            "after": {"role": args.role, "status": "active"},
        }
    pending = await _pending(ctx, args.email)
    if pending is not None:
        return {
            "status": "already_invited",
            "invite_id": str(pending.id),
            "before": {"invite": "pending", "role": pending.role},
            "after": {"invite": "pending", "role": pending.role},
        }
    invited = await ctx.service.request_member(
        ctx.tenant_id,
        args.email,
        args.role,
        ctx.child,
        actor_person_id=args.actor_person_id,
        operator_reference=args.operator_reference,
        operator_auto_join=True,
    )
    return {
        "status": "eligible",
        "invite_id": str(invited["invite_id"]),
        "email": _mask(args.email),
        "before": None,
        "after": {"invite": "pending", "role": args.role, "email": "invitation"},
    }


async def people_resend_invite(ctx: Context) -> Result:
    args = ctx.args
    pending = await _pending(ctx, args.email)
    if pending is None:
        raise OrganisationCommandError("no pending invite for that e-mail; use people invite")
    await ctx.service.revoke_invite(
        ctx.tenant_id,
        pending.id,
        uuid5(ctx.child, "revoke"),
        actor_person_id=args.actor_person_id,
        operator_reference=args.operator_reference,
    )
    invited = await ctx.service.request_member(
        ctx.tenant_id,
        args.email,
        pending.role,
        uuid5(ctx.child, "invite"),
        actor_person_id=args.actor_person_id,
        operator_reference=args.operator_reference,
        operator_auto_join=True,
    )
    return {
        "status": "eligible",
        "before": {"invite_id": str(pending.id), "role": pending.role},
        "after": {
            "invite_id": str(invited["invite_id"]),
            "role": pending.role,
            "email": "invitation",
            "revoked": str(pending.id),
        },
    }


async def people_set_role(ctx: Context) -> Result:
    args = ctx.args
    await _owner(ctx.database, ctx.tenant_id)
    _, target = await _member(ctx, args.person_id)
    before = {"role": target.role}
    if target.role == "owner":
        raise OrganisationCommandError("the owner's role changes only by transfer-owner")
    if target.role == args.role:
        return {"status": f"already_{args.role}", "before": before, "after": before}
    await ctx.service.change_member_role(
        ctx.tenant_id,
        args.person_id,
        args.role,
        ctx.child,
        actor_person_id=args.actor_person_id,
        operator_reference=args.operator_reference,
    )
    return {"status": "eligible", "before": before, "after": {"role": args.role}}


async def people_transfer_owner(ctx: Context) -> Result:
    args = ctx.args
    owner = await _owner(ctx.database, ctx.tenant_id)
    person, target = await _member(ctx, args.person_id)
    before = {"owner": str(owner.person_id), "person_role": target.role}
    if owner.person_id == args.person_id:
        return {"status": "already_owner", "before": before, "after": before}
    if person.email_verified_at is None:
        raise OrganisationCommandError("the new owner needs a verified e-mail")
    await ctx.service.transfer_ownership(
        ctx.tenant_id,
        args.person_id,
        ctx.child,
        actor_person_id=args.actor_person_id,
        operator_reference=args.operator_reference,
    )
    after = {"owner": str(args.person_id), "former_owner_role": "admin", "emails": "both"}
    return {"status": "eligible", "before": before, "after": after}


async def people_rename(ctx: Context) -> Result:
    args = ctx.args
    await _owner(ctx.database, ctx.tenant_id)
    person, _ = await _member(ctx, args.person_id)
    before = {"name": person.display_name}
    if person.display_name == args.name:
        return {"status": "already_named", "before": before, "after": before}
    # The app's own rename lets a person rename only themselves; an operator renames here.
    person.display_name = args.name
    person.revision += 1
    await ctx.database.flush()
    return {"status": "eligible", "before": before, "after": {"name": args.name}}


async def people_remove_member(ctx: Context) -> Result:
    args = ctx.args
    await _owner(ctx.database, ctx.tenant_id)
    target = (await _members(ctx.database, ctx.tenant_id)).get(args.person_id)
    if target is None:
        return {"status": "already_absent", "before": None, "after": None}
    if target.role == "owner":
        raise OrganisationCommandError("the owner is never removed; transfer-owner first")
    before = {"role": target.role, "status": "active"}
    await ctx.service.remove_member(
        ctx.tenant_id,
        args.person_id,
        ctx.child,
        actor_person_id=args.actor_person_id,
        operator_reference=args.operator_reference,
    )
    return {
        "status": "eligible",
        "before": before,
        "after": {"role": target.role, "status": "inactive"},
    }


async def people_taking_leads(ctx: Context) -> Result:
    """Team's "Taking new leads" switch, through the app's own save of a seller's rules
    (LeadDesk.save_rep): only the switch changes; the open-lead limit, languages, areas and
    interests stay as they are (owner, 17 Nov 2026: Wise Life's new leads wait in the no-owner
    pool and Shivam assigns them)."""
    from ac_platform.lead_desk.contracts import RepRules
    from ac_platform.lead_desk.models import LeadRep
    from ac_platform.lead_desk.store import default_cap, takes_new_leads

    args = ctx.args
    _, membership = await _member(ctx, args.person_id)
    desk = ctx.desk()
    row = await ctx.database.get(LeadRep, (ctx.tenant_id, args.person_id), with_for_update=True)
    before = {"taking": takes_new_leads(membership.role, row)}
    if before["taking"] == args.taking:
        word = "taking" if args.taking else "off"
        return {"status": f"already_{word}", "before": before, "after": before}
    rules = RepRules(
        expected_revision=row.revision if row else 0,
        available=args.taking,
        max_open=row.max_open if row else default_cap((await desk.settings())[1]),
        languages=tuple(row.languages or ()) if row else (),
        areas=tuple(row.areas or ()) if row else (),
        interests=tuple(row.interests or ()) if row else (),
    )
    await desk.save_rep(args.person_id, rules)
    saved = await ctx.database.get(LeadRep, (ctx.tenant_id, args.person_id))
    after = {"taking": takes_new_leads(membership.role, saved)}
    return {"status": "eligible", "before": before, "after": after}


# ----- workspaces ----------------------------------------------------------------------------


def _protected(settings: Settings) -> set[UUID | None]:
    return {settings.operations_tenant_id, settings.public_learner_tenant_id}


async def workspaces_list(ctx: Context) -> Result:
    counted = await ctx.database.execute(
        select(Membership.tenant_id, func.count())
        .where(
            Membership.status == "active",
            Membership.ended_at.is_(None),
            Membership.role != "processing",
        )
        .group_by(Membership.tenant_id)
    )
    counts: dict[UUID, int] = {tenant_id: int(count) for tenant_id, count in counted.all()}
    rows = await ctx.database.execute(
        select(Tenant)
        .join(Organisation, Organisation.tenant_id == Tenant.id)
        .order_by(Tenant.name, Tenant.id)
    )
    protected = _protected(ctx.settings)
    workspaces = [
        {
            "tenant_id": str(tenant.id),
            "name": tenant.name,
            "status": tenant.status,
            "members": int(counts.get(tenant.id, 0)),
        }
        for (tenant,) in rows
        if tenant.id not in protected
    ]
    return {"status": "read", "workspaces": workspaces}


async def _domains(database: AsyncSession, tenant_id: UUID) -> OrganisationDomainSetting | None:
    row: OrganisationDomainSetting | None = await database.scalar(
        select(OrganisationDomainSetting)
        .where(OrganisationDomainSetting.tenant_id == tenant_id)
        .order_by(OrganisationDomainSetting.version.desc())
        .limit(1)
    )
    return row


async def _switch(ctx: Context) -> tuple[int, dict[str, bool]]:
    from ac_platform.integrations.ai_writes import IN_APP, AiWrites

    return await AiWrites(ctx.desk(), IN_APP).settings()


async def workspaces_show(ctx: Context) -> Result:
    from ac_platform.lead_desk.models import Lead
    from ac_platform.organisations.invitations import active_pending_invites

    tenant = await ctx.database.get(Tenant, ctx.tenant_id)
    assert tenant is not None
    members = await _members(ctx.database, ctx.tenant_id)
    roles: dict[str, int] = {}
    for row in members.values():
        roles[row.role] = roles.get(row.role, 0) + 1
    owner = next((row.person_id for row in members.values() if row.role == "owner"), None)
    domains = await _domains(ctx.database, ctx.tenant_id)
    leads = {
        "on_desk": await _count_leads(ctx, Lead.archived_at.is_(None), Lead.binned_at.is_(None)),
        "archived": await _count_leads(ctx, Lead.archived_at.isnot(None), Lead.binned_at.is_(None)),
        "bin": await _count_leads(ctx, Lead.binned_at.isnot(None)),
        "unassigned": await _count_leads(
            ctx,
            Lead.owner_person_id.is_(None),
            Lead.archived_at.is_(None),
            Lead.binned_at.is_(None),
        ),
    }
    revision, switch = await _switch(ctx)
    return {
        "status": "read",
        "workspace": {
            "tenant_id": str(tenant.id),
            "name": tenant.name,
            "slug": tenant.slug,
            "status": tenant.status,
            "created_at": tenant.created_at.isoformat(),
            "owner_person_id": str(owner) if owner else None,
            "members_by_role": dict(sorted(roles.items())),
            "pending_invites": len(
                await active_pending_invites(ctx.database, tenant_id=ctx.tenant_id)
            ),
            "verified_domains": list(domains.verified_domains) if domains else [],
            "auto_join": bool(domains.auto_join) if domains else False,
            "ai_apps_switch": {"revision": revision, **switch},
            "leads": leads,
        },
    }


async def _count_leads(ctx: Context, *conditions: Any) -> int:
    from ac_platform.lead_desk.models import Lead

    return int(
        await ctx.database.scalar(
            select(func.count())
            .select_from(Lead)
            .where(Lead.tenant_id == ctx.tenant_id, *conditions)
        )
        or 0
    )


async def workspaces_create(ctx: Context) -> Result:
    args = ctx.args
    owner = await ctx.database.get(Person, args.owner_person_id)
    if owner is None or owner.status != "active" or owner.email_verified_at is None:
        raise OrganisationCommandError("the owner must be an active account with a verified e-mail")
    made = await ctx.service.create(
        args.name,
        args.owner_person_id,
        ctx.child,
        args.operator_reference,
        reason=_reason(args, ctx.child),
    )
    after = {
        "tenant_id": str(made.tenant_id),
        "name": made.name,
        "owner": str(made.owner_person_id),
    }
    status = "already_created" if made.replayed else "eligible"
    return {"status": status, "tenant_id": str(made.tenant_id), "before": None, "after": after}


async def workspaces_rename(ctx: Context) -> Result:
    tenant = await ctx.database.scalar(
        select(Tenant).where(Tenant.id == ctx.tenant_id).with_for_update(nowait=True)
    )
    assert tenant is not None
    before = {"name": tenant.name}
    if not 2 <= len(ctx.args.name) <= 80:
        raise OrganisationCommandError("organisation name must contain 2 to 80 characters")
    if tenant.name == ctx.args.name:
        return {"status": "already_named", "before": before, "after": before}
    # Organisation settings (organisations/settings.py) renames for an owner or admin who is a
    # member; an operator renames the same field here, audited below.
    tenant.name = ctx.args.name
    tenant.revision += 1
    await ctx.database.flush()
    return {"status": "eligible", "before": before, "after": {"name": ctx.args.name}}


async def workspaces_domains(ctx: Context) -> Result:
    latest = await _domains(ctx.database, ctx.tenant_id)
    before = {
        "verified_domains": list(latest.verified_domains) if latest else [],
        "auto_join": bool(latest.auto_join) if latest else False,
    }
    chosen = sorted({domain.strip().lower() for domain in ctx.args.domain})
    after = {"verified_domains": chosen, "auto_join": bool(ctx.args.auto_join)}
    if before == after:
        return {"status": "already_set", "before": before, "after": before}
    result = await ctx.service.set_domains_attested(
        ctx.tenant_id,
        chosen,
        bool(ctx.args.auto_join),
        ctx.args.operator_reference,
        ctx.child,
        actor_person_id=ctx.args.actor_person_id,
        reason=_reason(ctx.args, ctx.child),
    )
    after = {
        "verified_domains": list(result.verified_domains),
        "auto_join": bool(result.auto_join),
    }
    return {"status": "eligible", "before": before, "after": after}


async def workspaces_switches(ctx: Context) -> Result:
    from ac_platform.integrations.ai_writes import IN_APP, AiWrites

    revision, before = await _switch(ctx)
    if not _writes(ctx.args):
        return {"status": "read", "ai_apps_switch": {"revision": revision, **before}}
    values = {
        switch: getattr(ctx.args, switch)
        for switch in SWITCHES
        if getattr(ctx.args, switch) is not None
    }
    if all(before.get(name) == value for name, value in values.items()):
        return {"status": "already_set", "before": before, "after": before}
    saved = await AiWrites(ctx.desk(), IN_APP).save_settings(revision, values)
    after = {name: saved[name] for name in before}
    return {"status": "eligible", "before": before, "after": after}


async def _lead_rules_now(ctx: Context) -> dict[str, Any]:
    from ac_platform.lead_desk import hours as work_hours
    from ac_platform.lead_desk import routing_rules

    revision, config = await ctx.desk().settings()
    rules = routing_rules.stored(config)
    split = next((rule for rule in rules if rule.id == SPLIT_ID), None)
    return {
        "revision": revision,
        "split": (
            {
                "name": split.name,
                "enabled": split.enabled,
                "shares": {
                    str(person): share
                    for person, share in zip(split.give_to, split.shares, strict=False)
                },
            }
            if split is not None
            else None
        ),
        "other_routing_rules": sum(1 for rule in rules if rule.id != SPLIT_ID),
        "auto_reassign": bool(config.get("auto_reassign")),
        "reassign_minutes": int(config.get("reassign_minutes") or 0),
        "work_hours": work_hours.as_config(work_hours.parse(config)),
        "sellers_reassign": bool(config.get("sellers_reassign")),
    }


async def workspaces_lead_rules(ctx: Context) -> Result:
    """Lead rules through the app's own saves (LeadDesk.save_routing, save_settings,
    save_work_hours). Wise Life, 19 Nov 2026 (owner, Wise Life office session): Dheeraj 20%,
    Aniket 40%, Sachin 40%; 30 work minutes before an uncalled lead moves on; Mon-Sat;
    sellers may give a lead to a colleague with a reason. The split is one rule, first, with a
    fixed id, so a rerun replaces it and the split's counts carry on."""
    from ac_platform.lead_desk import routing_rules
    from ac_platform.lead_desk.contracts import SettingsCommand, WorkHoursCommand

    args = ctx.args
    before = await _lead_rules_now(ctx)
    if not _writes(args):
        return {"status": "read", "lead_rules": before}
    desk = ctx.desk()
    if args.split or args.no_split:
        members = await _members(ctx.database, ctx.tenant_id)
        if any(person not in members for person, _ in args.split):
            raise OrganisationCommandError("every person in the split must be a member")
        revision, config = await desk.settings()
        others = [rule for rule in routing_rules.stored(config) if rule.id != SPLIT_ID]
        made = (
            [
                routing_rules.Rule(
                    id=SPLIT_ID,
                    name=args.split_name,
                    give_to=tuple(person for person, _ in args.split),
                    shares=tuple(share for _, share in args.split),
                )
            ]
            if args.split
            else []
        )
        await desk.save_routing(
            routing_rules.RoutingCommand(
                expected_revision=revision,
                rules=(*made, *others),
                value_answer=config.get(routing_rules.VALUE_KEY),
            )
        )
    hours_given = (args.work_days, args.work_start, args.work_end, args.pause_leads)
    if any(value is not None for value in hours_given):
        revision, _ = await desk.settings()
        now = before["work_hours"] or {}
        await desk.save_work_hours(
            WorkHoursCommand(
                expected_revision=revision,
                days=args.work_days if args.work_days is not None else tuple(now.get("days", ())),
                start=args.work_start or now.get("start", "09:30"),
                end=args.work_end or now.get("end", "19:00"),
                pause_leads=(
                    args.pause_leads
                    if args.pause_leads is not None
                    else bool(now.get("pause_leads"))
                ),
            )
        )
    settings_given = (args.auto_reassign, args.reassign_minutes, args.sellers_reassign)
    if any(value is not None for value in settings_given):
        revision, config = await desk.settings()
        await desk.save_settings(
            SettingsCommand(
                expected_revision=revision,
                auto_reassign=(
                    args.auto_reassign
                    if args.auto_reassign is not None
                    else bool(config.get("auto_reassign"))
                ),
                reassign_minutes=(
                    args.reassign_minutes
                    if args.reassign_minutes is not None
                    else int(config.get("reassign_minutes") or 10)
                ),
                sellers_reassign=args.sellers_reassign,
            )
        )
    after = await _lead_rules_now(ctx)
    unchanged = {key: value for key, value in after.items() if key != "revision"} == {
        key: value for key, value in before.items() if key != "revision"
    }
    return {
        "status": "already_set" if unchanged else "eligible",
        "before": before,
        "after": after,
    }


# ----- ask dipak -----------------------------------------------------------------------------


async def ask_dipak_videos(ctx: Context) -> Result:
    """The lesson-video switch and the approved videos; with on or off, the switch changes."""
    from ac_platform.ask_dipak import videos

    before = await videos.current(ctx.database)
    tenant = {"tenant_id": str(ctx.settings.operations_tenant_id)}
    key = _key(ctx.args)
    if key == ("ask-dipak", "videos") and ctx.args.state is None:
        return {"status": "read", "lesson_videos": before}
    after = {"enabled": before["enabled"], "videos": dict(before["videos"])}
    try:
        if key == ("ask-dipak", "videos"):
            after["enabled"] = ctx.args.state == "on"
        elif key == ("ask-dipak", "add-video"):
            lesson = ctx.args.lesson.upper()
            after["videos"][lesson] = videos.check_video(
                lesson, ctx.args.src, ctx.args.poster, ctx.args.seconds
            )
        else:
            after["videos"].pop(ctx.args.lesson.upper(), None)
    except videos.VideoError as error:
        raise OrganisationCommandError(str(error)) from None
    result = await videos.record(
        ctx.database,
        state=after,
        approved_by=ctx.args.approver,
        issue=ctx.args.issue_reference,
        note=f"admin.py {ctx.args.group} {ctx.args.command}",
        now=datetime.now(UTC),
    )
    return {**result, **tenant}


# ----- leads ---------------------------------------------------------------------------------


def _filter(args: argparse.Namespace, *, owner: UUID | None = None) -> Any:
    from ac_platform.lead_desk.contracts import LeadFilter

    return LeadFilter(
        scope="unassigned" if args.where_unassigned else "team",
        side=args.where_side,
        stage=args.where_stage,
        step=args.where_step,
        search=args.where_search,
        owner=owner or args.where_owner,
        pipeline=args.where_pipeline,
        source=args.where_source,
        shelf=args.where_shelf,
    )


async def leads_list(ctx: Context) -> Result:
    args = ctx.args
    desk = ctx.desk()
    chosen = _filter(args)
    page = await desk.leads(
        scope=chosen.scope,
        stage=chosen.stage,
        search=args.search or chosen.search,
        offset=max(0, args.offset),
        limit=max(1, min(PAGE, args.limit)),
        owner=chosen.owner,
        pipeline=chosen.pipeline,
        source=chosen.source,
        side=chosen.side,
        step=chosen.step,
        shelf=chosen.shelf,
    )
    rows = [
        {
            "lead_id": str(row.lead_id),
            "name": row.name if args.names else f"{row.name[:1]}… ({len(row.name)})",
            "step": row.step,
            "stage": row.stage_label,
            "source": row.source_label,
            "owner_person_id": str(row.owner_person_id) if row.owner_person_id else None,
            "owner": row.owner_name,
            "created_at": row.created_at.isoformat(),
        }
        for row in page.leads
    ]
    return {"status": "read", "total": page.total, "next_offset": page.next_offset, "leads": rows}


async def leads_add(ctx: Context) -> Result:
    from ac_platform.lead_desk.contracts import NewLead

    args = ctx.args
    if args.owner_person_id is not None:
        await _member(ctx, args.owner_person_id)
    lead = await ctx.desk().add(
        NewLead(
            command_id=ctx.child,
            name=args.name,
            phone=args.phone,
            email=args.email,
            company=args.company,
            city=args.city,
            note=args.note,
            assign="person" if args.owner_person_id else "rules",
            person_id=args.owner_person_id,
            pipeline=args.pipeline,
            side=args.side,
        )
    )
    row = lead.lead
    return {
        "status": "eligible",
        "lead_id": str(row.lead_id),
        "before": None,
        "after": {
            "lead_id": str(row.lead_id),
            "step": row.step,
            "owner_person_id": str(row.owner_person_id) if row.owner_person_id else None,
        },
    }


async def _job(
    ctx: Context, action: str, *, ids: list[UUID] | None = None, **fields: Any
) -> Result:
    from ac_platform.lead_desk import bulk_jobs
    from ac_platform.lead_desk.contracts import BulkJobCommand

    args = ctx.args
    lead_ids = ids if ids is not None else args.lead_id
    command = BulkJobCommand(
        command_id=ctx.child,
        lead_ids=tuple(dict.fromkeys(lead_ids)) if lead_ids else None,
        filter=None if lead_ids else _filter(args, owner=fields.pop("owner", None)),
        expected_total=args.expected_total,
        action=action,
        **fields,
    )
    job = await bulk_jobs.run(ctx.desk(), command)
    before = {"selected": job.selected, "not_found": job.not_found}
    after = {
        "changed": job.changed,
        "unchanged": job.unchanged,
        "failed": {item.reason: item.count for item in job.failed},
        "job_id": str(job.job_id),
        "undo_until": job.undo_until.isoformat(),
        "words": job.words,
    }
    return {"status": "eligible" if job.changed else "unchanged", "before": before, "after": after}


async def leads_assign(ctx: Context) -> Result:
    if ctx.args.to_person_id is not None:
        await _member(ctx, ctx.args.to_person_id)
    return await _job(ctx, "assign", person_id=ctx.args.to_person_id)


async def leads_reassign(ctx: Context) -> Result:
    from ac_platform.lead_desk.models import Lead

    args = ctx.args
    await _owner(ctx.database, ctx.tenant_id)
    if args.to_person_id not in await _members(ctx.database, ctx.tenant_id):
        raise OrganisationCommandError("the leads go only to an active member")
    if _filtered(args):
        if args.where_owner is not None and args.where_owner != args.person_id:
            raise OrganisationCommandError("--where-owner is the --person-id already")
        return await _job(ctx, "assign", owner=args.person_id, person_id=args.to_person_id)
    # Every lead the person owns (Archived too; the Bin waits for its purge), as before.
    leads = list(
        await ctx.database.scalars(
            select(Lead.id)
            .where(
                Lead.tenant_id == ctx.tenant_id,
                Lead.owner_person_id == args.person_id,
                Lead.binned_at.is_(None),
            )
            .order_by(Lead.id)
        )
    )
    if not leads:
        before = {"leads_of_person": 0}
        return {"status": "no_leads", "before": before, "after": before}
    if len(leads) > MAX_LEADS:
        raise OrganisationCommandError("more than 2,000 leads; split the move with --where-*")
    done = await _job(ctx, "assign", ids=leads, person_id=args.to_person_id)
    # The first receipt's shape (v1.78): the person's lead count before, the move after.
    moved = done["after"]
    assert isinstance(moved, dict)
    done["before"] = {"leads_of_person": len(leads)}
    done["after"] = {
        "leads_of_person": len(leads) - int(moved["changed"]),
        "moved_to": str(args.to_person_id),
        "moved": moved["changed"],
        **moved,
    }
    return done


async def leads_stage(ctx: Context) -> Result:
    args = ctx.args
    return await _job(
        ctx,
        "stage",
        step=args.step,
        outcome_reason=args.outcome_reason,
        reason_note=args.reason_note,
        next_action_at=args.next_action_at,
    )


async def leads_shelf(ctx: Context) -> Result:
    return await _job(ctx, SHELF[ctx.args.command])


def _sibling(name: str) -> Any:
    import importlib.util

    here = globals().get("__file__")
    path = Path(here).resolve().parent / name if here else None
    if path is None or not path.is_file():
        raise OrganisationCommandError(f"{name} must sit beside admin.py; run it directly")
    spec = importlib.util.spec_from_file_location(name.replace("-", "_")[:-3], path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def leads_import(ctx: Context) -> Result:
    importer = _sibling("import-leads-file.py")
    spec = json.loads(ctx.args.input.read_text(encoding="utf-8"))
    tenant = str(spec.get("tenant", ""))
    if not tenant or not str(ctx.tenant_id).startswith(tenant):
        raise OrganisationCommandError("the input's tenant is not --tenant-id")
    if spec.get("issue") != ctx.args.issue_reference:
        raise OrganisationCommandError("the input's issue is not --issue")
    report = await importer.run(
        ctx.database, spec, mode="apply" if ctx.args.apply else "dry-run", now=datetime.now(UTC)
    )
    counts = report.get("counts", {})
    return {
        "status": "eligible"
        if any(counts.get(name) for name in ("created", "repeat", "merged", "staged"))
        else "unchanged",
        "before": report.get("before"),
        "after": report.get("after"),
        "counts": counts,
        "batches": report.get("batches"),
    }


HANDLERS: dict[tuple[str, str], Handler] = {
    ("people", "list"): people_list,
    ("people", "show"): people_show,
    ("people", "invite"): people_invite,
    ("people", "resend-invite"): people_resend_invite,
    ("people", "set-role"): people_set_role,
    ("people", "transfer-owner"): people_transfer_owner,
    ("people", "rename"): people_rename,
    ("people", "remove-member"): people_remove_member,
    ("people", "taking-leads"): people_taking_leads,
    ("workspaces", "list"): workspaces_list,
    ("workspaces", "show"): workspaces_show,
    ("workspaces", "create"): workspaces_create,
    ("workspaces", "rename"): workspaces_rename,
    ("workspaces", "domains"): workspaces_domains,
    ("workspaces", "switches"): workspaces_switches,
    ("workspaces", "lead-rules"): workspaces_lead_rules,
    ("leads", "list"): leads_list,
    ("leads", "add"): leads_add,
    ("leads", "assign"): leads_assign,
    ("leads", "reassign"): leads_reassign,
    ("leads", "stage"): leads_stage,
    **{("leads", name): leads_shelf for name in SHELF},
    ("leads", "import"): leads_import,
    **{("ask-dipak", name): ask_dipak_videos for name in COMMANDS["ask-dipak"]},
}
RESOURCES = {
    "people rename": "person",
    "people invite": "organisation_invite",
    "people resend-invite": "organisation_invite",
    "people taking-leads": "lead_rep",
    "workspaces create": "organisation",
    "workspaces rename": "organisation",
    "workspaces domains": "organisation_domains",
    "workspaces switches": "lead_desk_settings",
    "workspaces lead-rules": "lead_desk_settings",
    "ask-dipak videos": "ask_dipak_library",
    "ask-dipak add-video": "ask_dipak_library",
    "ask-dipak remove-video": "ask_dipak_library",
}


async def _batch(database: AsyncSession, settings: Settings, args: argparse.Namespace) -> Result:
    _check_command(args)
    if settings.operations_tenant_id is None or settings.public_learner_tenant_id is None:
        raise OrganisationCommandError("protected tenant IDs must be configured")
    writes = _writes(args)
    if (
        writes
        and args.apply
        and args.environment != "development"
        and args.snapshot_reference is None
    ):
        raise OrganisationCommandError("a recorded database snapshot is required before apply")
    key = _key(args)
    if key not in NO_TENANT:
        if args.tenant_id in _protected(settings):
            raise OrganisationCommandError("protected tenant refused")
        query = select(Organisation).where(Organisation.tenant_id == args.tenant_id)
        if writes:
            query = query.with_for_update()
        if await database.scalar(query) is None:
            raise OrganisationCommandError("registered organisation required")
        tenant = await database.get(Tenant, args.tenant_id)
        if tenant is None or tenant.status != "active":
            raise OrganisationCommandError("active tenant required")
    report: Result = {
        "environment": args.environment,
        "release_id": settings.release_id,
        "command": args.legacy or f"{args.group} {args.command}",
    }
    if key not in NO_TENANT:
        report["tenant_id"] = str(args.tenant_id)
    service = OrganisationService(
        database,
        operations_tenant_id=settings.operations_tenant_id,
        public_learner_tenant_id=settings.public_learner_tenant_id,
    )
    if not writes:
        ctx = Context(database, settings, args, UUID(int=0), service)
        return {**report, "mode": "read", **await HANDLERS[key](ctx)}
    actor = await database.get(Person, args.actor_person_id)
    if actor is None or actor.status != "active" or actor.email_verified_at is None:
        raise OrganisationCommandError("named active verified operator person required")
    intent = _intent(args)
    command_id = _command_id(args, intent)
    reason = _reason(args, command_id)
    report.update(
        mode="apply" if args.apply else "dry_run",
        attribution=json.loads(reason),
        snapshot_reference=args.snapshot_reference,
        command_id=str(command_id),
    )
    prior = await database.scalar(
        select(AuditEvent).where(AuditEvent.request_id == str(command_id)).limit(1)
    )
    if prior is not None:
        if (
            prior.action != ACTION
            or prior.payload.get("intent") != intent
            or prior.reason != reason
            or (key not in NO_TENANT and prior.tenant_id != args.tenant_id)
        ):
            raise OrganisationCommandError("command ID has different intent or attribution")
        return {**report, "status": "replayed", "applied_result": prior.payload["result"]}
    child = uuid5(command_id, "canonical-app-command")
    ctx = Context(database, settings, args, child, service)
    result = await HANDLERS[key](ctx)
    if result["status"] == "eligible" and args.apply:
        result["status"] = "applied"
    # A change that finds nothing to do (already_*, no_leads, unchanged) keeps its receipt
    # and audit too (PR 637): a retry of the same command id replays it, and never acts later.
    tenant_id = args.tenant_id if key not in NO_TENANT else UUID(str(result["tenant_id"]))
    await append_audit_event(
        database,
        tenant_id=tenant_id,
        actor_person_id=args.actor_person_id,
        actor_type="operator",
        action=ACTION,
        resource_type=RESOURCES.get(
            f"{args.group} {args.command}",
            "lead" if args.group == "leads" else "organisation_membership",
        ),
        resource_id=str(getattr(args, "person_id", None) or tenant_id),
        request_id=str(command_id),
        reason=reason,
        payload={
            "intent": intent,
            "result": result,
            "snapshot_reference": args.snapshot_reference,
            "canonical_command_id": str(child),
        },
    )
    result["audit"] = "written" if args.apply else "rehearsed"
    return {**report, **result}


def _words(value: object, indent: str = "") -> list[str]:
    """The receipt as plain lines, for a person at a terminal."""
    lines: list[str] = []
    if isinstance(value, dict):
        for name, item in value.items():
            if isinstance(item, dict | list) and item:
                lines.append(f"{indent}{name}:")
                lines.extend(_words(item, indent + "  "))
            else:
                lines.append(f"{indent}{name}: {'-' if item in (None, [], {}) else item}")
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                lines.append(f"{indent}- " + ", ".join(f"{k}={v}" for k, v in item.items()))
            else:
                lines.append(f"{indent}- {item}")
    return lines


async def execute(
    sessions: async_sessionmaker[AsyncSession], settings: Settings, args: argparse.Namespace
) -> Result:
    """One transaction: a read runs read-only; a dry run makes the change and rolls it back;
    ``--apply`` commits."""
    writes = _writes(args)
    try:
        async with sessions() as database, database.begin():
            if not writes:
                await database.execute(text("SET TRANSACTION READ ONLY"))
            output = await _batch(database, settings, args)
            if writes and not args.apply:
                raise Rehearsed(output)
    except Rehearsed as rehearsed:
        output = rehearsed.output
        if output.get("status") not in ("replayed",):
            output["rolled_back"] = True
    return output


async def _run(args: argparse.Namespace) -> int:
    _check_command(args)
    settings = _settings(args)
    engine = create_async_engine(
        settings.database_url, pool_pre_ping=True, echo=False, hide_parameters=True
    )
    committed = False
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        output = await execute(sessions, settings, args)
        committed = bool(args.apply)
        try:
            if args.json:
                print(json.dumps(output, sort_keys=True, default=str), flush=True)
            else:
                print("\n".join(_words(output)), flush=True)
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
        return run_async(_run(parse(argv)))
    except ResultDeliveryError:
        print(
            "transaction completed but receipt delivery failed; read back the command ID",
            file=sys.stderr,
        )
        return 3
    except (ValueError, RuntimeError, OSError, SQLAlchemyError, DomainError) as error:
        detail = str(error) if isinstance(error, OrganisationCommandError) else ""
        print(
            f"admin command refused or failed; nothing committed. {detail}".rstrip(),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
