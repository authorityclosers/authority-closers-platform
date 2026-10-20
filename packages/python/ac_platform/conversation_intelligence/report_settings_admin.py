"""Admin and app service for report settings versions (owner order, 19 Oct 2026).

Admins (the Sales X-Ray control accounts in the AC operations workspace) create
versions and choose which one applies to an organisation, an industry or
everyone. Every change is a new row; nothing is edited or deleted. Each command
carries an Idempotency-Key and leaves an audit event through the shared command
receipts. The app reads the version that applies to its workspace.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationConflict,
    ConversationDenied,
    ConversationError,
    utc,
)
from ac_platform.conversation_intelligence.provider_admin import ConversationProviderAdmin
from ac_platform.conversation_intelligence.report_settings import (
    INDUSTRY_PROFILES,
    PARAMETERS,
    SCHEMA,
    VERSION_1,
    VERSION_1_CREATED_AT,
    Choice,
    ReportSettings,
    changes,
    effective_version,
    industry_of,
    settings_from_document,
    valid_industry,
)
from ac_platform.conversation_intelligence.report_settings_models import (
    ReportSettingsEvent,
    ReportSettingsVersion,
)
from ac_platform.kernel.authz import ActorContext
from ac_platform.lead_desk.models import LeadJourneyVersion
from ac_platform.organisations.workspace_kinds import classify_workspaces
from ac_platform.tenancy.models import Tenant

MAX_VERSIONS = 200


def _industry(code: str | None) -> str | None:
    try:
        return valid_industry(code)
    except ValueError as error:
        raise ConversationError(str(error)) from None


HISTORY_LIMIT = 60
_LOCK = 725_903


class VersionIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=2, max_length=80)
    note: str | None = Field(default=None, max_length=500)
    base_number: int = Field(ge=1)
    industry_code: str | None = Field(default=None, max_length=16)
    settings: ReportSettings


class ChoiceIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: Literal["organisation", "industry", "general"]
    tenant_id: UUID | None = None
    industry_code: str | None = Field(default=None, max_length=16)
    # None: clear this choice, so the scope inherits again.
    version_number: int | None = Field(default=None, ge=1)
    # The version this scope uses now, as the admin saw it (None: inheriting).
    expected_version_number: int | None = Field(default=None, ge=1)
    reason: str | None = Field(default=None, max_length=300)


def _version_view(row: ReportSettingsVersion | None, settings: ReportSettings) -> dict[str, Any]:
    if row is None:
        return {
            "number": 1,
            "label": "Version 1 · today's report",
            "note": "Today's Report, Prospect and Coaching, frozen. Every version starts here.",
            "industry_code": None,
            "base_number": None,
            "origin": "built_in",
            "frozen": True,
            "created_at": VERSION_1_CREATED_AT.isoformat(),
            "created_by_person_id": None,
            "settings": settings.model_dump(mode="json"),
            "changes": [],
        }
    return {
        "number": row.number,
        "label": row.label,
        "note": row.note,
        "industry_code": row.industry_code,
        "base_number": row.base_number,
        "origin": row.origin,
        "frozen": True,
        "created_at": utc(row.created_at).isoformat(),
        "created_by_person_id": None
        if row.created_by_person_id is None
        else str(row.created_by_person_id),
        "settings": settings.model_dump(mode="json"),
        "changes": [],
    }


def _event_view(row: ReportSettingsEvent, names: dict[UUID, str]) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "kind": row.kind,
        "scope": row.scope,
        "tenant_id": None if row.tenant_id is None else str(row.tenant_id),
        "organisation": None if row.tenant_id is None else names.get(row.tenant_id, "Unknown"),
        "industry_code": row.industry_code,
        "version_number": row.version_number,
        "previous_version_number": row.previous_version_number,
        "reason": row.reason,
        "actor_person_id": None if row.actor_person_id is None else str(row.actor_person_id),
        "created_at": utc(row.created_at).isoformat(),
    }


class ReportSettingsStore:
    """Reads shared by Admin and the app; no admission here."""

    def __init__(self, database: AsyncSession) -> None:
        self.database = database

    async def versions(self) -> dict[int, tuple[ReportSettingsVersion | None, ReportSettings]]:
        rows = (
            await self.database.scalars(
                select(ReportSettingsVersion)
                .order_by(ReportSettingsVersion.number)
                .limit(MAX_VERSIONS)
            )
        ).all()
        found: dict[int, tuple[ReportSettingsVersion | None, ReportSettings]] = {
            1: (None, VERSION_1)
        }
        for row in rows:
            found[row.number] = (row, settings_from_document(row.settings))
        return found

    async def latest(
        self, scope: str, *, tenant_id: UUID | None = None, industry_code: str | None = None
    ) -> ReportSettingsEvent | None:
        query = select(ReportSettingsEvent).where(
            ReportSettingsEvent.kind == "assigned", ReportSettingsEvent.scope == scope
        )
        if scope == "organisation":
            query = query.where(ReportSettingsEvent.tenant_id == tenant_id)
        if scope == "industry":
            query = query.where(ReportSettingsEvent.industry_code == industry_code)
        row: ReportSettingsEvent | None = await self.database.scalar(
            query.order_by(ReportSettingsEvent.sequence.desc()).limit(1)
        )
        return row

    async def industry(self, tenant_id: UUID) -> str | None:
        """The lead-stage profile the organisation's newest lead stages came from."""

        profile = await self.database.scalar(
            select(LeadJourneyVersion.industry)
            .where(LeadJourneyVersion.tenant_id == tenant_id)
            .order_by(LeadJourneyVersion.version.desc())
            .limit(1)
        )
        return industry_of(profile)

    async def effective(self, tenant_id: UUID) -> dict[str, Any]:
        """The version that applies to one workspace, and where it came from."""

        industry = await self.industry(tenant_id)

        def choice(row: ReportSettingsEvent | None) -> Choice | None:
            return None if row is None else Choice(row.version_number, utc(row.created_at))

        number, source = effective_version(
            organisation=choice(await self.latest("organisation", tenant_id=tenant_id)),
            industry=None
            if industry is None
            else choice(await self.latest("industry", industry_code=industry)),
            general=choice(await self.latest("general")),
        )
        versions = await self.versions()
        row, settings = versions.get(number, (None, VERSION_1))
        if number not in versions:  # never happens: versions are never deleted
            number, source = 1, "built_in"
        return {
            "schema": SCHEMA,
            "version": {"number": number, "label": _version_view(row, settings)["label"]},
            "source": source,
            "industry_code": industry,
            "settings": settings.model_dump(mode="json"),
        }


class ReportSettingsAdmin:
    def __init__(
        self,
        application: ConversationApplication,
        *,
        operations_tenant_id: UUID,
        organisation_ids: tuple[UUID, ...],
        personal_tenant_id: UUID | None = None,
    ) -> None:
        self.application = application
        self.database: AsyncSession = application.database
        self.operations_tenant_id = operations_tenant_id
        self.personal_tenant_id = personal_tenant_id
        self.organisation_ids = tuple(
            item for item in dict.fromkeys(organisation_ids) if item != operations_tenant_id
        )
        self.store = ReportSettingsStore(self.database)

    async def admit(self, actor: ActorContext) -> None:
        if actor.tenant_id != self.operations_tenant_id:
            raise ConversationDenied("Report settings need the AC operations workspace.")
        await ConversationProviderAdmin(self.application).admit(actor)

    async def _names(self) -> dict[UUID, tuple[str, str | None]]:
        rows = (
            await self.database.execute(
                select(Tenant.id, Tenant.name).where(Tenant.id.in_(self.organisation_ids))
            )
        ).all()
        newest = (
            select(
                LeadJourneyVersion.tenant_id,
                func.max(LeadJourneyVersion.version).label("version"),
            )
            .where(LeadJourneyVersion.tenant_id.in_(self.organisation_ids))
            .group_by(LeadJourneyVersion.tenant_id)
            .subquery()
        )
        profiles: dict[UUID, str | None] = {
            tenant_id: industry
            for tenant_id, industry in (
                await self.database.execute(
                    select(LeadJourneyVersion.tenant_id, LeadJourneyVersion.industry).join(
                        newest,
                        (newest.c.tenant_id == LeadJourneyVersion.tenant_id)
                        & (newest.c.version == LeadJourneyVersion.version),
                    )
                )
            ).tuples()
        }
        # Clear names (Admin 2.0, 19 Oct 2026): "Personal accounts", not the registered name.
        clear = await classify_workspaces(
            self.database,
            operations_tenant_id=self.operations_tenant_id,
            personal_tenant_id=self.personal_tenant_id,
            tenant_ids=self.organisation_ids,
        )
        return {
            tenant_id: (
                clear[tenant_id].name if tenant_id in clear else name,
                industry_of(profiles.get(tenant_id)),
            )
            for tenant_id, name in rows
        }

    async def overview(self, actor: ActorContext) -> dict[str, Any]:
        """Parameters, every version with what it changes, who uses which, and the history."""

        await self.admit(actor)
        versions = await self.store.versions()
        names = await self._names()
        organisations = []
        used: dict[int, int] = {}
        for tenant_id, (name, industry) in sorted(names.items(), key=lambda item: item[1][0]):
            effective = await self.store.effective(tenant_id)
            number = effective["version"]["number"]
            used[number] = used.get(number, 0) + 1
            own = await self.store.latest("organisation", tenant_id=tenant_id)
            organisations.append(
                {
                    "tenant_id": str(tenant_id),
                    "name": name,
                    "industry_code": industry,
                    "version_number": number,
                    "source": effective["source"],
                    "own_version_number": None if own is None else own.version_number,
                }
            )
        general = await self.store.latest("general")
        industry_rows = (
            await self.database.scalars(
                select(ReportSettingsEvent)
                .where(
                    ReportSettingsEvent.kind == "assigned",
                    ReportSettingsEvent.scope == "industry",
                )
                .order_by(ReportSettingsEvent.sequence.desc())
            )
        ).all()
        industries: dict[str, int | None] = {}
        for row in industry_rows:
            if row.industry_code is not None and row.industry_code not in industries:
                industries[row.industry_code] = row.version_number
        events = (
            await self.database.scalars(
                select(ReportSettingsEvent)
                .order_by(ReportSettingsEvent.sequence.desc())
                .limit(HISTORY_LIMIT)
            )
        ).all()
        version_views = []
        for number, (version_row, settings) in versions.items():
            view = _version_view(version_row, settings)
            base = versions.get(version_row.base_number) if version_row is not None else None
            if base is not None:
                view["changes"] = changes(base[1], settings)
            view["organisations"] = used.get(number, 0)
            version_views.append(view)
        tenant_names = {tenant_id: value[0] for tenant_id, value in names.items()}
        return {
            "schema": SCHEMA,
            "parameters": [parameter.view() for parameter in PARAMETERS],
            "versions": version_views,
            "general_version_number": None if general is None else general.version_number,
            "industries": [
                {"industry_code": code, "version_number": number}
                for code, number in sorted(industries.items())
                if number is not None
            ],
            "organisations": organisations,
            "history": [_event_view(row, tenant_names) for row in events],
            # The industries a default can be set for: the lead-stage profiles.
            "industry_profiles": [
                {"id": profile, "name": name} for profile, name in INDUSTRY_PROFILES.items()
            ],
        }

    async def _lock(self) -> None:
        await self.database.execute(select(func.pg_advisory_xact_lock(_LOCK, 0)))

    async def _next_sequence(self) -> int:
        """The next history number; call only while holding ``_lock``."""

        latest = await self.database.scalar(select(func.max(ReportSettingsEvent.sequence)))
        return (latest or 0) + 1

    async def create_version(
        self, actor: ActorContext, intent: VersionIntent, *, key: str
    ) -> dict[str, Any]:
        await self.admit(actor)
        industry = _industry(intent.industry_code)
        payload = intent.model_dump(mode="json")
        replay = await self.application._replay(actor, key, "report_settings_version", payload)
        if replay is not None and replay.result_id is not None:
            saved = await self.database.get(ReportSettingsVersion, replay.result_id)
            if saved is None:
                raise ConversationConflict("The saved version receipt is unavailable.")
            return _version_view(saved, settings_from_document(saved.settings))
        await self._lock()
        versions = await self.store.versions()
        if intent.base_number not in versions:
            raise ConversationError("Start from a version that exists.")
        base = versions[intent.base_number][1]
        if not changes(base, intent.settings):
            raise ConversationError("This version changes nothing; change at least one setting.")
        if len(versions) >= MAX_VERSIONS:
            raise ConversationError("There are too many versions; reuse an earlier one.")
        number = max(versions) + 1
        now = utc(self.application.clock())
        row = ReportSettingsVersion(
            id=uuid4(),
            number=number,
            label=intent.label.strip(),
            note=(intent.note or "").strip() or None,
            industry_code=industry,
            base_number=intent.base_number,
            schema=SCHEMA,
            settings=intent.settings.document(),
            settings_sha256=intent.settings.digest(),
            origin="admin",
            created_by_person_id=actor.person_id,
            created_at=now,
        )
        self.database.add(row)
        self.database.add(
            ReportSettingsEvent(
                id=uuid4(),
                sequence=await self._next_sequence(),
                kind="version_created",
                scope="version",
                version_number=number,
                previous_version_number=intent.base_number,
                reason=row.note,
                actor_person_id=actor.person_id,
                created_at=now,
            )
        )
        await self.database.flush()
        await self.application._receipt(
            actor,
            key,
            "report_settings_version",
            payload,
            row.id,
            now,
            resource_type="conversation_report_settings_version",
        )
        view = _version_view(row, intent.settings)
        view["changes"] = changes(base, intent.settings)
        return view

    async def choose(
        self, actor: ActorContext, intent: ChoiceIntent, *, key: str
    ) -> dict[str, Any]:
        """Which version an organisation, an industry or everyone uses (or roll back)."""

        await self.admit(actor)
        industry = _industry(intent.industry_code) if intent.scope == "industry" else None
        if intent.scope == "industry" and industry is None:
            raise ConversationError("Name the industry code.")
        if intent.scope == "organisation":
            if intent.tenant_id is None or intent.tenant_id not in self.organisation_ids:
                raise ConversationError("Choose a Sales X-Ray organisation.")
        elif intent.tenant_id is not None:
            raise ConversationError("Only an organisation choice names an organisation.")
        if intent.scope != "industry" and intent.industry_code is not None:
            raise ConversationError("Only an industry choice names an industry.")
        payload = intent.model_dump(mode="json")
        replay = await self.application._replay(actor, key, "report_settings_choice", payload)
        if replay is not None and replay.result_id is not None:
            saved = await self.database.get(ReportSettingsEvent, replay.result_id)
            if saved is None:
                raise ConversationConflict("The saved choice receipt is unavailable.")
            return _event_view(saved, {})
        await self._lock()
        versions = await self.store.versions()
        if intent.version_number is not None and intent.version_number not in versions:
            raise ConversationError("Choose a version that exists.")
        current = await self.store.latest(
            intent.scope, tenant_id=intent.tenant_id, industry_code=industry
        )
        current_number = None if current is None else current.version_number
        if current_number != intent.expected_version_number:
            raise ConversationConflict("Someone changed this choice. Reload before changing it.")
        if current_number == intent.version_number:
            raise ConversationError("That version is already chosen here.")
        now = utc(self.application.clock())
        row = ReportSettingsEvent(
            id=uuid4(),
            sequence=await self._next_sequence(),
            kind="assigned",
            scope=intent.scope,
            tenant_id=intent.tenant_id,
            industry_code=industry,
            version_number=intent.version_number,
            previous_version_number=current_number,
            reason=(intent.reason or "").strip() or None,
            actor_person_id=actor.person_id,
            created_at=now,
        )
        self.database.add(row)
        await self.database.flush()
        await self.application._receipt(
            actor,
            key,
            "report_settings_choice",
            payload,
            row.id,
            now,
            resource_type="conversation_report_settings_event",
        )
        names = {tenant: value[0] for tenant, value in (await self._names()).items()}
        return _event_view(row, names)


__all__ = [
    "ChoiceIntent",
    "ReportSettingsAdmin",
    "ReportSettingsStore",
    "VersionIntent",
]
