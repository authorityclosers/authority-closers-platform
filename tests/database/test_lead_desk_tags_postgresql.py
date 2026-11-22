"""Tags on leads (owner's picks, 17 Nov 2026: M2-A "Add tag", the phone dock's Tag, import I4;
migration 0165, v1.94), through the HTTP API on PostgreSQL: making tags, one lead's tags, chips
on rows and the lead page, the history lines, the tag filter and saved views, bulk tag and untag
with Undo, who may change tags, renames and deletes; then the rules: one name per workspace (two
at once included), 10 tags a lead, audit events, a seller's own leads only, managers' renames
and deletes, and a merge carrying tags."""

import asyncio
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain
from ac_platform.lead_desk import tags as lead_tags
from tests.database.test_conversation_account_library_postgresql import _session
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_lead_desk_postgresql import _organisation

WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
BASE = "/v1/lead-desk"


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def test_tags_on_leads_end_to_end(postgres_harness: Any, tmp_path: Path) -> None:
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

                async def team(**options: str) -> dict[str, Any]:
                    page = await client.get(
                        f"{BASE}/leads", params={"scope": "team", "view": "all", **options}
                    )
                    assert page.status_code == 200, page.text
                    return cast(dict[str, Any], page.json())

                as_(setup.token)
                ids = []
                for index in range(3):
                    added = await post(
                        "/leads",
                        {"command_id": str(uuid4()), "name": f"Tag Fictional {index}"},
                    )
                    assert added.status_code == 201, added.text
                    ids.append(added.json()["lead"]["lead_id"])

                # A tag; the same command, or the same name in other letters, is that tag.
                command = str(uuid4())
                made = await post("/tags", {"command_id": command, "name": "Hot"})
                assert made.status_code == 201, made.text
                hot = made.json()
                assert hot["colour"] in {"mint", "sky", "amber", "rose", "violet", "slate"}
                assert (await post("/tags", {"command_id": command, "name": "Hot"})).json()[
                    "tag_id"
                ] == hot["tag_id"]
                same = await post("/tags", {"command_id": str(uuid4()), "name": "  hot "})
                assert same.json()["tag_id"] == hot["tag_id"]

                # One lead: add Hot and make "Nov video ad" on the way.
                one = await post(
                    f"/leads/{ids[0]}/tags",
                    {"command_id": str(uuid4()), "add": [hot["tag_id"]], "new": ["Nov video ad"]},
                )
                assert one.status_code == 200, one.text
                assert [tag["name"] for tag in one.json()["tags"]] == ["Hot", "Nov video ad"]
                assert one.json()["added"] == 2
                listed = (await client.get(f"{BASE}/tags")).json()["tags"]
                assert [(tag["name"], tag["leads"]) for tag in listed] == [
                    ("Hot", 1),
                    ("Nov video ad", 1),
                ]
                video = listed[1]

                # Chips on the row, the filter, the lead page and its history.
                page = await team(tag=hot["tag_id"])
                assert [row["lead_id"] for row in page["leads"]] == [ids[0]]
                assert [chip["name"] for chip in page["leads"][0]["tags"]] == [
                    "Hot",
                    "Nov video ad",
                ]
                detail = (await client.get(f"{BASE}/leads/{ids[0]}")).json()
                assert len(detail["lead"]["tags"]) == 2
                lines = [
                    event["allocation_reason"]
                    for event in detail["events"]
                    if event["changed"] == ["tags"]
                ]
                assert lines == ["Tags added: Hot, Nov video ad"]

                # A saved view keeps the tag and counts it.
                view = await post(
                    "/views",
                    {
                        "command_id": str(uuid4()),
                        "name": "Hot ones",
                        "filter": {"scope": "team", "tag": hot["tag_id"]},
                    },
                )
                assert view.status_code == 201, view.text
                views = (await client.get(f"{BASE}/views?counts=true")).json()["views"]
                assert views[0]["count"] == 1

                # Bulk tag on all three: two change, one had it; Undo takes it off those two.
                job = await post(
                    "/leads/bulk-jobs",
                    {
                        "command_id": str(uuid4()),
                        "lead_ids": ids,
                        "action": "tag",
                        "tag_ids": [hot["tag_id"]],
                    },
                )
                assert job.status_code == 200, job.text
                assert (job.json()["changed"], job.json()["unchanged"]) == (2, 1)
                assert job.json()["words"] == "2 leads tagged Hot"
                assert (await team(tag=hot["tag_id"]))["total"] == 3
                undone = await client.post(
                    f"{BASE}/leads/bulk-jobs/{job.json()['job_id']}/undo", headers=WRITE
                )
                assert undone.status_code == 200, undone.text
                assert (undone.json()["restored"], undone.json()["skipped"]) == (2, 0)
                assert [row["lead_id"] for row in (await team(tag=hot["tag_id"]))["leads"]] == [
                    ids[0]
                ]

                # Untag "all matching" the filter, then Undo puts it back.
                off = await post(
                    "/leads/bulk-jobs",
                    {
                        "command_id": str(uuid4()),
                        "filter": {"scope": "team", "tag": video["tag_id"]},
                        "expected_total": 1,
                        "action": "untag",
                        "tag_ids": [video["tag_id"]],
                    },
                )
                assert off.status_code == 200, off.text
                assert off.json()["words"] == "Nov video ad taken off 1 lead"
                assert (await team(tag=video["tag_id"]))["total"] == 0
                await client.post(
                    f"{BASE}/leads/bulk-jobs/{off.json()['job_id']}/undo", headers=WRITE
                )
                assert (await team(tag=video["tag_id"]))["total"] == 1
                no_tag = await post(
                    "/leads/bulk-jobs",
                    {"command_id": str(uuid4()), "lead_ids": ids, "action": "tag"},
                )
                assert no_tag.status_code == 422

                # A seller sees the tags and tags their own lead, but changes no tag.
                as_(seller_token)
                assert len((await client.get(f"{BASE}/tags")).json()["tags"]) == 2
                renamed = await client.put(
                    f"{BASE}/tags/{hot['tag_id']}",
                    json={"expected_revision": 1, "name": "Warm"},
                    headers=WRITE,
                )
                assert renamed.status_code == 403
                bulk = await post(
                    "/leads/bulk-jobs",
                    {
                        "command_id": str(uuid4()),
                        "lead_ids": ids,
                        "action": "tag",
                        "tag_ids": [hot["tag_id"]],
                    },
                )
                assert bulk.status_code == 403
                own = await post("/leads", {"command_id": str(uuid4()), "name": "Seller Fic"})
                mine = await post(
                    f"/leads/{own.json()['lead']['lead_id']}/tags",
                    {"command_id": str(uuid4()), "add": [hot["tag_id"]]},
                )
                assert mine.status_code == 200, mine.text
                theirs = await post(
                    f"/leads/{uuid4()}/tags",
                    {"command_id": str(uuid4()), "add": [hot["tag_id"]]},
                )
                assert theirs.status_code == 404

                # The owner renames by revision (a stale one is 409), then deletes a tag:
                # it leaves every lead, and the history keeps what it said.
                as_(setup.token)
                renamed = await client.put(
                    f"{BASE}/tags/{hot['tag_id']}",
                    json={"expected_revision": 1, "name": "Warm", "colour": "rose"},
                    headers=WRITE,
                )
                assert renamed.status_code == 200, renamed.text
                assert (renamed.json()["name"], renamed.json()["colour"]) == ("Warm", "rose")
                stale = await client.put(
                    f"{BASE}/tags/{hot['tag_id']}",
                    json={"expected_revision": 1, "name": "Cold"},
                    headers=WRITE,
                )
                assert stale.status_code == 409
                taken = await client.put(
                    f"{BASE}/tags/{hot['tag_id']}",
                    json={"expected_revision": 2, "name": "nov VIDEO ad"},
                    headers=WRITE,
                )
                assert taken.status_code == 409
                gone = await post(f"/tags/{hot['tag_id']}/delete", {"expected_revision": 2})
                assert gone.status_code == 200, gone.text
                assert [tag["name"] for tag in gone.json()["tags"]] == ["Nov video ad"]
                detail = (await client.get(f"{BASE}/leads/{ids[0]}")).json()
                assert [chip["name"] for chip in detail["lead"]["tags"]] == ["Nov video ad"]
                assert "Tags added: Hot, Nov video ad" in [
                    event["allocation_reason"] for event in detail["events"]
                ]
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_tag_rules_names_cap_audit_roles_and_merge(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            tenant = setup.state.tenant_id
            people = {
                role: await seed(setup.engine, tenant_id=tenant, role=kind)
                for role, kind in (
                    ("seller", "member"),
                    ("other", "member"),
                    ("manager", "manager"),
                    ("viewer", "viewer"),
                )
            }
            tokens = {role: await _session(setup, who) for role, who in people.items()}
            tokens["admin"] = setup.token
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:

                def as_(role: str) -> None:
                    client.cookies.set(setup.settings.session_cookie_name, tokens[role])

                async def post(path: str, body: dict[str, Any]) -> httpx.Response:
                    return await client.post(f"{BASE}{path}", json=body, headers=WRITE)

                async def lead(name: str) -> str:
                    added = await post("/leads", {"command_id": str(uuid4()), "name": name})
                    assert added.status_code == 201, added.text
                    return str(added.json()["lead"]["lead_id"])

                async def chips(lead_id: str) -> list[str]:
                    detail = (await client.get(f"{BASE}/leads/{lead_id}")).json()
                    return [chip["name"] for chip in detail["lead"]["tags"]]

                async def names() -> list[str]:
                    return [
                        tag["name"] for tag in (await client.get(f"{BASE}/tags")).json()["tags"]
                    ]

                # Two people make "Hot" at the same moment: one tag (the unique name decides).
                as_("admin")
                twins = await asyncio.gather(
                    post("/tags", {"command_id": str(uuid4()), "name": "Hot"}),
                    post("/tags", {"command_id": str(uuid4()), "name": "HOT"}),
                )
                assert [made.status_code for made in twins] == [201, 201], twins[1].text
                assert twins[0].json()["tag_id"] == twins[1].json()["tag_id"]
                hot = twins[0].json()["tag_id"]
                assert await names() == ["Hot"]

                # Ten tags on a lead; the eleventh is refused with words, and nothing changes
                # (not even a tag made by name on the way).
                ten = []
                for index in range(10):
                    made = await post(
                        "/tags", {"command_id": str(uuid4()), "name": f"Batch {index + 1}"}
                    )
                    assert made.status_code == 201, made.text
                    ten.append(made.json()["tag_id"])
                full, room = await lead("Full Fictional"), await lead("Room Fictional")
                filled = await post(f"/leads/{full}/tags", {"command_id": str(uuid4()), "add": ten})
                assert (filled.status_code, filled.json()["added"]) == (200, 10), filled.text
                more = await post(f"/leads/{full}/tags", {"command_id": str(uuid4()), "add": [hot]})
                assert more.status_code == 422
                assert more.json()["detail"] == lead_tags.FULL
                fresh = await post(
                    f"/leads/{full}/tags", {"command_id": str(uuid4()), "new": ["Fresh"]}
                )
                assert fresh.status_code == 422
                assert "Fresh" not in await names()
                # Swapping one for another fits.
                swap = await post(
                    f"/leads/{full}/tags",
                    {"command_id": str(uuid4()), "add": [hot], "remove": [ten[0]]},
                )
                assert (swap.status_code, swap.json()["added"]) == (200, 1), swap.text
                # A bulk tag changes the lead with room and counts the full one.
                bulk = await post(
                    "/leads/bulk-jobs",
                    {
                        "command_id": str(uuid4()),
                        "lead_ids": [full, room],
                        "action": "tag",
                        "tag_ids": [ten[0]],
                    },
                )
                assert bulk.status_code == 200, bulk.text
                assert bulk.json()["changed"] == 1
                assert bulk.json()["failed"] == [{"reason": lead_tags.FULL_REASON, "count": 1}]
                assert await chips(room) == ["Batch 1"]

                # Only owners, admins and managers rename, recolour and delete; a Viewer
                # makes no tag.
                for role in ("seller", "viewer"):
                    as_(role)
                    assert len(await names()) == 11
                    renamed = await client.put(
                        f"{BASE}/tags/{ten[1]}",
                        json={"expected_revision": 1, "name": "Nope"},
                        headers=WRITE,
                    )
                    assert renamed.status_code == 403, role
                    deleted = await post(f"/tags/{ten[2]}/delete", {"expected_revision": 1})
                    assert deleted.status_code == 403, role
                made = await post("/tags", {"command_id": str(uuid4()), "name": "Viewer tag"})
                assert made.status_code == 403
                as_("manager")
                renamed = await client.put(
                    f"{BASE}/tags/{ten[1]}",
                    json={"expected_revision": 1, "name": "Callback list", "colour": "violet"},
                    headers=WRITE,
                )
                assert renamed.status_code == 200, renamed.text
                assert (renamed.json()["name"], renamed.json()["revision"]) == ("Callback list", 2)
                gone = await post(f"/tags/{ten[2]}/delete", {"expected_revision": 1})
                assert gone.status_code == 200, gone.text
                assert "Batch 3" not in [tag["name"] for tag in gone.json()["tags"]]

                # A seller tags their own leads only: another seller's real lead is not there.
                as_("other")
                theirs = await lead("Other Seller Fictional")
                as_("seller")
                mine = await lead("Seller Fictional")
                refused = await post(
                    f"/leads/{theirs}/tags", {"command_id": str(uuid4()), "add": [hot]}
                )
                assert refused.status_code == 404
                done = await post(f"/leads/{mine}/tags", {"command_id": str(uuid4()), "add": [hot]})
                assert done.status_code == 200, done.text
                as_("other")
                assert await chips(theirs) == []

                # A merge puts the other lead's tags on the kept lead; an unmerge takes off
                # exactly those.
                as_("admin")
                kept, twin = await lead("Merge Fictional"), await lead("Merge Fictional Twin")
                await post(f"/leads/{kept}/tags", {"command_id": str(uuid4()), "add": [hot]})
                await post(
                    f"/leads/{twin}/tags",
                    {"command_id": str(uuid4()), "add": [hot, ten[3], ten[4]]},
                )
                merged = await post(
                    "/duplicates/merge",
                    {"command_id": str(uuid4()), "lead_ids": [kept, twin], "keep": kept},
                )
                assert merged.status_code == 200, merged.text
                assert await chips(kept) == ["Hot", "Batch 4", "Batch 5"]
                undone = await post(
                    f"/merges/{merged.json()['merge_id']}/undo", {"command_id": str(uuid4())}
                )
                assert undone.status_code == 200, undone.text
                assert await chips(kept) == ["Hot"]
                assert await chips(twin) == ["Hot", "Batch 4", "Batch 5"]

            # One audit event per tag made, renamed or deleted: ids, never the tag's words.
            async with setup.sessions() as db:
                events = (
                    await db.scalars(
                        select(AuditEvent)
                        .where(
                            AuditEvent.tenant_id == tenant,
                            AuditEvent.resource_type == lead_tags.AUDIT_RESOURCE,
                        )
                        .order_by(AuditEvent.sequence_no)
                    )
                ).all()
                made_ids = [e.resource_id for e in events if e.action == "lead_desk.tag.created"]
                assert sorted(made_ids) == sorted([hot, *ten])
                edited = [e for e in events if e.action == "lead_desk.tag.edited"]
                assert [(e.resource_id, e.payload) for e in edited] == [
                    (ten[1], {"changed": ["name", "colour"], "revision": 2})
                ]
                assert edited[0].actor_person_id == people["manager"].person_id
                deleted = [e for e in events if e.action == "lead_desk.tag.deleted"]
                assert [(e.resource_id, e.payload) for e in deleted] == [(ten[2], {"leads": 1})]
                words = str([event.payload for event in events])
                assert not any(name in words for name in ("Hot", "Batch", "Callback"))
                assert (await verify_audit_chain(db, tenant)).valid
        finally:
            await setup.engine.dispose()

    run(exercise())
