"""Admin's sandbox call browser (AUT-1798) on PostgreSQL.

A disposable schema holds foreign-key-free copies of the two sandbox tables,
so no full migration is needed. Proves: only sandbox organisations' full calls
are listed (newest revision), the index follows new imports, and one call
never carries fixture truth or the private coaching.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Column, MetaData, Table, create_engine, insert
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateSchema, DropSchema

import ac_platform.db.models  # noqa: F401 - register every mapper
from ac_platform.conversation_intelligence.application import ConversationNotFound
from ac_platform.conversation_intelligence.synthetic_import_models import (
    ConversationSandboxOrganisation,
    ConversationSyntheticRecord,
)
from ac_platform.conversation_intelligence.synthetic_sandbox_browser import SandboxCallBrowser

NOW = datetime(2026, 10, 11, 9, 0, tzinfo=UTC)
scratch = MetaData()
for model in (ConversationSandboxOrganisation, ConversationSyntheticRecord):
    Table(
        model.__table__.name,
        scratch,
        *[
            Column(column.name, column.type, primary_key=column.primary_key, nullable=True)
            for column in model.__table__.columns
        ],
    )


@pytest.fixture
def database_url() -> Iterator[URL]:
    raw = os.getenv("AC_CONVERSATION_POSTGRES_TEST_URL") or os.getenv("AC_TEST_DATABASE_URL")
    if not raw:
        pytest.fail("NOT EXECUTED: a disposable loopback PostgreSQL URL is required", pytrace=False)
    url = make_url(raw).set(drivername="postgresql+psycopg")
    if url.host not in {"127.0.0.1", "localhost", "::1"}:
        pytest.fail("The sandbox browser proof refuses non-loopback PostgreSQL", pytrace=False)
    schema = f"sandbox_browser_{uuid4().hex}"
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


def bundle(call_id: str, business: str, language: str, outcome: str, at: str) -> dict[str, Any]:
    return {
        "schema": "synthetic-call-bundle/1",
        "synthetic": True,
        "metadata": {
            "call_id": call_id,
            "business_id": business,
            "journey_id": call_id.rsplit("-C-", 1)[0],
            "rep_id": business + "-R1",
            "at": at,
            "sequence": 1,
            "language_mix": language,
            "scenario": "no_next_step",
            "outcome": outcome,
            "crm_stage": "Evaluation",
            "net_deal_value_inr": 36000,
            "duration_ms": 219861,
            "audio_status": "verified_legacy_text",
            "private_coaching": True,
        },
        "transcript": {
            "participants": [{"role": "rep", "name": "Fictional Rep"}],
            "lines": [
                {
                    "line_id": call_id + ":L001",
                    "speaker": "rep",
                    "text": "नमस्ते, fictional opening",
                    "phase": "opening",
                    "start_ms": 0,
                    "end_ms": 2000,
                    "person_id": "not-served",
                }
            ],
        },
        "answer_key": {"mistake_labels": ["price_early"], "fixture_truth": {"secret": 1}},
        "report": {"summary": "Authored"},
        "coaching": {"mission": "private to the rep"},
    }


def record(tenant: UUID, kind: str, key: str, revision: int, payload: dict[str, Any], at: datetime):
    return {
        "tenant_id": tenant,
        "kind": kind,
        "synthetic_key": key,
        "revision": revision,
        "business_id": payload.get("metadata", {}).get("business_id", "syn-x"),
        "imported_by_person_id": uuid4(),
        "payload_sha256": "0" * 64,
        "payload": payload,
        "occurred_at": at,
        "imported_at": at,
    }


def run(database_url: URL, body: Any) -> None:
    async def exercise() -> None:
        engine = create_async_engine(database_url)
        try:
            await body(async_sessionmaker(engine, expire_on_commit=False))
        finally:
            await engine.dispose()

    asyncio.run(exercise())


def test_sandbox_calls_list_filter_follow_imports_and_hide_truth(database_url: URL) -> None:
    sandbox, real = uuid4(), uuid4()

    async def body(sessions: async_sessionmaker[AsyncSession]) -> None:
        first = bundle("syn-saas-J01-C-01", "syn-saas", "hi-en", "Won", "2026-07-24T10:00:00+05:30")
        later = bundle(
            "syn-saas-J01-C-02", "syn-saas", "mr-en", "Lost", "2026-08-01T10:00:00+05:30"
        )
        revised = bundle(
            "syn-saas-J01-C-02", "syn-saas", "mr-en", "Won", "2026-08-01T10:00:00+05:30"
        )
        async with sessions() as db, db.begin():
            await db.execute(
                insert(ConversationSandboxOrganisation.__table__),
                [
                    {
                        "tenant_id": sandbox,
                        "approved_by_person_id": uuid4(),
                        "approval_reference": "ref:fictional",
                        "created_at": NOW,
                    }
                ],
            )
            await db.execute(
                insert(ConversationSyntheticRecord.__table__),
                [
                    record(sandbox, "call", "syn-saas-J01-C-01", 1, first, NOW),
                    record(sandbox, "call", "syn-saas-J01-C-02", 1, later, NOW),
                    record(sandbox, "call", "syn-saas-J01-C-02", 2, revised, NOW),
                    # Not full calls, or not a sandbox organisation: never listed.
                    record(sandbox, "call_summary", "syn-saas-SIM-J1-C-01", 1, first, NOW),
                    record(real, "call", "syn-real-J01-C-01", 1, first, NOW),
                ],
            )
        async with sessions() as db:
            browser = SandboxCallBrowser(db)
            page = await browser.index()
            assert page["source"] == "sandbox" and page["synthetic"] is True
            assert page["dataset_total"] == 2
            assert [item["call_id"] for item in page["items"]] == [
                "syn-saas-J01-C-02",
                "syn-saas-J01-C-01",
            ]
            # The newest revision is the row; deal value from the authored net value.
            assert page["items"][0]["outcome"] == "Won"
            assert page["items"][0]["deal_value_inr"] == 36000
            assert {"value": "Won", "count": 2} in page["facets"]["outcomes"]
            assert (await browser.index(language="mr-en"))["total"] == 1
            assert (await browser.index(query="nothing-like-this"))["total"] == 0

            one = await browser.call("syn-saas-J01-C-01")
            assert one["lines"][0]["text"] == "नमस्ते, fictional opening"
            assert "person_id" not in one["lines"][0]
            assert one["answer_key"] == {"mistake_labels": ["price_early"]}
            assert "coaching" not in one and "report" not in one
            assert "private_coaching" not in one["call"]
            with pytest.raises(ConversationNotFound):
                await browser.call("syn-real-J01-C-01")
            with pytest.raises(ConversationNotFound):
                await browser.call("../etc/passwd")

        newer = bundle(
            "syn-estate-J01-C-01", "syn-estate", "hi-en", "Won", "2026-09-01T10:00:00+05:30"
        )
        async with sessions() as db, db.begin():
            await db.execute(
                insert(ConversationSyntheticRecord.__table__),
                [
                    record(
                        sandbox, "call", "syn-estate-J01-C-01", 1, newer, NOW + timedelta(hours=1)
                    )
                ],
            )
        async with sessions() as db:
            page = await SandboxCallBrowser(db).index()
            # A new import is seen at once (the cached index is keyed by import state).
            assert page["dataset_total"] == 3
            assert page["items"][0]["call_id"] == "syn-estate-J01-C-01"

    run(database_url, body)


def test_no_sandbox_organisation_lists_nothing(database_url: URL) -> None:
    async def body(sessions: async_sessionmaker[AsyncSession]) -> None:
        async with sessions() as db:
            browser = SandboxCallBrowser(db)
            page = await browser.index()
            assert page["total"] == 0 and page["items"] == []
            with pytest.raises(ConversationNotFound):
                await browser.call("syn-saas-J01-C-01")

    run(database_url, body)
