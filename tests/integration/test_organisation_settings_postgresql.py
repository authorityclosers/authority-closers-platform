"""Fictional PostgreSQL proof for additive storage and settings/logo isolation."""

# ruff: noqa: F811 - imported relational pytest fixture

import asyncio
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from hmac import digest
from typing import Any, cast
from uuid import uuid4

import httpx
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from fastapi import FastAPI
from sqlalchemy import MetaData, Table, inspect, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from ac_platform.application.settings import Settings
from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain_sync
from ac_platform.db.models import model_metadata
from ac_platform.http.auth import install_identity_http
from ac_platform.http.organisation import install_organisation_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.kernel.errors import ResourceConflict
from ac_platform.media.local_avatar_processing import LocalAvatarProcessor, LocalAvatarScanner
from ac_platform.media.local_avatar_runtime import LocalAvatarMediaService, LocalAvatarRuntime
from ac_platform.media.local_avatar_storage import LocalAvatarStorage
from ac_platform.media.signing import MediaSigner
from ac_platform.media.storage import InMemoryPrivateObjectStorage
from ac_platform.organisations.settings import OrganisationSettingsService
from ac_platform.tenancy.models import Membership, Organisation, Tenant
from tests.database.test_plans_confirmed_values_postgresql import catalogue_schema
from tests.integration.test_media_delivery_renewal_postgresql import postgres_harness  # noqa: F401
from tests.unit.http.test_organisation_settings import DETAILS, picture


def test_populated_0075_upgrade_preserves_rows_and_matches_organisation_model():
    with catalogue_schema("20261004_0075") as schema:
        tenants = Table("tenants", MetaData(), autoload_with=schema.engine)
        organisations = Table("organisations", MetaData(), autoload_with=schema.engine)
        tenant_id = uuid4()
        with schema.engine.begin() as db:
            db.execute(tenants.insert().values(id=tenant_id, name="Fictional", slug="fictional"))
            db.execute(
                organisations.insert().values(
                    tenant_id=tenant_id,
                    creation_command_id=uuid4(),
                    domain_verification_token="f" * 43,
                )
            )
            before = dict(db.execute(select(organisations)).mappings().one())
        schema.migrate("20261005_0076")
        schema.migrate("head")
        with schema.engine.connect() as db:
            after = dict(db.execute(select(Organisation.__table__)).mappings().one())
            assert {key: after[key] for key in before} == before
            assert after["details"] == {} and after["logo_id"] is None
            assert db.scalar(text("SELECT version_num FROM alembic_version")) == "20261005_0076"
            columns = {
                column["name"]: column for column in inspect(db).get_columns("organisations")
            }
            assert not columns["details"]["nullable"] and columns["logo_id"]["nullable"]
            drift = compare_metadata(MigrationContext.configure(db), model_metadata())
            assert [entry for entry in drift if "organisations" in repr(entry)] == []


def test_settings_and_logo_survive_runtime_restart_with_roles_locks_and_audit(
    postgres_harness, tmp_path, monkeypatch
):  # noqa: F811
    async def exercise():
        public, operations, tenant, other = (uuid4() for _ in range(4))
        owner, admin, member, stranger = (uuid4() for _ in range(4))
        people = (owner, admin, member, stranger)
        tokens = dict(zip(people, ("o" * 43, "a" * 43, "m" * 43, "s" * 43), strict=True))
        settings = Settings(
            _env_file=None,
            environment="test",
            public_learner_tenant_id=public,
            operations_tenant_id=operations,
        )
        now = datetime.now(UTC)
        with Session(postgres_harness.engine) as db, db.begin():
            db.add_all(
                [
                    Person(id=p, email=f"settings-{p}@example.test", email_verified_at=now)
                    for p in people
                ]
            )
            db.add_all(
                [
                    Tenant(id=t, name="Fictional " + str(t), slug="fixture-" + t.hex)
                    for t in (public, operations, tenant, other)
                ]
            )
            db.flush()
            db.add_all(
                [
                    Organisation(
                        tenant_id=t, creation_command_id=uuid4(), domain_verification_token="f" * 43
                    )
                    for t in (tenant, other)
                ]
                + [
                    Membership(tenant_id=tenant, person_id=p, role=r)
                    for p, r in ((owner, "owner"), (admin, "admin"), (member, "member"))
                ]
                + [Membership(tenant_id=other, person_id=stranger, role="owner")]
            )
            db.flush()
            db.add_all(
                [
                    IdentitySession(
                        id=uuid4(),
                        person_id=p,
                        selected_tenant_id=other if p == stranger else tenant,
                        token_hash=digest(
                            settings.session_token_pepper.get_secret_value().encode(),
                            tokens[p].encode(),
                            sha256,
                        ),
                        created_at=now,
                        expires_at=now + timedelta(days=1),
                    )
                    for p in people
                ]
            )

        def snapshot():
            with Session(postgres_harness.engine) as db:
                assert verify_audit_chain_sync(db, tenant).valid
                row = db.get(Organisation, tenant)
                events = list(
                    db.scalars(
                        select(AuditEvent)
                        .where(AuditEvent.tenant_id == tenant)
                        .order_by(AuditEvent.sequence_no)
                    )
                )
                return db.get(Tenant, tenant).name, dict(row.details), row.logo_id, events

        def runtime():
            engine = create_async_engine(postgres_harness.schema_url, hide_parameters=True)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            app = FastAPI()
            register_problem_handlers(app)
            actor = install_identity_http(app, settings=settings, sessions=cast(Any, sessions))
            install_organisation_http(app, settings=settings, require_actor=actor)
            signer = MediaSigner(b"fictional-settings-image-signing-key")
            storage = LocalAvatarStorage(
                root=tmp_path / "avatar-objects",
                signer=signer,
                fallback=InMemoryPrivateObjectStorage(signer),
            )
            media = LocalAvatarMediaService(
                storage=storage,
                signer=signer,
                webhook_secret=b"f" * 32,
                scanner=LocalAvatarScanner(),
                processor=LocalAvatarProcessor(),
            )
            app.state.organisation_avatar_runtime = LocalAvatarRuntime(storage, media)
            return app, engine, sessions

        app, engine, sessions = runtime()
        key, logo = uuid4(), uuid4()
        source = picture()
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="https://learner.authorityclosers.test",
            ) as client:

                async def send(method, path, *, person=owner, body=None, image=None, command=None):
                    headers = {} if person is None else {"cookie": f"ac_session={tokens[person]}"}
                    if command is not None:
                        headers["Idempotency-Key"] = str(command)
                    if image is not None:
                        headers["content-type"] = "image/png"
                    return await client.request(
                        method, "/v1/organisation" + path, headers=headers, json=body, content=image
                    )

                response = await send("PUT", "/settings", body=DETAILS, command=key)
                assert response.status_code == 200, response.text
                expected = {**DETAILS, "tenant_id": str(tenant), "logo_url": None}
                assert response.json() == expected
                assert (
                    await send("PUT", "/settings", body=DETAILS, command=key)
                ).json() == expected
                assert len(snapshot()[3]) == 1
                for person, status in ((None, 401), (member, 403)):
                    assert (
                        await send("PUT", "/settings", person=person, body=DETAILS, command=uuid4())
                    ).status_code == status
                    assert (
                        await send("PUT", "/logo", person=person, image=source, command=uuid4())
                    ).status_code == status
                assert (
                    await send(
                        "PUT",
                        "/settings",
                        body={**DETAILS, "tenant_id": str(other)},
                        command=uuid4(),
                    )
                ).status_code == 422
                assert (await send("GET", "/settings", person=stranger)).json()["legal_name"] == ""
                assert (await send("GET", "/settings", person=member)).status_code == 403

                before = snapshot()[:3]
                async with sessions() as fence, fence.begin():
                    await fence.execute(
                        select(Tenant).where(Tenant.id == tenant).with_for_update(read=True)
                    )
                    busy = await send(
                        "PUT", "/settings", body={"name": "Blocked Fixture"}, command=uuid4()
                    )
                    assert busy.status_code == 409
                assert snapshot()[:3] == before and len(snapshot()[3]) == 1

                async def fail_audit(*args, **kwargs):
                    raise ResourceConflict("Fictional audit failure")

                with monkeypatch.context() as patch:
                    patch.setattr(OrganisationSettingsService, "_audit", fail_audit)
                    assert (
                        await send(
                            "PUT", "/settings", body={"name": "Rollback Fixture"}, command=uuid4()
                        )
                    ).status_code == 409
                assert snapshot()[:3] == before and len(snapshot()[3]) == 1

                uploaded = await send("PUT", "/logo", person=admin, image=source, command=logo)
                assert uploaded.status_code == 200, uploaded.text
                expected["logo_url"] = f"/v1/organisation/logo/{logo}"
                assert uploaded.json() == expected
                assert (
                    await send("PUT", "/logo", person=admin, image=source, command=logo)
                ).json() == expected
                assert (await send("GET", f"/logo/{logo}", person=stranger)).status_code == 404
                assert (
                    await send("PUT", "/logo", image=b"bad image", command=uuid4())
                ).status_code == 400
                _, _, saved_logo, events = snapshot()
                assert saved_logo == logo and len(events) == 2
                assert [(event.action, event.actor_person_id) for event in events] == [
                    ("organisation.details_changed", owner),
                    ("organisation.logo_changed", admin),
                ]
                assert all(event.resource_id == str(tenant) for event in events)
        finally:
            await engine.dispose()

        # Reconstruct database pools, app and private storage; nothing is held in the first runtime.
        app, engine, _ = runtime()
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="https://learner.authorityclosers.test",
                headers={"cookie": f"ac_session={tokens[owner]}"},
            ) as client:
                assert (await client.get("/v1/organisation/settings")).json() == expected
                logo_response = await client.get(expected["logo_url"])
                assert (
                    logo_response.status_code == 200
                    and logo_response.headers["content-type"] == "image/webp"
                )
                assert logo_response.content != source
                assert (await client.get("/v1/organisation/branding")).json() == {
                    k: expected[k] for k in ("tenant_id", "name", "logo_url")
                }
        finally:
            await engine.dispose()

    asyncio.run(exercise())
