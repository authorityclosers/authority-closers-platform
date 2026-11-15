"""Call reports by API key (API, MCP and CLI gaps, 15 Nov 2026, gap 5): an organisation key with
reports:read lists the organisation's ready reports (and its maker's Saved ones), and reads one
report, its Word file and its transcript; without the scope, or for a call not ready, it is
refused. A person's connection reads their own calls' reports, and the organisation's only as an
owner or admin, as in the app."""

from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import update

from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.conversation_intelligence.report_saves import set_report_saved
from ac_platform.http.routes import RouteContext
from ac_platform.integrations import keys, reports_api
from ac_platform.integrations.api_http import ApiError, Caller, Reader, install_integrations_api
from ac_platform.integrations.http import install_integrations_http
from ac_platform.integrations.reports_api import install_reports_api
from ac_platform.tenancy.models import Membership
from tests.database.test_coaching_access_postgresql import team
from tests.database.test_coaching_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN
from tests.database.test_prospect_store_postgresql import direct_call

WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
PAGE = "/v1/sales-xray/integrations"


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def test_an_organisation_key_reads_reports_saved_reports_and_transcripts(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup, _, owners, sellers, _ = await team(postgres_harness, tmp_path)
        try:
            waiting = await direct_call(setup)  # a call whose report isn't ready
            context = RouteContext(setup.settings, setup.require_actor, setup.sessions)
            install_integrations_http(setup.app, context)
            install_integrations_api(setup.app, context)
            install_reports_api(setup.app, context)
            # The owner saves the seller's report in the app.
            async with setup.sessions() as db, db.begin():
                assert await set_report_saved(
                    GuestOwnership(setup.factory(db)),
                    sellers,
                    actor=setup.state.actor,
                    saved=True,
                    shared_identity_locks=True,
                )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                made = await client.post(
                    f"{PAGE}/keys",
                    headers=WRITE,
                    json={"name": "Reports", "scopes": ["calls:read", "reports:read"]},
                )
                assert made.status_code == 200, made.text
                calls_only = await client.post(
                    f"{PAGE}/keys", headers=WRITE, json={"name": "Calls", "scopes": ["calls:read"]}
                )
                assert calls_only.status_code == 200, calls_only.text
            bearer = {"Authorization": f"Bearer {made.json()['key']}"}
            narrow = {"Authorization": f"Bearer {calls_only.json()['key']}"}
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as app:
                listed = await app.get("/v1/api/reports", headers=bearer)
                assert listed.status_code == 200, listed.text
                rows = {row["id"]: row for row in listed.json()["reports"]}
                # Both ready reports, never the call still waiting for one.
                assert set(rows) == {str(owners), str(sellers)}
                assert rows[str(sellers)]["saved"] and not rows[str(owners)]["saved"]
                assert listed.json()["next_before"] is None
                saved = await app.get("/v1/api/reports?saved=true", headers=bearer)
                assert [row["id"] for row in saved.json()["reports"]] == [str(sellers)]

                one = await app.get(f"/v1/api/calls/{sellers}/report", headers=bearer)
                assert one.status_code == 200, one.text
                body = one.json()
                assert body["schema"] == reports_api.SCHEMA
                assert body["call"]["id"] == str(sellers) and body["official_score"] is False
                assert "summary" in body["report"] and "dimensions" in body["report"]
                # Internal provenance stays out of the API's answer.
                assert not {"recording_id", "run_id", "source_sha256"} & set(body)
                assert one.headers["cache-control"] == "no-store"

                word = await app.get(f"/v1/api/calls/{sellers}/report.docx", headers=bearer)
                assert word.status_code == 200, word.text
                assert word.headers["content-type"] == reports_api.DOCX
                assert word.content[:2] == b"PK"

                spoken = await app.get(f"/v1/api/calls/{sellers}/transcript", headers=bearer)
                assert spoken.status_code == 200, spoken.text
                assert spoken.json()["call"]["id"] == str(sellers)
                assert isinstance(spoken.json()["segments"], list) and spoken.json()["segments"]

                not_ready = await app.get(f"/v1/api/calls/{waiting}/report", headers=bearer)
                assert not_ready.status_code == 404
                assert not_ready.json()["error"]["code"] == "report_not_ready"
                missing = await app.get(f"/v1/api/calls/{uuid4()}/report", headers=bearer)
                assert missing.json()["error"]["code"] == "call_missing"

                for path in (
                    "/v1/api/reports",
                    f"/v1/api/calls/{sellers}/report",
                    f"/v1/api/calls/{sellers}/report.docx",
                    f"/v1/api/calls/{sellers}/transcript",
                ):
                    refused = await app.get(path, headers=narrow)
                    assert refused.status_code == 403, path
                    assert refused.json()["error"]["code"] == "scope_missing"
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_a_person_reads_their_own_reports_and_the_team_s_only_as_owner_or_admin(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup, seller, owners, sellers, _ = await team(postgres_harness, tmp_path)
        tenant = setup.state.tenant_id

        def person(person_id: Any, role: str) -> Caller:
            key = keys.KeyContext(
                key_id=uuid4(),
                tenant_id=tenant,
                scopes=frozenset({"reports:read"}),
                prefix="app test",
                acting_person_id=person_id,
            )
            return Caller(key=key, reach="person", role=role)

        async def ids(caller: Caller) -> set[str]:
            async with setup.sessions() as db, db.begin():
                page = await reports_api.reports(Reader(db, caller, None, "test"))
            return {row["id"] for row in page["reports"]}

        async def opens(caller: Caller, call: Any) -> bool:
            async with setup.sessions() as db, db.begin():
                try:
                    await reports_api.report(Reader(db, caller, None, "test"), call)
                except ApiError as error:
                    assert error.code == "call_missing"
                    return False
            return True

        try:
            sellers_own = person(seller.actor.person_id, "member")
            assert await ids(sellers_own) == {str(sellers)}
            assert await opens(sellers_own, sellers) and not await opens(sellers_own, owners)
            # A manager sees the team's calls in the call list, but opens only their own
            # reports, as in the app.
            assert await ids(person(seller.actor.person_id, "manager")) == {str(sellers)}
            owner = person(setup.state.actor.person_id, "owner")
            assert await ids(owner) == {str(owners), str(sellers)}
            assert await opens(owner, sellers)
            admin = person(setup.state.actor.person_id, "admin")
            assert await ids(admin) == {str(owners), str(sellers)}
            # The role is the caller's live one (the opener reads it), so a demoted owner
            # is back to their own reports.
            async with setup.sessions() as db, db.begin():
                await db.execute(
                    update(Membership)
                    .where(Membership.person_id == setup.state.actor.person_id)
                    .values(role="member")
                )
            assert await ids(person(setup.state.actor.person_id, "member")) == {str(owners)}
        finally:
            await setup.engine.dispose()

    run(exercise())
