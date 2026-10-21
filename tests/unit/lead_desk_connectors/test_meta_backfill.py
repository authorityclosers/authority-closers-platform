"""Bring in older Meta leads: all 90 days Meta keeps, a slice at a time, never twice."""

import asyncio
import base64
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ac_platform.lead_desk.connectors import meta, meta_backfill

KEY = base64.urlsafe_b64encode(b"k" * 32).decode()
ENV = {
    "AC_META_APP_ID": "1234567890",
    "AC_META_APP_SECRET": "app-secret",
    "AC_META_LOGIN_CONFIG_ID": "987654321",
    "AC_META_WEBHOOK_VERIFY_TOKEN": "verify-me",
    "AC_LEAD_DESK_TOKEN_KEY": KEY,
}
NOW = 1_800_000_000
DAYS_90 = 90 * 86400


def cfg() -> meta.MetaConfig:
    value = meta.config(ENV)
    assert value is not None
    return value


@dataclass
class Source:
    config: dict[str, Any]
    label: str = "Meta · Test Page"
    received: int = 0
    last_received_at: datetime | None = None


def lead(form: str, n: int) -> dict[str, Any]:
    return {
        "id": f"{form}-{n}",
        "created_time": "2027-01-01T09:00:00+0000",
        "form_id": form,
        "field_data": [{"name": "full_name", "values": [f"Lead {form} {n}"]}],
    }


@dataclass
class Graph:
    """Two forms: f1 has 3 pages of 2 leads, f2 has 1 page of 1 lead."""

    pages: dict[str, list[list[dict[str, Any]]]] = field(
        default_factory=lambda: {
            "f1": [[lead("f1", 1), lead("f1", 2)], [lead("f1", 3), lead("f1", 4)], [lead("f1", 5)]],
            "f2": [[lead("f2", 1)]],
        }
    )
    calls: list[tuple[str, int, str | None]] = field(default_factory=list)
    fail: meta.MetaError | None = None

    async def forms(self, page_id: str, page_token: str) -> list[dict[str, str]]:
        return [{"id": form, "name": form.upper(), "status": "ACTIVE"} for form in self.pages]

    async def leads_page(
        self, form_id: str, page_token: str, *, since: int, after: str | None = None
    ) -> tuple[list[dict[str, Any]], str | None]:
        self.calls.append((form_id, since, after))
        if self.fail is not None:
            raise self.fail
        index = int(after or 0)
        pages = self.pages[form_id]
        return pages[index], str(index + 1) if index + 1 < len(pages) else None


@dataclass
class Desk:
    known: set[str] = field(default_factory=set)
    now: datetime = datetime(2027, 1, 15, 10, 0, tzinfo=UTC)
    filed: list[str] = field(default_factory=list)
    test_data: dict[str, bool] = field(default_factory=dict)

    async def ingest(self, record: Any, **kwargs: Any) -> tuple[None, str]:
        ref = kwargs["source_ref"]
        assert kwargs["source"] == "meta" and kwargs["actor"] is None
        self.filed.append(ref)
        self.test_data[ref] = kwargs["test_data"]
        if ref in self.known:
            return None, "known"
        self.known.add(ref)
        return None, "created"


def source() -> Source:
    sealed = meta.seal(cfg().token_key, "page-token", page_id="p1")
    config = {"page_id": "p1", "page_name": "Test Page", "token": sealed, "forms": "all"}
    return Source(config=meta_backfill.begin(config, form_ids=["f1", "f2"], now=NOW))


def test_bringing_in_older_leads_covers_the_90_days_meta_keeps() -> None:
    state = meta_backfill.state(source().config)
    assert state is not None
    assert (state["state"], state["since"], state["forms"]) == (
        "running",
        NOW - DAYS_90,
        ["f1", "f2"],
    )
    assert meta.BACKFILL_DAYS == 90 and meta.PULL_DAYS == 7


def test_one_step_reads_every_form_page_by_page_and_finishes() -> None:
    src, graph, desk = source(), Graph(), Desk()
    created = asyncio.run(meta_backfill.step(desk, src, graph, cfg(), now=NOW + 60))
    assert created == 6
    assert desk.filed == ["f1-1", "f1-2", "f1-3", "f1-4", "f1-5", "f2-1"]
    assert [(form, after) for form, _, after in graph.calls] == [
        ("f1", None),
        ("f1", "1"),
        ("f1", "2"),
        ("f2", None),
    ]
    assert all(since == NOW - DAYS_90 for _, since, _ in graph.calls)
    state = meta_backfill.state(src.config)
    assert state is not None
    assert (state["state"], state["created"], state["seen"], state["finished_at"]) == (
        "done",
        6,
        6,
        NOW + 60,
    )
    assert src.received == 6 and src.last_received_at == desk.now
    assert not meta_backfill.running(src.config)


def test_leads_metas_testing_tool_made_are_filed_as_test_data() -> None:
    made_up = {
        "id": "f1-9",
        "form_id": "f1",
        "field_data": [
            {"name": "email", "values": ["test@meta.com"]},
            {"name": "full_name", "values": ["<test lead: dummy data for full_name>"]},
        ],
    }
    desk = Desk()
    graph = Graph(pages={"f1": [[lead("f1", 1), made_up]], "f2": [[lead("f2", 1)]]})
    asyncio.run(meta_backfill.step(desk, source(), graph, cfg(), now=NOW))
    assert desk.test_data == {"f1-1": False, "f1-9": True, "f2-1": False}


def test_a_step_stops_at_its_budget_and_the_next_one_carries_on() -> None:
    src, graph, desk = source(), Graph(), Desk()
    first = asyncio.run(meta_backfill.step(desk, src, graph, cfg(), now=NOW, budget=3))
    state = meta_backfill.state(src.config)
    assert first == 4  # a page is filed whole: the budget is checked between pages
    assert state is not None and (state["form"], state["after"]) == (0, "2")
    assert meta_backfill.running(src.config)
    second = asyncio.run(meta_backfill.step(desk, src, graph, cfg(), now=NOW + 60, budget=3))
    assert second == 2 and not meta_backfill.running(src.config)
    assert desk.filed == ["f1-1", "f1-2", "f1-3", "f1-4", "f1-5", "f2-1"]


def test_asking_again_adds_nothing_new() -> None:
    desk = Desk()
    once = source()
    asyncio.run(meta_backfill.step(desk, once, Graph(), cfg(), now=NOW))
    again = source()
    created = asyncio.run(meta_backfill.step(desk, again, Graph(), cfg(), now=NOW + 60))
    state = meta_backfill.state(again.config)
    assert created == 0 and state is not None and (state["seen"], state["created"]) == (6, 0)
    assert again.received == 0


def test_leads_access_manager_blocks_until_the_customer_allows_the_app() -> None:
    src = source()
    graph = Graph(fail=meta.MetaError(meta.LEAD_ACCESS_TEXT, "lead_access"))
    assert asyncio.run(meta_backfill.step(Desk(), src, graph, cfg(), now=NOW)) == 0
    state = meta_backfill.state(src.config)
    assert state is not None
    assert (state["state"], state["error"]) == ("blocked", meta.LEAD_ACCESS_TEXT)
    assert not meta_backfill.running(src.config)


def test_a_passing_failure_keeps_the_place_and_tries_again() -> None:
    src = source()
    graph = Graph(fail=meta.MetaError("Meta didn't answer. Try again in a minute."))
    asyncio.run(meta_backfill.step(Desk(), src, graph, cfg(), now=NOW))
    state = meta_backfill.state(src.config)
    assert state is not None and state["state"] == "running" and state["error"]
    graph.fail = None
    asyncio.run(meta_backfill.step(Desk(), src, graph, cfg(), now=NOW + 60))
    state = meta_backfill.state(src.config)
    assert state is not None and (state["state"], state["error"]) == ("done", None)


def test_a_finished_or_missing_backfill_does_nothing() -> None:
    src = Source(config={"page_id": "p1"})
    graph = Graph()
    assert asyncio.run(meta_backfill.step(Desk(), src, graph, cfg(), now=NOW)) == 0
    assert graph.calls == []


def test_the_pages_forms_are_kept_with_their_names_and_status() -> None:
    kept = meta_backfill.remember_forms(
        {"page_id": "p1"},
        [{"id": "f1", "name": "Enquiry", "status": "ACTIVE"}, {"id": "f2", "name": "Old"}],
    )
    assert kept["form_list"] == [
        {"id": "f1", "name": "Enquiry", "status": "ACTIVE"},
        {"id": "f2", "name": "Old", "status": ""},
    ]
