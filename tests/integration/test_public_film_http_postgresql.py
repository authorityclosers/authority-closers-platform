"""Real ASGI routes, opaque session cookies, migrated PostgreSQL and pinned films.

Required run: AC_TEST_DATABASE_URL (approved local schema-owner target),
AC_PUBLIC_FILMS_POSTGRES_PACK_ROOT (the actual pinned 12-second package),
AC_REQUIRE_STAGING_SEED_POSTGRES_TEST=1 and AC_REQUIRE_PUBLIC_FILMS_PLAYBACK_TEST=1.
Run this file with pytest. The shared harness migrates/drops a fresh random schema;
it never changes an existing academy, running API, deployed policy or source pack.

Only app Settings and its database session factory are test infrastructure. There
are no dependency overrides, fabricated HTTP actors, injected media runtimes or
substitute byte inventories. This is HTTP/transaction evidence, not a browser,
external identity-provider, Linux image or VPS acceptance claim.
"""

from __future__ import annotations

import hashlib
import importlib
import logging
import os
import re
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, unquote, urlsplit
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select

from ac_platform.audit import AuditRepository
from ac_platform.audit.models import AuditEvent
from ac_platform.identity.application import AsyncIdentityApplication
from ac_platform.learning.models import (
    ActivityProgress,
    EvidenceSubmission,
    LearningEvidence,
    PlaybackSession,
    VideoWatchInterval,
)
from ac_platform.media.models import MediaPlaybackGrant
from tests.integration.test_public_film_delivery_postgresql import ORIGIN, _learner
from tests.integration.test_public_film_delivery_postgresql import actual_pack as actual_pack
from tests.integration.test_public_film_import_postgresql import (
    PEPPER,
    RELEASE,
    import_once,
    scenario,
)
from tests.integration.test_staging_seed_postgresql import _run_async
from tests.integration.test_staging_seed_postgresql import postgres_harness as postgres_harness
from tests.unit.media.test_public_film_settings import public_film_settings


def _check(condition: bool, message: str) -> None:
    # Pytest expression expansion must never include cookies or signed URLs.
    __tracebackhide__ = True
    if not condition:
        pytest.fail(message, pytrace=False)


@pytest.fixture(autouse=True)
def _safe_http_logs(caplog):
    # HTTPX's normal INFO request line includes the private token query. The app
    # keeps its normal request middleware (which logs path, never query/cookie).
    caplog.set_level(logging.WARNING, logger="httpx")


@pytest.fixture(scope="module", autouse=True)
def _required_target():
    if os.getenv("AC_REQUIRE_PUBLIC_FILMS_PLAYBACK_TEST") == "1" and not (
        os.getenv("AC_TEST_DATABASE_URL") or os.getenv("AC_STAGING_SEED_POSTGRES_TEST_URL")
    ):
        pytest.fail("The required public-film HTTP PostgreSQL target is not configured")


async def _request(client, method, target, *, expected=200, **kwargs):
    __tracebackhide__ = True
    try:
        response = await client.request(method, target, **kwargs)
    except Exception:
        pytest.fail("The isolated ASGI request failed before a response", pytrace=False)
    _check(
        response.status_code == expected,
        f"ASGI {method} expected status {expected}; received {response.status_code}",
    )
    return response


def _json(response):
    __tracebackhide__ = True
    try:
        value = response.json()
    except ValueError:
        pytest.fail("The ASGI response is not valid JSON", pytrace=False)
    _check(isinstance(value, dict), "The ASGI response is not a JSON object")
    return value


def _signed_key(value):
    __tracebackhide__ = True
    _check(isinstance(value, str), "A required delivery URL is absent")
    parsed = urlsplit(value)
    _check(
        f"{parsed.scheme}://{parsed.netloc}" == ORIGIN
        and parsed.path.startswith("/v1/media/playback/")
        and not parsed.fragment
        and set(parse_qs(parsed.query)) == {"token"}
        and len(parse_qs(parsed.query)["token"]) == 1,
        "Delivery must be a signed same-origin playback route",
    )
    return unquote(parsed.path.removeprefix("/v1/media/playback/"))


@asynccontextmanager
async def _http_scenario(schema_url, pack, monkeypatch):
    async with scenario(schema_url, pack) as h:
        imported = await import_once(h)
        _check(imported.status == "imported", "The canonical film import did not commit")
        learner = await _learner(h)
        person_id = learner.actors["learner"].person_id
        foreign_tenant = learner.actors["other_tenant"].tenant_id
        settings = public_film_settings(
            Path(os.environ["AC_PUBLIC_FILMS_POSTGRES_PACK_ROOT"]),
            release_id=RELEASE,
            public_learner_tenant_id=pack.tenant_id,
            session_token_pepper=PEPPER,
        )
        app_module = importlib.import_module("ac_platform.http.app")
        with monkeypatch.context() as patched:
            patched.setattr(app_module, "settings", settings)
            patched.setattr(app_module, "session_factory", h.sessions)
            app = app_module.create_app()
            _check(not app.dependency_overrides, "Authentication must not be overridden")
            async with AsyncExitStack() as stack:
                clients = {}
                for name in ("learner", "other_session", "other_tenant", "anonymous"):
                    client = await stack.enter_async_context(
                        httpx.AsyncClient(
                            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                            base_url=ORIGIN,
                            headers={"Origin": ORIGIN},
                            follow_redirects=False,
                        )
                    )
                    clients[name] = client
                    if name == "anonymous":
                        continue
                    # This is canonical session issuance for an explicitly
                    # verified synthetic identity, not a fake HTTP auth actor.
                    async with h.sessions() as database, database.begin():
                        issued = await AsyncIdentityApplication(
                            database, token_pepper=PEPPER
                        ).issue_authenticated_session(person_id)
                    client.cookies.set(
                        settings.session_cookie_name,
                        issued.token,
                        domain=urlsplit(ORIGIN).hostname,
                        path="/",
                    )
                    tenant_id = foreign_tenant if name == "other_tenant" else pack.tenant_id
                    selected = _json(
                        await _request(
                            client, "POST", "/v1/context", json={"tenant_id": str(tenant_id)}
                        )
                    )
                    _check(
                        selected.get("person_id") == str(person_id)
                        and selected.get("session_id") == str(issued.metadata.id)
                        and selected.get("tenant_id") == str(tenant_id),
                        "Normal context selection did not retain the canonical identity/session",
                    )
                    me = _json(await _request(client, "GET", "/v1/me"))
                    _check(
                        me.get("person_id") == str(person_id)
                        and me.get("selected_tenant_id") == str(tenant_id)
                        and me.get("membership_role") == "learner",
                        "The HTTP fixture must remain a real selected learner session",
                    )
                yield SimpleNamespace(
                    database=h,
                    app=app,
                    clients=clients,
                    learner=learner,
                    imported=imported,
                    session_cookie_name=settings.session_cookie_name,
                )


async def _activity(proof, *, index=0, client_name="learner"):
    h = proof.database
    clip = h.pack.clips[index]
    response = await _request(
        proof.clients[client_name], "GET", f"/v1/activities/{h.catalog.activity_ids[index]}"
    )
    body = _json(response)
    _check(
        body.get("program_version_id") == str(h.catalog.program_version_id)
        and body.get("enrollment_id") == str(proof.learner.enrollment.enrollment_id)
        and body.get("required") is False
        and body.get("allowed_actions") == ["save_draft"],
        "Demo descriptor must retain its enrollment and optional activity without Watch completion",
    )
    media = body.get("media")
    _check(isinstance(media, dict), "The activity has no media descriptor")
    _check(
        media.get("state") == "approved"
        and media.get("playback_available") is True
        and media.get("binding_id") == str(proof.imported.binding_ids[index])
        and media.get("media_version_id") == str(clip.version_id)
        and media.get("width") == clip.spec.width
        and media.get("height") == clip.spec.height
        and media.get("duration_seconds") == clip.spec.duration_seconds,
        "The HTTP descriptor does not match the approved pinned media binding",
    )
    _check(response.headers.get("cache-control") == "no-store", "Descriptor must not cache")
    delivery = media.get("delivery")
    _check(isinstance(delivery, dict), "The descriptor has no delivery projection")
    _check(delivery.get("protocol") == "hls", "The pinned source must expose HLS")
    for value in (delivery.get("manifest_url"), delivery.get("progressive_url")):
        _signed_key(value)
    _check(len(media.get("captions", [])) == 1, "The pinned caption is missing or duplicated")
    _signed_key(media["captions"][0].get("source_url"))
    return response, body


async def _media(client, method, url, *, expected=200, **kwargs):
    _signed_key(url)
    response = await _request(client, method, url, expected=expected, **kwargs)
    if expected in (200, 206):
        _check(
            response.headers.get("cache-control") == "private, no-store",
            "Private media must not enter a reusable cache",
        )
        _check(
            response.headers.get("access-control-allow-origin") == ORIGIN,
            "Media must retain exact-origin CORS",
        )
    return response


def _playlist_children(response):
    _check(response.content.startswith(b"#EXTM3U"), "The HLS response is not a manifest")
    return [line for line in response.text.splitlines() if line and not line.startswith("#")]


def _matches_object(response, expected):
    _check(
        len(response.content) == expected.content_length
        and hashlib.sha256(response.content).hexdigest() == expected.sha256
        and response.headers.get("content-type", "").split(";", 1)[0] == expected.content_type,
        "The HTTP object bytes/MIME differ from the immutable pack inventory",
    )


def test_real_asgi_descriptors_and_actual_hls_progressive_caption_bytes(
    postgres_harness, actual_pack, monkeypatch
):
    async def run():
        async with _http_scenario(postgres_harness, actual_pack, monkeypatch) as proof:
            client = proof.clients["learner"]
            for index, clip in enumerate(actual_pack.clips):
                _, body = await _activity(proof, index=index)
                media = body["media"]
                delivery = media["delivery"]
                inventory = {
                    f"{clip.source_key}/renditions/{item.path.split('/', 1)[1]}": item
                    for item in clip.spec.objects
                }
                master = await _media(client, "GET", delivery["manifest_url"])
                master_head = await _media(client, "HEAD", delivery["manifest_url"])
                _check(
                    not master_head.content
                    and master_head.headers.get("content-length") == str(len(master.content)),
                    "The real manifest HEAD must match GET metadata without a body",
                )
                variants = _playlist_children(master)
                _check(len(variants) == (3 if index == 0 else 2), "An HLS quality is missing")
                subtitle_playlists = re.findall(
                    r'^#EXT-X-MEDIA:.*URI="([^"]+)"', master.text, re.MULTILINE
                )
                _check(len(subtitle_playlists) == 1, "The HLS subtitle playlist is missing")
                playlists = variants + subtitle_playlists
                playlist_keys = [_signed_key(url) for url in playlists]
                _check(
                    len(set(playlist_keys)) == len(playlist_keys)
                    and set(playlist_keys)
                    == {
                        key
                        for key, item in inventory.items()
                        if item.path.endswith(".m3u8") and not item.path.endswith("/master.m3u8")
                    },
                    "The HLS graph must contain every exact pinned playlist once",
                )
                observed_fragments = set()
                for child in playlists:
                    playlist = await _media(client, "GET", child)
                    fragments = _playlist_children(playlist)
                    _check(bool(fragments), "The actual HLS playlist has no fragments")
                    fragment_keys = [_signed_key(url) for url in fragments]
                    _check(
                        len(fragment_keys) == len(set(fragment_keys))
                        and set(fragment_keys)
                        == {
                            key
                            for key, item in inventory.items()
                            if key.rsplit("/", 1)[0] == _signed_key(child).rsplit("/", 1)[0]
                            and item.content_type in {"video/mp2t", "text/vtt"}
                        },
                        "The HLS playlist must contain every exact pinned fragment once",
                    )
                    for fragment in fragments:
                        key = _signed_key(fragment)
                        observed_fragments.add(key)
                        _check(key in inventory, "An HLS fragment escaped the pinned inventory")
                        _matches_object(await _media(client, "GET", fragment), inventory[key])
                _check(
                    observed_fragments
                    == {
                        key
                        for key, item in inventory.items()
                        if item.content_type in {"video/mp2t", "text/vtt"}
                    },
                    "The actual HTTP graph did not deliver all pinned TS/VTT fragments",
                )

                progressive = await _media(client, "GET", delivery["progressive_url"])
                progressive_item = inventory[_signed_key(delivery["progressive_url"])]
                _matches_object(progressive, progressive_item)
                head = await _media(client, "HEAD", delivery["progressive_url"])
                _check(
                    not head.content
                    and head.headers.get("content-length") == str(len(progressive.content))
                    and head.headers.get("content-type") == progressive.headers["content-type"],
                    "Progressive HEAD must report the actual GET metadata without bytes",
                )
                ranged = await _media(
                    client,
                    "GET",
                    delivery["progressive_url"],
                    expected=206,
                    headers={"Range": "bytes=0-4095"},
                )
                _check(
                    ranged.content == progressive.content[:4096]
                    and ranged.headers.get("content-range")
                    == f"bytes 0-4095/{len(progressive.content)}",
                    "The real progressive route did not return the exact requested range",
                )
                caption_url = media["captions"][0]["source_url"]
                caption = await _media(client, "GET", caption_url)
                _matches_object(caption, inventory[_signed_key(caption_url)])
                _check(caption.content.startswith(b"WEBVTT"), "The caption is not actual VTT")
                caption_head = await _media(client, "HEAD", caption_url)
                _check(
                    not caption_head.content
                    and caption_head.headers.get("content-length") == str(len(caption.content)),
                    "Caption HEAD must report the actual private VTT length",
                )

    _run_async(run())


def test_real_asgi_session_binding_and_absent_watch_policy(
    postgres_harness, actual_pack, monkeypatch
):
    async def run():
        async with _http_scenario(postgres_harness, actual_pack, monkeypatch) as proof:
            response, body = await _activity(proof)
            h = proof.database
            activity_path = f"/v1/activities/{h.catalog.activity_ids[0]}"
            media = body["media"]
            urls = (
                media["delivery"]["manifest_url"],
                media["delivery"]["progressive_url"],
                media["captions"][0]["source_url"],
            )
            for name, denied in (("anonymous", 401), ("other_session", 403), ("other_tenant", 403)):
                for url in urls:
                    for method in ("GET", "HEAD"):
                        await _media(proof.clients[name], method, url, expected=denied)
            await _request(proof.clients["anonymous"], "GET", activity_path, expected=401)
            await _request(proof.clients["other_tenant"], "GET", activity_path, expected=404)
            # The second session is not globally blocked: its own descriptor
            # grants work, but neither authenticated session may reuse the other's.
            _, other = await _activity(proof, client_name="other_session")
            other_url = other["media"]["delivery"]["manifest_url"]
            await _media(proof.clients["other_session"], "GET", other_url)
            await _media(proof.clients["learner"], "GET", other_url, expected=403)
            await _media(
                proof.clients["learner"],
                "GET",
                urls[0],
                expected=403,
                headers={"Origin": "https://untrusted.example.test"},
            )

            client = proof.clients["learner"]
            pre_logout_token = client.cookies.get(proof.session_cookie_name)
            _check(
                isinstance(pre_logout_token, str) and bool(pre_logout_token),
                "The learner client must retain its pre-logout session cookie",
            )
            for action in ("start", "heartbeat", "finish"):
                await _request(
                    client,
                    "POST",
                    f"{activity_path}/playback/{action}",
                    expected=404,
                    headers={"If-Match": response.headers["etag"], "Idempotency-Key": str(uuid4())},
                    json={},
                )
            denied = await _request(
                client,
                "POST",
                f"{activity_path}/evidence",
                expected=403,
                headers={"If-Match": response.headers["etag"], "Idempotency-Key": str(uuid4())},
                json={"evidence_type": "video_watch", "payload": {}},
            )
            _check(
                _json(denied).get("code") == "activity_action_unavailable",
                "Evidence must be refused by the absent Watch action, not malformed input",
            )
            _, unchanged = await _activity(proof)
            _check(
                unchanged["revision"] == body["revision"]
                and unchanged["state"] == body["state"]
                and unchanged["allowed_actions"] == body["allowed_actions"] == ["save_draft"],
                "Byte delivery or refused evidence changed canonical learning state",
            )
            logout = await _request(client, "POST", "/v1/auth/logout", expected=204)
            _check(
                'ac_session=""' in logout.headers.get("set-cookie", ""),
                "Logout must clear the session cookie",
            )
            await _media(client, "GET", urls[0], expected=401)
            await _media(
                proof.clients["anonymous"],
                "GET",
                urls[0],
                expected=401,
                headers={"Cookie": f"{proof.session_cookie_name}={pre_logout_token}"},
            )
            async with h.sessions() as database, database.begin():
                for model in (
                    ActivityProgress,
                    PlaybackSession,
                    VideoWatchInterval,
                    LearningEvidence,
                    EvidenceSubmission,
                ):
                    count = await database.scalar(
                        select(func.count())
                        .select_from(model)
                        .where(model.tenant_id == actual_pack.tenant_id)
                    )
                    _check(count == 0, f"Read-only playback unexpectedly stored {model.__name__}")
                for model, extra in (
                    (MediaPlaybackGrant, ()),
                    (AuditEvent, (AuditEvent.action == "media.activity_delivery_granted",)),
                ):
                    count = await database.scalar(
                        select(func.count())
                        .select_from(model)
                        .where(model.tenant_id == actual_pack.tenant_id, *extra)
                    )
                    _check(
                        count == 2, "Only the two authenticated descriptor grants may be appended"
                    )
                chain = await AuditRepository(database).verify_chain(
                    tenant_id=actual_pack.tenant_id
                )
                _check(chain.valid, "HTTP delivery left an invalid canonical audit chain")

    _run_async(run())
