"""Anyone's photo, for the people who share an organisation with them (avatars on leads,
notes and tasks; 25 Oct 2026): the person sees their own, a teammate sees it, an outsider
gets 404, and the URL's version makes it cacheable."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.orm import Session

from ac_platform.http.auth import install_identity_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.http.sales_xray_profile import install_sales_xray_profile_http
from ac_platform.identity.models import Person
from ac_platform.identity.sales_xray_profile_models import PersonPhoto
from ac_platform.tenancy.models import Membership, Organisation
from tests.unit.http.test_workspaces import TOKEN, HttpDatabase, workspace_state  # noqa: F401

WEBP = b"RIFF\x10\x00\x00\x00WEBPVP8 fictional"
HOST = "https://learner.authorityclosers.test"


@pytest.fixture
def world(workspace_state):  # noqa: F811
    """Alpha is an organisation; the signed-in person, a teammate and an outsider."""
    state = workspace_state
    teammate, outsider = uuid4(), uuid4()
    now = datetime.now(UTC)
    with Session(state.engine) as db, db.begin():
        db.add(
            Organisation(
                tenant_id=state.tenants["Alpha"],
                creation_command_id=uuid4(),
                domain_verification_token="f" * 43,
            )
        )
        for person, email in ((teammate, "teammate"), (outsider, "outsider")):
            db.add(Person(id=person, email=f"{email}@example.test", email_verified_at=now))
        db.flush()
        db.add(Membership(tenant_id=state.tenants["Alpha"], person_id=teammate, role="member"))
        db.add(Membership(tenant_id=state.tenants["Other"], person_id=outsider, role="member"))
        for person in (state.person, teammate, outsider):
            db.add(
                PersonPhoto(
                    person_id=person,
                    source="upload",
                    content_type="image/webp",
                    photo=WEBP,
                    byte_size=len(WEBP),
                    sha256="c" * 64,
                    revision=1,
                    updated_at=now,
                )
            )
    state.teammate, state.outsider = teammate, outsider
    return state


async def test_a_photo_is_seen_by_its_person_and_their_organisation_only(world) -> None:
    @asynccontextmanager
    async def sessions():
        with Session(world.engine) as db:
            yield HttpDatabase(db)

    app = FastAPI()
    register_problem_handlers(app)
    actor = install_identity_http(app, settings=world.settings, sessions=cast(Any, sessions))
    install_sales_xray_profile_http(app, settings=world.settings, require_actor=actor)
    cookie = {"cookie": f"ac_session={TOKEN}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=HOST) as client:

        async def photo(person, **params):
            return await client.get(f"/v1/people/{person}/photo", headers=cookie, params=params)

        own, teammate = await photo(world.person, v="cccccccc"), await photo(world.teammate)
        outsider, nobody = await photo(world.outsider), await photo(uuid4())
        extra = await photo(world.teammate, size="large")
        signed_out = await client.get(f"/v1/people/{world.teammate}/photo")
    assert own.status_code == teammate.status_code == 200
    assert teammate.content == WEBP and teammate.headers["content-type"] == "image/webp"
    assert teammate.headers["cache-control"] == "private, max-age=86400"
    assert outsider.status_code == nobody.status_code == extra.status_code == 404
    assert signed_out.status_code == 401
