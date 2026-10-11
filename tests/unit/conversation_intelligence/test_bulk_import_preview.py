"""Fictional manifest and current organisation-authority proof; no recording bytes."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import ValidationError
from sqlalchemy import event
from sqlalchemy.orm import Session

from ac_platform.conversation_intelligence.acquisition_sessions import AcquisitionSessions
from ac_platform.conversation_intelligence.application import ConversationDenied
from ac_platform.conversation_intelligence.bulk_import_preview import (
    BatchManifest,
    ImportMember,
    preview_import,
    project_import_preview,
)
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.http.auth import install_identity_http, require_safe_origin
from ac_platform.http.conversation_imports import install_import_http
from ac_platform.http.conversation_submissions import _Owner
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.kernel.authz import ActorContext
from ac_platform.tenancy.models import Membership
from tests.unit.http.test_organisation import state  # noqa: F401
from tests.unit.http.test_workspaces import TOKEN, HttpDatabase, workspace_state  # noqa: F401


def file(path="Swamini/call", digest="a" * 64, size=1024):
    return {"relative_path": path, "source_sha256": digest, "source_bytes": size}


def test_names_are_only_proposals_and_ambiguous_folders_stay_unassigned():
    swamini, first, second, devanagari = (uuid4() for _ in range(4))
    manifest = BatchManifest.model_validate(
        {"files": [file(), file("Ankita/call.mp3"), file("स्वामिनी/call.ogg"), file("root.wav")]}
    )
    result = project_import_preview(
        manifest,
        [
            ImportMember(swamini, "Swamini Test", "Swamini"),
            ImportMember(first, "Ankita One", "Ankita"),
            ImportMember(second, "Ankita Two", "Ankita"),
            ImportMember(devanagari, "स्वामिनी", None),
        ],
    )
    folders = {row["folder"]: row for row in result["folders"]}
    assert folders["Swamini"]["proposed_person_id"] == str(swamini)
    assert folders["Ankita"]["proposed_person_id"] is None
    assert folders["Ankita"]["match_state"] == "ambiguous"
    assert folders["स्वामिनी"]["proposed_person_id"] == str(devanagari)
    assert folders[""]["match_state"] == "unassigned"
    assert result["requires_confirmation"] is True
    assert result["total_files"] == 4
    assert result["total_bytes"] == 4096


def test_exact_display_name_wins_over_first_name_hint_and_nested_folders_group_once():
    exact, longer = uuid4(), uuid4()
    manifest = BatchManifest.model_validate(
        {"files": [file("Ｓｗａｍｉｎｉ/week-1/one"), file("Ｓｗａｍｉｎｉ/week-2/two", "b" * 64)]}
    )
    result = project_import_preview(
        manifest,
        [ImportMember(longer, "Swamini Longer", "Swamini"), ImportMember(exact, "Swamini", None)],
    )
    assert len(result["folders"]) == 1
    assert result["folders"][0]["proposed_person_id"] == str(exact)
    assert result["folders"][0]["file_count"] == 2


def test_duplicate_hash_is_a_hint_without_assigning_or_importing_another_members_call():
    manifest = BatchManifest.model_validate(
        {"files": [file("First/one.wav"), file("Second/copy.m4a"), file("Third/other", "b" * 64)]}
    )
    result = project_import_preview(manifest, [])
    assert [row["duplicate_of_path"] for row in result["files"]] == [None, "First/one.wav", None]
    assert result["unique_source_hints"] == 2
    assert all(row["proposed_person_id"] is None for row in result["folders"])


@pytest.mark.parametrize(
    "path",
    [
        "/absolute.wav",
        "../call.wav",
        "Rep/../call",
        "Rep//call",
        "Rep/./call",
        "Rep\\call",
        "C:/call",
        "Rep/call\x00",
        "Rep/call\n",
        "Rep/call\ud800",
    ],
)
def test_manifest_rejects_unsafe_or_ambiguous_relative_paths(path):
    with pytest.raises(ValidationError):
        BatchManifest.model_validate({"files": [file(path)]})


@pytest.mark.parametrize("size", [0, -1, True, 32 * 1024 * 1024 + 1])
def test_file_limits_match_normal_intake_and_do_not_trust_boolean_size(size):
    with pytest.raises(ValidationError):
        BatchManifest.model_validate({"files": [file(size=size)]})


def test_manifest_is_bounded_and_duplicate_paths_are_not_silently_overwritten():
    for files in (
        [],
        [file(), file()],
        [file(f"Rep/{index}") for index in range(257)],
        [file(f"Rep/{index}", size=32 * 1024 * 1024) for index in range(33)],
    ):
        with pytest.raises(ValidationError):
            BatchManifest.model_validate({"files": files})


@pytest.mark.parametrize("digest", ["a" * 63, "G" * 64, "A" * 64, "../../"])
def test_source_hints_require_bounded_digests(digest):
    with pytest.raises(ValidationError):
        BatchManifest.model_validate({"files": [file(digest=digest)]})


def test_unicode_normalization_does_not_expand_the_path_past_its_limit():
    with pytest.raises(ValidationError):
        BatchManifest.model_validate({"files": [file("\u0344" * 512)]})


@pytest.mark.parametrize("role", ["owner", "admin", "member"])
async def test_preview_checks_live_role_and_never_writes_canonical_state(state, role):  # noqa: F811
    with Session(state.engine) as database, database.begin():
        database.get(Membership, (state.tenant, state.person)).role = role
        database.get(Person, state.member).first_name = "Swamini"
        database.get(Person, state.member).display_name = "Swamini Test"
    writes = []

    def capture(_connection, _cursor, statement, *_args):
        if statement.split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)

    event.listen(state.engine, "before_cursor_execute", capture)
    try:
        with Session(state.engine) as database, database.begin():
            ownership = GuestOwnership(
                AcquisitionSessions(
                    HttpDatabase(database), tenant_id=state.tenant, policy_revision="fictional"
                )
            )
            actor = ActorContext(state.person, state.session, state.tenant)
            manifest = BatchManifest.model_validate({"files": [file()]})
            if role == "member":
                with pytest.raises(ConversationDenied):
                    await preview_import(ownership, actor, manifest)
            else:
                result = await preview_import(ownership, actor, manifest)
                assert result["tenant_id"] == str(state.tenant)
                assert result["folders"][0]["proposed_person_id"] == str(state.member)
                database.get(Membership, (state.tenant, state.person)).role = "member"
                database.flush()
                writes.clear()
                with pytest.raises(ConversationDenied):
                    await preview_import(ownership, actor, manifest)
        assert writes == []
    finally:
        event.remove(state.engine, "before_cursor_execute", capture)


async def test_preview_excludes_inactive_members_and_never_crosses_selected_tenant(state):  # noqa: F811
    with Session(state.engine) as database, database.begin():
        database.get(Person, state.member).first_name = "Swamini"
        member = database.get(Membership, (state.tenant, state.member))
        member.status, member.ended_at = "inactive", datetime.now(UTC)
    with Session(state.engine) as database, database.begin():
        ownership = GuestOwnership(
            AcquisitionSessions(
                HttpDatabase(database), tenant_id=state.tenant, policy_revision="fictional"
            )
        )
        manifest = BatchManifest.model_validate({"files": [file()]})
        result = await preview_import(
            ownership, ActorContext(state.person, state.session, state.tenant), manifest
        )
        assert str(state.member) not in {member["person_id"] for member in result["members"]}
        assert result["folders"][0]["match_state"] == "unassigned"
        with pytest.raises(ConversationDenied):
            await preview_import(
                ownership,
                ActorContext(state.person, state.session, state.tenants["Beta"]),
                manifest,
            )
        with pytest.raises(ConversationDenied):
            await preview_import(ownership, None, manifest)


def preview_app(context):
    app = FastAPI()
    register_problem_handlers(app)

    @asynccontextmanager
    async def sessions():
        with Session(context.engine) as database:
            yield HttpDatabase(database)

    require_actor = install_identity_http(
        app, settings=context.settings, sessions=cast(Any, sessions)
    )

    async def current_owner(request):
        async with asynccontextmanager(require_actor)(request) as auth:
            actor = auth.resolved.actor
            yield _Owner(
                GuestOwnership(
                    AcquisitionSessions(
                        auth.database,
                        tenant_id=actor.tenant_id,
                        policy_revision="fictional",
                        operations_tenant_id=context.settings.operations_tenant_id,
                    )
                ),
                None,
                actor,
            )

    def guard(request, response, *, write=False):
        if write:
            require_safe_origin(request, context.settings)
        response.headers.update({"Cache-Control": "private, no-store", "Vary": "Cookie"})
        return "learner"

    router = APIRouter(prefix="/v1/conversation/acquisition")
    install_import_http(
        router,
        current_owner=current_owner,
        guard=guard,
        fail=lambda status, message: HTTPException(
            status, message, headers={"Cache-Control": "private, no-store"}
        ),
    )
    app.include_router(router)
    return app


async def test_cookie_http_preview_rechecks_roles_and_preserves_private_headers(state):  # noqa: F811
    app = preview_app(state)
    with Session(state.engine) as database, database.begin():
        database.get(Person, state.member).first_name = "Swamini"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://learner.authorityclosers.test"
    ) as client:
        path = "/v1/conversation/acquisition/imports/preview"
        headers = {
            "Origin": "https://learner.authorityclosers.test",
            "Cookie": f"ac_session={TOKEN}",
        }
        body = {"files": [file()]}
        assert (
            await client.post(path, json=body, headers={"Origin": headers["Origin"]})
        ).status_code == 401
        response = await client.post(path, json=body, headers=headers)
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "private, no-store"
        assert response.json()["requires_confirmation"] is True
        assert response.json()["folders"][0]["proposed_person_id"] == str(state.member)
        assert "email" not in response.text
        assert (
            await client.post(
                path, json=dict(body, owner_person_id=str(state.member)), headers=headers
            )
        ).status_code == 422
        assert (
            await client.post(
                path, json=body, headers={**headers, "Origin": "https://other.example.test"}
            )
        ).status_code == 403
        with Session(state.engine) as database, database.begin():
            database.get(Membership, (state.tenant, state.person)).role = "member"
        assert (await client.post(path, json=body, headers=headers)).status_code == 403


async def test_cookie_http_preview_rejects_changed_workspace_and_revoked_session(state):  # noqa: F811
    app = preview_app(state)
    headers = {"Origin": "https://learner.authorityclosers.test", "Cookie": f"ac_session={TOKEN}"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://learner.authorityclosers.test"
    ) as client:
        path = "/v1/conversation/acquisition/imports/preview"
        with Session(state.engine) as database, database.begin():
            database.get(IdentitySession, state.session).selected_tenant_id = state.tenants["Beta"]
        assert (
            await client.post(path, json={"files": [file()]}, headers=headers)
        ).status_code == 403
        with Session(state.engine) as database, database.begin():
            database.get(IdentitySession, state.session).revoked_at = datetime.now(UTC)
        assert (
            await client.post(path, json={"files": [file()]}, headers=headers)
        ).status_code == 401


@pytest.mark.parametrize("target", ["wrong", "malformed", "repeated"])
async def test_cookie_preview_asserts_the_exact_operator_target_without_granting_authority(
    state,  # noqa: F811
    target,
):
    app = preview_app(state)
    headers = [
        ("Origin", "https://learner.authorityclosers.test"),
        ("Cookie", f"ac_session={TOKEN}"),
        ("X-Recording-Import-Tenant", str(state.tenant)),
    ]
    if target == "wrong":
        headers[-1] = ("X-Recording-Import-Tenant", str(state.tenants["Beta"]))
    elif target == "malformed":
        headers[-1] = ("X-Recording-Import-Tenant", "unavailable")
    else:
        headers.append(headers[-1])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://learner.authorityclosers.test"
    ) as client:
        path = "/v1/conversation/acquisition/imports/preview"
        refused = await client.post(path, json={"files": [file()]}, headers=headers)
        assert refused.status_code == 403
        assert refused.headers["cache-control"] == "private, no-store"
        accepted = await client.post(
            path,
            json={"files": [file()]},
            headers={
                "Origin": headers[0][1],
                "Cookie": headers[1][1],
                "X-Recording-Import-Tenant": str(state.tenant),
            },
        )
        assert accepted.status_code == 200
        assert accepted.json()["tenant_id"] == str(state.tenant)
