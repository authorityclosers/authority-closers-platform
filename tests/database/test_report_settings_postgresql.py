"""Report settings versions on PostgreSQL (owner order, 19 Oct 2026).

Versions are numbered and never edited; every choice is a new event; rolling
back is choosing again; the app reads the version that applies to its workspace
(its own choice, its industry's default, the general default, else version 1).
Disposable loopback PostgreSQL.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.audit.models import AuditEvent
from ac_platform.conversation_intelligence import report_settings_admin
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationConflict,
    ConversationDenied,
    ConversationError,
)
from ac_platform.conversation_intelligence.report_settings import VERSION_1
from ac_platform.conversation_intelligence.report_settings_admin import (
    ChoiceIntent,
    ReportSettingsAdmin,
    ReportSettingsStore,
    VersionIntent,
)
from ac_platform.conversation_intelligence.report_settings_models import (
    ReportSettingsEvent,
    ReportSettingsVersion,
)
from ac_platform.kernel.authz import ActorContext
from ac_platform.tenancy.models import Organisation, Tenant
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed

NOW = datetime(2026, 10, 19, 6, 0, tzinfo=UTC)


@pytest.fixture
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()  # type: ignore[attr-defined]


class _Admit:
    def __init__(self, _application: object) -> None:
        pass

    async def admit(self, _actor: object) -> None:
        return None


async def _organisation(
    sessions: async_sessionmaker[AsyncSession], name: str, industry: str | None
) -> UUID:
    tenant_id = uuid4()
    async with sessions() as database, database.begin():
        database.add(
            Tenant(
                id=tenant_id,
                slug=f"report-settings-{tenant_id.hex[:8]}",
                name=name,
                status="active",
                revision=1,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await database.flush()
        database.add(
            Organisation(
                tenant_id=tenant_id,
                created_by_person_id=None,
                created_at=NOW,
                creation_command_id=uuid4(),
                domain_verification_token="fictional-" + "x" * 44,
                details={} if industry is None else {"industry_code": industry},
            )
        )
    return tenant_id


def _version(base: int, label: str, **report: Any) -> VersionIntent:
    settings = VERSION_1.model_copy(update={"report": VERSION_1.report.model_copy(update=report)})
    return VersionIntent(label=label, base_number=base, settings=settings)


def test_versions_choices_rollback_and_the_apps_version(
    postgres_harness: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(report_settings_admin, "ConversationProviderAdmin", _Admit)

    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            fixture = await seed(engine)
            operations = fixture.tenant_id
            actor = ActorContext(fixture.person_id, fixture.session_id, operations)
            wise = await _organisation(sessions, "Sunrise Rooftops", "68100")
            other = await _organisation(sessions, "Other Co", None)

            async def admin(database: AsyncSession) -> ReportSettingsAdmin:
                return ReportSettingsAdmin(
                    ConversationApplication(database, clock=lambda: NOW),
                    operations_tenant_id=operations,
                    organisation_ids=(wise, other, operations),
                )

            async def effective(tenant_id: UUID) -> dict[str, Any]:
                async with sessions() as database:
                    return await ReportSettingsStore(database).effective(tenant_id)

            # Nothing chosen: everyone sees version 1.
            assert (await effective(wise))["version"]["number"] == 1
            assert (await effective(wise))["source"] == "built_in"

            async with sessions() as database, database.begin():
                with pytest.raises(ConversationDenied):
                    await (await admin(database)).overview(
                        ActorContext(fixture.person_id, fixture.session_id, wise)
                    )
            # A version that changes nothing is refused; version 1 can't be edited.
            async with sessions() as database, database.begin():
                with pytest.raises(ConversationError, match="changes nothing"):
                    await (await admin(database)).create_version(
                        actor,
                        VersionIntent(label="Same", base_number=1, settings=VERSION_1),
                        key="same",
                    )
            async with sessions() as database, database.begin():
                compact = await (await admin(database)).create_version(
                    actor, _version(1, "Compact", style="compact"), key="v2"
                )
            assert compact["number"] == 2
            assert compact["changes"] == [
                {"key": "report.style", "from": "guided", "to": "compact"}
            ]
            # The same key replays the same version, never a second one.
            async with sessions() as database, database.begin():
                replay = await (await admin(database)).create_version(
                    actor, _version(1, "Compact", style="compact"), key="v2"
                )
            assert replay["number"] == 2
            async with sessions() as database, database.begin():
                scorecard = await (await admin(database)).create_version(
                    actor, _version(2, "Scorecard", style="scorecard"), key="v3"
                )
            assert scorecard["number"] == 3

            async def choose(key: str, **fields: Any) -> dict[str, Any]:
                async with sessions() as database, database.begin():
                    return await (await admin(database)).choose(
                        actor, ChoiceIntent(**fields), key=key
                    )

            await choose("general", scope="general", version_number=2)
            assert (await effective(other))["version"]["number"] == 2
            await choose("industry", scope="industry", industry_code="68100", version_number=3)
            assert (await effective(wise))["source"] == "industry"
            assert (await effective(wise))["version"]["number"] == 3
            assert (await effective(other))["version"]["number"] == 2
            await choose(
                "wise",
                scope="organisation",
                tenant_id=wise,
                version_number=1,
                reason="The reviewer wants the full report for Sunrise Rooftops",
            )
            assert (await effective(wise))["version"]["number"] == 1
            assert (await effective(wise))["source"] == "organisation"
            # A stale screen can't overwrite a newer choice.
            with pytest.raises(ConversationConflict):
                await choose(
                    "stale",
                    scope="organisation",
                    tenant_id=wise,
                    version_number=2,
                    expected_version_number=None,
                )
            # Roll back: choose what it had before (inherit again).
            await choose(
                "rollback",
                scope="organisation",
                tenant_id=wise,
                version_number=None,
                expected_version_number=1,
            )
            assert (await effective(wise))["version"]["number"] == 3
            # Only served organisations can be chosen for.
            with pytest.raises(ConversationError):
                await choose("stranger", scope="organisation", tenant_id=uuid4(), version_number=2)

            async with sessions() as database, database.begin():
                overview = await (await admin(database)).overview(actor)
            assert [item["number"] for item in overview["versions"]] == [1, 2, 3]
            assert overview["versions"][0]["frozen"] is True
            assert overview["general_version_number"] == 2
            assert overview["industries"] == [{"industry_code": "68100", "version_number": 3}]
            names = {row["name"]: row for row in overview["organisations"]}
            assert names["Sunrise Rooftops"]["version_number"] == 3
            assert names["Sunrise Rooftops"]["own_version_number"] is None
            kinds = [(row["kind"], row["scope"]) for row in overview["history"]]
            assert kinds[0] == ("assigned", "organisation") and len(kinds) == 6
            assert (
                overview["history"][1]["reason"]
                == "The reviewer wants the full report for Sunrise Rooftops"
            )

            async with sessions() as database:
                versions = await database.scalar(
                    select(func.count()).select_from(ReportSettingsVersion)
                )
                events = await database.scalar(
                    select(func.count()).select_from(ReportSettingsEvent)
                )
                audits = await database.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(AuditEvent.action.like("conversation.report_settings_%"))
                )
            # Append-only: 2 versions, 2 created + 4 choices, one audit per command.
            assert (versions, events, audits) == (2, 6, 6)
        finally:
            await engine.dispose()

    run(exercise())
