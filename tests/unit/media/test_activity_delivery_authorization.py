"""Behavioral SQLite/HTTP tests for signed, request-bound course media delivery."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from ac_platform.catalog.models import Activity, Module, Program, ProgramVersion
from ac_platform.db.models import model_metadata
from ac_platform.enrollment.models import Enrollment, Entitlement
from ac_platform.http.auth import AuthenticatedTransaction, AuthenticationRequired
from ac_platform.http.learning import _default_activity_resolver
from ac_platform.http.media_delivery import install_media_delivery_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.kernel.authz import ActorContext
from ac_platform.learning.models import PlaybackSession
from ac_platform.learning.services import SqlAlchemyLearningRepository
from ac_platform.media.api_contracts import ActivityMediaBindingRequest
from ac_platform.media.bindings import resolve_activity_media_binding_for_learning
from ac_platform.media.database_delivery_authorizer import DatabaseMediaDeliveryAuthorizer
from ac_platform.media.delivery import PrivateMediaDeliveryHandler
from ac_platform.media.errors import MediaForbidden
from ac_platform.media.models import (
    ActivityMediaBinding,
    MediaAsset,
    MediaCaptionTrack,
    MediaPlaybackGrant,
    MediaRendition,
    MediaVersion,
)
from ac_platform.media.policy import MediaCorsPolicy, SignedMediaDeliveryPort
from ac_platform.media.service import MediaService
from ac_platform.media.signing import MediaSigner
from ac_platform.media.storage import InMemoryPrivateObjectStorage
from ac_platform.tenancy.models import Membership, Tenant

PLAYBACK = "playback"


@pytest.fixture
def harness() -> Iterator[Any]:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    model_metadata().create_all(engine)
    database = Session(engine)
    now = datetime.now(UTC).replace(microsecond=0)
    tenant, person, session_id, program, version, module, activity = (uuid4() for _ in range(7))
    owner = uuid4()
    actor = ActorContext(person, session_id, tenant)
    catalog_scope = {"scope": "tenant", "owner_key": tenant, "tenant_id": tenant}
    version_scope = {**catalog_scope, "program_id": program, "program_version_id": version}
    database.add_all(
        [
            Tenant(id=tenant, slug=f"tenant-{tenant}", name="Test media tenant"),
            Person(id=person),
            Person(id=owner),
            Membership(tenant_id=tenant, person_id=person, role="learner"),
            Membership(tenant_id=tenant, person_id=owner, role="owner"),
            IdentitySession(
                id=session_id,
                person_id=person,
                token_hash=b"s" * 32,
                selected_tenant_id=tenant,
                created_at=now - timedelta(minutes=1),
                expires_at=now + timedelta(hours=1),
            ),
            Program(
                id=program, slug="labeled-test-media", title="Licensed test films", **catalog_scope
            ),
            ProgramVersion(
                id=version,
                program_id=program,
                version_number=1,
                status="published",
                **catalog_scope,
            ),
            Module(
                id=module, position=1, title="Test fixtures, not course recordings", **version_scope
            ),
            Activity(
                id=activity,
                module_id=module,
                position=1,
                kind="VIDEO",
                title="Openly licensed playback fixture",
                **version_scope,
            ),
        ]
    )
    database.flush()
    enrollment = Enrollment(
        id=uuid4(),
        tenant_id=tenant,
        person_id=person,
        program_version_id=version,
        program_id=program,
        program_scope="tenant",
        program_tenant_id=tenant,
        program_owner_key=tenant,
        source="free_self",
        status="active",
    )
    database.add(enrollment)
    database.flush()
    entitlement = Entitlement(
        tenant_id=tenant,
        person_id=person,
        enrollment_id=enrollment.id,
        provenance_id=uuid4(),
        program_version_id=version,
        program_id=program,
        program_scope="tenant",
        program_tenant_id=tenant,
        program_owner_key=tenant,
        status="active",
    )
    database.add(entitlement)
    asset_id, media_version_id = uuid4(), uuid4()
    prefix = f"tenants/{tenant}/media/video/{asset_id}/{media_version_id}"
    asset = MediaAsset(
        id=asset_id,
        tenant_id=tenant,
        owner_person_id=owner,
        purpose="video",
        state="ready",
        current_version_id=media_version_id,
    )
    media_version = MediaVersion(
        id=media_version_id,
        tenant_id=tenant,
        asset_id=asset_id,
        version_number=1,
        purpose="video",
        state="ready",
        content_type="video/mp4",
        declared_bytes=10,
        actual_bytes=10,
        object_key=f"{prefix}/original",
        duration_seconds=12,
        width=1920,
        height=1080,
    )
    rendition = MediaRendition(
        tenant_id=tenant,
        asset_id=asset_id,
        version_id=media_version_id,
        protocol="progressive",
        content_type="video/mp4",
        object_key=f"{prefix}/renditions/1080p.mp4",
        width=1920,
        height=1080,
    )
    caption = MediaCaptionTrack(
        tenant_id=tenant,
        version_id=media_version_id,
        language="en",
        kind="captions",
        state="ready",
        content_type="text/vtt",
        object_key=f"{prefix}/captions/en.vtt",
        is_default=True,
    )
    database.add_all([asset, media_version, rendition, caption])
    database.flush()
    signer = MediaSigner("activity-delivery-isolated-test-key-32bytes")
    storage = InMemoryPrivateObjectStorage(signer)
    storage.put(object_key=rendition.object_key, body=b"0123456789", content_type="video/mp4")
    storage.put(object_key=caption.object_key, body=b"WEBVTT\n\n", content_type="text/vtt")
    port = SignedMediaDeliveryPort(signer=signer, delivery_origin="https://app.test")
    service = MediaService(
        storage=storage,
        signer=signer,
        webhook_secret="isolated-webhook-test-value-32bytes",  # noqa: S106 - isolated test key
        delivery_port=port,
        delivery_activity_resolver=_default_activity_resolver,
    )
    service._now = lambda: now
    binding = service.bind_activity_media(
        database,
        replace(actor, permissions=frozenset({"catalog_write"})),
        ActivityMediaBindingRequest(
            activity_id=activity,
            module_id=module,
            program_version_id=version,
            program_id=program,
            program_scope="tenant",
            program_owner_key=tenant,
            asset_id=asset_id,
            version_id=media_version_id,
            approval_reference="TEST-ONLY-APPROVED-FIXTURE",
        ),
        idempotency_key="test-activity-binding",
    )
    store = SqlAlchemyLearningRepository(
        database,
        activity_resolver=_default_activity_resolver,
        reviewer_resolver=lambda _access: None,
        activity_media_resolver=resolve_activity_media_binding_for_learning,
    )
    access = store.resolve_access(
        actor=actor,
        tenant_id=tenant,
        enrollment_id=enrollment.id,
        program_version_id=version,
        activity_id=activity,
    )
    yield SimpleNamespace(
        database=database,
        actor=actor,
        now=now,
        service=service,
        signer=signer,
        port=port,
        storage=storage,
        access=access,
        binding=binding,
        enrollment=enrollment,
        entitlement=entitlement,
        asset=asset,
        version=media_version,
        prefix=prefix,
        rendition=rendition,
        caption=caption,
    )
    database.close()
    engine.dispose()


def descriptor(h: Any) -> Any:
    return h.service.resolve_activity_media_descriptor_for_learner(h.database, h.actor, h.access)


def split_url(url: str) -> tuple[str, str]:
    parsed = urlsplit(url)
    return unquote(parsed.path.split("/playback/", 1)[1]), parse_qs(parsed.query)["token"][0]


def authorizer(h: Any, actor: ActorContext | None = None) -> DatabaseMediaDeliveryAuthorizer:
    return DatabaseMediaDeliveryAuthorizer(
        h.database,
        actor or h.actor,
        signer=h.signer,
        activity_resolver=_default_activity_resolver,
        clock=lambda: h.now,
    )


def handler(h: Any, actor: ActorContext | None = None) -> PrivateMediaDeliveryHandler:
    return PrivateMediaDeliveryHandler(
        storage=h.storage,
        signer=h.signer,
        delivery_port=h.port,
        cors_policy=MediaCorsPolicy(("https://app.test",)),
        authorizer=authorizer(h, actor),
    )


def claims_for(h: Any, url: str) -> dict[str, Any]:
    return h.signer.verify(split_url(url)[1], token_type=PLAYBACK, now=h.now)


def test_descriptor_issues_reusable_persisted_grant_and_exact_signed_bytes(harness: Any) -> None:
    h = harness
    result = descriptor(h)
    assert result.playback_available and result.reason == "approved_media_delivery_available"
    assert result.delivery.protocol == "progressive"
    key, token = split_url(result.delivery.progressive_url)
    claims = claims_for(h, result.delivery.progressive_url)
    assert claims["session_id"] == str(h.actor.session_id)
    assert claims["binding_id"] == str(h.binding.id)
    assert claims["enrollment_id"] == str(h.enrollment.id)
    assert authorizer(h).authorize(claims, PLAYBACK)
    delivered = handler(h).serve(
        token=token, token_type=PLAYBACK, object_key=key, range_header="bytes=2-5", now=h.now
    )
    assert delivered.status_code == 206 and b"".join(delivered.body) == b"2345"
    assert delivered.headers["Cache-Control"] == "private, no-store"
    caption_claims = claims_for(h, result.captions[0].source_url)
    assert caption_claims["delivery_grant_id"] == claims["delivery_grant_id"]
    assert authorizer(h).authorize(caption_claims, PLAYBACK)
    assert (
        claims_for(h, descriptor(h).delivery.progressive_url)["delivery_grant_id"]
        == claims["delivery_grant_id"]
    )
    assert h.database.scalar(select(func.count()).select_from(MediaPlaybackGrant)) == 1
    assert h.database.scalar(select(func.count()).select_from(PlaybackSession)) == 0


def test_missing_explicit_composition_or_rendition_never_issues_grant(harness: Any) -> None:
    h = harness
    h.service.delivery_activity_resolver = None
    assert not descriptor(h).playback_available
    h.service.delivery_activity_resolver = _default_activity_resolver
    h.database.delete(h.rendition)
    h.database.flush()
    assert descriptor(h).reason == "approved_media_rendition_unavailable"
    assert h.database.scalar(select(func.count()).select_from(MediaPlaybackGrant)) == 0


@pytest.mark.parametrize(
    "field",
    [
        "tenant_id",
        "person_id",
        "session_id",
        "activity_id",
        "activity_version",
        "asset_id",
        "version_id",
        "enrollment_id",
        "binding_id",
        "delivery_grant_id",
        "iat",
        "exp",
    ],
)
def test_grant_rejects_each_changed_scope_field(harness: Any, field: str) -> None:
    h = harness
    claims = claims_for(h, descriptor(h).delivery.progressive_url)
    claims[field] = claims[field] + 1 if field in {"iat", "exp"} else str(uuid4())
    assert not authorizer(h).authorize(claims, PLAYBACK)


@pytest.mark.parametrize(
    "change",
    [
        "grant_revoked",
        "grant_expired",
        "grant_digest",
        "grant_fingerprint",
        "session_revoked",
        "session_expired",
        "session_tenant",
        "person_suspended",
        "tenant_suspended",
        "membership_inactive",
        "enrollment_revoked",
        "entitlement_revoked",
        "binding_superseded",
        "asset_retired",
        "version_failed",
    ],
)
def test_current_database_revocation_and_scope_are_rechecked(harness: Any, change: str) -> None:
    h = harness
    claims = claims_for(h, descriptor(h).delivery.progressive_url)
    grant = h.database.scalar(select(MediaPlaybackGrant))
    identity = h.database.get(IdentitySession, h.actor.session_id)
    changes = {
        "grant_revoked": (grant, "revoked_at", h.now),
        "grant_expired": (grant, "expires_at", h.now),
        "grant_digest": (grant, "token_digest", b"z" * 32),
        "grant_fingerprint": (grant, "request_fingerprint", "f" * 64),
        "session_revoked": (identity, "revoked_at", h.now),
        "session_expired": (identity, "expires_at", h.now),
        "session_tenant": (identity, "selected_tenant_id", None),
        "person_suspended": (h.database.get(Person, h.actor.person_id), "status", "suspended"),
        "tenant_suspended": (h.database.get(Tenant, h.actor.tenant_id), "status", "suspended"),
        "membership_inactive": (
            h.database.scalar(select(Membership).where(Membership.person_id == h.actor.person_id)),
            "status",
            "inactive",
        ),
        "enrollment_revoked": (h.enrollment, "status", "revoked"),
        "entitlement_revoked": (h.entitlement, "status", "revoked"),
        "binding_superseded": (
            h.database.get(ActivityMediaBinding, h.binding.id),
            "state",
            "superseded",
        ),
        "asset_retired": (h.asset, "state", "retired"),
        "version_failed": (h.version, "state", "failed"),
    }
    target, attribute, value = changes[change]
    setattr(target, attribute, value)
    if change == "membership_inactive":
        target.ended_at = h.now
    if change == "binding_superseded":
        target.superseded_at = h.now
    h.database.flush()
    assert not authorizer(h).authorize(claims, PLAYBACK)


@pytest.mark.parametrize("field", ["person_id", "session_id", "tenant_id"])
def test_copied_url_cannot_cross_request_actor(harness: Any, field: str) -> None:
    h = harness
    key, token = split_url(descriptor(h).delivery.progressive_url)
    other = replace(h.actor, **{field: uuid4()})
    with pytest.raises(MediaForbidden):
        handler(h, other).serve(token=token, token_type=PLAYBACK, object_key=key, now=h.now)


def test_configured_prerequisites_are_rechecked_on_delivery(harness: Any) -> None:
    h = harness
    claims = claims_for(h, descriptor(h).delivery.progressive_url)

    def prerequisite_resolver(row: object, version: object) -> Any:
        return replace(_default_activity_resolver(row, version), prerequisites=(uuid4(),))

    check = DatabaseMediaDeliveryAuthorizer(
        h.database,
        h.actor,
        signer=h.signer,
        activity_resolver=prerequisite_resolver,
        clock=lambda: h.now,
    )
    assert not check.authorize(claims, PLAYBACK)


def test_expiry_boundary_and_refresh_append_a_new_grant(harness: Any) -> None:
    h = harness
    first = descriptor(h)
    claims = claims_for(h, first.delivery.progressive_url)
    grant = h.database.scalar(select(MediaPlaybackGrant))
    h.now = grant.expires_at.replace(tzinfo=UTC) - timedelta(seconds=1)
    assert authorizer(h).authorize(claims, PLAYBACK)
    h.now += timedelta(seconds=1)
    assert not authorizer(h).authorize(claims, PLAYBACK)
    h.service._now = lambda: h.now
    refreshed = claims_for(h, descriptor(h).delivery.progressive_url)
    assert refreshed["delivery_grant_id"] != claims["delivery_grant_id"]
    assert authorizer(h).authorize(refreshed, PLAYBACK)
    assert h.database.scalar(select(func.count()).select_from(MediaPlaybackGrant)) == 2


def test_hls_children_preserve_grant_scope_expiry_and_deny_after_revoke(harness: Any) -> None:
    h = harness
    master_key = f"{h.prefix}/renditions/hls/master.m3u8"
    playlist_key = f"{h.prefix}/renditions/hls/1080p/index.m3u8"
    segment_key = f"{h.prefix}/renditions/hls/1080p/segment.ts"
    h.storage.put(
        object_key=master_key,
        content_type="application/vnd.apple.mpegurl",
        body=(
            b"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000000,RESOLUTION=1920x1080\n1080p/index.m3u8\n"
        ),
    )
    h.storage.put(
        object_key=playlist_key,
        content_type="application/vnd.apple.mpegurl",
        body=(b"#EXTM3U\n#EXT-X-TARGETDURATION:4\n#EXTINF:4,\nsegment.ts\n#EXT-X-ENDLIST\n"),
    )
    h.storage.put(object_key=segment_key, content_type="video/mp2t", body=b"test-segment")
    h.database.add(
        MediaRendition(
            tenant_id=h.actor.tenant_id,
            asset_id=h.asset.id,
            version_id=h.version.id,
            protocol="hls",
            content_type="application/vnd.apple.mpegurl",
            object_key=master_key,
        )
    )
    h.database.flush()
    result = descriptor(h)
    assert result.delivery.protocol == "hls" and result.delivery.progressive_url
    root_claims = claims_for(h, result.delivery.manifest_url)
    key, token = split_url(result.delivery.manifest_url)
    master = handler(h).serve(token=token, token_type=PLAYBACK, object_key=key, now=h.now)
    child_url = next(
        line for line in b"".join(master.body).decode().splitlines() if line.startswith("https://")
    )
    child_claims = claims_for(h, child_url)
    for name in ("delivery_grant_id", "enrollment_id", "binding_id", "session_id", "iat", "exp"):
        assert child_claims[name] == root_claims[name]
    child_key, child_token = split_url(child_url)
    assert child_key == playlist_key
    playlist = handler(h).serve(
        token=child_token, token_type=PLAYBACK, object_key=child_key, now=h.now
    )
    segment_url = next(
        line
        for line in b"".join(playlist.body).decode().splitlines()
        if line.startswith("https://")
    )
    segment_key, segment_token = split_url(segment_url)
    grant = h.database.scalar(select(MediaPlaybackGrant))
    grant.revoked_at = h.now
    h.database.flush()
    with pytest.raises(MediaForbidden):
        handler(h).serve(
            token=segment_token, token_type=PLAYBACK, object_key=segment_key, now=h.now
        )


def test_authenticated_http_get_head_copy_and_anonymous_policy(
    harness: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = harness
    url = descriptor(h).delivery.progressive_url
    factory_calls: list[ActorContext] = []
    active_transaction = False
    stream_calls = 0
    original_stream = PrivateMediaDeliveryHandler._stream

    def stream_after_transaction(self: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal stream_calls
        # Check when StreamingResponse consumes its lazy body, not at creation.
        assert not active_transaction
        stream_calls += 1
        yield from original_stream(self, *args, **kwargs)

    monkeypatch.setattr(PrivateMediaDeliveryHandler, "_stream", stream_after_transaction)

    class AsyncDatabase:
        async def run_sync(self, operation: Any) -> Any:
            return operation(h.database)

    async def require_actor(request: Request) -> AsyncIterator[AuthenticatedTransaction]:
        nonlocal active_transaction
        selected = request.headers.get("x-test-session")
        if selected is None:
            raise AuthenticationRequired("An authenticated test session is required.")
        actor = h.actor if selected == "original" else replace(h.actor, session_id=uuid4())
        active_transaction = True
        try:
            yield AuthenticatedTransaction(
                database=AsyncDatabase(),
                identity=None,
                resolved=SimpleNamespace(actor=actor),
                token="test",  # noqa: S106 - synthetic authenticated dependency
            )
        finally:
            active_transaction = False

    def factory(database: Session, actor: ActorContext) -> PrivateMediaDeliveryHandler:
        assert database is h.database
        factory_calls.append(actor)
        return handler(h, actor)

    app = FastAPI()
    register_problem_handlers(app)
    install_media_delivery_http(
        app,
        cors_policy=MediaCorsPolicy(("https://app.test",)),
        require_actor=require_actor,
        authenticated_handler_factory=factory,
    )
    operations = app.openapi()["paths"]["/v1/media/{kind}/{object_key}"]
    assert operations["get"]["operationId"] == "get_signed_media_delivery"
    assert operations["head"]["operationId"] == "head_signed_media_delivery"
    with TestClient(app, base_url="https://app.test") as client:
        for method in ("GET", "HEAD"):
            assert client.request(method, url).status_code == 401
            assert (
                client.request(method, url, headers={"x-test-session": "other"}).status_code == 403
            )
            response = client.request(
                method, url, headers={"x-test-session": "original", "Range": "bytes=2-5"}
            )
            assert response.status_code == 206
            assert response.content == (b"2345" if method == "GET" else b"")
        before = len(factory_calls)
        preflight = client.options(
            url, headers={"Origin": "https://app.test", "Access-Control-Request-Method": "GET"}
        )
        assert preflight.status_code == 204 and not preflight.content
        assert len(factory_calls) == before  # no object/grant access during preflight
        assert client.options(url, headers={"Origin": "https://attacker.test"}).status_code == 403
        assert stream_calls == 1


def test_incomplete_authenticated_composition_is_rejected(harness: Any) -> None:
    with pytest.raises(ValueError, match="both identity and handler factory"):
        install_media_delivery_http(
            FastAPI(),
            cors_policy=MediaCorsPolicy(("https://app.test",)),
            authenticated_handler_factory=lambda _db, _actor: handler(harness),
        )
