"""Lead capture sources: file upload, website webhook, Google Sheet, sandbox test leads.

Every source ends in ``LeadDesk.ingest``: one record in, the original kept as
the lead's payload, deduped by phone, then allocated by the rules. Meta lead
forms use the same path once the Meta app is set up (``meta.py``).
"""

from __future__ import annotations

import hashlib
import re
import secrets
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any, Final
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4, uuid5

import httpx
from sqlalchemy import func, select

from ac_platform.conversation_intelligence.synthetic_import_models import (
    ConversationSandboxOrganisation,
    ConversationSyntheticRecord,
)
from ac_platform.identity.models import Person
from ac_platform.lead_desk import imports
from ac_platform.lead_desk.capture import (
    CRM_EXPORTS,
    FIELDS,
    REFERENCE_KEYS,
    CaptureError,
    Extracted,
    clean,
    detect_crm,
    extract,
    language_name,
    read_csv,
    read_file,
    suggest_mapping,
)
from ac_platform.lead_desk.capture import key as header_key
from ac_platform.lead_desk.contracts import (
    ImportCommand,
    ImportGiven,
    ImportPreview,
    ImportResult,
    ImportSkip,
    NewSource,
    SeedCommand,
    Sources,
    SourceView,
)
from ac_platform.lead_desk.journey import model as journeys
from ac_platform.lead_desk.models import Lead, LeadRep, LeadSource
from ac_platform.lead_desk.store import DeskError, LeadDesk, Viewer, content_ref
from ac_platform.tenancy.models import Membership

MAX_FILE_BYTES: Final[int] = 900 * 1024
SHEET_ID = re.compile(r"/spreadsheets/d/([A-Za-z0-9_-]{20,})")
SHEET_HOSTS: Final[frozenset[str]] = frozenset({"docs.google.com"})
SHEET_FINAL_HOSTS: Final[tuple[str, ...]] = ("docs.google.com", ".googleusercontent.com")
# The dev sandbox loader's identity scheme (scripts/dev/load-sales-xray-sandbox.py).
SANDBOX_PEOPLE = UUID("1dfdfac9-bfa2-49ab-b061-d98776454e0f")


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def sheet_csv_url(config: Mapping[str, Any]) -> str:
    """A connected sheet's tab as CSV, from its source config (``_sheet_config``)."""
    return (
        f"https://docs.google.com/spreadsheets/d/{config['sheet_id']}"
        f"/export?format=csv&gid={config.get('gid', '0')}"
    )


# Stage and owner columns (paste import, 23 Oct 2026): the headers that usually hold them.
STAGE_HEADERS: Final[tuple[str, ...]] = (
    "stage",
    "lead_stage",
    "status",
    "lead_status",
    "pipeline_stage",
    # Other CRMs' exports (universal intake, 25 Oct 2026).
    "deal_stage",
    "lifecycle_stage",
    "current_stage",
    "disposition",
)
# A file's own list name for its leads (ph1-18, 1 Nov 2026: "Expo list", "Old database").
SOURCE_HEADERS: Final[tuple[str, ...]] = (
    "source",
    "lead_source",
    "source_name",
    "list",
    "list_name",
    "lead_list",
)
OWNER_HEADERS: Final[tuple[str, ...]] = (
    "owner",
    "lead_owner",
    "assigned_to",
    "assignee",
    "assigned",
    "sales_rep",
    "salesperson",
    "sales_person",
    "rep",
    "counsellor",
    "counselor",
    "caller",
    "agent",
    "contact_owner",
    "deal_owner",
    "sales_owner",
    "owner_name",
    "lead_owner_name",
    "person_owner",
    "account_owner",
    "assigned_user",
)
# What other CRMs call their statuses, by the kind of stage each means here (universal
# intake): a file's "Attempted to Contact" lands in Not Connected, "Closed Won" in Won.
STATUS_KINDS: Final[dict[str, str]] = {
    **dict.fromkeys(
        (
            "open",
            "fresh",
            "fresh_lead",
            "new_lead",
            "not_contacted",
            "uncontacted",
            "untouched",
            "unattended",
            "yet_to_contact",
            "pending",
        ),
        "new",
    ),
    **dict.fromkeys(
        (
            "attempted_to_contact",
            "attempted",
            "no_answer",
            "not_answered",
            "unanswered",
            "not_reachable",
            "unreachable",
            "switched_off",
            "ringing",
            "busy",
            "rnr",
            "dnp",
            "did_not_pick",
            "not_picked",
            "call_not_picked",
        ),
        "not_connected",
    ),
    **dict.fromkeys(
        (
            "contacted",
            "followup",
            "follow_up_required",
            "callback",
            "call_back",
            "in_progress",
            "working",
            "nurturing",
            "nurture",
            "in_discussion",
            "discussion",
            "connected",
        ),
        "follow_up",
    ),
    **dict.fromkeys(
        (
            "qualified",
            "prospect",
            "sales_qualified_lead",
            "marketing_qualified_lead",
            "sql",
            "mql",
            "opportunity",
            "negotiation",
            "proposal",
            "quotation_sent",
            "quote_sent",
            "demo_scheduled",
            "site_visit",
            "site_visit_scheduled",
            "visit_scheduled",
            "demo_done",
            "site_visit_done",
            "meeting_done",
        ),
        "interested",
    ),
    **dict.fromkeys(
        (
            "closed_won",
            "converted",
            "customer",
            "enrolled",
            "admission",
            "booked",
            "booking_done",
            "sold",
            "paid",
            "deal_won",
        ),
        "won",
    ),
    **dict.fromkeys(
        (
            "closed_lost",
            "not_interested",
            "not_qualified",
            "unqualified",
            "dead",
            "lost_lead",
            "deal_lost",
            "dropped",
            "rejected",
        ),
        "lost",
    ),
    **dict.fromkeys(
        (
            "junk_lead",
            "spam",
            "fake",
            "invalid",
            "invalid_number",
            "wrong_number",
            "disqualified",
        ),
        "junk",
    ),
}
CRM_NAMES: Final[frozenset[str]] = frozenset(name for name, _ in CRM_EXPORTS)
# Names that matched nothing are said back, the first this many.
UNMATCHED_SHOWN: Final[int] = 10
# The stages a bulk upload may start new leads in (section 5): the first, or Open Leads or
# Interested when the file has real past talks.
START_KINDS: Final[frozenset[str]] = frozenset({"new", "follow_up", "interested"})
# The details Fill blanks and Replace take from a row for a lead already here; never the
# phone, which is how the row found that lead (competitor teardown 5).
REFRESHED: Final[tuple[str, ...]] = ("name", "email", "company", "city", "language", "interest")


def unreadable_number(found: Extracted) -> bool:
    """The row's phone cell has words but no number we can read, and it has no email: no
    way to reach the person, so the import skips it and says why."""
    return found.phone is None and bool(found.phone_raw) and not found.email


def suggest_columns(headers: Iterable[str], taken: Mapping[str, str]) -> dict[str, str]:
    """The stage, owner and source columns, when a header says which they are."""
    by_key = {header_key(header): header for header in headers}
    found: dict[str, str] = {}
    for name, aliases in (
        ("stage", STAGE_HEADERS),
        ("owner", OWNER_HEADERS),
        ("source", SOURCE_HEADERS),
    ):
        for alias in aliases:
            header = by_key.get(alias)
            if header is not None and header not in (*taken.values(), *found.values()):
                found[name] = header
                break
    return found


def match_stage(journey: journeys.Journey, text: str) -> journeys.Stage | None:
    """The pipeline's stage a sheet names: by its label or key, else by its kind's word
    ("Interested", "Won", "Lost") or another CRM's word for it ("Closed Won"), the first
    live stage of that kind."""
    wanted = header_key(text)
    live = [stage for stage in journey.stages if not stage.archived]
    for stage in live:
        if wanted in (header_key(stage.label), header_key(stage.key)):
            return stage
    kind = wanted if any(stage.kind == wanted for stage in live) else STATUS_KINDS.get(wanted)
    return next((stage for stage in live if stage.kind == kind), None)


def people_index(
    people: Iterable[tuple[UUID, str]], emails: Iterable[tuple[UUID, str]] = ()
) -> dict[str, UUID | None]:
    """Who an owner column can name: a teammate's full name, their email, or a first name
    only one teammate has. Two people with the same name match neither (None)."""
    index: dict[str, UUID | None] = {}
    for person_id, email in emails:
        if email and header_key(email):
            index[header_key(email)] = person_id
    firsts: dict[str, set[UUID]] = {}
    for person_id, name in people:
        whole = header_key(name)
        if whole:
            index[whole] = person_id if index.get(whole, person_id) == person_id else None
        words = name.split()
        if words and header_key(words[0]):
            firsts.setdefault(header_key(words[0]), set()).add(person_id)
    for first, ids in firsts.items():
        index.setdefault(first, next(iter(ids)) if len(ids) == 1 else None)
    return index


def _result(outcomes: list[str], desk_leads: list[Lead | None]) -> ImportResult:
    pairs = zip(desk_leads, outcomes, strict=True)
    created = [lead for lead, outcome in pairs if outcome == "created"]
    return ImportResult(
        created=len(created),
        repeats=outcomes.count("repeat") + outcomes.count("known"),
        skipped=outcomes.count("skipped"),
        assigned=sum(1 for lead in created if lead is not None and lead.owner_person_id),
        waiting=sum(1 for lead in created if lead is not None and not lead.owner_person_id),
    )


class Intake:
    def __init__(self, desk: LeadDesk, *, app_url: str) -> None:
        self.desk = desk
        self.db = desk.db
        self.tenant_id = desk.tenant_id
        self.app_url = app_url.rstrip("/")

    # ----- files -----------------------------------------------------------------

    async def preview(self, file_name: str, data: bytes) -> ImportPreview:
        if not data:
            raise DeskError(422, "The file is empty.")
        if len(data) > MAX_FILE_BYTES:
            raise DeskError(
                413, "Files can be up to 900 KB (about 5,000 leads). Split bigger files."
            )
        try:
            sheet = read_file(file_name, data)
        except CaptureError as error:
            raise DeskError(422, str(error)) from None
        mapping = suggest_mapping(sheet.headers)
        mapping.update(suggest_columns(sheet.headers, mapping))
        _, config = await self.desk.settings()
        fields = {name: header for name, header in mapping.items() if name in FIELDS}
        found = [
            extract(row, fields, default_country=config["default_country"]) for row in sheet.rows
        ]
        phones = [item.phone for item in found if item.phone is not None]
        emails = {item.email for item in found if item.phone is None and item.email}
        known = 0
        if phones:
            known = (
                await self.db.scalar(
                    select(func.count(func.distinct(Lead.phone))).where(
                        Lead.tenant_id == self.tenant_id, Lead.phone.in_(set(phones))
                    )
                )
            ) or 0
        if emails:
            known += (
                await self.db.scalar(
                    select(func.count(func.distinct(Lead.email))).where(
                        Lead.tenant_id == self.tenant_id, Lead.email.in_(emails)
                    )
                )
            ) or 0
        return ImportPreview(
            file_name=file_name[:200],
            headers=sheet.headers,
            rows=sheet.rows,
            total_rows=len(sheet.rows),
            truncated=sheet.truncated,
            mapping=mapping,
            with_phone=len(phones),
            repeats_in_file=len(phones) - len(set(phones)),
            known_leads=known,
            detected=detect_crm(sheet.headers),
            importable=sum(
                1
                for item in found
                if (item.name or item.phone or item.email) and not unreadable_number(item)
            ),
            bad_numbers=sum(1 for item in found if unreadable_number(item)),
        )

    async def commit(self, command: ImportCommand) -> ImportResult:
        mapping = {
            name: header for name, header in command.mapping.items() if name in FIELDS and header
        }
        if "name" not in mapping and "phone" not in mapping:
            raise DeskError(422, "Choose which column has the name or the phone number.")
        # Only owners and admins give leads to others; anyone else's go on their own desk.
        assign = command.assign if self.desk.viewer.can_manage else "me"
        # Only they change leads already here, which may be anyone's (competitor teardown 5).
        if command.duplicates != "skip" and not self.desk.viewer.can_manage:
            raise DeskError(403, "Only owners and admins change leads that are already here.")
        _, config = await self.desk.settings()
        reps = await self.desk._reps()
        # The salespeople the owner picked and how many each takes, in order (section 5).
        names = {rep.state.person_id: rep.state.name for rep in reps}
        queue: list[list[Any]] = []
        if assign == "people":
            for share in command.shares:
                if share.person_id not in names:
                    raise DeskError(422, "Pick the salespeople from your team.")
                await self.desk._require_seller(share.person_id)
            queue = [[share.person_id, share.count] for share in command.shares if share.count]
        handed: dict[UUID, int] = {}
        chosen = f"Chosen by {await self.desk._name(self.desk.viewer.person_id)}"
        start = await self._start(command)
        # A row may name its lead's stage, its list (Source), and (owners and admins) its owner.
        stage_header = command.mapping.get("stage") or None
        source_header = command.mapping.get("source") or None
        owner_header = (
            (command.mapping.get("owner") or None) if self.desk.viewer.can_manage else None
        )
        people: dict[str, UUID | None] = {}
        if owner_header:
            team = [rep.state.person_id for rep in reps]
            emails = (
                await self.db.execute(
                    select(Person.id, Person.email).where(
                        Person.id.in_(team), Person.email.is_not(None)
                    )
                )
            ).tuples()
            people = people_index(
                ((rep.state.person_id, rep.state.name) for rep in reps),
                ((person_id, str(email)) for person_id, email in emails),
            )
        journeys_read: dict[str, journeys.Journey] = {}
        staged = owned = 0
        missing_stages: dict[str, None] = {}
        missing_owners: dict[str, None] = {}
        outcomes: list[str] = []
        leads: list[Lead | None] = []
        # The leads earlier rows made or found, and every row that made none and changed
        # none, with why.
        used: set[UUID] = set()
        skips: list[ImportSkip] = []
        updated = 0
        label = (
            f"{command.source_name} export: {command.file_name}"
            if command.source_name in CRM_NAMES
            else f"File: {command.file_name}"
        )[:120]
        for index, row in enumerate(command.rows):
            record = {str(k)[:120]: str(v)[:1000] for k, v in row.items() if v not in (None, "")}
            found = extract(record, mapping, default_country=config["default_country"])
            if unreadable_number(found):
                outcomes.append("skipped")
                leads.append(None)
                skips.append(ImportSkip(row=index, reason="Number can't be read"))
                continue
            named = clean(row.get(owner_header)) if owner_header else None
            listed = clean(row.get(source_header)) if source_header else None
            person = people.get(header_key(named)) if named else None
            if named and person is None:
                missing_owners.setdefault(named[:80])
            # Picked salespeople get theirs after the lead is made: it is made unassigned.
            way: Any = "person" if person else "none" if assign in ("people", "none") else assign
            try:
                lead, outcome = await self.desk.ingest(
                    record,
                    source="csv",
                    source_label=listed[:120] if listed else label,
                    source_ref=content_ref(record),
                    mapping=mapping,
                    assign=way,
                    person_id=person,
                    actor=self.desk.viewer.person_id,
                    test_data=self.desk.sandbox,
                    reps=reps,
                    pipeline=command.pipeline,
                    batch=(command.command_id, command.file_name[:120]),
                    as_is=True,
                )
                why = "No name, phone or email"
            except CaptureError as error:
                lead, outcome, why = None, "skipped", str(error)
            outcomes.append(outcome)
            leads.append(lead)
            if lead is None:
                skips.append(ImportSkip(row=index, reason=why))
                continue
            # Only new leads take the row's stage and owner; a number already a lead keeps its
            # own, and only Fill blanks or Replace change its details. A second row for a lead
            # an earlier row made or found changes nothing: the first row wins.
            if lead.id in used:
                skips.append(ImportSkip(row=index, reason="Repeated in the file"))
                continue
            used.add(lead.id)
            if outcome != "created":
                if command.duplicates == "skip":
                    skips.append(ImportSkip(row=index, reason="Already a lead"))
                elif await self._refresh(lead, found, command, index):
                    updated += 1
                else:
                    skips.append(ImportSkip(row=index, reason="Already a lead with these details"))
                continue
            if person is not None:
                owned += 1
            # Inbound or Cold (0146), set on new leads only.
            lead.pipeline = command.side
            if person is None and queue:
                to = queue[0]
                await self.desk._set_owner(
                    lead, to[0], chosen, "manual", actor=self.desk.viewer.person_id
                )
                handed[to[0]] = handed.get(to[0], 0) + 1
                to[1] -= 1
                if not to[1]:
                    queue.pop(0)
            wanted = clean(row.get(stage_header)) if stage_header else None
            if not wanted and start is None:
                continue
            pipeline = journeys.pipeline_of(lead)
            if pipeline not in journeys_read:
                journeys_read[pipeline] = await journeys.read(self.db, self.tenant_id, pipeline)
            journey = journeys_read[pipeline]
            stage = match_stage(journey, wanted) if wanted else journey.stage_for(start or "")
            if stage is None:
                if wanted:
                    missing_stages.setdefault(wanted[:80])
                continue
            staged += 1
            now = journey.resolve(lead.stage, lead.step)
            if now is None or now.key != stage.key:
                # The file says where the lead stands: the stage list's moves don't apply,
                # and a Lost or Junk lead without a reason is "Imported" (Lead OS).
                self.desk.to_stage(
                    lead,
                    journey,
                    stage,
                    note=None,
                    command_id=uuid5(command.command_id, f"import-stage:{index}"),
                    source="import",
                    via="api",
                )
        await self.db.flush()
        given = {
            lead.owner_person_id
            for lead, outcome in zip(leads, outcomes, strict=True)
            if lead is not None and outcome == "created" and lead.owner_person_id is not None
        }
        return _result(outcomes, leads).model_copy(
            update={
                # The limit counts Inbound only: a Cold list never says over it (ph1-17).
                "warnings": tuple(await self.desk.over_limit(given))
                if given and command.side != "cold"
                else (),
                "staged": staged,
                "owned": owned,
                "unmatched_stages": tuple(missing_stages)[:UNMATCHED_SHOWN],
                "unmatched_owners": tuple(missing_owners)[:UNMATCHED_SHOWN],
                "given": tuple(
                    ImportGiven(person_id=person_id, name=names.get(person_id, ""), leads=count)
                    for person_id, count in handed.items()
                ),
                "side": command.side,
                "updated": updated,
                "skipped_rows": tuple(skips),
                # Undo import, for owners and admins, for 48 hours (imports.py).
                **(
                    {
                        "import_id": command.command_id,
                        "undo_until": self.desk.now + imports.UNDO_FOR,
                    }
                    if self.desk.viewer.can_delete and any(o == "created" for o in outcomes)
                    else {}
                ),
            }
        )

    async def _refresh(
        self, lead: Lead, found: Extracted, command: ImportCommand, index: int
    ) -> bool:
        """Fill blanks or Replace on a lead already here (competitor teardown 5): only the
        row's filled cells count, so a blank cell never empties a detail. The change is in
        the lead's history; Replace keeps what it replaced there. True when anything changed."""
        lead = (
            await self.db.scalar(
                select(Lead)
                .where(Lead.tenant_id == self.tenant_id, Lead.id == lead.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            or lead
        )
        replace = command.duplicates == "replace"
        before: dict[str, str | None] = {}
        for name in REFRESHED:
            value = found.get(name)
            now = getattr(lead, name)
            if value is None or value == now or (now is not None and not replace):
                continue
            before[name] = now
            setattr(lead, name, value)
        if not before:
            return False
        lead.revision += 1
        lead.updated_at = self.desk.now
        self.desk._event(
            lead,
            "edited",
            {
                "changed": list(before),
                "source": "import",
                "import_file": command.file_name[:120],
                **({"replaced": before} if replace else {}),
            },
            actor=self.desk.viewer.person_id,
            command_id=uuid5(command.command_id, f"import-edit:{index}"),
        )
        return True

    async def _start(self, command: ImportCommand) -> str | None:
        """The stage new leads start in when the owner picked one past the first (section 5):
        an in-talks or interested stage of the pipeline they go to. None: the first stage."""
        if not command.step:
            return None
        journey = await journeys.read(
            self.db, self.tenant_id, command.pipeline or journeys.MAIN_PIPELINE
        )
        stage = journey.stage_for(command.step)
        if stage is None or stage.archived or stage.kind not in START_KINDS:
            raise DeskError(
                422, "New leads start in the first stage, an in-talks stage or an interested one."
            )
        return None if stage.kind == "new" else stage.key

    # ----- sources ---------------------------------------------------------------

    def _view(self, source: LeadSource, token: str | None = None) -> SourceView:
        return SourceView(
            source_id=source.id,
            kind=source.kind,
            label=source.label,
            active=source.active,
            received=source.received,
            last_received_at=source.last_received_at,
            endpoint=f"{self.app_url}/v1/lead-desk/capture/{source.id}"
            if source.kind == "webhook"
            else None,
            sheet_url=source.config.get("url") if source.kind == "sheet" else None,
            token=token,
            problem=source.config.get("problem") if source.kind == "sheet" else None,
        )

    async def sources(self, *, meta_ready: bool) -> Sources:
        self.desk._require_manager()
        rows = (
            await self.db.scalars(
                select(LeadSource)
                .where(LeadSource.tenant_id == self.tenant_id)
                .order_by(LeadSource.created_at)
            )
        ).all()
        # Accounts connected with Continue with Google have their own card (connectors/http.py),
        # and so has the website line (websites.py).
        return Sources(
            sources=tuple(
                self._view(row)
                for row in rows
                if (row.config or {}).get("connector") is None
                and not (row.config or {}).get("website")
            ),
            meta="ready" if meta_ready else "not_configured",
        )

    async def add_source(self, command: NewSource) -> SourceView:
        self.desk._require_manager()
        count = await self.db.scalar(
            select(func.count()).where(LeadSource.tenant_id == self.tenant_id)
        )
        if int(count or 0) >= 20:
            raise DeskError(422, "A workspace can connect up to 20 sources.")
        config: dict[str, Any] = {}
        token = None
        if command.kind == "sheet":
            config = self._sheet_config(command.sheet_url or "")
        else:
            token = secrets.token_urlsafe(32)
        source = LeadSource(
            id=uuid4(),
            tenant_id=self.tenant_id,
            kind=command.kind,
            label=command.label,
            token_sha256=token_hash(token) if token else None,
            config=config,
            active=True,
            received=0,
            created_by_person_id=self.desk.viewer.person_id,
            created_at=self.desk.now,
            updated_at=self.desk.now,
        )
        self.db.add(source)
        await self.db.flush()
        return self._view(source, token)

    async def _source(self, source_id: UUID) -> LeadSource:
        self.desk._require_manager()
        source = await self.db.scalar(
            select(LeadSource)
            .where(LeadSource.id == source_id, LeadSource.tenant_id == self.tenant_id)
            .with_for_update()
        )
        if source is None:
            raise DeskError(404, "That source isn't connected to this workspace.")
        return source

    async def rotate(self, source_id: UUID) -> SourceView:
        source = await self._source(source_id)
        if source.kind != "webhook":
            raise DeskError(422, "Only website form sources have a key.")
        if (source.config or {}).get("connector") is not None:
            # Sales Xray wrote this key into the account's lead forms itself.
            raise DeskError(
                422, "This account's key is managed by Sales Xray. Reconnect it instead."
            )
        if (source.config or {}).get("website"):
            raise DeskError(422, "The website line's key changes under Websites.")
        token = secrets.token_urlsafe(32)
        source.token_sha256 = token_hash(token)
        source.updated_at = self.desk.now
        await self.db.flush()
        return self._view(source, token)

    async def set_active(self, source_id: UUID, active: bool) -> SourceView:
        source = await self._source(source_id)
        source.active = active
        source.updated_at = self.desk.now
        await self.db.flush()
        return self._view(source)

    @staticmethod
    def _sheet_config(url: str) -> dict[str, Any]:
        parts = urlsplit(url.strip())
        match = SHEET_ID.search(parts.path)
        if parts.scheme != "https" or parts.hostname not in SHEET_HOSTS or match is None:
            raise DeskError(
                422, "Paste the Google Sheet's link (https://docs.google.com/spreadsheets/d/…)."
            )
        gid = (parse_qs(parts.query).get("gid") or parse_qs(parts.fragment).get("gid") or ["0"])[0]
        if not gid.isdigit():
            gid = "0"
        return {"url": url.strip()[:500], "sheet_id": match.group(1), "gid": gid}

    async def sync_sheet(self, source_id: UUID) -> ImportResult:
        source = await self._source(source_id)
        if source.kind != "sheet" or not source.active:
            raise DeskError(422, "Choose a connected Google Sheet.")
        return await self.file_sheet(source, await self._fetch_sheet(sheet_csv_url(source.config)))

    async def file_sheet(self, source: LeadSource, data: bytes) -> ImportResult:
        """A sheet's rows as leads, for "Sync" and the 10-minute pass (lead_desk/sheet_sync.py):
        rows seen before read as "known", so a sheet read again files only its new rows."""
        try:
            sheet = read_csv(data)
        except CaptureError as error:
            raise DeskError(422, str(error)) from None
        reps = await self.desk._reps()
        outcomes: list[str] = []
        leads: list[Lead | None] = []
        for row in sheet.rows:
            try:
                lead, outcome = await self.desk.ingest(
                    row,
                    source="sheet",
                    source_label=f"Sheet: {source.label}"[:120],
                    source_ref=content_ref(row),
                    actor=None,
                    test_data=self.desk.sandbox,
                    reps=reps,
                )
            except CaptureError:
                lead, outcome = None, "skipped"
            outcomes.append(outcome)
            leads.append(lead)
        result = _result(outcomes, leads)
        source.received += result.created + outcomes.count("repeat")
        source.last_received_at = self.desk.now
        source.updated_at = self.desk.now
        source.config = {
            **(source.config or {}),
            "synced_at": self.desk.now.timestamp(),
            "problem": None,
        }
        await self.db.flush()
        return result

    @staticmethod
    async def _fetch_sheet(url: str) -> bytes:
        try:
            async with (
                httpx.AsyncClient(timeout=15, follow_redirects=True) as client,
                client.stream("GET", url) as response,
            ):
                host = response.url.host or ""
                if not (host == "docs.google.com" or host.endswith(".googleusercontent.com")):
                    raise DeskError(422, "Google sent the sheet from an unexpected place.")
                if response.status_code in {401, 403, 404} or "accounts.google" in str(
                    response.url
                ):
                    raise DeskError(
                        422,
                        "Sales Xray can't open this sheet. In Google Sheets, choose Share → "
                        "General access → Anyone with the link (Viewer), then sync again.",
                    )
                if response.status_code != 200:
                    raise DeskError(502, "Google Sheets didn't answer. Try again in a minute.")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_FILE_BYTES:
                        raise DeskError(413, "The sheet is too big to sync (900 KB at most).")
                if body.lstrip()[:15].lower().startswith(b"<!doctype html"):
                    raise DeskError(
                        422,
                        "Sales Xray can't open this sheet. Share it as 'Anyone with the "
                        "link (Viewer)', then sync again.",
                    )
                return bytes(body)
        except httpx.HTTPError:
            raise DeskError(502, "Google Sheets didn't answer. Try again in a minute.") from None

    # ----- website webhook (no session: the source key is the authority) ------------

    @staticmethod
    async def capture(
        database: Any,
        source_id: UUID,
        token: str,
        record: Mapping[str, Any],
        *,
        app_url: str,
        test_data: bool = False,
        kind: str | None = None,
        key_sha256: str | None = None,
        received_at: datetime | None = None,
    ) -> tuple[UUID | None, str]:
        """``test_data``: the sender marked it a test (Google Ads' "Send test data").
        ``kind``: the narrower source it is, for pipelines ("google_ads").
        ``key_sha256`` and ``received_at``: a lead the release spool kept (lead_desk/
        spool.py), which holds only the key's hash and the time the lead reached it."""
        source = await database.scalar(
            select(LeadSource)
            .where(LeadSource.id == source_id, LeadSource.kind == "webhook")
            .with_for_update()
        )
        digest = key_sha256 if key_sha256 is not None else token_hash(token)
        if (
            source is None
            or not source.active
            or source.token_sha256 is None
            or not secrets.compare_digest(source.token_sha256, digest)
            # The website line's key is public (it sits in the site's page): its leads come
            # only through /site/lead, with the page's Origin and the bot checks.
            or (source.config or {}).get("website")
        ):
            raise DeskError(401, "Unknown source or key.")
        desk = LeadDesk(
            database,
            Viewer(
                person_id=source.created_by_person_id,
                tenant_id=source.tenant_id,
                role="system",
                name=source.label,
            ),
        )
        reference = next(
            (
                str(record[key])[:200]
                for key in REFERENCE_KEYS
                if isinstance(record.get(key), (str, int)) and str(record[key]).strip()
            ),
            None,
        )
        try:
            lead, outcome = await desk.ingest(
                record,
                source="webhook",
                source_label=source.label,
                source_ref=reference or content_ref(record),
                actor=None,
                test_data=test_data,
                kind=kind,
                received_at=received_at,
            )
        except CaptureError as error:
            raise DeskError(422, str(error)) from None
        if outcome in {"created", "repeat"}:
            source.received += 1
            source.last_received_at = desk.now
        await database.flush()
        return (lead.id if lead else None), outcome

    # ----- sandbox test leads ------------------------------------------------------

    async def seed_sandbox(self, command: SeedCommand) -> ImportResult:
        """Owners/admins of the flagged AC Sandbox org: pull recent synthetic leads in."""
        self.desk._require_manager()
        flagged = await self.db.scalar(
            select(ConversationSandboxOrganisation.tenant_id).where(
                ConversationSandboxOrganisation.tenant_id == self.tenant_id
            )
        )
        if flagged is None:
            raise DeskError(403, "Test leads are only for the AC Sandbox organisation.")
        await self._seed_rep_rules()
        taken = set(
            (
                await self.db.scalars(
                    select(Lead.source_ref).where(
                        Lead.tenant_id == self.tenant_id, Lead.source == "synthetic"
                    )
                )
            ).all()
        )
        records = (
            await self.db.scalars(
                select(ConversationSyntheticRecord)
                .where(
                    ConversationSyntheticRecord.tenant_id == self.tenant_id,
                    ConversationSyntheticRecord.kind == "leads",
                )
                .order_by(
                    ConversationSyntheticRecord.occurred_at.desc(),
                    ConversationSyntheticRecord.synthetic_key,
                )
                .limit(command.count + len(taken))
            )
        ).all()
        fresh = [record for record in records if record.synthetic_key not in taken][: command.count]
        related = await self._related(fresh)
        reps = await self.desk._reps()
        outcomes: list[str] = []
        leads: list[Lead | None] = []
        for record in fresh:
            lead_payload = record.payload
            buyer = related.get(("contacts", str(lead_payload.get("person_id"))), {})
            company = related.get(("companies", str(lead_payload.get("company_id"))), {})
            deal = related.get(
                ("deals", str(lead_payload.get("lead_id", "")).replace("-LEAD", "-DEAL")), {}
            )
            world = related.get(("world", record.business_id), {})
            product = next(
                (
                    item.get("name")
                    for item in world.get("products", [])
                    if isinstance(item, dict) and item.get("product_id") == deal.get("product_id")
                ),
                None,
            )
            languages = [lang for lang in buyer.get("languages", []) if isinstance(lang, str)]
            row = {
                "name": buyer.get("name"),
                "company": company.get("name"),
                "city": deal.get("city") or company.get("city"),
                "language": language_name(languages[0]) if languages else None,
                "languages": [language_name(lang) for lang in languages],
                "interest": product,
                "lead_source": lead_payload.get("source"),
                "business": world.get("name"),
                "synthetic_lead_id": record.synthetic_key,
                "original_created_at": lead_payload.get("created_at"),
                "synthetic": True,
            }
            row = {key: value for key, value in row.items() if value not in (None, [], "")}
            lead, outcome = await self.desk.ingest(
                row,
                source="synthetic",
                source_label=f"Test data · {lead_payload.get('source', 'lead')}",
                source_ref=record.synthetic_key,
                actor=self.desk.viewer.person_id,
                test_data=True,
                reps=reps,
                command_id=uuid5(command.command_id, record.synthetic_key),
            )
            outcomes.append(outcome)
            leads.append(lead)
        await self.db.flush()
        return _result(outcomes, leads)

    async def _related(
        self, leads: list[ConversationSyntheticRecord]
    ) -> dict[tuple[str, str], dict[str, Any]]:
        wanted: dict[str, set[str]] = {"contacts": set(), "companies": set(), "deals": set()}
        businesses: set[str] = set()
        for record in leads:
            payload = record.payload
            wanted["contacts"].add(str(payload.get("person_id")))
            wanted["companies"].add(str(payload.get("company_id")))
            wanted["deals"].add(str(payload.get("lead_id", "")).replace("-LEAD", "-DEAL"))
            businesses.add(record.business_id)
        found: dict[tuple[str, str], dict[str, Any]] = {}
        for kind, keys in [*wanted.items(), ("world", businesses)]:
            if not keys:
                continue
            rows = (
                await self.db.scalars(
                    select(ConversationSyntheticRecord).where(
                        ConversationSyntheticRecord.tenant_id == self.tenant_id,
                        ConversationSyntheticRecord.kind == kind,
                        ConversationSyntheticRecord.synthetic_key.in_(keys)
                        if kind != "world"
                        else ConversationSyntheticRecord.business_id.in_(keys),
                    )
                )
            ).all()
            for row in rows:
                key = row.business_id if kind == "world" else row.synthetic_key
                if isinstance(row.payload, dict):
                    found[(kind, key)] = row.payload
        return found

    async def _seed_rep_rules(self) -> None:
        """Give the fictional reps their authored languages, territories and products."""
        people = (
            await self.db.scalars(
                select(ConversationSyntheticRecord).where(
                    ConversationSyntheticRecord.tenant_id == self.tenant_id,
                    ConversationSyntheticRecord.kind == "people",
                )
            )
        ).all()
        worlds = {
            row.business_id: row.payload
            for row in (
                await self.db.scalars(
                    select(ConversationSyntheticRecord).where(
                        ConversationSyntheticRecord.tenant_id == self.tenant_id,
                        ConversationSyntheticRecord.kind == "world",
                    )
                )
            ).all()
        }
        members = set(
            (
                await self.db.scalars(
                    select(Membership.person_id).where(
                        Membership.tenant_id == self.tenant_id, Membership.status == "active"
                    )
                )
            ).all()
        )
        existing = set(
            (
                await self.db.scalars(
                    select(LeadRep.person_id).where(LeadRep.tenant_id == self.tenant_id)
                )
            ).all()
        )
        for record in people:
            payload = record.payload if isinstance(record.payload, dict) else {}
            raw_fields = payload.get("fields")
            fields: dict[str, Any] = raw_fields if isinstance(raw_fields, dict) else {}
            if "manager" in (payload.get("duties") or []):
                continue
            person_id = uuid5(SANDBOX_PEOPLE, f"{self.tenant_id}:person:{record.synthetic_key}")
            if person_id not in members or person_id in existing:
                continue
            world = worlds.get(record.business_id, {})
            products = [
                item["name"]
                for item in world.get("products", [])
                if isinstance(item, dict) and isinstance(item.get("name"), str)
            ]
            self.db.add(
                LeadRep(
                    tenant_id=self.tenant_id,
                    person_id=person_id,
                    revision=1,
                    available=True,
                    max_open=25,
                    languages=[
                        name
                        for lang in fields.get("languages", [])
                        if isinstance(lang, str) and (name := language_name(lang))
                    ][:12],
                    areas=[a for a in fields.get("territory", []) if isinstance(a, str)][:40],
                    interests=products[:40],
                    updated_by_person_id=self.desk.viewer.person_id,
                    updated_at=self.desk.now,
                )
            )
        await self.db.flush()
