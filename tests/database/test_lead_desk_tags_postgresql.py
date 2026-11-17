"""Lead tags (owner's picks, 17 Nov 2026; tags.py) through the HTTP API on PostgreSQL: the
workspace's tags made by owners and managers, one lead's tags with a history line, the list
filter, saved views, bulk tag and untag with Undo (only what the job put on comes off), the
import's tags on every new lead, and a deleted tag gone from every lead."""

from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain
from ac_platform.lead_desk.models import LeadTagLink
from tests.database.test_conversation_account_library_postgresql import _session
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_lead_desk_postgresql import _organisation

WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
BASE = "/v1/lead-desk"
NAMES = ("Asha Tagfix", "Ravi Tagfix", "Meera Tagfix")


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def test_lead_tags_end_to_end(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            tenant = setup.state.tenant_id
            seller = await seed(setup.engine, tenant_id=tenant, role="member")
            seller_token = await _session(setup, seller)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:

                def as_(token: str) -> None:
                    client.cookies.set(setup.settings.session_cookie_name, token)

                async def post(path: str, body: dict[str, Any]) -> httpx.Response:
                    return await client.post(f"{BASE}{path}", json=body, headers=WRITE)

                async def tagged(tag: str) -> set[str]:
                    page = await client.get(f"{BASE}/leads?scope=team&side=inbound&tag={tag}")
                    assert page.status_code == 200, page.text
                    return {row["name"] for row in page.json()["leads"]}

                as_(setup.token)
                leads: list[UUID] = []
                for name in NAMES:
                    added = await post(
                        "/leads",
                        {"command_id": str(uuid4()), "name": name, "city": "Pune", "assign": "me"},
                    )
                    assert added.status_code == 201, added.text
                    leads.append(UUID(added.json()["lead"]["lead_id"]))
                first = leads[0]

                # Owners make tags; the same name again is the same tag; sellers can't.
                made = await post(
                    "/tags", {"command_id": str(uuid4()), "name": "Nov  video ad", "colour": "sky"}
                )
                assert made.status_code == 201, made.text
                tag = made.json()
                assert (tag["name"], tag["colour"], tag["revision"]) == ("Nov video ad", "sky", 1)
                tag_id = tag["tag_id"]
                same = await post("/tags", {"command_id": str(uuid4()), "name": "nov video AD"})
                assert same.json()["tag_id"] == tag_id
                hot = {"command_id": str(uuid4()), "name": "Hot", "colour": "rose"}
                other = (await post("/tags", hot)).json()
                red = {"command_id": str(uuid4()), "name": "x", "colour": "red"}
                bad = await post("/tags", red)
                assert bad.status_code == 422
                as_(seller_token)
                refused = await post("/tags", {"command_id": str(uuid4()), "name": "Mine"})
                assert refused.status_code == 403
                assert (await client.get(f"{BASE}/tags")).json()["can_change"] is False
                as_(setup.token)

                # One lead's tags from its page, once per command, with a history line.
                change = {"command_id": str(uuid4()), "add": [tag_id]}
                on = await post(f"/leads/{first}/tags", change)
                assert on.status_code == 200, on.text
                assert [chip["name"] for chip in on.json()["tags"]] == ["Nov video ad"]
                assert (await post(f"/leads/{first}/tags", change)).json() == on.json()
                detail = (await client.get(f"{BASE}/leads/{first}")).json()
                assert [chip["tag_id"] for chip in detail["lead"]["tags"]] == [tag_id]
                line = detail["events"][0]
                assert line["kind"] == "edited" and line["changed"] == ["tags"]
                assert line["tags_added"] == ["Nov video ad"] and line["tags_removed"] == []
                assert await tagged(tag_id) == {"Asha Tagfix"}

                # All three matching, tagged in one job: two change, one already had it.
                job = await post(
                    "/leads/bulk-jobs",
                    {
                        "command_id": str(uuid4()),
                        "filter": {"scope": "team", "side": "inbound", "search": "Tagfix"},
                        "expected_total": 3,
                        "action": "tag",
                        "tag_ids": [tag_id],
                    },
                )
                assert job.status_code == 200, job.text
                answer = job.json()
                assert (answer["changed"], answer["unchanged"]) == (2, 1), answer
                assert answer["words"] == "2 leads tagged Nov video ad"
                assert await tagged(tag_id) == set(NAMES)
                rows = (await client.get(f"{BASE}/leads?scope=team&side=inbound")).json()["leads"]
                assert all(row["tags"][0]["name"] == "Nov video ad" for row in rows)
                no_tag = await post(
                    "/leads/bulk-jobs",
                    {"command_id": str(uuid4()), "lead_ids": [str(first)], "action": "tag"},
                )
                assert no_tag.status_code == 422

                # Undo takes off only what the job put on: the first lead keeps its own.
                undone = await post(f"/leads/bulk-jobs/{answer['job_id']}/undo", {})
                assert undone.status_code == 200, undone.text
                assert (undone.json()["restored"], undone.json()["skipped"]) == (2, 0)
                assert await tagged(tag_id) == {"Asha Tagfix"}

                # Untag the first, then Undo puts it back.
                off = await post(
                    "/leads/bulk-jobs",
                    {
                        "command_id": str(uuid4()),
                        "lead_ids": [str(first)],
                        "action": "untag",
                        "tag_ids": [tag_id],
                    },
                )
                assert off.json()["changed"] == 1 and await tagged(tag_id) == set()
                assert off.json()["words"] == "Nov video ad taken off 1 lead"
                back = await post(f"/leads/bulk-jobs/{off.json()['job_id']}/undo", {})
                assert back.json()["restored"] == 1 and await tagged(tag_id) == {"Asha Tagfix"}

                # The tags list counts; a rename by revision, a stale one refused.
                listed = (await client.get(f"{BASE}/tags")).json()
                assert [(t["name"], t["leads"]) for t in listed["tags"]] == [
                    ("Hot", 0),
                    ("Nov video ad", 1),
                ]
                renamed = await client.put(
                    f"{BASE}/tags/{tag_id}",
                    json={"expected_revision": 1, "name": "Nov video"},
                    headers=WRITE,
                )
                assert renamed.status_code == 200 and renamed.json()["revision"] == 2
                stale = await client.put(
                    f"{BASE}/tags/{tag_id}",
                    json={"expected_revision": 1, "colour": "mint"},
                    headers=WRITE,
                )
                assert stale.status_code == 409
                clash = await client.put(
                    f"{BASE}/tags/{tag_id}",
                    json={"expected_revision": 2, "name": "HOT"},
                    headers=WRITE,
                )
                assert clash.status_code == 409

                # A saved view with the tag counts its leads.
                view = await post(
                    "/views",
                    {
                        "command_id": str(uuid4()),
                        "name": "Video ad leads",
                        "visibility": "me",
                        "filter": {"scope": "team", "side": "inbound", "tag": tag_id},
                    },
                )
                assert view.status_code == 201, view.text
                views = (await client.get(f"{BASE}/views?counts=true")).json()["views"]
                assert [v["count"] for v in views if v["name"] == "Video ad leads"] == [1]

                # An import tags every lead it makes.
                imported = await post(
                    "/imports",
                    {
                        "command_id": str(uuid4()),
                        "file_name": "nov.csv",
                        "mapping": {"name": "Name", "phone": "Phone"},
                        "rows": [{"Name": "Kiran Tagfix", "Phone": "9876500011"}],
                        "assign": "me",
                        "tags": [tag_id, other["tag_id"]],
                    },
                )
                assert imported.status_code == 200, imported.text
                assert imported.json()["created"] == 1
                assert await tagged(tag_id) == {"Asha Tagfix", "Kiran Tagfix"}
                assert await tagged(other["tag_id"]) == {"Kiran Tagfix"}

                # A deleted tag comes off every lead; the history keeps its name.
                gone = await post(f"/tags/{tag_id}/delete", {"expected_revision": 2})
                assert gone.status_code == 200, gone.text
                assert [t["name"] for t in gone.json()["tags"]] == ["Hot"]
                detail = (await client.get(f"{BASE}/leads/{first}")).json()
                assert detail["lead"]["tags"] == []
                assert any(e.get("tags_added") == ["Nov video ad"] for e in detail["events"])
                missing = await client.get(f"{BASE}/leads?scope=team&side=inbound&tag={tag_id}")
                assert missing.json()["leads"] == []

            async with setup.sessions() as db:
                links = (await db.scalars(select(LeadTagLink.tag_id))).all()
                assert {str(tag_id) for tag_id in links} == {other["tag_id"]}
                events = (
                    await db.scalars(
                        select(AuditEvent).where(
                            AuditEvent.tenant_id == tenant,
                            AuditEvent.resource_type.in_(("lead_desk.tag", "lead_desk.bulk_job")),
                        )
                    )
                ).all()
                assert events
                words = str([event.payload for event in events])
                assert not any(private in words for private in (*NAMES, "Nov video", "Tagfix"))
                assert (await verify_audit_chain(db, tenant)).valid
        finally:
            await setup.engine.dispose()

    run(exercise())
