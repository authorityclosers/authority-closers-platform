"""The company view (AUT-1798) on PostgreSQL: projection, aggregates and scope.

A disposable schema holds foreign-key-free copies of only the tables the
company view reads, so no full migration is needed; the table itself is
checked against its migration by the model registry test.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Uuid,
    create_engine,
    insert,
    select,
    text,
)
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateSchema, DropSchema

import ac_platform.db.models  # noqa: F401 - register every mapper
from ac_platform.conversation_intelligence import org_insights
from ac_platform.conversation_intelligence.call_metrics_models import ConversationCallMetrics
from ac_platform.conversation_intelligence.guest_models import ConversationGuestSubmission
from ac_platform.conversation_intelligence.insight_models import (
    SKILL_ORDER,
    ConversationInsightCall,
)
from ac_platform.conversation_intelligence.models import (
    ConversationProcessingPlan,
    ConversationReportDraft,
)
from ac_platform.conversation_intelligence.org_insights import InsightFilters, OrganisationInsights
from ac_platform.conversation_intelligence.speaker_map_models import (
    ConversationSpeakerMapRevision,
)
from ac_platform.conversation_intelligence.synthetic_import_models import (
    ConversationSandboxOrganisation,
    ConversationSyntheticRecord,
)
from ac_platform.identity.models import Person

NOW = datetime(2026, 10, 11, 9, 0, tzinfo=UTC)
MODELS = (
    ConversationInsightCall,
    ConversationReportDraft,
    ConversationCallMetrics,
    ConversationSpeakerMapRevision,
    ConversationProcessingPlan,
    ConversationSandboxOrganisation,
    ConversationSyntheticRecord,
    ConversationGuestSubmission,
    Person,
)

scratch = MetaData()
for model in MODELS:
    source = model.__table__
    Table(
        source.name,
        scratch,
        *[
            Column(column.name, column.type, primary_key=column.primary_key, nullable=True)
            for column in source.columns
        ],
    )
scope_table = Table(
    "scope_calls",
    scratch,
    Column("submission_id", Uuid),
    Column("submission_text", String(36)),
    Column("owner", Uuid),
    Column("created_at", DateTime(timezone=True)),
    Column("seconds", Integer),
    Column("recording_id", Uuid),
)


@pytest.fixture
def database_url() -> Iterator[URL]:
    raw = os.getenv("AC_CONVERSATION_POSTGRES_TEST_URL") or os.getenv("AC_TEST_DATABASE_URL")
    if not raw:
        pytest.fail("NOT EXECUTED: a disposable loopback PostgreSQL URL is required", pytrace=False)
    url = make_url(raw).set(drivername="postgresql+psycopg")
    if url.host not in {"127.0.0.1", "localhost", "::1"}:
        pytest.fail("The company view proof refuses non-loopback PostgreSQL", pytrace=False)
    schema = f"org_insights_{uuid4().hex}"
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(CreateSchema(schema))
    scoped = url.set(query={**url.query, "options": f"-csearch_path={schema}"})
    try:
        engine = create_engine(scoped)
        with engine.begin() as connection:
            scratch.create_all(connection)
        engine.dispose()
        yield scoped
    finally:
        with admin.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        admin.dispose()


def dimensions(states: dict[str, str]) -> list[dict[str, Any]]:
    return [
        {"dimension_id": skill, "call_state": states.get(skill, "observed")}
        for skill in SKILL_ORDER
    ]


def report(outcome: str, states: dict[str, str], objections: list[str]) -> dict[str, Any]:
    return {
        "dimensions": dimensions(states),
        "overview": {"outcome": {"kind": outcome}},
        "call_map": {"objections": [{"kind": kind} for kind in objections]},
    }


async def seed_calls(
    sessions: async_sessionmaker[AsyncSession],
) -> tuple[UUID, dict[str, UUID]]:
    tenant = uuid4()
    ids = {name: uuid4() for name in ("asha", "ravi", "s1", "s2", "r1", "r2", "d1", "d2")}
    async with sessions() as db, db.begin():
        await db.execute(
            insert(Person.__table__),
            [
                {"id": ids["asha"], "email": "asha@example.test", "display_name": "Asha"},
                {"id": ids["ravi"], "email": "ravi@example.test", "display_name": None},
            ],
        )
        calls = (
            (
                "s1",
                "asha",
                "r1",
                "d1",
                NOW - timedelta(days=3),
                600,
                report("closed", {"qualification": "needs_attention"}, ["price"]),
            ),
            (
                "s2",
                "ravi",
                "r2",
                "d2",
                NOW - timedelta(days=40),
                1200,
                report(
                    "no_sale",
                    {
                        "qualification": "needs_attention",
                        "closing_decision_management": "needs_attention",
                    },
                    ["timing", "price"],
                ),
            ),
        )
        for submission, owner, recording, draft, at, seconds, payload in calls:
            await db.execute(
                insert(scope_table).values(
                    submission_id=ids[submission],
                    submission_text=str(ids[submission]),
                    owner=ids[owner],
                    created_at=at,
                    seconds=seconds,
                    recording_id=ids[recording],
                )
            )
            await db.execute(
                insert(ConversationGuestSubmission.__table__).values(
                    tenant_id=tenant,
                    submission_id=ids[submission],
                    recording_id=ids[recording],
                )
            )
            await db.execute(
                insert(ConversationReportDraft.__table__).values(
                    id=ids[draft],
                    tenant_id=tenant,
                    person_id=ids[owner],
                    recording_id=ids[recording],
                    run_id=uuid4(),
                    source_revision=1,
                    payload=payload,
                    created_at=at,
                )
            )
            await db.execute(
                insert(ConversationProcessingPlan.__table__).values(
                    id=uuid4(),
                    tenant_id=tenant,
                    person_id=ids[owner],
                    recording_id=ids[recording],
                    state="completed",
                    created_at=at,
                    manifest={"report_language": "hi-Deva+en" if owner == "asha" else "en"},
                )
            )
        await db.execute(
            insert(ConversationCallMetrics.__table__).values(
                usage_id=uuid4(),
                tenant_id=tenant,
                submission_id=ids["s1"],
                created_at=NOW,
                summary={"speakers": {"A": {"talk_share": 0.55}, "B": {"talk_share": 0.45}}},
            )
        )
        await db.execute(
            insert(ConversationSpeakerMapRevision.__table__).values(
                id=uuid4(),
                tenant_id=tenant,
                submission_id=ids["s1"],
                revision=1,
                created_at=NOW,
                speakers=[{"speaker_id": "A", "role": "you"}],
            )
        )
    return tenant, ids


def library(db: AsyncSession, tenant: UUID) -> OrganisationInsights:
    rows = select(
        scope_table.c.submission_id,
        scope_table.c.owner,
        scope_table.c.created_at,
        scope_table.c.seconds,
        scope_table.c.recording_id,
    )
    return OrganisationInsights(
        db, tenant, scope_ids=select(scope_table.c.submission_text), scope_rows=rows
    )


def run(database_url: URL, body: Any) -> None:
    async def exercise() -> None:
        engine = create_async_engine(database_url)
        try:
            await body(async_sessionmaker(engine, expire_on_commit=False))
        finally:
            await engine.dispose()

    asyncio.run(exercise())


def test_real_calls_project_aggregate_and_leave_with_the_library(database_url: URL) -> None:
    async def body(sessions: async_sessionmaker[AsyncSession]) -> None:
        tenant, ids = await seed_calls(sessions)
        async with sessions() as db, db.begin():
            insights = library(db, tenant)
            assert await insights.source() == "call"
            assert await insights.pending() == 2
            assert await insights.refresh(now=NOW) == {"projected": 2, "pending": 0}
            assert await library(db, tenant).refresh(now=NOW) == {"projected": 0, "pending": 0}

        async with sessions() as db, db.begin():
            rows = {row.call_key: row for row in await db.scalars(select(ConversationInsightCall))}
            asha = rows[str(ids["s1"])]
            assert (asha.outcome, asha.talk_share, asha.language) == ("won", 55, "hi-en")
            assert asha.skills == "OONOOOOO" and asha.objection == "price"
            assert asha.duration_ms == 600_000 and asha.source_ref == str(ids["d1"])
            ravi = rows[str(ids["s2"])]
            assert (ravi.outcome, ravi.talk_share, ravi.objection) == ("lost", None, "timing|price")

            everything = await library(db, tenant).overview(
                InsightFilters.window(NOW, span="12m"), now=NOW
            )
            assert everything["source"] == "call" and everything["synthetic"] is False
            totals = everything["totals"]
            assert (totals["calls"], totals["won"], totals["people"]) == (2, 1, 2)
            assert totals["minutes"] == 30 and totals["talk_share"] == 55
            assert totals["needs_attention_share"] == round(3 / 16, 4)
            outcomes = {row["outcome"]: row["calls"] for row in everything["outcomes"]}
            assert (outcomes["won"], outcomes["lost"], outcomes["booked"]) == (1, 1, 0)
            qualification = next(s for s in everything["skills"] if s["id"] == "qualification")
            assert qualification["needs_attention"] == 2 and qualification["observed"] == 0
            people = {row["name"]: row for row in everything["people"]}
            # Without a display name a person shows as a masked email, never the address.
            assert set(people) == {"Asha", "r***@example.test"}
            assert people["Asha"]["won"] == 1 and people["Asha"]["talk_share"] == 55
            assert everything["teams"] == []
            assert {row["kind"]: row["calls"] for row in everything["objections"]} == {
                "price": 2,
                "timing": 1,
            }
            assert everything["talk"][2] == {"band": "50_60", "label": "50–60%", "calls": 1}
            strongest = everything["calls"]["strongest"]
            assert strongest[0]["key"] == str(ids["s1"]) and strongest[0]["needs_attention"] == 1
            assert everything["calls"]["weakest"][0]["key"] == str(ids["s2"])
            assert everything["pending"] == 0
            assert everything["window"]["unit"] == "month"
            assert {row["key"] for row in everything["facets"]["languages"]} == {"en", "hi-en"}

            recent = await library(db, tenant).overview(
                InsightFilters.window(NOW, span="30d"), now=NOW
            )
            assert recent["totals"]["calls"] == 1 and recent["window"]["unit"] == "week"
            assert recent["previous"]["calls"] == 1  # Ravi's call, 40 days ago
            won = await library(db, tenant).overview(
                InsightFilters.window(NOW, span="12m", outcome="won"), now=NOW
            )
            assert won["totals"]["calls"] == 1
            ravi_calls = await library(db, tenant).calls(
                InsightFilters.window(NOW, span="12m", person=str(ids["ravi"]))
            )
            assert ravi_calls["total"] == 1 and ravi_calls["items"][0]["outcome"] == "lost"
            page = await library(db, tenant).calls(InsightFilters.window(NOW, span="12m"))
            assert [item["key"] for item in page["items"]] == [str(ids["s1"]), str(ids["s2"])]
            assert page["items"][0]["objections"] == ["price"] and page["next_offset"] is None
            # Admin opens a real call in the review console by its recording.
            assert page["items"][0]["recording_id"] == str(ids["r1"])
            assert strongest[0]["recording_id"] == str(ids["r1"])

            # A call the library no longer shows drops out of every read at once ...
            await db.execute(scope_table.delete().where(scope_table.c.submission_id == ids["s2"]))
            after = await library(db, tenant).overview(
                InsightFilters.window(NOW, span="12m"), now=NOW
            )
            assert after["totals"]["calls"] == 1 and after["pending"] == 1
            # ... and the next refresh removes its projected row.
            await library(db, tenant).refresh(now=NOW)
            assert set(await db.scalars(select(ConversationInsightCall.call_key))) == {
                str(ids["s1"])
            }

            # Without a library scope nothing is read.
            blind = await OrganisationInsights(db, tenant).overview(
                InsightFilters.window(NOW, span="all"), now=NOW
            )
            assert blind["totals"]["calls"] == 0 and blind["people"] == []

    run(database_url, body)


def test_a_newer_report_replaces_the_projected_row(database_url: URL) -> None:
    async def body(sessions: async_sessionmaker[AsyncSession]) -> None:
        tenant, ids = await seed_calls(sessions)
        async with sessions() as db, db.begin():
            await library(db, tenant).refresh(now=NOW)
            newer = uuid4()
            await db.execute(
                insert(ConversationReportDraft.__table__).values(
                    id=newer,
                    tenant_id=tenant,
                    person_id=ids["asha"],
                    recording_id=ids["r1"],
                    run_id=uuid4(),
                    source_revision=2,
                    payload=report("follow_up", {}, []),
                    created_at=NOW,
                )
            )
            insights = library(db, tenant)
            assert await insights.pending() == 1
            assert (await insights.refresh(now=NOW))["projected"] == 1
            row = await db.get(ConversationInsightCall, (tenant, "call", str(ids["s1"])))
            assert row is not None
            assert (row.source_ref, row.outcome, row.skills) == (
                str(newer),
                "follow_up",
                "OOOOOOOO",
            )

    run(database_url, body)


def summary(key: str, rep: str, at: str, outcome: str, **extra: Any) -> dict[str, Any]:
    states = extra.pop("states", {})
    return {
        "synthetic": True,
        "call_id": key,
        "rep_id": rep,
        "at": at,
        "outcome": outcome,
        "language_mix": "mr-en",
        "duration_ms": 300_000,
        "objection": "price",
        "primary_weakness": "talking_too_much",
        "mistake_present": True,
        "quoted_net_value_inr": 40_000,
        "coaching_completed_count": 3,
        "report": {
            "your_skills_on_this_call": [
                {"skill_id": f"skill-{index}", "state": states.get(index, "Observed")}
                for index in range(1, 9)
            ]
        },
        **extra,
    }


async def seed_sandbox(sessions: async_sessionmaker[AsyncSession]) -> UUID:
    tenant = uuid4()
    rows: list[dict[str, Any]] = [
        {
            "kind": "people",
            "synthetic_key": "syn-x-R1",
            "business_id": "syn-x",
            "payload": {"fields": {"name": "Meera Joshi", "team_id": "syn-x-TEAM"}},
            "occurred_at": NOW - timedelta(days=900),
        },
        {
            "kind": "people",
            "synthetic_key": "syn-x-R2",
            "business_id": "syn-x",
            "payload": {"fields": {"name": "Kabir Rao", "team_id": "syn-x-TEAM"}},
            "occurred_at": NOW - timedelta(days=900),
        },
        {
            "kind": "world",
            "synthetic_key": "syn-x",
            "business_id": "syn-x",
            "payload": {"name": "Fictional Advisory"},
            "occurred_at": NOW - timedelta(days=1000),
        },
        {
            "kind": "call_summary",
            "synthetic_key": "syn-x-C1",
            "business_id": "syn-x",
            "payload": summary("syn-x-C1", "syn-x-R1", "2026-10-01T10:00:00+05:30", "Won"),
            "occurred_at": datetime(2026, 10, 1, 4, 30, tzinfo=UTC),
        },
        {
            "kind": "call_summary",
            "synthetic_key": "syn-x-C2",
            "business_id": "syn-x",
            "payload": summary(
                "syn-x-C2",
                "syn-x-R2",
                "2026-09-20T10:00:00+05:30",
                "Meeting Booked",
                states={2: "Needs Attention", 7: "Strongly Demonstrated"},
                duration_ms="not a number",
            ),
            "occurred_at": datetime(2026, 9, 20, 4, 30, tzinfo=UTC),
        },
        {
            # A full authored call with no summary: projected from its bundle.
            "kind": "call",
            "synthetic_key": "syn-x-C3",
            "business_id": "syn-x",
            "payload": {
                "metadata": {
                    "rep_id": "syn-x-R1",
                    "outcome": "Lost",
                    "language_mix": "hi-en",
                    "duration_ms": 420_000,
                    "objection_category": "timing",
                    "net_deal_value_inr": 0,
                },
                "report": {
                    "how_the_call_played_out": {
                        "metrics": {"speaker_talk_share_percent": {"rep": 61.4}}
                    },
                    "your_skills_on_this_call": [
                        {"skill_id": f"skill-{index}", "state": "Observed"} for index in range(1, 9)
                    ],
                },
            },
            "occurred_at": datetime(2026, 8, 5, 4, 30, tzinfo=UTC),
        },
    ]
    async with sessions() as db, db.begin():
        await db.execute(insert(ConversationSandboxOrganisation.__table__).values(tenant_id=tenant))
        for row in rows:
            await db.execute(
                insert(ConversationSyntheticRecord.__table__).values(
                    tenant_id=tenant, revision=1, **row
                )
            )
    return tenant


def test_sandbox_history_projects_in_sql_and_is_labelled_synthetic(database_url: URL) -> None:
    async def body(sessions: async_sessionmaker[AsyncSession]) -> None:
        tenant = await seed_sandbox(sessions)
        org_insights._CACHE.clear()
        async with sessions() as db, db.begin():
            insights = OrganisationInsights(db, tenant)
            assert await insights.source() == "synthetic"
            assert await insights.pending() == 3
            assert await insights.refresh(now=NOW) == {"projected": 3, "pending": 0}
            assert (await OrganisationInsights(db, tenant).refresh(now=NOW))["projected"] == 0

        async with sessions() as db, db.begin():
            rows = {row.call_key: row for row in await db.scalars(select(ConversationInsightCall))}
            first = rows["syn-x-C1"]
            assert (first.person_key, first.team_key, first.outcome) == (
                "syn-x-R1",
                "syn-x-TEAM",
                "won",
            )
            assert (first.duration_ms, first.language, first.focus) == (
                300_000,
                "mr-en",
                "talking_too_much",
            )
            assert (first.deal_value, first.coaching_done, first.talk_share) == (40_000, 3, None)
            booked = rows["syn-x-C2"]
            assert booked.outcome == "booked" and booked.skills == "ONOOOOSO"
            # A non-numeric authored value stays unknown, never zero.
            assert booked.duration_ms is None
            bundle = rows["syn-x-C3"]
            assert (bundle.outcome, bundle.talk_share, bundle.objection) == ("lost", 61, "timing")
            assert bundle.source_ref == "c1" and first.source_ref == "s1c0"

            result = await OrganisationInsights(db, tenant).overview(
                InsightFilters.window(NOW, span="12m"), now=NOW
            )
            assert result["synthetic"] is True and result["source"] == "synthetic"
            assert result["totals"]["calls"] == 3 and result["totals"]["won_value"] == 40_000
            assert {row["name"] for row in result["people"]} == {"Meera Joshi", "Kabir Rao"}
            assert result["teams"][0]["name"] == "Fictional Advisory"
            assert result["teams"][0]["calls"] == 3
            assert result["mistakes"] == [
                {"kind": "talking_too_much", "label": "Talked too much", "calls": 2}
            ]
            assert result["facets"]["teams"] == [
                {"key": "syn-x-TEAM", "name": "Fictional Advisory"}
            ]
            team = await OrganisationInsights(db, tenant).overview(
                InsightFilters.window(NOW, span="12m", team="syn-x-TEAM", language="mr-en"),
                now=NOW,
            )
            assert team["totals"]["calls"] == 2
            page = await OrganisationInsights(db, tenant).calls(
                InsightFilters.window(NOW, span="all")
            )
            assert page["synthetic"] is True
            assert [item["key"] for item in page["items"]] == ["syn-x-C1", "syn-x-C2", "syn-x-C3"]
            assert page["items"][0]["person"] == "Meera Joshi"
            assert page["items"][0]["recording_id"] is None

            # Cached per projection state: a repeat read is served from the cache,
            # a refresh that projects new rows reads fresh.
            assert len(org_insights._CACHE) == 2
            await db.execute(
                insert(ConversationSyntheticRecord.__table__).values(
                    tenant_id=tenant,
                    revision=2,
                    kind="call_summary",
                    synthetic_key="syn-x-C1",
                    business_id="syn-x",
                    payload=summary("syn-x-C1", "syn-x-R1", "2026-10-01T10:00:00+05:30", "Lost"),
                    occurred_at=datetime(2026, 10, 1, 4, 30, tzinfo=UTC),
                )
            )
            revised = OrganisationInsights(db, tenant)
            assert (await revised.refresh(now=NOW + timedelta(minutes=1)))["projected"] == 1
            fresh = await OrganisationInsights(db, tenant).overview(
                InsightFilters.window(NOW, span="12m"), now=NOW
            )
            assert fresh["totals"]["won"] == 0
            row = await db.get(
                ConversationInsightCall,
                (tenant, "synthetic", "syn-x-C1"),
                populate_existing=True,
            )
            assert row is not None and row.source_ref == "s2c0" and row.outcome == "lost"

    run(database_url, body)


def test_projection_keeps_payloads_out(database_url: URL) -> None:
    """The projection stores codes and numbers only, never authored text."""

    async def body(sessions: async_sessionmaker[AsyncSession]) -> None:
        tenant = await seed_sandbox(sessions)
        async with sessions() as db, db.begin():
            await OrganisationInsights(db, tenant).refresh(now=NOW)
            rows = (await db.execute(text("SELECT * FROM conversation_insight_calls"))).all()
            dumped = json.dumps([list(map(str, row)) for row in rows])
            assert "Meera" not in dumped and "Fictional Advisory" not in dumped

    run(database_url, body)
