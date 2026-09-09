"""Published-to-draft Studio revision through the real relational HTTP boundary."""

from dataclasses import replace
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import AuditRepository, verify_audit_chain_sync
from ac_platform.catalog.models import (
    Activity,
    ActivityKind,
    CatalogAuthoringCommand,
    LearnerVersionPin,
    Module,
    ModulePrerequisite,
    ProgramVersion,
)
from ac_platform.catalog.services import CatalogAccessDeniedError
from ac_platform.db.base import Base
from ac_platform.http.surfaces import CoachSurfaceMiddleware
from ac_platform.tenancy.models import Membership
from tests.unit.catalog.test_studio_capabilities import (
    capability_state,  # noqa: F401
    catalog_state,  # noqa: F401
)
from tests.unit.http.test_admin_learning_routes import _settings
from tests.unit.http.test_studio_draft_authoring import (
    etag,
    send,
    studio_draft,  # noqa: F401
)


@pytest.fixture
async def published(studio_draft):  # noqa: F811
    state = studio_draft
    state.application.add_middleware(CoachSurfaceMiddleware, settings=_settings())
    second = state.resources[state.program].second
    state.domain.add_module_prerequisite(second, state.module, tenant_id=state.academy)
    for position, kind in enumerate(ActivityKind, start=2):
        state.domain.add_activity(
            state.module,
            tenant_id=state.academy,
            kind=kind,
            title=f"{kind.value} practice",
            prompt=f"Prompt for {kind.value}",
            is_required=position % 2 == 0,
            position=position,
        )
    version = state.domain.get_version(state.version, tenant_id=state.academy)
    state.db.get(ProgramVersion, state.version).content_digest = (
        state.domain._canonical_content_digest(version)  # noqa: SLF001
    )
    state.db.flush()
    state.domain.publish_version(state.version, tenant_id=state.academy)
    state.db.add(
        LearnerVersionPin(
            tenant_id=state.academy,
            learner_person_id=state.learner,
            program_id=state.program,
            program_version_id=state.version,
            program_scope="tenant",
            program_tenant_id=state.academy,
            program_owner_key=state.academy,
        )
    )
    state.db.flush()
    return state


def counts(state):
    return tuple(
        state.db.scalar(select(func.count()).select_from(model))
        for model in (
            ProgramVersion,
            Module,
            Activity,
            ModulePrerequisite,
            CatalogAuthoringCommand,
            AuditEvent,
        )
    )


def unrelated_rows(state):
    changed = {
        "program_versions",
        "modules",
        "activities",
        "module_prerequisites",
        "catalog_authoring_commands",
        "audit_events",
        "audit_chain_heads",
    }
    return {
        table.name: tuple(state.db.execute(select(table)).all())
        for table in Base.metadata.sorted_tables
        if table.name not in changed
    }


async def test_revision_clones_only_content_and_remapped_prerequisites(published):
    state = published
    source_etag = etag(state)
    before, unrelated = counts(state), unrelated_rows(state)
    source = state.db.get(ProgramVersion, state.version)
    source_modules = state.db.scalars(
        select(Module).where(Module.program_version_id == source.id).order_by(Module.position)
    ).all()
    source_activities = state.db.scalars(
        select(Activity).where(Activity.program_version_id == source.id).order_by(Activity.position)
    ).all()
    source_edges = state.db.scalars(
        select(ModulePrerequisite).where(ModulePrerequisite.program_version_id == source.id)
    ).all()
    response = await send(state, "revision", {})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["replayed"] is False and response.headers["cache-control"] == "no-store"
    new_id = UUID(payload["resource_id"])
    draft = state.db.get(ProgramVersion, new_id)
    assert draft.id != source.id and draft.version_number == source.version_number + 1
    assert draft.status == "draft" and draft.supersedes_version_id == source.id
    assert draft.program_id == source.program_id and draft.tenant_id == source.tenant_id
    assert draft.content_source_ref == source.content_source_ref
    assert draft.content_seed_kind == source.content_seed_kind
    assert all(
        getattr(draft, field) is None
        for field in (
            "content_digest",
            "content_reviewed_by",
            "content_reviewed_at",
            "release_id",
            "published_at",
            "superseded_at",
        )
    )
    new_modules = state.db.scalars(
        select(Module).where(Module.program_version_id == new_id).order_by(Module.position)
    ).all()
    new_activities = state.db.scalars(
        select(Activity).where(Activity.program_version_id == new_id).order_by(Activity.position)
    ).all()
    assert [(row.title, row.position) for row in new_modules] == [
        (row.title, row.position) for row in source_modules
    ]
    module_map = {old.id: new.id for old, new in zip(source_modules, new_modules, strict=True)}
    assert not set(module_map) & set(module_map.values())
    assert {row.id for row in new_activities}.isdisjoint(row.id for row in source_activities)
    for old, new in zip(source_activities, new_activities, strict=True):
        assert new.module_id == module_map[old.module_id]
        assert (new.kind, new.title, new.prompt, new.position, new.is_required) == (
            old.kind,
            old.title,
            old.prompt,
            old.position,
            old.is_required,
        )
    new_edges = state.db.scalars(
        select(ModulePrerequisite).where(ModulePrerequisite.program_version_id == new_id)
    ).all()
    assert {(row.module_id, row.prerequisite_module_id) for row in new_edges} == {
        (module_map[row.module_id], module_map[row.prerequisite_module_id]) for row in source_edges
    }
    assert {row.id for row in new_edges}.isdisjoint(row.id for row in source_edges)
    assert counts(state) == (
        before[0] + 1,
        before[1] + len(source_modules),
        before[2] + len(source_activities),
        before[3] + len(source_edges),
        before[4] + 1,
        before[5] + 1,
    )
    assert unrelated_rows(state) == unrelated
    assert source.status == "published" and etag(state) == source_etag
    rendered = next(row for row in payload["program"]["versions"] if row["id"] == str(new_id))
    assert rendered["readiness"] == "blocked" and "provenance_incomplete" in rendered["blockers"]
    original = next(row for row in payload["program"]["versions"] if row["id"] == str(source.id))
    assert original["readiness"] == "immutable" and original["etag"] == source_etag
    receipt = state.db.scalar(
        select(CatalogAuthoringCommand).where(CatalogAuthoringCommand.resource_id == new_id)
    )
    assert receipt.operation == "version_revise" and receipt.program_version_id == source.id
    audit = state.db.get(AuditEvent, receipt.audit_event_id)
    assert audit.payload == {
        "operation": "version_revise",
        "program_id": str(state.program),
        "resource_id": str(new_id),
    }
    assert verify_audit_chain_sync(state.db, state.academy).valid


async def test_exact_replay_changed_intent_and_independent_new_revision(published):
    state = published
    expected, key = etag(state), str(uuid4())
    saved = await send(state, "revision", {}, expected=expected, key=key)
    before = counts(state)
    replay = await send(state, "revision", {}, expected=expected, key=key)
    assert replay.status_code == 200 and replay.json()["replayed"] is True
    assert replay.json()["resource_id"] == saved.json()["resource_id"]
    changed = await send(
        state, "revision", {}, expected='"program-version-' + "0" * 64 + '"', key=key
    )
    assert changed.status_code == 409 and counts(state) == before
    another = await send(state, "revision", {}, expected=expected)
    assert (
        another.status_code == 200 and another.json()["resource_id"] != saved.json()["resource_id"]
    )
    assert state.db.get(ProgramVersion, UUID(another.json()["resource_id"])).version_number == 3


@pytest.mark.parametrize(
    "body",
    [
        None,
        [],
        {"title": "Unexpected"},
        {"content_reviewed_by": "Claim"},
        {"tenant_id": str(uuid4())},
    ],
)
async def test_revision_requires_an_explicit_empty_object(published, body):
    before = counts(published)
    assert (await send(published, "revision", body)).status_code == 422
    assert counts(published) == before


@pytest.mark.parametrize("permission", ["read", "write"])
async def test_revoked_capability_blocks_new_command_and_exact_replay(published, permission):
    state = published
    expected, key = etag(state), str(uuid4())
    assert (await send(state, "revision", {}, expected=expected, key=key)).status_code == 200
    await state.app.revoke(
        state.actor,
        command_id=uuid4(),
        grant_id=getattr(state, f"{permission}_grant").id,
        reason="Fixture assignment ended",
    )
    before = counts(state)
    assert (await send(state, "revision", {}, expected=expected, key=key)).status_code == 403
    assert (await send(state, "revision", {}, expected=expected)).status_code == 403
    with pytest.raises(CatalogAccessDeniedError):
        await state.catalog.revise_published_version(
            actor=state.learner_actor,
            tenant_id=state.academy,
            program_version_id=state.version,
            expected_etag=expected,
            idempotency_key=key,
        )
    assert counts(state) == before


@pytest.mark.parametrize("target", ["second", "foreign", "global_program"])
async def test_revision_is_confined_to_exact_assigned_tenant_program(published, target):
    state = published
    expected = etag(state)
    state.version = state.resources[getattr(state, target)].version
    before = counts(state)
    assert (await send(state, "revision", {}, expected=expected)).status_code == 404
    with pytest.raises(CatalogAccessDeniedError):
        await state.catalog.revise_published_version(
            actor=state.learner_actor,
            tenant_id=state.academy,
            program_version_id=state.version,
            expected_etag=expected,
            idempotency_key=str(uuid4()),
        )
    assert counts(state) == before


async def test_stale_etag_draft_and_superseded_sources_are_rejected(published):
    state = published
    before = counts(state)
    assert (
        await send(state, "revision", {}, expected='"program-version-' + "0" * 64 + '"')
    ).status_code == 412
    assert counts(state) == before
    saved = await send(state, "revision", {})
    source_id = state.version
    state.version = UUID(saved.json()["resource_id"])
    before = counts(state)
    assert (await send(state, "revision", {})).status_code == 409
    assert counts(state) == before
    review_and_publish(state, state.version)
    state.version = source_id
    before = counts(state)
    assert (await send(state, "revision", {})).status_code == 409
    assert counts(state) == before


def review_and_publish(state, version_id):
    # Explicit isolated fixture review; never an application review shortcut.
    version = state.domain.get_version(version_id, tenant_id=state.academy)
    row = state.db.get(ProgramVersion, version_id)
    row.content_reviewed_by = "Isolated test reviewer"
    row.content_reviewed_at = state.db.get(ProgramVersion, state.version).created_at
    row.release_id = "f" * 40
    # Identical reviewed content cannot be re-published under the unique digest:
    # a real revision must change reviewed content first.
    module = state.db.scalar(select(Module).where(Module.program_version_id == version_id))
    state.domain.update_module(module.id, tenant_id=state.academy, title="Reviewed revision")
    row.content_digest = state.domain._canonical_content_digest(version)  # noqa: SLF001
    state.db.flush()
    state.domain.publish_version(version_id, tenant_id=state.academy)


async def test_receipt_replays_after_source_supersession_and_result_history_truncation(
    published, monkeypatch
):
    import ac_platform.http.admin_learning as routes

    state = published
    expected, key = etag(state), str(uuid4())
    saved = await send(state, "revision", {}, expected=expected, key=key)
    result_id = UUID(saved.json()["resource_id"])
    review_and_publish(state, result_id)
    assert state.db.get(ProgramVersion, state.version).status == "superseded"
    monkeypatch.setattr(routes, "STUDIO_IMMUTABLE_VERSION_LIMIT", 0)
    before = counts(state)
    replay = await send(state, "revision", {}, expected=expected, key=key)
    assert replay.status_code == 200, replay.text
    assert replay.json()["replayed"] is True and replay.json()["resource_id"] == str(result_id)
    assert any(v["id"] == str(result_id) for v in replay.json()["program"]["versions"])
    assert replay.json()["program"]["versions_truncated"] is True and counts(state) == before
    state.version = result_id
    changed_source = await send(state, "revision", {}, key=key)
    assert changed_source.status_code == 409 and counts(state) == before


async def test_receipt_key_cannot_cross_between_authoring_and_revision_intents(published):
    state = published
    key = str(uuid4())
    saved = await send(state, "revision", {}, key=key)
    state.version = UUID(saved.json()["resource_id"])
    before = counts(state)
    collision = await send(state, "modules", {"title": "Another command"}, key=key)
    assert collision.status_code == 409 and counts(state) == before


async def test_failed_audit_and_failed_outer_commit_roll_back_complete_revision(
    published, monkeypatch
):
    state = published
    before, unrelated = counts(state), unrelated_rows(state)
    original = AuditRepository.append_for_actor

    async def fail_audit(*_args, **_kwargs):
        assert counts(state)[0] == before[0] + 1
        raise RuntimeError("revision audit fixture failure")

    monkeypatch.setattr(AuditRepository, "append_for_actor", fail_audit)
    with pytest.raises(RuntimeError, match="revision audit fixture failure"):
        await send(state, "revision", {})
    assert counts(state) == before and unrelated_rows(state) == unrelated
    monkeypatch.setattr(AuditRepository, "append_for_actor", original)
    state.fail_commit = True
    assert (await send(state, "revision", {})).status_code == 500
    assert counts(state) == before and unrelated_rows(state) == unrelated


@pytest.mark.parametrize(
    "case,status",
    [("missing_etag", 428), ("missing_key", 428), ("bad_etag", 400), ("cross_origin", 403)],
)
async def test_revision_origin_and_exact_preconditions(published, case, status):
    headers = {
        "Origin": published.origin,
        "If-Match": etag(published),
        "Idempotency-Key": str(uuid4()),
    }
    if case == "missing_etag":
        del headers["If-Match"]
    elif case == "missing_key":
        del headers["Idempotency-Key"]
    elif case == "bad_etag":
        headers["If-Match"] = "*"
    else:
        headers["Origin"] = "https://untrusted.example.test"
    before = counts(published)
    assert (await send(published, "revision", {}, headers=headers)).status_code == status
    assert counts(published) == before


async def test_global_catalog_etag_remains_unavailable(studio_draft):  # noqa: F811
    state = studio_draft
    state.domain.publish_version(state.resources[state.global_program].version, tenant_id=None)
    state.db.get(Membership, (state.academy, state.learner)).role = "admin"
    state.learner_actor = replace(state.learner_actor, permissions=frozenset({"catalog_read"}))
    state.db.flush()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=state.application), base_url=state.origin
    ) as client:
        response = await client.get(f"/v1/admin/studio/programs/{state.global_program}")
    assert response.status_code == 200, response.text
    assert len(response.json()["versions"]) == 1
    assert all(
        v["etag"] is None and v["readiness"] == "global_read_only"
        for v in response.json()["versions"]
    )
