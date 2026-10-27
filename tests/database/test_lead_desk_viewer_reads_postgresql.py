"""Viewers read the team's calls, reports and team page (Roles B; orchestrator, 27 Oct 2026),
through the HTTP API on PostgreSQL. They change nothing, and a seller is still refused the
team's reports."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest

from tests.database.test_conversation_account_library_postgresql import _session
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_lead_desk_postgresql import _india_day, _organisation

WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
BASE = "/v1/lead-desk"
VIEW_ONLY = "Your role can view only. Ask an owner or admin to change this."
OWN_ONLY = "Your role sees your own leads and calls only."


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def test_viewers_read_the_teams_calls_reports_and_team_and_change_nothing(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            tenant = setup.state.tenant_id
            seller = await seed(setup.engine, tenant_id=tenant, role="member")
            seller_token = await _session(setup, seller)
            viewer = await seed(setup.engine, tenant_id=tenant, role="viewer")
            viewer_token = await _session(setup, viewer)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:

                def as_(token: str) -> None:
                    client.cookies.set(setup.settings.session_cookie_name, token)

                # A teammate's work: a seller's lead and one call the phone logged.
                as_(seller_token)
                added = await client.post(
                    f"{BASE}/leads",
                    json={
                        "command_id": str(uuid4()),
                        "name": "Fictional Viewer Lead",
                        "phone": "98760 86001",
                        "assign": "me",
                    },
                    headers=WRITE,
                )
                assert added.status_code == 201, added.text
                lead_id = added.json()["lead"]["lead_id"]
                now = datetime.now(UTC)
                logged = await client.post(
                    f"{BASE}/phone-log",
                    json={
                        "device_id": str(uuid4()),
                        "calls": [
                            {
                                "log_id": "1",
                                "number": "9876086001",
                                "started_at": (now - timedelta(minutes=3)).isoformat(),
                                "duration_seconds": 90,
                                "direction": "outgoing",
                            }
                        ],
                    },
                    headers=WRITE,
                )
                assert logged.json()["logged"] == 1
                today = _india_day(now)
                calls_query = {"start": str(today - timedelta(days=1)), "end": str(today)}
                reads = (
                    ("/team", {}),
                    ("/reports/calls", calls_query),
                    ("/reports/performance", {"days": 7}),
                )

                # A seller still reads only their own: not the team's reports or page.
                for path, params in reads:
                    refused = await client.get(f"{BASE}{path}", params=params)
                    assert refused.status_code == 403, path
                    assert refused.json()["detail"] == OWN_ONLY, path
                me = (await client.get(BASE)).json()["me"]
                assert (me["can_manage"], me["can_see_team"]) == (False, False)

                # A Viewer reads the team page, the teammate's calls and the sales report.
                as_(viewer_token)
                me = (await client.get(BASE)).json()["me"]
                assert (me["can_manage"], me["can_see_team"]) == (False, True)
                team = await client.get(f"{BASE}/team")
                assert team.status_code == 200, team.text
                reps = {rep["person_id"]: rep for rep in team.json()["reps"]}
                assert str(seller.person_id) in reps
                calls = await client.get(f"{BASE}/reports/calls", params=calls_query)
                assert calls.status_code == 200, calls.text
                rows = {row["person_id"]: row for row in calls.json()["sellers"]}
                assert rows[str(seller.person_id)]["calls"] == 1
                performance = await client.get(f"{BASE}/reports/performance", params={"days": 7})
                assert performance.status_code == 200, performance.text
                assert (await client.get(f"{BASE}/leads/{lead_id}")).status_code == 200

                # Every change is refused with the read-only words, before it runs.
                rep = reps[str(seller.person_id)]
                settings = team.json()["settings"]
                for method, path, body in (
                    (
                        "PUT",
                        f"/team/{seller.person_id}",
                        {
                            "expected_revision": rep["revision"],
                            "available": False,
                            "max_open": None,
                        },
                    ),
                    (
                        "PUT",
                        "/settings",
                        {
                            "expected_revision": settings["revision"],
                            "auto_reassign": False,
                            "reassign_minutes": 10,
                            "strict_language": True,
                        },
                    ),
                    (
                        "POST",
                        "/leads",
                        {"command_id": str(uuid4()), "name": "Fictional", "phone": "98760 86002"},
                    ),
                    ("POST", f"/leads/{lead_id}/notes", {"command_id": str(uuid4()), "note": "x"}),
                ):
                    refused = await client.request(
                        method, f"{BASE}{path}", json=body, headers=WRITE
                    )
                    assert refused.status_code == 403, (path, refused.text)
                    assert refused.json()["detail"] == VIEW_ONLY, path
        finally:
            await setup.engine.dispose()

    run(exercise())
