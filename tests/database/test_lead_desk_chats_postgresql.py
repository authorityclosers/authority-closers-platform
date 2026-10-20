"""Sales Xray Chats on PostgreSQL with Meta faked: read marks and attachments.

Read marks: their messages count as unread until this person reads further, or a person
on the team answers (an automatic reply doesn't); a mark never moves back, never passes
the newest message, and needs this app's page. Attachments: a WhatsApp photo and a
Messenger file stream through Sales Xray from Meta's file hosts only, a voice note can
seek (Range), a link elsewhere is refused, and nothing is kept.
"""

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select

from ac_platform.http.routes import RouteContext
from ac_platform.lead_desk.chats import media, reads
from ac_platform.lead_desk.chats.http import install_chats_http
from ac_platform.lead_desk.chats.models import LeadChatRead
from ac_platform.lead_desk.models import (
    Lead,
    LeadSocialAccount,
    LeadSocialMessage,
    LeadWhatsAppMessage,
    LeadWhatsAppNumber,
)
from ac_platform.lead_desk.social import graph
from ac_platform.lead_desk.store import LeadDesk, Viewer
from ac_platform.lead_desk.whatsapp import cloud
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_lead_desk_postgresql import _organisation
from tests.unit.lead_desk_social.test_social_graph import ENV, PAGE, PSID

ROOT = Path(__file__).resolve().parents[2]
WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
BASE = "/v1/lead-desk/chats"
CHAT_ENV = {**ENV, "AC_WHATSAPP_CONFIG_ID": "5550002"}
WA_ID = "919000000001"  # a fictional WhatsApp number
NUMBER_ID = "2000000001"
MEDIA_ID = "5550000001"
GRAPH = "https://graph.facebook.com/v23.0"
PHOTO = b"\xff\xd8\xff\xe0fictional-photo\xff\xd9"
VOICE = b"OggS-fictional-voice-note"


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def fake_meta(request: httpx.Request) -> httpx.Response:
    """Meta's Graph API and file hosts for one fictional organisation."""
    url = str(request.url)
    auth = request.headers.get("authorization")
    if url == f"{GRAPH}/{MEDIA_ID}":
        assert auth == "Bearer number-token"
        return httpx.Response(
            200,
            json={
                "url": "https://lookaside.fbsbx.com/whatsapp_business/attachments/?mid=1",
                "mime_type": "image/jpeg",
                "file_size": len(PHOTO),
            },
        )
    if url.startswith("https://lookaside.fbsbx.com/whatsapp_business/"):
        assert auth == "Bearer number-token"
        return httpx.Response(
            200,
            content=PHOTO,
            headers={"content-type": "image/jpeg", "content-length": str(len(PHOTO))},
        )
    if url.startswith(f"{GRAPH}/m.file?"):
        assert auth == "Bearer page-token"
        return httpx.Response(
            200,
            json={
                "attachments": {
                    "data": [
                        {
                            "mime_type": "text/html",
                            "name": "price list.html",
                            "size": 9,
                            "file_url": "https://cdn.fbsbx.com/v/t59/fictional-price-list",
                        }
                    ]
                }
            },
        )
    if url.startswith(f"{GRAPH}/m.voice?"):
        return httpx.Response(
            200,
            json={
                "attachments": {
                    "data": [
                        {
                            "mime_type": "audio/ogg",
                            "name": "audioclip.ogg",
                            "file_url": "https://cdn.fbsbx.com/v/t59/fictional-voice",
                        }
                    ]
                }
            },
        )
    if url.startswith(f"{GRAPH}/m.elsewhere?"):
        return httpx.Response(
            200, json={"attachments": {"data": [{"file_url": "https://example.com/x"}]}}
        )
    if url.startswith(f"{GRAPH}/m.gone?"):
        return httpx.Response(400, json={"error": {"code": 100, "message": "gone"}})
    if url == "https://cdn.fbsbx.com/v/t59/fictional-price-list":
        assert auth is None  # the Page token never goes to a file host
        return httpx.Response(200, content=b"<b>hi</b>", headers={"content-type": "text/html"})
    if url == "https://cdn.fbsbx.com/v/t59/fictional-voice":
        if request.headers.get("range") == "bytes=0-3":
            return httpx.Response(
                206,
                content=VOICE[:4],
                headers={
                    "content-type": "audio/ogg",
                    "content-length": "4",
                    "content-range": f"bytes 0-3/{len(VOICE)}",
                },
            )
        return httpx.Response(200, content=VOICE, headers={"content-type": "audio/ogg"})
    raise AssertionError(f"Unexpected call to {url}")


class SimpleRows:
    def __init__(self, lead_id: UUID, number_id: UUID, page_account: UUID) -> None:
        self.lead_id = lead_id
        self.number_id = number_id
        self.page_account = page_account


async def _rows(setup: Any, now: datetime) -> SimpleRows:
    tenant = setup.state.tenant_id
    person = setup.state.person_id
    cfg = cloud.config()
    social = graph.config()
    assert cfg is not None and social is not None
    lead_id, number_id, page_account = uuid4(), uuid4(), uuid4()
    async with setup.sessions() as db, db.begin():
        db.add(
            Lead(
                id=lead_id,
                tenant_id=tenant,
                revision=1,
                source="manual",
                payload={},
                name="Asha Fictional",
                stage="new",
                owner_person_id=person,
                assigned_at=now - timedelta(hours=1),
                attempts=0,
                calls=0,
                repeats=0,
                test_data=False,
                created_by_person_id=person,
                created_at=now - timedelta(hours=1),
                updated_at=now - timedelta(hours=1),
            )
        )
        db.add(
            LeadWhatsAppNumber(
                id=number_id,
                tenant_id=tenant,
                waba_id="1000000001",
                phone_number_id=NUMBER_ID,
                display_number="+91 90000 00000",
                token=cloud.seal(cfg, "number-token", phone_number_id=NUMBER_ID, what="token"),
                status="active",
                config={},
                connected_by_person_id=person,
                created_at=now - timedelta(hours=1),
                updated_at=now - timedelta(hours=1),
            )
        )
        db.add(
            LeadSocialAccount(
                id=page_account,
                tenant_id=tenant,
                page_id=PAGE,
                page_name="Fictional Homes",
                token=graph.seal(social, "page-token", page_id=PAGE),
                status="active",
                config={},
                connected_by_person_id=person,
                created_at=now - timedelta(hours=1),
                updated_at=now - timedelta(hours=1),
            )
        )
    return SimpleRows(lead_id, number_id, page_account)


def _wa(
    rows: SimpleRows, tenant: UUID, at: datetime, *, direction: str = "in", **extra: Any
) -> LeadWhatsAppMessage:
    values: dict[str, Any] = {
        "kind": "text",
        "body": "Fictional words",
        "status": "received" if direction == "in" else "sent",
        **extra,
    }
    return LeadWhatsAppMessage(
        id=uuid4(),
        tenant_id=tenant,
        number_id=rows.number_id,
        lead_id=rows.lead_id,
        wa_id=WA_ID,
        direction=direction,
        meta_time=at,
        created_at=at,
        **values,
    )


def _social(
    rows: SimpleRows,
    tenant: UUID,
    at: datetime,
    *,
    mid: str | None,
    kind: str = "text",
    **extra: Any,
) -> LeadSocialMessage:
    return LeadSocialMessage(
        id=uuid4(),
        tenant_id=tenant,
        account_id=rows.page_account,
        lead_id=rows.lead_id,
        channel="messenger",
        user_id=PSID,
        direction="in",
        mid=mid,
        kind=kind,
        status="received",
        meta_time=at,
        created_at=at,
        **extra,
    )


def test_read_marks_follow_the_person_across_devices(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value in CHAT_ENV.items():
        monkeypatch.setenv(name, value)

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            settings = setup.settings.model_copy(update={"public_learner_tenant_id": uuid4()})
            install_chats_http(
                setup.app, RouteContext(settings, setup.require_actor, setup.sessions)
            )
            tenant, person = setup.state.tenant_id, setup.state.person_id
            now = datetime.now(UTC)
            rows = await _rows(setup, now)
            viewer = Viewer(person_id=person, tenant_id=tenant, role="admin", name="Fictional")

            async def unread() -> dict[tuple[str, UUID, UUID], int]:
                async with setup.sessions() as db, db.begin():
                    return await reads.unread(LeadDesk(db, viewer))

            async with setup.sessions() as db, db.begin():
                for minutes in (30, 20, 10):
                    db.add(_wa(rows, tenant, now - timedelta(minutes=minutes)))
                db.add(_wa(rows, tenant, now - timedelta(minutes=9), kind="reaction", body="👍"))
                db.add(_social(rows, tenant, now - timedelta(minutes=8), mid="m.in1"))
                db.add(
                    _social(
                        rows,
                        tenant,
                        now - timedelta(minutes=7),
                        mid=None,
                        kind="comment",
                        comment_id="555_1",
                    )
                )
            wa = ("whatsapp", rows.number_id, rows.lead_id)
            fb = ("messenger", rows.page_account, rows.lead_id)
            # Three WhatsApp messages (a reaction isn't one) and one Messenger message (a
            # comment isn't one): nobody has read or answered yet.
            assert await unread() == {wa: 3, fb: 1}

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)

                async def mark(read_to: datetime | None, **extra: Any) -> httpx.Response:
                    body: dict[str, Any] = {
                        "channel": "whatsapp",
                        "leadId": str(rows.lead_id),
                        "accountId": str(rows.number_id),
                        **extra,
                    }
                    if read_to is not None:
                        body["readTo"] = read_to.isoformat()
                    return await client.post(f"{BASE}/read", json=body, headers=WRITE)

                first = await mark(now - timedelta(minutes=20))
                assert first.status_code == 200, first.text
                assert first.headers["cache-control"] == "private, no-store"
                assert await unread() == {wa: 1, fb: 1}

                # A page can't mark past the newest message, nor into the future.
                ahead = await mark(now + timedelta(days=1))
                assert ahead.status_code == 200
                newest = datetime.fromisoformat(ahead.json()["readTo"])
                assert newest == now - timedelta(minutes=9)
                assert await unread() == {fb: 1}

                # Back in time changes nothing and adds no row.
                back = await mark(now - timedelta(minutes=30))
                assert datetime.fromisoformat(back.json()["readTo"]) == newest
                async with setup.sessions() as db:
                    assert await db.scalar(select(func.count()).select_from(LeadChatRead)) == 2

                # Another page's request, a stranger's lead, a made-up channel.
                no_origin = await client.post(
                    f"{BASE}/read",
                    json={
                        "channel": "whatsapp",
                        "leadId": str(rows.lead_id),
                        "accountId": str(rows.number_id),
                    },
                )
                assert no_origin.status_code == 403
                assert (await mark(None, leadId=str(uuid4()))).status_code == 404
                assert (await mark(None, accountId=str(uuid4()))).status_code == 404
                assert (await mark(None, channel="sms")).status_code == 422

                # Messenger read from "the phone": the computer's list says so too.
                phone = await client.post(
                    f"{BASE}/read",
                    json={
                        "channel": "messenger",
                        "leadId": str(rows.lead_id),
                        "accountId": str(rows.page_account),
                    },
                    headers=WRITE,
                )
                assert phone.status_code == 200, phone.text
                assert await unread() == {}

            # A new message is unread; a teammate's reply answers it; an automatic
            # reply doesn't.
            async with setup.sessions() as db, db.begin():
                db.add(_wa(rows, tenant, now - timedelta(minutes=5)))
            assert await unread() == {wa: 1}
            async with setup.sessions() as db, db.begin():
                db.add(
                    _wa(
                        rows,
                        tenant,
                        now - timedelta(minutes=4),
                        direction="out",
                        sent_by_person_id=person,
                    )
                )
            assert await unread() == {}
            async with setup.sessions() as db, db.begin():
                db.add(_wa(rows, tenant, now - timedelta(minutes=3)))
                db.add(
                    _wa(
                        rows,
                        tenant,
                        now - timedelta(minutes=2),
                        direction="out",
                        auto="out_of_hours",
                    )
                )
            assert await unread() == {wa: 1}
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_attachments_stream_from_meta_and_stay_there(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value in CHAT_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(media, "TRANSPORT", httpx.MockTransport(fake_meta))

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            settings = setup.settings.model_copy(update={"public_learner_tenant_id": uuid4()})
            install_chats_http(
                setup.app, RouteContext(settings, setup.require_actor, setup.sessions)
            )
            tenant = setup.state.tenant_id
            now = datetime.now(UTC)
            rows = await _rows(setup, now)
            photo = _wa(
                rows,
                tenant,
                now - timedelta(minutes=3),
                kind="image",
                body=None,
                media={"id": MEDIA_ID, "mime_type": "image/jpeg"},
            )
            words = _wa(rows, tenant, now - timedelta(minutes=2))
            file = _social(rows, tenant, now - timedelta(minutes=1), mid="m.file", kind="file")
            voice = _social(rows, tenant, now, mid="m.voice", kind="audio")
            elsewhere = _social(rows, tenant, now, mid="m.elsewhere", kind="file")
            gone = _social(rows, tenant, now, mid="m.gone", kind="image")
            async with setup.sessions() as db, db.begin():
                db.add_all([photo, words, file, voice, elsewhere, gone])

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)

                shown = await client.get(f"{BASE}/media/whatsapp/{photo.id}")
                assert shown.status_code == 200, shown.text
                assert shown.content == PHOTO
                assert shown.headers["content-type"] == "image/jpeg"
                assert shown.headers["content-disposition"].startswith("inline;")
                assert shown.headers["cache-control"] == "private, max-age=300"
                assert shown.headers["x-content-type-options"] == "nosniff"
                assert "sandbox" in shown.headers["content-security-policy"]
                assert "fbsbx" not in shown.text and "number-token" not in str(shown.headers)

                # An HTML file is never shown as a page: it downloads as plain bytes.
                download = await client.get(f"{BASE}/media/messenger/{file.id}")
                assert download.status_code == 200, download.text
                assert download.headers["content-type"] == "application/octet-stream"
                assert download.headers["content-disposition"].startswith("attachment;")
                assert "price list.html" in download.headers["content-disposition"]
                about = await client.get(f"{BASE}/media/messenger/{file.id}/info")
                assert about.json() == {
                    "kind": "file",
                    "mime": "application/octet-stream",
                    "name": "price list.html",
                    "size": 9,
                }

                # A voice note seeks.
                part = await client.get(
                    f"{BASE}/media/messenger/{voice.id}", headers={"Range": "bytes=0-3"}
                )
                assert part.status_code == 206
                assert part.content == VOICE[:4]
                assert part.headers["content-range"] == f"bytes 0-3/{len(VOICE)}"

                # Only Meta's own file hosts; a file Meta forgot; a message without one;
                # a channel mix-up; a stranger's message.
                assert (
                    await client.get(f"{BASE}/media/messenger/{elsewhere.id}")
                ).status_code == 410
                assert (await client.get(f"{BASE}/media/messenger/{gone.id}")).status_code == 410
                assert (await client.get(f"{BASE}/media/whatsapp/{words.id}")).status_code == 404
                assert (await client.get(f"{BASE}/media/instagram/{file.id}")).status_code == 404
                assert (await client.get(f"{BASE}/media/whatsapp/{uuid4()}")).status_code == 404

            # Nothing about the file was kept.
            async with setup.sessions() as db:
                kept = await db.get(LeadWhatsAppMessage, photo.id)
                assert kept is not None and kept.media == {
                    "id": MEDIA_ID,
                    "mime_type": "image/jpeg",
                }
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_media_hosts_and_types_are_meta_only() -> None:
    assert media.meta_host("https://lookaside.fbsbx.com/x")
    assert media.meta_host("https://scontent.xx.fbcdn.net/v/1.jpg")
    assert not media.meta_host("http://lookaside.fbsbx.com/x")
    assert not media.meta_host("https://fbsbx.com.example.com/x")
    assert not media.meta_host("https://user@lookaside.fbsbx.com/x")
    assert not media.meta_host("https://lookaside.fbsbx.com:8443/x")
    assert media.content_type("image/svg+xml") == "application/octet-stream"
    assert media.content_type("audio/ogg; codecs=opus") == "audio/ogg"
    assert media.content_type("") == "application/octet-stream"
    assert media.disposition("image/jpeg", None, "image").startswith('inline; filename="photo"')
    assert media.disposition("application/pdf", '../"evil".pdf', "file").startswith(
        'attachment; filename="_evil_.pdf"'
    )


def test_migration_0113_follows_0112() -> None:
    path = ROOT / "db/migrations/versions/20261020_0113_lead_desk_chat_reads.py"
    spec = importlib.util.spec_from_file_location("chat_reads_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert (module.revision, module.down_revision) == ("20261020_0113", "20261020_0112")
