"""Lead capture sources: file upload, website webhook, Google Sheet, sandbox test leads.

Every source ends in ``LeadDesk.ingest``: one record in, the original kept as
the lead's payload, deduped by phone, then allocated by the rules. Meta lead
forms use the same path once the Meta app is set up (``meta.py``).
"""

from __future__ import annotations

import hashlib
import re
import secrets
from collections.abc import Mapping
from typing import Any, Final
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4, uuid5

import httpx
from sqlalchemy import func, select

from ac_platform.conversation_intelligence.synthetic_import_models import (
    ConversationSandboxOrganisation,
    ConversationSyntheticRecord,
)
from ac_platform.lead_desk.capture import (
    FIELDS,
    CaptureError,
    language_name,
    normalise_phone,
    read_csv,
    read_file,
    suggest_mapping,
)
from ac_platform.lead_desk.contracts import (
    ImportCommand,
    ImportPreview,
    ImportResult,
    NewSource,
    SeedCommand,
    Sources,
    SourceView,
)
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
        phones: list[str] = []
        if "phone" in mapping:
            phones = [
                phone
                for row in sheet.rows
                if (phone := normalise_phone(row.get(mapping["phone"]))) is not None
            ]
        return ImportPreview(
            file_name=file_name[:200],
            headers=sheet.headers,
            rows=sheet.rows,
            total_rows=len(sheet.rows),
            truncated=sheet.truncated,
            mapping=mapping,
            with_phone=len(phones),
            repeats_in_file=len(phones) - len(set(phones)),
        )

    async def commit(self, command: ImportCommand) -> ImportResult:
        mapping = {
            name: header for name, header in command.mapping.items() if name in FIELDS and header
        }
        if "name" not in mapping and "phone" not in mapping:
            raise DeskError(422, "Choose which column has the name or the phone number.")
        if command.assign == "rules" and not self.desk.viewer.can_manage:
            assign = "me"
        else:
            assign = command.assign
        reps = await self.desk._reps()
        outcomes: list[str] = []
        leads: list[Lead | None] = []
        label = f"File: {command.file_name}"[:120]
        for row in command.rows:
            record = {str(k)[:120]: str(v)[:1000] for k, v in row.items() if v not in (None, "")}
            try:
                lead, outcome = await self.desk.ingest(
                    record,
                    source="csv",
                    source_label=label,
                    source_ref=content_ref(record),
                    mapping=mapping,
                    assign=assign,  # type: ignore[arg-type]
                    actor=self.desk.viewer.person_id,
                    test_data=self.desk.sandbox,
                    reps=reps,
                )
            except CaptureError:
                lead, outcome = None, "skipped"
            outcomes.append(outcome)
            leads.append(lead)
        await self.db.flush()
        return _result(outcomes, leads)

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
        return Sources(
            sources=tuple(self._view(row) for row in rows),
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
        url = (
            f"https://docs.google.com/spreadsheets/d/{source.config['sheet_id']}"
            f"/export?format=csv&gid={source.config.get('gid', '0')}"
        )
        data = await self._fetch_sheet(url)
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
        database: Any, source_id: UUID, token: str, record: Mapping[str, Any], *, app_url: str
    ) -> tuple[UUID | None, str]:
        source = await database.scalar(
            select(LeadSource)
            .where(LeadSource.id == source_id, LeadSource.kind == "webhook")
            .with_for_update()
        )
        if (
            source is None
            or not source.active
            or source.token_sha256 is None
            or not secrets.compare_digest(source.token_sha256, token_hash(token))
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
                for key in ("leadgen_id", "lead_id", "id", "submission_id", "entry_id")
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
