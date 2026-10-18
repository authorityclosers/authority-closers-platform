"""Google Ads accounts: turning one on points its forms here; the pull is the safety net."""

import asyncio
import base64
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ac_platform.lead_desk.connectors import google_ads_api as api
from ac_platform.lead_desk.connectors import google_pull

KEY = base64.urlsafe_b64encode(b"k" * 32).decode()
ENV = {
    "AC_GOOGLE_ADS_CLIENT_ID": "client-1",
    "AC_GOOGLE_ADS_CLIENT_SECRET": "client-secret",
    "AC_GOOGLE_ADS_DEVELOPER_TOKEN": "dev-token",
    "AC_LEAD_DESK_TOKEN_KEY": KEY,
}
NOW = 1_800_000_000
MONTH = api.BACKFILL_DAYS * 86400
APP = "https://salesxray.test"


def cfg() -> api.GoogleAdsConfig:
    value = api.config(ENV)
    assert value is not None
    return value


@dataclass
class Source:
    config: dict[str, Any]
    id: UUID = field(default_factory=uuid4)
    kind: str = "webhook"
    label: str = "Google Ads · Rao Solar"
    received: int = 0
    last_received_at: datetime | None = None


def source(**config: Any) -> Source:
    seal = cfg().token_key
    return Source(
        config={
            "connector": "google_ads",
            "customer_id": "101",
            "account_name": "Rao Solar",
            "login_customer_id": "100",
            "token": api.seal(seal, "refresh-1", customer_id="101", what="token"),
            "key": api.seal(seal, "hook-key", customer_id="101", what="key"),
            "forms": "all",
            **config,
        }
    )


@dataclass
class Ads:
    forms: list[api.LeadForm] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    refuse: set[str] = field(default_factory=set)
    set_calls: list[tuple[str, str, str, str | None]] = field(default_factory=list)
    pulls: list[tuple[str, str | None, str, int]] = field(default_factory=list)

    async def access_token(self, refresh_token: str) -> str:
        assert refresh_token == "refresh-1"  # noqa: S105 - a test value
        return "access-1"

    async def lead_forms(self, account: api.Account, access: str) -> list[api.LeadForm]:
        return self.forms

    async def set_webhook(
        self, account: api.Account, form: api.LeadForm, access: str, *, url: str, key: str
    ) -> None:
        if form.form_id in self.refuse:
            raise api.GoogleAdsApiError("Google Ads refused the request.")
        self.set_calls.append((form.form_id, url, key, account.login_customer_id))

    async def submissions(
        self, account: api.Account, access: str, *, since: int
    ) -> list[dict[str, Any]]:
        self.pulls.append((account.customer_id, account.login_customer_id, access, since))
        return self.rows


@dataclass
class Desk:
    outcomes: list[str]
    now: datetime = datetime(2027, 1, 15, 10, 0, tzinfo=UTC)
    filed: list[dict[str, Any]] = field(default_factory=list)

    async def ingest(self, record: Any, **kwargs: Any) -> tuple[None, str]:
        self.filed.append({"record": record, **kwargs})
        return None, self.outcomes[len(self.filed) - 1]


def lead(n: int, *, gclid: bool = True) -> dict[str, Any]:
    row: dict[str, Any] = {
        "lead_id": f"sub-{n}",
        "user_column_data": [
            {"column_id": "FULL_NAME", "string_value": f"Lead {n}"},
            {"column_id": "PHONE_NUMBER", "string_value": f"+91980000000{n}"},
        ],
    }
    if gclid:
        row["gcl_id"] = f"click-{n}"
    return row


def test_turning_on_points_free_forms_at_sales_xray_and_keeps_other_hooks() -> None:
    src = source()
    url = f"{APP}/v1/lead-desk/capture/{src.id}/google-ads"
    ads = Ads(
        forms=[
            api.LeadForm("customers/101/assets/1", "1", "New form", None, None),
            api.LeadForm("customers/101/assets/2", "2", "Ours already", url, "hook-key"),
            api.LeadForm(
                "customers/101/assets/3", "3", "Zapier", "https://hooks.zapier.com/x", "z"
            ),
            api.LeadForm("customers/101/assets/4", "4", "Old key", url, "stale"),
            api.LeadForm("customers/101/assets/5", "5", "Refused", None, None),
        ],
        refuse={"5"},
    )
    result = asyncio.run(google_pull.ensure_webhooks(src, ads, cfg(), app_url=APP + "/"))
    assert ads.set_calls == [("1", url, "hook-key", "100"), ("4", url, "hook-key", "100")]
    assert (result.forms, result.sending, result.other, result.failed) == (5, 3, 1, 1)
    assert src.config["webhooks"] == {"forms": 5, "sending": 3, "other": 1, "failed": 1}


def test_the_first_pull_reads_the_same_month_as_turning_on() -> None:
    assert google_pull.since({}, NOW) == NOW - MONTH
    assert google_pull.since({"last_pulled_at": NOW - 600}, NOW) == NOW - 600 - 3600
    assert google_pull.since({"last_pulled_at": NOW - 90 * 86400}, NOW) == NOW - MONTH
    assert google_pull.due({}, NOW)
    assert not google_pull.due({"last_pulled_at": NOW - 120}, NOW)
    assert google_pull.due({"last_pulled_at": NOW - 600}, NOW)


def test_a_pull_files_each_lead_like_the_webhook_and_records_the_time() -> None:
    src = source()
    ads = Ads(rows=[lead(1), lead(2), lead(3, gclid=False), {"lead_id": "empty"}])
    desk = Desk(["created", "known", "repeat"])
    counts = asyncio.run(google_pull.pull_source(desk, src, ads, cfg(), now=NOW))
    assert (counts.fetched, counts.created, counts.known, counts.repeat, counts.skipped) == (
        4,
        1,
        1,
        1,
        1,
    )
    assert ads.pulls == [("101", "100", "access-1", NOW - MONTH)]
    assert [f["source_ref"] for f in desk.filed] == ["gclid:click-1", "gclid:click-2", "sub-3"]
    assert all(f["source"] == "webhook" and f["actor"] is None for f in desk.filed)
    assert all(f["source_label"] == "Google Ads · Rao Solar" for f in desk.filed)
    assert src.received == 2 and src.last_received_at == desk.now
    assert src.config["last_pulled_at"] == NOW


def test_a_broken_seal_asks_to_connect_again() -> None:
    src = source(token={"n": "x", "c": "y"})
    with pytest.raises(api.GoogleAdsApiError, match="Connect this Google Ads account again"):
        asyncio.run(google_pull.pull_source(Desk([]), src, Ads(), cfg(), now=NOW))


def test_tests_and_local_runs_do_not_start_the_puller() -> None:
    app = FastAPI()
    before = app.router.lifespan_context
    google_pull.attach(app, None, "test")  # type: ignore[arg-type]
    assert app.router.lifespan_context is before


def test_the_puller_starts_and_stops_with_the_api(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    async def fake(sessions: Any, stop: asyncio.Event, **_: Any) -> None:
        seen.append("started")
        await stop.wait()

    monkeypatch.setattr(google_pull, "run_google_puller", fake)
    app = FastAPI()
    google_pull.attach(app, None, "development")  # type: ignore[arg-type]
    with TestClient(app):
        pass
    assert seen == ["started"]
