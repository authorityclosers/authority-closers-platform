"""Meta Lead Ads pull: leads arrive while Meta holds webhooks (apps in development mode)."""

import asyncio
import base64
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ac_platform.lead_desk.connectors import meta, meta_pull

KEY = base64.urlsafe_b64encode(b"k" * 32).decode()
ENV = {
    "AC_META_APP_ID": "1234567890",
    "AC_META_APP_SECRET": "app-secret",
    "AC_META_LOGIN_CONFIG_ID": "987654321",
    "AC_META_WEBHOOK_VERIFY_TOKEN": "verify-me",
    "AC_LEAD_DESK_TOKEN_KEY": KEY,
}
NOW = 1_800_000_000
WEEK = meta.PULL_DAYS * 86400


def cfg() -> meta.MetaConfig:
    value = meta.config(ENV)
    assert value is not None
    return value


@dataclass
class Source:
    config: dict[str, Any]
    label: str = "Facebook: Test Page"
    received: int = 0
    last_received_at: datetime | None = None


@dataclass
class Graph:
    leads: list[dict[str, Any]]
    forms_called: int = 0
    calls: list[tuple[list[str], str, int]] = field(default_factory=list)

    async def forms(self, page_id: str, page_token: str) -> list[dict[str, str]]:
        self.forms_called += 1
        return [
            {"id": "f1", "name": "A", "status": "ACTIVE"},
            {"id": "f2", "name": "B", "status": "ACTIVE"},
        ]

    async def recent_leads(
        self, form_ids: list[str], page_token: str, *, since: int
    ) -> list[dict[str, Any]]:
        self.calls.append((list(form_ids), page_token, since))
        return self.leads


class NoLeads:
    """No lead here yet: every Meta lead goes to intake."""

    async def scalar(self, statement: Any) -> None:
        return None


@dataclass
class Desk:
    outcomes: list[str]
    now: datetime = datetime(2027, 1, 15, 10, 0, tzinfo=UTC)
    filed: list[dict[str, Any]] = field(default_factory=list)
    db: NoLeads = field(default_factory=NoLeads)
    tenant_id: UUID = field(default_factory=uuid4)

    async def settings(self) -> tuple[int, dict[str, Any]]:
        return 1, {"default_country": "91"}

    async def ingest(self, record: Any, **kwargs: Any) -> tuple[None, str]:
        self.filed.append({"record": record, **kwargs})
        return None, self.outcomes[len(self.filed) - 1]


def source(**config: Any) -> Source:
    sealed = meta.seal(cfg().token_key, "page-token", page_id="p1")
    return Source(config={"page_id": "p1", "page_name": "Test Page", "token": sealed, **config})


def lead(n: int) -> dict[str, Any]:
    return {
        "id": f"lead-{n}",
        "created_time": "2027-01-15T09:00:00+0000",
        "form_id": "f1",
        "field_data": [
            {"name": "full_name", "values": [f"Lead {n}"]},
            {"name": "phone_number", "values": [f"+91980000000{n}"]},
        ],
    }


def test_the_first_pull_reads_the_same_week_as_connecting() -> None:
    assert meta_pull.since({}, NOW) == NOW - WEEK


def test_later_pulls_reread_the_last_hour_but_never_beyond_a_week() -> None:
    assert meta_pull.since({"last_pulled_at": NOW - 600}, NOW) == NOW - 600 - 3600
    assert meta_pull.since({"last_pulled_at": NOW - 30 * 86400}, NOW) == NOW - WEEK
    assert meta_pull.since({"last_pulled_at": True}, NOW) == NOW - WEEK


def test_a_page_is_due_every_ten_minutes() -> None:
    assert meta_pull.due({}, NOW)
    assert not meta_pull.due({"last_pulled_at": NOW - 120}, NOW)
    assert meta_pull.due({"last_pulled_at": NOW - 600}, NOW)


def test_a_pull_files_each_lead_like_the_webhook_and_records_the_time() -> None:
    src, graph = source(), Graph([lead(1), lead(2), lead(3)])
    desk = Desk(["created", "known", "repeat"])
    counts = asyncio.run(meta_pull.pull_source(desk, src, graph, cfg(), now=NOW))
    assert (counts.fetched, counts.created, counts.known, counts.repeat) == (3, 1, 1, 1)
    assert graph.calls == [(["f1", "f2"], "page-token", NOW - WEEK)]
    assert [f["source_ref"] for f in desk.filed] == ["lead-1", "lead-2", "lead-3"]
    assert all(f["source"] == "meta" and f["actor"] is None for f in desk.filed)
    assert src.received == 2 and src.last_received_at == desk.now
    assert src.config["last_pulled_at"] == NOW and src.config["token"]


def test_every_pull_keeps_the_pages_forms_so_the_page_can_show_them() -> None:
    src = source()
    asyncio.run(meta_pull.pull_source(Desk([]), src, Graph([]), cfg(), now=NOW))
    assert src.config["form_list"] == [
        {"id": "f1", "name": "A", "status": "ACTIVE", "leads": None},
        {"id": "f2", "name": "B", "status": "ACTIVE", "leads": None},
    ]


def test_a_good_pull_clears_metas_last_refusal() -> None:
    src = source(last_error={"at": NOW - 600, "kind": "other", "text": "Meta didn't answer."})
    asyncio.run(meta_pull.pull_source(Desk([]), src, Graph([]), cfg(), now=NOW))
    assert "last_error" not in src.config


def test_a_refused_pull_is_kept_for_the_manager() -> None:
    error = meta.MetaError(meta.LEAD_ACCESS_TEXT, "lead_access")
    kept = meta_pull.failed({"page_id": "p1"}, error, NOW)
    assert kept["last_error"] == {"at": NOW, "kind": "lead_access", "text": meta.LEAD_ACCESS_TEXT}


def test_picked_forms_are_read_without_listing_the_page() -> None:
    src, graph = source(forms=["f9"]), Graph([])
    asyncio.run(meta_pull.pull_source(Desk([]), src, graph, cfg(), now=NOW))
    assert graph.forms_called == 0 and graph.calls[0][0] == ["f9"]


def test_pulling_twice_adds_nothing_the_second_time() -> None:
    src, graph = source(), Graph([lead(1)])
    first = asyncio.run(meta_pull.pull_source(Desk(["created"]), src, graph, cfg(), now=NOW))
    second = asyncio.run(meta_pull.pull_source(Desk(["known"]), src, graph, cfg(), now=NOW + 600))
    assert (first.created, second.created, second.known) == (1, 0, 1)
    assert graph.calls[1][2] == NOW - 3600
    assert src.received == 1


def test_tests_and_local_runs_do_not_start_the_puller() -> None:
    app = FastAPI()
    before = app.router.lifespan_context
    meta_pull.attach(app, None, "test")
    assert app.router.lifespan_context is before


def test_the_puller_starts_and_stops_with_the_api(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    async def fake(sessions: Any, stop: asyncio.Event, **_: Any) -> None:
        seen.append("started")
        await stop.wait()

    monkeypatch.setattr(meta_pull, "run_meta_puller", fake)
    app = FastAPI()
    meta_pull.attach(app, None, "development")
    with TestClient(app):
        pass
    assert seen == ["started"]
