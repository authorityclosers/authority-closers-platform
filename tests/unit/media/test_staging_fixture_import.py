"""Hermetic byte-contract and real ORM transaction tests, not codec/VPS proof.

Tiny structural media doubles replace only the package manifest in tests. The
deployed loader/CLI have no caller-manifest or byte-validation bypass.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain_sync
from ac_platform.catalog.models import Activity, ProgramVersion
from ac_platform.db.models import model_metadata
from ac_platform.enrollment.models import Enrollment
from ac_platform.identity.models import Person
from ac_platform.kernel.authz import ActorContext
from ac_platform.media import staging_fixture_manifest as manifest_module
from ac_platform.media.errors import (
    MediaConfigurationError,
    MediaConflict,
    MediaForbidden,
    MediaStorageUnavailable,
)
from ac_platform.media.models import (
    ActivityMediaBinding,
    MediaAsset,
    MediaCaptionTrack,
    MediaLifecycle,
    MediaPurpose,
    MediaRendition,
    MediaVersion,
)
from ac_platform.media.staging_fixture_import import (
    StagingFixtureImportApplication,
    _TenantStagingSeedApplication,
    main,
)
from ac_platform.media.staging_fixture_manifest import (
    MANIFEST_PATH,
    MANIFEST_SHA256,
    VerifiedFixtureProcessor,
    load_verified_staging_fixture_pack,
)
from ac_platform.media.storage import UnconfiguredPrivateObjectStorage
from ac_platform.seed.application import StagingSeedApplication
from ac_platform.seed.technical_media_fixture_v2 import (
    FILM_ACTIVITY_PROMPTS,
    FILM_ACTIVITY_TITLES,
    technical_media_identity,
    technical_media_seed,
)
from ac_platform.seed.technical_validation_fixture import technical_validation_seed
from ac_platform.tenancy.models import Membership, Tenant

RELEASE = "a" * 40


class AsyncDatabase:
    """Async application facade over a real SQLite Session/transaction/savepoint."""

    def __init__(self, session: Session) -> None:
        self.session = session

    @asynccontextmanager
    async def begin(self):
        with self.session.begin():
            yield self

    @asynccontextmanager
    async def begin_nested(self):
        with self.session.begin_nested():
            yield self

    def get_transaction(self):
        transaction = self.session.get_transaction()
        return None if transaction is None else SimpleNamespace(sync_transaction=transaction)

    def get_bind(self):
        return self.session.get_bind()

    async def scalar(self, statement):
        return self.session.scalar(statement)

    async def scalars(self, statement):
        return self.session.scalars(statement)

    async def execute(self, statement):
        return self.session.execute(statement)

    async def run_sync(self, operation):
        return operation(self.session)

    async def flush(self):
        self.session.flush()

    def add(self, row):
        self.session.add(row)


@pytest.fixture
def artifact_factory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    original = json.loads(MANIFEST_PATH.read_bytes())

    def make(*, mutate=None, tenant_id=None):
        root = tmp_path / str(uuid4())
        root.mkdir()
        payload = json.loads(json.dumps(original))
        for clip in payload["clips"]:
            directory = clip["progressive_path"].split("/", 1)[0]
            video = b"\x00\x00\x00\x18ftypisom" + b"STRUCTURAL_TEST_ONLY" * 8
            probe = {
                "streams": [
                    {
                        "codec_type": "video",
                        "codec_name": "h264",
                        "width": clip["width"],
                        "height": clip["height"],
                        "r_frame_rate": clip["fps"],
                        "duration": "12.000000",
                    },
                    {"codec_type": "audio", "codec_name": "aac", "duration": "12.032000"},
                ],
                "format": {"duration": "12.032000", "size": str(len(video))},
            }
            files = {
                "progressive.mp4": video,
                "probe.json": json.dumps(probe).encode(),
                "hls/master.m3u8": (
                    b'#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",'
                    b'NAME="English",LANGUAGE="en",URI="captions/stress-en.m3u8"\n'
                    b'#EXT-X-STREAM-INF:BANDWIDTH=1000000,SUBTITLES="subs"\n360p/index.m3u8\n'
                ),
                "hls/360p/index.m3u8": (
                    b"#EXTM3U\n#EXT-X-TARGETDURATION:4\n#EXT-X-MEDIA-SEQUENCE:0\n"
                    b"#EXTINF:4,\n000.ts\n#EXTINF:4,\n001.ts\n#EXTINF:4,\n002.ts\n"
                    b"#EXT-X-ENDLIST\n"
                ),
                "hls/360p/000.ts": b"TEST ONLY TS 0",
                "hls/360p/001.ts": b"TEST ONLY TS 1",
                "hls/360p/002.ts": b"TEST ONLY TS 2",
                "hls/captions/stress-en.m3u8": (
                    b"#EXTM3U\n#EXT-X-TARGETDURATION:12\n#EXT-X-MEDIA-SEQUENCE:0\n"
                    b"#EXTINF:12,\nstress-en.vtt\n#EXT-X-ENDLIST\n"
                ),
                "hls/captions/stress-en.vtt": (
                    b"WEBVTT\n\n00:00:00.000 --> 00:00:12.000\n"
                    b"Synthetic test cue, not film dialogue.\n"
                ),
            }
            if mutate:
                mutate(clip, files)
            clip["objects"] = []
            for relative, body in files.items():
                path = f"{directory}/{relative}"
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(body)
                clip["objects"].append(
                    {
                        "path": path,
                        "content_type": manifest_module._MEDIA_TYPES[target.suffix],
                        "content_length": len(body),
                        "sha256": hashlib.sha256(body).hexdigest(),
                    }
                )
        raw = json.dumps(payload).encode()
        manifest = root / "test-only-manifest.json"
        manifest.write_bytes(raw)
        digest = hashlib.sha256(raw).hexdigest()
        monkeypatch.setattr(manifest_module, "MANIFEST_PATH", manifest)
        monkeypatch.setattr(manifest_module, "MANIFEST_SHA256", digest)
        return SimpleNamespace(
            root=root,
            payload=payload,
            manifest=manifest,
            digest=digest,
            tenant_id=tenant_id or uuid4(),
        )

    return make


def load(artifact):
    return load_verified_staging_fixture_pack(
        environment="test",
        release_id=RELEASE,
        tenant_id=artifact.tenant_id,
        root=artifact.root,
        expected_manifest_sha256=artifact.digest,
    )


@pytest.fixture
async def harness(artifact_factory):
    artifact = artifact_factory()
    pack = load(artifact)
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    model_metadata().create_all(engine)
    database = Session(engine, expire_on_commit=False)
    actor_id = uuid4()
    with database.begin():
        database.add(Person(id=actor_id))
        database.add(Tenant(id=artifact.tenant_id, slug=f"test-{artifact.tenant_id}", name="Test"))
        database.flush()
        database.add(Membership(tenant_id=artifact.tenant_id, person_id=actor_id, role="owner"))
    async_database = AsyncDatabase(database)
    actor = ActorContext(actor_id, uuid4(), None)
    old_seed = technical_validation_seed(RELEASE)
    old = await StagingSeedApplication(
        async_database,
        environment="test",
        expected_release_id=RELEASE,
    ).apply_technical_validation(old_seed, actor=actor)
    with database.begin():
        enrollment = Enrollment(
            id=uuid4(),
            tenant_id=artifact.tenant_id,
            person_id=actor_id,
            program_id=old.program_id,
            program_version_id=old.program_version_id,
            program_scope="global",
            program_tenant_id=None,
            program_owner_key=UUID(int=0),
            source="free_self",
            status="active",
        )
        database.add(enrollment)
    published = await _TenantStagingSeedApplication(
        async_database,
        environment="test",
        release_id=RELEASE,
        tenant_id=pack.tenant_id,
    ).apply_technical_validation(technical_media_seed(RELEASE), actor=actor)
    application = StagingFixtureImportApplication(
        async_database,
        environment="test",
        release_id=RELEASE,
        pack=pack,
    )
    yield SimpleNamespace(
        artifact=artifact,
        pack=pack,
        database=database,
        async_database=async_database,
        actor_id=actor_id,
        actor=ActorContext(
            actor_id, uuid4(), pack.tenant_id, permissions=frozenset({"catalog_write"})
        ),
        old=old,
        published=published,
        old_enrollment_id=enrollment.id,
        app=application,
    )
    database.close()
    engine.dispose()


async def apply(h):
    return await h.app.apply(
        actor_person_id=h.actor_id, expected_catalog_version_id=h.published.program_version_id
    )


def test_baked_manifest_digest_and_real_two_film_inventory_are_pinned():
    raw = MANIFEST_PATH.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == MANIFEST_SHA256
    manifest = manifest_module.StagingFixtureManifest.model_validate_json(raw)
    assert [(clip.width, clip.height, clip.duration_seconds) for clip in manifest.clips] == [
        (3840, 2160, 12.032),
        (1920, 1080, 12.032),
    ]
    assert sum(len(clip.objects) for clip in manifest.clips) == 30


def test_pack_loads_only_verified_bytes_with_exact_metadata(artifact_factory):
    artifact = artifact_factory()
    pack = load(artifact)
    assert len(pack.clips) == 2
    for clip in pack.clips:
        assert clip.processing_result.duration_seconds == 12.032
        assert len(clip.processing_result.renditions) == 2
        assert clip.processing_result.captions[0].is_default
        assert all(
            key.startswith(clip.source_key + "/renditions/")
            for key in clip.processing_result.object_keys
        )


@pytest.mark.parametrize("environment", ["production", "local", "development", "", "STAGING"])
def test_environment_is_rejected_before_any_filesystem_io(environment, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("filesystem touched before deployment guard")

    monkeypatch.setattr(Path, "read_bytes", unexpected)
    with pytest.raises(MediaConfigurationError):
        load_verified_staging_fixture_pack(
            environment=environment,
            release_id=RELEASE,
            tenant_id=uuid4(),
            root=Path("/nonexistent"),
            expected_manifest_sha256=MANIFEST_SHA256,
        )


@pytest.mark.parametrize(
    "change", ["source", "duration", "dimensions", "graph", "timeline", "mime"]
)
def test_manifest_and_measured_inventory_fail_closed(artifact_factory, change):
    def mutate(clip, files):
        if change == "source":
            clip["source_sha256"] = "f" * 64
        elif change == "duration":
            probe = json.loads(files["probe.json"])
            probe["format"]["duration"] = "12.4"
            files["probe.json"] = json.dumps(probe).encode()
        elif change == "dimensions":
            probe = json.loads(files["probe.json"])
            probe["streams"][0]["width"] = 640
            files["probe.json"] = json.dumps(probe).encode()
        elif change == "graph":
            files["hls/unused.ts"] = b"not reachable"
        elif change == "timeline":
            files["hls/360p/index.m3u8"] = files["hls/360p/index.m3u8"].replace(
                b"#EXTINF:4", b"#EXTINF:3"
            )
        elif change == "mime":
            clip["width"] = 640

    with pytest.raises((MediaConfigurationError, ValueError)):
        load(artifact_factory(mutate=mutate))


def test_caller_digest_and_modified_artifact_cannot_reauthorize_bytes(artifact_factory):
    artifact = artifact_factory()
    with pytest.raises(MediaConfigurationError, match="manifest hash"):
        load_verified_staging_fixture_pack(
            environment="test",
            release_id=RELEASE,
            tenant_id=artifact.tenant_id,
            root=artifact.root,
            expected_manifest_sha256="f" * 64,
        )
    artifact.manifest.write_bytes(artifact.manifest.read_bytes() + b" ")
    with pytest.raises(MediaConfigurationError, match="manifest bytes"):
        load(artifact)


def test_sealed_pack_cannot_be_reused_for_other_actor_scope_or_processor(artifact_factory):
    pack = load(artifact_factory())
    for scope in ({"tenant_id": uuid4()}, {"release_id": "b" * 40}, {"environment": "production"}):
        kwargs = {"environment": "test", "release_id": RELEASE, "tenant_id": pack.tenant_id} | scope
        with pytest.raises(MediaConfigurationError):
            pack.require_scope(**kwargs)
    with pytest.raises(MediaConfigurationError):
        replace(pack, _seal=object()).require_scope(
            environment="test",
            release_id=RELEASE,
            tenant_id=pack.tenant_id,
        )
    with pytest.raises(MediaConfigurationError):
        VerifiedFixtureProcessor(pack).process(
            storage=UnconfiguredPrivateObjectStorage(),
            version_id=pack.clips[0].version_id,
            purpose=MediaPurpose.VIDEO,
            source_key=pack.clips[0].source_key,
            content_type="video/mp4",
            crop=None,
        )


async def test_source_registration_stops_at_processing_and_never_claims_ready(harness):
    h = harness
    with h.database.begin():
        version = h.app.service.register_verified_staging_fixture_source(
            h.database,
            h.actor,
            h.pack,
            h.pack.clips[0].spec.fixture_id,
            environment="test",
            release_id=RELEASE,
        )
        assert version.state == MediaLifecycle.PROCESSING.value
        assert version.duration_seconds is None and version.width is None
        assert h.database.scalar(select(func.count()).select_from(MediaRendition)) == 0
        assert h.database.scalar(select(func.count()).select_from(ActivityMediaBinding)) == 0


async def test_atomic_import_and_replay_preserve_previous_catalog_and_enrollment(harness):
    h = harness
    first = await apply(h)
    second = await apply(h)
    assert first.status == "imported" and second.status == "already_imported"
    assert (
        first.binding_ids == second.binding_ids
        and first.media_version_ids == second.media_version_ids
    )
    with h.database.begin():
        assert h.database.scalar(select(func.count()).select_from(MediaAsset)) == 2
        assert h.database.scalar(select(func.count()).select_from(MediaVersion)) == 2
        assert h.database.scalar(select(func.count()).select_from(ActivityMediaBinding)) == 2
        assert h.database.scalar(select(func.count()).select_from(MediaRendition)) == 4
        assert h.database.scalar(select(func.count()).select_from(MediaCaptionTrack)) == 2
        assert h.database.scalar(select(func.count()).select_from(AuditEvent)) == 1
        assert (
            h.database.get(Enrollment, h.old_enrollment_id).program_version_id
            == h.old.program_version_id
        )
        assert h.database.get(ProgramVersion, h.old.program_version_id).status == "superseded"
        assert (
            h.database.get(ProgramVersion, first.catalog_version_id).supersedes_version_id
            == h.old.program_version_id
        )
        assert (
            h.database.get(ProgramVersion, first.catalog_version_id).content_seed_kind
            == "technical-validation"
        )
        audit = h.database.scalar(select(AuditEvent))
        assert audit.session_id is None and audit.actor_person_id == h.actor_id
        assert audit.payload["course_content"] is False
        assert verify_audit_chain_sync(h.database, h.pack.tenant_id).valid
        videos = h.database.scalars(
            select(Activity)
            .where(
                Activity.id.in_(technical_media_identity(RELEASE)[3]),
            )
            .order_by(Activity.position)
        ).all()
        assert tuple(item.title for item in videos) == FILM_ACTIVITY_TITLES
        assert tuple(item.prompt for item in videos) == FILM_ACTIVITY_PROMPTS
        assert all(
            "not Dipak instruction" in item.prompt and "creativecommons.org" in item.prompt
            for item in videos
        )


@pytest.mark.parametrize(
    "kind", ["learner", "inactive_person", "inactive_tenant", "ended", "other_tenant"]
)
async def test_persisted_authority_is_rechecked_not_caller_permissions(harness, kind):
    h = harness
    with h.database.begin():
        member = h.database.scalar(select(Membership).where(Membership.person_id == h.actor_id))
        if kind == "learner":
            member.role = "learner"
        elif kind == "inactive_person":
            h.database.get(Person, h.actor_id).status = "suspended"
        elif kind == "inactive_tenant":
            h.database.get(Tenant, h.pack.tenant_id).status = "suspended"
        elif kind == "ended":
            member.status = "inactive"
            member.ended_at = datetime.now(UTC)
        else:
            other = Tenant(id=uuid4(), slug="other", name="Other")
            h.database.add(other)
            h.database.flush()
            member.role = "learner"
            h.database.add(Membership(tenant_id=other.id, person_id=h.actor_id, role="owner"))
    with pytest.raises(MediaForbidden):
        await apply(h)
    with h.database.begin():
        assert h.database.scalar(select(func.count()).select_from(MediaAsset)) == 0


async def test_wrong_catalog_is_denied_without_any_media_state(harness):
    h = harness
    with pytest.raises(MediaForbidden):
        await h.app.apply(
            actor_person_id=h.actor_id, expected_catalog_version_id=h.old.program_version_id
        )
    with h.database.begin():
        assert h.database.scalar(select(func.count()).select_from(MediaAsset)) == 0


@pytest.mark.parametrize("failure", ["second_processing", "second_binding", "audit"])
async def test_any_late_failure_rolls_back_both_films_and_all_approvals(
    harness, monkeypatch, failure
):
    h = harness
    if failure == "audit":
        from ac_platform.audit import AuditRepository

        async def fail(*args, **kwargs):
            raise MediaConflict("test audit failure")

        monkeypatch.setattr(AuditRepository, "append", fail)
    else:
        method = "process_version" if failure == "second_processing" else "bind_activity_media"
        original = getattr(h.app.service, method)
        calls = 0

        def fail_second(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise MediaConflict("test second film failure")
            return original(*args, **kwargs)

        monkeypatch.setattr(h.app.service, method, fail_second)
    with pytest.raises(MediaConflict):
        await apply(h)
    with h.database.begin():
        for model in (
            MediaAsset,
            MediaVersion,
            MediaRendition,
            MediaCaptionTrack,
            ActivityMediaBinding,
            AuditEvent,
        ):
            assert h.database.scalar(select(func.count()).select_from(model)) == 0


@pytest.mark.parametrize("change", ["binding", "rendition", "caption", "version", "asset", "actor"])
async def test_replay_does_not_repair_revocation_or_drift(harness, change):
    h = harness
    result = await apply(h)
    with h.database.begin():
        if change == "binding":
            h.database.get(ActivityMediaBinding, result.binding_ids[0]).state = "revoked"
        elif change == "rendition":
            h.database.scalar(select(MediaRendition)).width = 1
        elif change == "caption":
            h.database.scalar(select(MediaCaptionTrack)).state = "retired"
        elif change == "version":
            h.database.get(MediaVersion, result.media_version_ids[0]).state = "retired"
        elif change == "asset":
            h.database.get(MediaAsset, h.pack.clips[0].asset_id).current_version_id = None
        else:
            person = Person(id=uuid4())
            h.database.add(person)
            h.database.flush()
            h.database.add(
                Membership(tenant_id=h.pack.tenant_id, person_id=person.id, role="owner")
            )
            h.actor_id = person.id
    with pytest.raises((MediaConflict, MediaForbidden)):
        await apply(h)
    with h.database.begin():
        assert h.database.scalar(select(func.count()).select_from(AuditEvent)) == 1
        assert h.database.scalar(select(func.count()).select_from(ActivityMediaBinding)) == 2


def test_cli_production_rejection_precedes_settings_database_or_file_access(monkeypatch, capsys):
    monkeypatch.setenv("AC_ENVIRONMENT", "production")
    assert (
        main(
            [
                "--actor-person-id",
                str(uuid4()),
                "--tenant-id",
                str(uuid4()),
                "--release-id",
                RELEASE,
                "--publish-catalog",
                "--acknowledge-staging-public-film-tests",
            ]
        )
        == 2
    )
    assert "refused" in capsys.readouterr().err


@pytest.mark.parametrize(
    "field,value",
    [
        ("production_enabled", True),
        ("course_content", True),
        ("fixture_registry_sha256", "f" * 64),
        ("unexpected_provider_url", "https://example.com/a"),
    ],
)
def test_manifest_rejects_activation_or_provenance_extensions(field, value):
    payload = json.loads(MANIFEST_PATH.read_bytes())
    payload[field] = value
    with pytest.raises(ValueError):
        manifest_module.StagingFixtureManifest.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize(
    "field,value",
    [
        ("path", "../outside.mp4"),
        ("path", "bbb-12s/./progressive.mp4"),
        ("path", "C:/outside.mp4"),
        ("content_type", "application/octet-stream"),
        ("content_length", True),
        ("content_length", 0),
        ("content_length", 128 * 1024**2 + 1),
        ("sha256", "f" * 63),
    ],
)
def test_manifest_inventory_paths_mime_bytes_and_hash_are_strict(field, value):
    payload = json.loads(MANIFEST_PATH.read_bytes())
    payload["clips"][0]["objects"][0][field] = value
    with pytest.raises(ValueError):
        manifest_module.StagingFixtureManifest.model_validate_json(json.dumps(payload))


async def test_changed_source_after_pack_load_fails_before_database_transaction(
    harness, monkeypatch
):
    h = harness
    target = h.artifact.root / h.pack.clips[1].spec.progressive_path
    target.write_bytes(target.read_bytes() + b"changed")

    def unexpected():
        pytest.fail("database transaction opened before every source was revalidated")

    monkeypatch.setattr(h.async_database, "begin", unexpected)
    with pytest.raises(MediaStorageUnavailable):
        await apply(h)
    assert not h.database.in_transaction()


async def test_partial_out_of_band_source_is_not_silently_adopted(harness):
    h = harness
    with h.database.begin():
        h.app.service.register_verified_staging_fixture_source(
            h.database,
            h.actor,
            h.pack,
            h.pack.clips[0].spec.fixture_id,
            environment="test",
            release_id=RELEASE,
        )
    with pytest.raises(MediaConflict, match="incomplete"):
        await apply(h)
    with h.database.begin():
        assert h.database.scalar(select(func.count()).select_from(MediaVersion)) == 1
        assert h.database.scalar(select(func.count()).select_from(ActivityMediaBinding)) == 0
        assert h.database.scalar(select(func.count()).select_from(AuditEvent)) == 0


async def test_new_seed_replay_is_canonical_and_exact_tenant_guard_runs_on_replay(harness):
    h = harness
    command = _TenantStagingSeedApplication(
        h.async_database,
        environment="test",
        release_id=RELEASE,
        tenant_id=h.pack.tenant_id,
    )
    result = await command.apply_technical_validation(
        technical_media_seed(RELEASE),
        actor=replace(h.actor, tenant_id=None),
    )
    assert result.status == "already_applied"
    assert result.program_version_id == h.published.program_version_id
    with h.database.begin():
        member = h.database.scalar(select(Membership).where(Membership.person_id == h.actor_id))
        member.role = "learner"
    with pytest.raises(MediaForbidden):
        await command.apply_technical_validation(
            technical_media_seed(RELEASE),
            actor=replace(h.actor, tenant_id=None),
        )


def test_staging_requires_exact_baked_release_before_manifest_io(monkeypatch):
    def refused(release_id):
        assert release_id == RELEASE
        raise MediaConfigurationError("baked release mismatch")

    monkeypatch.setattr(manifest_module, "require_baked_release_id", refused)
    with pytest.raises(MediaConfigurationError, match="baked release"):
        load_verified_staging_fixture_pack(
            environment="staging",
            release_id=RELEASE,
            tenant_id=uuid4(),
            root=Path("/nonexistent"),
            expected_manifest_sha256=MANIFEST_SHA256,
        )
