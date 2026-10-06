"""Fictional settings/logo HTTP evidence over canonical authentication and storage."""

# ruff: noqa: F811 - imported relational pytest fixtures

import io
from uuid import uuid4

import httpx
import pytest
from PIL import Image, PngImagePlugin
from sqlalchemy import select
from sqlalchemy.orm import Session

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain_sync
from ac_platform.kernel.errors import DomainError
from ac_platform.media.local_avatar_processing import (
    MAX_LOGO_BYTES,
    LocalAvatarProcessor,
    LocalAvatarScanner,
)
from ac_platform.media.local_avatar_runtime import LocalAvatarMediaService, LocalAvatarRuntime
from ac_platform.media.local_avatar_storage import LocalAvatarStorage
from ac_platform.media.runtime import create_default_media_runtime
from ac_platform.media.scanner import FailClosedScanner
from ac_platform.media.signing import MediaSigner
from ac_platform.media.storage import InMemoryPrivateObjectStorage
from ac_platform.organisations.service import OrganisationService
from ac_platform.organisations.settings import logo_key
from ac_platform.tenancy.models import Membership, Organisation, Tenant
from tests.unit.http.test_organisation import call, state  # noqa: F401
from tests.unit.http.test_workspaces import TOKEN, workspace_state  # noqa: F401
from tests.unit.media.test_clamav_scanner import FakeSocket
from tests.unit.media.test_development_organisation_avatar_runtime import dev_store  # noqa: F401

DETAILS = {
    "name": "Fictional Studio",
    "legal_name": "Fictional Studio Private Limited",
    "gstin": "FICTIONAL-NOT-A-REAL-GSTIN",
    "address": "123 Example Street",
    "industry": "Training",
    "team_size": "3-10",
    "website": "https://example.test",
    "city": "Example City",
}


def picture(format="PNG", size=(90, 60), **options):
    with Image.new("RGB", size, "red") as image:
        output = io.BytesIO()
        image.save(output, format=format, **options)
        return output.getvalue()


@pytest.fixture(params=["local", "development"])
def avatar(state, tmp_path, request, monkeypatch, dev_store):  # noqa: F811
    if request.param == "development":
        from ac_platform.media import clamav_scanner

        monkeypatch.setattr(clamav_scanner, "_connect", lambda *args: FakeSocket())
        runtime = create_default_media_runtime(dev_store).organisation_avatar_runtime
        state.app.state.organisation_avatar_runtime = runtime
        return runtime
    signer = MediaSigner(b"fictional-organisation-images-123456789")
    fallback = InMemoryPrivateObjectStorage(signer)
    storage = LocalAvatarStorage(root=tmp_path / "avatar-objects", signer=signer, fallback=fallback)
    service = LocalAvatarMediaService(
        storage=storage,
        signer=signer,
        webhook_secret=b"x" * 32,
        scanner=LocalAvatarScanner(),
        processor=LocalAvatarProcessor(),
    )
    runtime = LocalAvatarRuntime(storage, service)
    state.app.state.organisation_avatar_runtime = runtime
    return runtime


async def upload(state, body, *, content_type="image/png", key=None, token=TOKEN):  # noqa: F811
    headers = {"content-type": content_type, "Idempotency-Key": str(key or uuid4())}
    if token is not None:
        headers["cookie"] = f"ac_session={token}"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=state.app),
        base_url="https://learner.authorityclosers.test",
    ) as client:
        return await client.put("/v1/organisation/logo", headers=headers, content=body)


def snapshot(state):  # noqa: F811
    with Session(state.engine) as db:
        assert verify_audit_chain_sync(db, tenant_id=state.tenant).valid
        tenant = db.get(Tenant, state.tenant)
        org = db.get(Organisation, state.tenant)
        audits = list(db.scalars(select(AuditEvent).where(AuditEvent.tenant_id == state.tenant)))
        return tenant.name, dict(org.details), org.logo_id, audits


@pytest.mark.parametrize("role", ["owner", "admin"])
async def test_details_persist_across_requests_and_new_database_connections(state, role):  # noqa: F811
    with Session(state.engine) as db, db.begin():
        db.get(Membership, (state.tenant, state.person)).role = role
    key = uuid4()
    response = await call(state, "PUT", "/settings", body=DETAILS, key=key)
    expected = {**DETAILS, "tenant_id": str(state.tenant), "logo_url": None}
    assert response.status_code == 200, response.text
    assert response.json() == expected
    assert (await call(state, path="/settings")).json() == expected
    assert (await call(state, path="/profile")).json()["name"] == DETAILS["name"]
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["vary"] == "Cookie"
    assert (await call(state, "PUT", "/settings", body=DETAILS, key=key)).json() == expected
    name, details, logo, (audit,) = snapshot(state)
    assert name == DETAILS["name"] and details == {k: v for k, v in DETAILS.items() if k != "name"}
    assert logo is None and audit.actor_person_id == state.person
    assert audit.action == "organisation.details_changed" and audit.resource_id == str(state.tenant)
    assert audit.payload["before"]["name"] == "Alpha" and audit.payload["after"] == expected
    assert (
        await call(state, "PUT", "/settings", body={"name": "New Studio"}, key=key)
    ).status_code == 409
    assert (
        await call(state, "PUT", "/settings", body={"name": "New Studio"}, key=uuid4())
    ).status_code == 200
    # Replay returns the original response without rolling back the later change.
    assert (await call(state, "PUT", "/settings", body=DETAILS, key=key)).json() == expected
    saved = (await call(state, path="/settings")).json()
    assert saved["name"] == "New Studio" and saved["legal_name"] == ""
    assert len(snapshot(state)[3]) == 2


@pytest.mark.parametrize(
    "body",
    [
        {"name": " "},
        {"name": "a"},
        {"name": "a" * 81},
        {"name": "Valid", "address": "x" * 1001},
        {"name": "Valid", "team_size": 3},
        {"name": "Valid", "gstin": None},
        {"name": "Valid", "tenant_id": str(uuid4())},
        {"name": "Valid", "logo_url": "https://example.test/untrusted"},
    ],
)
async def test_invalid_details_leave_values_and_audit_unchanged(state, body):  # noqa: F811
    assert (await call(state, "PUT", "/settings", body=body, key=uuid4())).status_code == 422
    assert snapshot(state) == ("Alpha", {}, None, [])


async def test_name_normalization_and_empty_optional_details(state):  # noqa: F811
    response = await call(state, "PUT", "/settings", body={"name": "  New Studio  "}, key=uuid4())
    assert response.status_code == 200 and response.json()["name"] == "New Studio"
    assert response.json()["city"] == "" and response.json()["team_size"] == ""


@pytest.mark.parametrize("role", ["owner", "admin", "member", "learner"])
async def test_personal_workspace_branding_and_organisation_only_reads(state, role):  # noqa: F811
    from ac_platform.identity.models import Session as IdentitySession

    personal = uuid4()
    with Session(state.engine) as db, db.begin():
        db.add(Tenant(id=personal, name="Fictional Personal", slug=f"personal-{personal.hex}"))
        db.flush()
        db.add(Membership(tenant_id=personal, person_id=state.person, role=role))
        db.get(IdentitySession, state.session).selected_tenant_id = personal
        assert db.get(Organisation, personal) is None

    response = await call(state, path="/branding")
    assert response.status_code == 200, response.text
    assert response.json() == {
        "tenant_id": str(personal),
        "name": "Fictional Personal",
        "logo_url": None,
    }
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["vary"] == "Cookie"
    for path in ("/settings", f"/logo/{uuid4()}"):
        response = await call(state, path=path)
        assert response.status_code == 404, response.text
        assert response.json()["detail"] == "No organisation selected."


@pytest.mark.parametrize("token", [None, "invalid"])
async def test_anonymous_settings_branding_and_logo_requests_fail(state, avatar, token):  # noqa: F811
    for path in ("/settings", "/branding", f"/logo/{uuid4()}"):
        assert (await call(state, path=path, token=token)).status_code == 401
    assert (
        await call(state, "PUT", "/settings", body=DETAILS, key=uuid4(), token=token)
    ).status_code == 401
    assert (await upload(state, picture(), token=token)).status_code == 401
    assert len(list(avatar.storage.root.glob("*.blob"))) == 0


async def test_member_cannot_read_edit_or_replay_private_settings_but_can_read_branding(
    state, avatar
):  # noqa: F811
    key = uuid4()
    assert (await call(state, "PUT", "/settings", body=DETAILS, key=key)).status_code == 200
    with Session(state.engine) as db, db.begin():
        db.get(Membership, (state.tenant, state.person)).role = "member"
    assert (await call(state, path="/settings")).status_code == 403
    for command in (key, uuid4()):
        assert (await call(state, "PUT", "/settings", body=DETAILS, key=command)).status_code == 403
    assert (await upload(state, picture())).status_code == 403
    assert (await call(state, path="/branding")).json() == {
        "tenant_id": str(state.tenant),
        "name": DETAILS["name"],
        "logo_url": None,
    }
    assert len(list(avatar.storage.root.glob("*.blob"))) == 0 and len(snapshot(state)[3]) == 1


@pytest.mark.parametrize("format,mime", [("PNG", "image/png"), ("JPEG", "image/jpeg")])
@pytest.mark.parametrize("role", ["owner", "admin"])
async def test_logo_uses_existing_store_strips_metadata_and_persists_reference(
    state, avatar, format, mime, role, dev_store
):  # noqa: F811
    with Session(state.engine) as db, db.begin():
        db.get(Membership, (state.tenant, state.person)).role = role
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("comment", "fictional private metadata")
    source = picture(format, pnginfo=metadata) if format == "PNG" else picture(format)
    key = uuid4()
    response = await upload(state, source, content_type=mime, key=key)
    assert response.status_code == 200, response.text
    url = f"/v1/organisation/logo/{key}"
    assert response.json()["logo_url"] == url
    assert (await call(state, path="/settings")).json()["logo_url"] == url
    assert (await upload(state, source, content_type=mime, key=key)).json() == response.json()
    assert len(snapshot(state)[3]) == 1
    # Reopening the existing store proves that delivery is not an in-memory image cache.
    if (avatar.storage.root / ".development-organisation-avatar-store").exists():
        reopened = create_default_media_runtime(dev_store).organisation_avatar_runtime.storage
    else:
        reopened = LocalAvatarStorage(
            root=avatar.storage.root, signer=avatar.storage.signer, fallback=avatar.storage.fallback
        )
    stored = reopened.read(logo_key(state.tenant, key))
    with Image.open(io.BytesIO(stored)) as image:
        assert image.size == (512, 512) and image.format == "WEBP"
        assert not image.getexif() and "comment" not in image.info
    assert source != stored and b"fictional private metadata" not in stored
    _, _, logo, (audit,) = snapshot(state)
    assert logo == key and audit.action == "organisation.logo_changed"
    assert audit.actor_person_id == state.person and audit.payload["before"]["logo_url"] is None
    with Session(state.engine) as db, db.begin():
        db.get(Membership, (state.tenant, state.person)).role = "member"
    delivery = await call(state, path=f"/logo/{key}")
    assert delivery.status_code == 200 and delivery.content == stored
    assert delivery.headers["content-type"] == "image/webp"
    assert delivery.headers["x-content-type-options"] == "nosniff"
    assert (await call(state, path="/branding")).json()["logo_url"] == url


@pytest.mark.parametrize(
    "body,mime",
    [
        (b"", "image/png"),
        (b"bad image", "image/png"),
        (b"<svg xmlns='http://www.w3.org/2000/svg'/>", "image/svg+xml"),
        (picture("GIF"), "image/gif"),
        (picture(), "image/jpeg"),
        (b"x" * (MAX_LOGO_BYTES + 1), "image/png"),
        (picture(size=(8193, 1)), "image/png"),
        (picture(size=(4000, 3001)), "image/png"),
    ],
    ids=["empty", "bad", "svg", "gif", "mime-mismatch", "oversize", "edge", "pixels"],
)
async def test_invalid_logos_preserve_previous_reference_and_success_audit(
    state, avatar, body, mime
):  # noqa: F811
    key = uuid4()
    assert (await upload(state, picture(), key=key)).status_code == 200
    response = await upload(state, body, content_type=mime)
    assert response.status_code == 400, response.text
    assert snapshot(state)[2] == key and len(snapshot(state)[3]) == 1
    assert len(list(avatar.storage.root.glob("*.blob"))) == 1


async def test_replacement_preserves_history_and_old_bytes_but_does_not_replay_old_logo(
    state, avatar
):  # noqa: F811
    first, second = uuid4(), uuid4()
    initial = await upload(state, picture(), key=first)
    assert initial.status_code == 200
    assert (
        await upload(state, picture("JPEG"), content_type="image/jpeg", key=second)
    ).status_code == 200
    assert (await upload(state, picture(), key=first)).json() == initial.json()
    assert snapshot(state)[2] == second and len(snapshot(state)[3]) == 2
    assert avatar.storage.read(logo_key(state.tenant, first))
    assert (await call(state, path=f"/logo/{first}")).status_code == 404


async def test_scanner_and_audit_failure_keep_the_previous_logo_and_details(
    state, avatar, monkeypatch
):  # noqa: F811
    key = uuid4()
    assert (await upload(state, picture(), key=key)).status_code == 200
    prior = snapshot(state)
    original_scanner = avatar.service.scanner
    avatar.service.scanner = FailClosedScanner()
    rejected = uuid4()
    assert (await upload(state, picture(), key=rejected)).status_code == 400
    assert (await call(state, path=f"/logo/{rejected}")).status_code == 404
    current = snapshot(state)
    assert current[:3] == prior[:3]
    assert [(a.id, a.payload) for a in current[3]] == [(a.id, a.payload) for a in prior[3]]
    avatar.service.scanner = original_scanner

    async def fail_audit(*args, **kwargs):
        raise DomainError("Fictional audit failure.")

    monkeypatch.setattr(OrganisationService, "_audit", fail_audit)
    assert (await call(state, "PUT", "/settings", body=DETAILS, key=uuid4())).status_code == 422
    assert (await upload(state, picture(), key=uuid4())).status_code == 422
    current = snapshot(state)
    assert current[:3] == prior[:3]
    assert [(a.id, a.payload) for a in current[3]] == [(a.id, a.payload) for a in prior[3]]


async def test_selected_context_never_accepts_another_tenants_logo_id(state, avatar):  # noqa: F811
    from ac_platform.identity.models import Session as IdentitySession

    key = uuid4()
    assert (await upload(state, picture(), key=key)).status_code == 200
    # A registered second organisation uses its own details and image reference.
    other = state.tenants["Inactive"]
    with Session(state.engine) as db, db.begin():
        tenant = db.get(Tenant, other)
        tenant.status = "active"
        db.add(
            Organisation(
                tenant_id=other, creation_command_id=uuid4(), domain_verification_token="f" * 43
            )
        )
        membership = db.get(Membership, (other, state.person))
        membership.role, membership.status, membership.ended_at = "owner", "active", None
        db.get(IdentitySession, state.session).selected_tenant_id = other
    assert (await call(state, path=f"/logo/{key}")).status_code == 404
    assert (await call(state, path="/settings")).json()["name"] == "Inactive"
    assert (
        await call(state, "PUT", "/settings", body={"name": "Other Studio"}, key=uuid4())
    ).status_code == 200
    assert snapshot(state)[0] == "Alpha" and snapshot(state)[2] == key
    assert (await upload(state, picture(), key=key)).status_code == 409
    assert len(snapshot(state)[3]) == 1


async def test_missing_image_storage_fails_closed(state):  # noqa: F811
    assert (await upload(state, picture())).status_code == 503
    assert snapshot(state) == ("Alpha", {}, None, [])


@pytest.mark.parametrize("reply", [b"stream: Eicar-Test-Signature FOUND\0", b"stream: ERROR\0"])
async def test_dev_scanner_rejection_preserves_logo_details_and_audit(
    state, dev_store, monkeypatch, reply
):  # noqa: F811
    from ac_platform.media import clamav_scanner

    monkeypatch.setattr(clamav_scanner, "_connect", lambda *args: FakeSocket())
    runtime = create_default_media_runtime(dev_store).organisation_avatar_runtime
    state.app.state.organisation_avatar_runtime = runtime
    assert (await upload(state, picture())).status_code == 200
    prior = snapshot(state)
    monkeypatch.setattr(clamav_scanner, "_connect", lambda *args: FakeSocket([reply]))
    rejected = uuid4()
    response = await upload(state, picture(), key=rejected)
    assert response.status_code in {400, 503}
    current = snapshot(state)
    assert current[:3] == prior[:3]
    assert [(a.id, a.payload) for a in current[3]] == [(a.id, a.payload) for a in prior[3]]
    assert (await call(state, path=f"/logo/{rejected}")).status_code == 404
