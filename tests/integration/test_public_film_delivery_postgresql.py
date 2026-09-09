"""Actual pinned film bytes + migrated PostgreSQL, not a browser/VPS claim.

Run with AC_TEST_DATABASE_URL and AC_PUBLIC_FILMS_POSTGRES_PACK_ROOT. The
shared harness creates/drops only a fresh random schema. No existing learner
data, deployed policy, source film, or manifest is changed by this proof.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, unquote, urlsplit
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from ac_platform.audit import AuditRepository
from ac_platform.audit.models import AuditEvent
from ac_platform.enrollment.models import Enrollment, EnrollmentEligibilityFact, Entitlement
from ac_platform.enrollment.services import AsyncEnrollmentApplication, FreeEnrollmentCommand
from ac_platform.identity.application import AsyncIdentityApplication
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.learning.catalog_activity import resolve_catalog_activity
from ac_platform.learning.models import ActivityProgress, PlaybackSession
from ac_platform.learning.services import SqlAlchemyLearningRepository
from ac_platform.media import public_film_manifest as manifest
from ac_platform.media.errors import MediaForbidden
from ac_platform.media.models import MediaPlaybackGrant
from ac_platform.media.runtime import create_default_media_runtime
from ac_platform.tenancy.models import Membership, Tenant
from tests.integration.test_public_film_import_postgresql import (
    PEPPER,
    RELEASE,
    import_once,
    scenario,
)
from tests.integration.test_staging_seed_postgresql import _run_async
from tests.integration.test_staging_seed_postgresql import postgres_harness as postgres_harness
from tests.unit.media.test_public_film_settings import public_film_settings

ORIGIN = "https://learner.authorityclosers.com"


@pytest.fixture(scope="module", autouse=True)
def required_database():
    if os.getenv("AC_REQUIRE_PUBLIC_FILMS_PLAYBACK_TEST") == "1" and not (
        os.getenv("AC_TEST_DATABASE_URL") or os.getenv("AC_STAGING_SEED_POSTGRES_TEST_URL")
    ):
        pytest.fail("The required actual-film PostgreSQL target is not configured")


@pytest.fixture
def actual_pack():
    raw = os.getenv("AC_PUBLIC_FILMS_POSTGRES_PACK_ROOT")
    if not raw:
        if os.getenv("AC_REQUIRE_PUBLIC_FILMS_PLAYBACK_TEST") == "1":
            pytest.fail("The required actual public-film byte package is not configured")
        pytest.skip("Actual public-film byte package is not configured")
    # No manifest patching, generated pseudo-video, or network acquisition.
    return manifest.load_verified_public_film_pack(
        environment="test",
        release_id=RELEASE,
        tenant_id=uuid4(),
        root=Path(raw),
        expected_manifest_sha256=manifest.MANIFEST_SHA256,
    )


async def _learner(h):
    person_id, other_tenant = uuid4(), uuid4()
    now = datetime.now(UTC)
    tokens = {
        name: secrets.token_urlsafe(32) for name in ("learner", "other_session", "other_tenant")
    }
    session_ids = {name: uuid4() for name in tokens}
    async with h.sessions() as database, database.begin():
        database.add_all(
            [
                Person(
                    id=person_id, email=f"film-{person_id.hex}@example.test", email_verified_at=now
                ),
                Tenant(
                    id=other_tenant,
                    slug=f"film-other-{other_tenant.hex}",
                    name="Other test academy",
                ),
            ]
        )
        await database.flush()
        database.add_all(
            [
                Membership(person_id=person_id, tenant_id=tenant, role="learner")
                for tenant in (h.pack.tenant_id, other_tenant)
            ]
        )
        await database.flush()
        for name, token in tokens.items():
            database.add(
                IdentitySession(
                    id=session_ids[name],
                    person_id=person_id,
                    selected_tenant_id=other_tenant if name == "other_tenant" else h.pack.tenant_id,
                    token_hash=hmac.new(PEPPER.encode(), token.encode(), hashlib.sha256).digest(),
                    created_at=now - timedelta(minutes=1),
                    expires_at=now + timedelta(hours=1),
                )
            )
        # Test-only eligibility is separate from importing/publishing the films.
        database.add(
            EnrollmentEligibilityFact(
                tenant_id=h.pack.tenant_id,
                person_id=person_id,
                program_version_id=h.catalog.program_version_id,
                program_id=h.catalog.program_id,
                program_scope="tenant",
                program_tenant_id=h.pack.tenant_id,
                program_owner_key=h.pack.tenant_id,
                age_gate_passed=True,
                eligibility_passed=True,
                prerequisites_satisfied=True,
                policy_version="isolated-public-film-playback-test",
                evidence={"test_only": True},
                evaluated_at=now,
            )
        )
    actors = {}
    for name, token in tokens.items():
        async with h.sessions() as database, database.begin():
            actors[name] = (
                await AsyncIdentityApplication(database, token_pepper=PEPPER).resolve_actor(
                    token, require_tenant=True
                )
            ).actor
            assert not actors[name].permissions
    async with h.sessions() as database, database.begin():
        enrollment = await AsyncEnrollmentApplication(database).enroll_free(
            FreeEnrollmentCommand(
                actor_person_id=person_id,
                subject_person_id=person_id,
                tenant_id=h.pack.tenant_id,
                program_version_id=h.catalog.program_version_id,
                idempotency_key=f"test-{uuid4()}",
            ),
            actor=actors["learner"],
        )
    return SimpleNamespace(actors=actors, enrollment=enrollment)


async def _descriptor(h, runtime, learner, index):
    actor = learner.actors["learner"]
    async with h.sessions() as database, database.begin():
        access = await database.run_sync(
            lambda sync: SqlAlchemyLearningRepository(
                sync,
                activity_resolver=resolve_catalog_activity,
                reviewer_resolver=lambda _: None,
                activity_media_resolver=runtime.activity_media_resolver,
            ).resolve_access(
                actor=actor,
                tenant_id=h.pack.tenant_id,
                enrollment_id=learner.enrollment.enrollment_id,
                program_version_id=h.catalog.program_version_id,
                activity_id=h.catalog.activity_ids[index],
            )
        )
        return await runtime.media_descriptor_resolver(database, actor, access)


def _signed_key(url):
    parsed = urlsplit(url)
    assert parsed.scheme == "https" and parsed.netloc == "learner.authorityclosers.com"
    assert parsed.path.startswith("/v1/media/playback/")
    return unquote(parsed.path.split("/playback/", 1)[1])


def _serve(sync, runtime, actor, url, **kwargs):
    parsed = urlsplit(url)
    token = parse_qs(parsed.query)["token"][0]
    handler = runtime.authenticated_delivery_handler_factory(sync, actor)
    result = handler.serve(
        token=token,
        token_type="playback",  # noqa: S106 - token kind, not a secret
        object_key=_signed_key(url),
        origin=ORIGIN,
        **kwargs,
    )
    # Consume streaming bodies too; metadata/status alone does not prove bytes.
    return result, b"".join(result.body or ())


async def _request(h, runtime, actor, url, **kwargs):
    async with h.sessions() as database, database.begin():
        return await database.run_sync(lambda sync: _serve(sync, runtime, actor, url, **kwargs))


def test_actual_public_films_import_publish_deliver_and_deny_revoked_access(
    postgres_harness, actual_pack
):
    async def run():
        async with scenario(postgres_harness, actual_pack) as h:
            first = await import_once(h)
            assert first.status == "imported"
            assert (await import_once(h)).binding_ids == first.binding_ids
            async with h.sessions() as database, database.begin():
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(Enrollment)
                        .where(Enrollment.tenant_id == h.pack.tenant_id)
                    )
                    == 0
                )  # Publishing never silently grants learners access.
            learner = await _learner(h)
            settings = public_film_settings(
                Path(os.environ["AC_PUBLIC_FILMS_POSTGRES_PACK_ROOT"]),
                release_id=RELEASE,
                public_learner_tenant_id=h.pack.tenant_id,
                session_token_pepper=PEPPER,
            )
            runtime = create_default_media_runtime(settings)
            assert (
                runtime.playback_policy_resolver is None and not runtime.learning_playback_composed
            )
            actor = learner.actors["learner"]
            descriptors = []
            for index, clip in enumerate(h.pack.clips):
                descriptor = await _descriptor(h, runtime, learner, index)
                descriptors.append(descriptor)
                assert descriptor.playback_available and descriptor.state == "approved"
                assert (descriptor.width, descriptor.height) == (
                    (3840, 2160) if index == 0 else (1920, 1080)
                )
                assert descriptor.duration_seconds == pytest.approx(12.032)
                assert descriptor.delivery.manifest_url and descriptor.delivery.progressive_url
                # Each URL has a fresh nonce. An ordinary reread must nevertheless
                # share the current persisted grant and not append an issue audit.
                await _descriptor(h, runtime, learner, index)
                async with h.sessions() as database, database.begin():
                    for model, predicates in (
                        (MediaPlaybackGrant, ()),
                        (AuditEvent, (AuditEvent.action == "media.activity_delivery_granted",)),
                    ):
                        assert (
                            await database.scalar(
                                select(func.count())
                                .select_from(model)
                                .where(
                                    model.tenant_id == h.pack.tenant_id,
                                    *predicates,
                                )
                            )
                            == index + 1
                        )
                inventory = {
                    f"{clip.source_key}/renditions/{item.path.split('/', 1)[1]}": item
                    for item in clip.spec.objects
                }
                result, master = await _request(h, runtime, actor, descriptor.delivery.manifest_url)
                assert result.status_code == 200 and master.startswith(b"#EXTM3U")
                assert result.headers["Cache-Control"] == "private, no-store"
                variants = [
                    line
                    for line in master.decode().splitlines()
                    if line and not line.startswith("#")
                ]
                assert len(variants) == (3 if index == 0 else 2)
                subtitle_playlists = re.findall(
                    r'^#EXT-X-MEDIA:.*URI="([^"]+)"', master.decode(), re.MULTILINE
                )
                assert len(subtitle_playlists) == 1
                playlists = variants + subtitle_playlists
                playlist_keys = [_signed_key(url) for url in playlists]
                assert len(set(playlist_keys)) == len(playlist_keys)
                assert set(playlist_keys) == {
                    key
                    for key, item in inventory.items()
                    if item.path.endswith(".m3u8") and not item.path.endswith("/master.m3u8")
                }
                observed_segments = set()
                for variant in playlists:
                    result, playlist = await _request(h, runtime, actor, variant)
                    assert result.status_code == 200 and b"#EXT-X-ENDLIST" in playlist
                    segments = [
                        line
                        for line in playlist.decode().splitlines()
                        if line and not line.startswith("#")
                    ]
                    segment_keys = [_signed_key(url) for url in segments]
                    assert len(segment_keys) == len(set(segment_keys))
                    assert set(segment_keys) == {
                        key
                        for key, item in inventory.items()
                        if key.rsplit("/", 1)[0] == _signed_key(variant).rsplit("/", 1)[0]
                        and item.content_type in {"video/mp2t", "text/vtt"}
                    }
                    for segment in segments:
                        result, body = await _request(h, runtime, actor, segment)
                        key = _signed_key(segment)
                        observed_segments.add(key)
                        assert (
                            result.status_code == 200
                            and body
                            and len(body) == result.content_length
                        )
                        assert hashlib.sha256(body).hexdigest() == inventory[key].sha256
                assert observed_segments == {
                    key
                    for key, item in inventory.items()
                    if item.content_type in {"video/mp2t", "text/vtt"}
                }
                result, progressive = await _request(
                    h, runtime, actor, descriptor.delivery.progressive_url
                )
                expected_progressive = next(
                    item for item in clip.spec.objects if item.path == clip.spec.progressive_path
                )
                assert (
                    result.status_code == 200
                    and len(progressive) == expected_progressive.content_length
                )
                assert hashlib.sha256(progressive).hexdigest() == expected_progressive.sha256
                result, body = await _request(
                    h,
                    runtime,
                    actor,
                    descriptor.delivery.progressive_url,
                    range_header="bytes=0-1023",
                )
                assert result.status_code == 206 and len(body) == 1024 and b"ftyp" in body[:32]
                assert body == progressive[:1024]
                assert result.headers["Content-Range"].startswith("bytes 0-1023/")
                result, body = await _request(
                    h,
                    runtime,
                    actor,
                    descriptor.delivery.progressive_url,
                    range_header=f"bytes={expected_progressive.content_length - 1024}-",
                )
                assert result.status_code == 206 and len(body) == 1024
                assert body == progressive[-1024:]
                # Existing bounded policy deliberately supports single forward
                # ranges, not suffix or multipart requests.
                for rejected_range in ("bytes=-1024", "bytes=0-15,32-47"):
                    result, body = await _request(
                        h,
                        runtime,
                        actor,
                        descriptor.delivery.progressive_url,
                        range_header=rejected_range,
                    )
                    assert result.status_code == 416 and not body
                result, body = await _request(
                    h, runtime, actor, descriptor.delivery.progressive_url, method="HEAD"
                )
                assert result.status_code == 200 and not body and result.content_length > 1024
                assert len(descriptor.captions) == 1 and descriptor.captions[0].source_url
                result, caption = await _request(
                    h, runtime, actor, descriptor.captions[0].source_url
                )
                assert result.status_code == 200 and caption.startswith(b"WEBVTT")
                assert (
                    hashlib.sha256(caption).hexdigest()
                    == inventory[_signed_key(descriptor.captions[0].source_url)].sha256
                )
                with pytest.raises(MediaForbidden):
                    await _request(
                        h,
                        runtime,
                        actor,
                        descriptor.delivery.progressive_url,
                        now=datetime.now(UTC) + timedelta(minutes=6),
                    )
                for other in ("other_session", "other_tenant"):
                    with pytest.raises(MediaForbidden):
                        await _request(
                            h, runtime, learner.actors[other], descriptor.delivery.progressive_url
                        )
            url = descriptors[0].delivery.progressive_url
            # Mutations are confined to this disposable fixture and rolled back
            # individually. This is not an operational recovery path.
            for capability in ("session", "grant", "entitlement", "membership"):
                assert (await _request(h, runtime, actor, url, range_header="bytes=0-15"))[
                    0
                ].status_code == 206
                async with h.sessions() as database, database.begin():
                    if capability == "session":
                        row = await database.get(IdentitySession, actor.session_id)
                        row.revoked_at = datetime.now(UTC)
                    elif capability == "grant":
                        row = await database.scalar(
                            select(MediaPlaybackGrant).where(
                                MediaPlaybackGrant.tenant_id == h.pack.tenant_id,
                                MediaPlaybackGrant.version_id == h.pack.clips[0].version_id,
                            )
                        )
                        row.revoked_at = datetime.now(UTC)
                    elif capability == "entitlement":
                        row = await database.get(Entitlement, learner.enrollment.entitlement_id)
                        row.status = "revoked"
                    else:
                        row = await database.scalar(
                            select(Membership).where(
                                Membership.person_id == actor.person_id,
                                Membership.tenant_id == h.pack.tenant_id,
                            )
                        )
                        row.status = "inactive"
                        row.ended_at = datetime.now(UTC)
                    await database.flush()
                    with pytest.raises(MediaForbidden):
                        await database.run_sync(lambda sync: _serve(sync, runtime, actor, url))
                    await database.rollback()
                assert (await _request(h, runtime, actor, url, range_header="bytes=0-15"))[
                    0
                ].status_code == 206
            # Playback delivery must not create evidence or canonical completion.
            async with h.sessions() as database, database.begin():
                for model in (ActivityProgress, PlaybackSession):
                    assert (
                        await database.scalar(
                            select(func.count())
                            .select_from(model)
                            .where(model.tenant_id == h.pack.tenant_id)
                        )
                        == 0
                    )
                assert (await AuditRepository(database).verify(h.pack.tenant_id)).valid

    _run_async(run())
