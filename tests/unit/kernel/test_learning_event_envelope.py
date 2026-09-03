from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import TypeAdapter

from ac_platform.identity.application import ResolvedActorContext
from ac_platform.kernel.authz import ActorContext
from ac_platform.kernel.errors import AuthorizationDenied
from ac_platform.kernel.events import (
    LEARNING_EVENT_PAYLOAD_KEYS,
    LEARNING_EVENT_VERSIONS,
    EventCategory,
    EventEnvelope,
    ValidatedLearningEventProjection,
    _build_validated_learning_event_context,
    _build_validated_learning_event_projection,
    _copy_json_value,
    _freeze_learning_payload,
    _validated_clock,
    _validated_release_identity_from_settings,
    _validated_trace_from_request_id,
    _ValidatedClock,
    _ValidatedLearningEventContext,
    _ValidatedReleaseIdentity,
    _ValidatedTrace,
)

RELEASE_SHA = "a" * 40
NOW = datetime(2026, 9, 4, 10, 30, tzinfo=UTC)


def _integration_actor_context(
    *,
    tenant_id: object | None,
    membership_role: str | None = "learner",
    tenant_revision: int | None = 1,
    membership_revision: int | None = 1,
) -> ResolvedActorContext:
    actor = ActorContext(
        person_id=uuid4(),
        session_id=uuid4(),
        tenant_id=tenant_id,  # type: ignore[arg-type]
    )
    return ResolvedActorContext(
        actor=actor,
        membership_role=membership_role,
        person_revision=1,
        session_revision=1,
        tenant_revision=tenant_revision,
        membership_revision=membership_revision,
    )


def _projection_context(
    actor_context: ResolvedActorContext,
    *,
    now: datetime = NOW,
    subject_id: object | None = None,
):
    return _build_validated_learning_event_context(
        actor_context=actor_context,
        trace=_validated_trace_from_request_id("request-activity-1"),
        release=_validated_release_identity_from_settings(
            SimpleNamespace(environment="test", release_id=RELEASE_SHA)
        ),
        clock=_validated_clock(lambda: now),
        subject_id=subject_id,  # type: ignore[arg-type]
    )


def _event(
    *,
    name: str = "activity.completed",
    category: EventCategory = EventCategory.DOMAIN_FACT,
    tenant_id: object | None = None,
    payload: object | None = None,
) -> EventEnvelope:
    return EventEnvelope(
        name=name,
        category=category,
        aggregate_type="activity",
        aggregate_id=uuid4(),
        tenant_id=tenant_id if tenant_id is not None else uuid4(),  # type: ignore[arg-type]
        payload={} if payload is None else payload,  # type: ignore[arg-type]
        occurred_at=NOW,
    )


def test_public_projection_construction_is_not_the_creation_path() -> None:
    with pytest.raises(TypeError, match="in-process construction"):
        ValidatedLearningEventProjection(
            event_name="activity.completed",
            event_version="1.0",
            occurred_at=NOW,
            event_id=uuid4(),
            tenant_id=uuid4(),
            actor_id=uuid4(),
            subject_id=uuid4(),
            trace_id="request-1",
            release_sha=RELEASE_SHA,
            payload={},
        )


def test_projection_contract_serializes_with_standard_and_pydantic_paths() -> None:
    tenant_id = uuid4()
    projection = _build_validated_learning_event_projection(
        _event(tenant_id=tenant_id),
        context=_projection_context(_integration_actor_context(tenant_id=tenant_id)),
    )
    contract = projection.to_contract()
    adapter = TypeAdapter(ValidatedLearningEventProjection)

    assert adapter.dump_python(projection, mode="json") == contract
    assert json.loads(adapter.dump_json(projection)) == contract
    detached = asdict(projection)
    assert detached["payload"] == {}
    with pytest.raises(TypeError, match="immutable"):
        detached["payload"]["new"] = "caller mutation"
    with pytest.raises(TypeError, match="immutable"):
        projection.payload["new"] = "caller mutation"  # type: ignore[index]
    assert projection.to_contract()["payload"] == {}


def test_projection_context_carriers_are_not_directly_constructible() -> None:
    with pytest.raises(TypeError, match="projection factory"):
        _ValidatedLearningEventContext()
    with pytest.raises(TypeError, match="projection factory"):
        _ValidatedTrace("request-1")
    with pytest.raises(TypeError, match="projection factory"):
        _ValidatedReleaseIdentity("a" * 40)
    with pytest.raises(TypeError, match="projection factory"):
        _ValidatedClock(lambda: NOW)


def test_factory_projects_validated_fields_from_integration_context() -> None:
    tenant_id = uuid4()
    integration_context = _integration_actor_context(tenant_id=tenant_id)
    source = _event(tenant_id=tenant_id)

    projection = _build_validated_learning_event_projection(
        source, context=_projection_context(integration_context)
    )

    assert projection.event_id == source.event_id
    assert projection.event_name == "activity.completed"
    assert projection.event_version == "1.0"
    assert projection.occurred_at == NOW
    assert projection.tenant_id == tenant_id
    assert projection.actor_id == integration_context.actor.person_id
    assert projection.subject_id == integration_context.actor.person_id
    assert projection.trace_id == "request-activity-1"
    assert projection.release_sha == RELEASE_SHA
    assert json.loads(json.dumps(projection.to_contract()))["payload"] == {}


def test_projection_context_retains_validated_subject_and_membership_fields() -> None:
    tenant_id = uuid4()
    integration_context = _integration_actor_context(tenant_id=tenant_id)

    context = _projection_context(integration_context)

    assert context.subject_id == integration_context.actor.person_id
    assert context.membership.tenant_id == tenant_id
    assert context.membership.person_id == integration_context.actor.person_id
    assert context.membership.role == "learner"
    assert context.membership.person_revision == integration_context.person_revision
    assert context.membership.session_revision == integration_context.session_revision
    assert context.membership.tenant_revision == integration_context.tenant_revision
    assert context.membership.membership_revision == integration_context.membership_revision


def test_factory_requires_validated_membership_and_rejects_cross_tenant_event() -> None:
    tenant_id = uuid4()
    integration_context = _integration_actor_context(tenant_id=tenant_id)

    with pytest.raises(AuthorizationDenied, match="membership context"):
        _projection_context(_integration_actor_context(tenant_id=tenant_id, membership_role=None))

    with pytest.raises(AuthorizationDenied, match="tenant"):
        _build_validated_learning_event_projection(
            _event(tenant_id=uuid4()), context=_projection_context(integration_context)
        )

    with pytest.raises(AuthorizationDenied, match="cross-subject"):
        _projection_context(integration_context, subject_id=uuid4())

    with pytest.raises(TypeError, match="EventEnvelope"):
        _build_validated_learning_event_projection(
            object(),
            context=_projection_context(integration_context),  # type: ignore[arg-type]
        )


def test_factory_rejects_audit_tenantless_and_unknown_domain_events() -> None:
    tenant_id = uuid4()
    integration_context = _integration_actor_context(tenant_id=tenant_id)
    context = _projection_context(integration_context)

    with pytest.raises(ValueError, match="audit events"):
        _build_validated_learning_event_projection(
            _event(
                name="audit.activity.completed",
                category=EventCategory.AUDIT,
                tenant_id=tenant_id,
            ),
            context=context,
        )

    tenantless = EventEnvelope(
        name="activity.completed",
        category=EventCategory.DOMAIN_FACT,
        aggregate_type="activity",
        aggregate_id=uuid4(),
        tenant_id=None,
        payload={},
        occurred_at=NOW,
    )
    with pytest.raises(AuthorizationDenied, match="tenant"):
        _build_validated_learning_event_projection(tenantless, context=context)

    for name in ("payment.verified", "unknown.domain.fact", "activity.completed.v1"):
        with pytest.raises(ValueError, match="approved learning event"):
            _build_validated_learning_event_projection(
                _event(name=name, tenant_id=tenant_id), context=context
            )


def test_registry_contains_only_controlled_learning_names_and_version_one() -> None:
    expected = {
        "enrollment.created",
        "learning.started",
        "module.started",
        "activity.opened",
        "activity.progressed",
        "activity.completed",
        "activity.reopened",
        "module.completed",
        "program.completed",
        "next_action.generated",
        "streak.changed",
    }
    assert set(LEARNING_EVENT_VERSIONS) == expected
    assert set(LEARNING_EVENT_VERSIONS.values()) == {"1.0"}
    assert set(LEARNING_EVENT_PAYLOAD_KEYS) == expected
    assert all(not keys for keys in LEARNING_EVENT_PAYLOAD_KEYS.values())


@pytest.mark.parametrize(
    "payload",
    [
        {"activity_id": "not-yet-controlled"},
        {"email": "learner@example.test"},
        {"token": "Bearer secret"},
        {"transcript": "private text"},
        {"answer": "private response"},
    ],
)
def test_payload_is_fail_closed_until_an_event_schema_allowlists_fields(
    payload: dict[str, str],
) -> None:
    tenant_id = uuid4()
    with pytest.raises(ValueError, match="not allowlisted|sensitive"):
        _build_validated_learning_event_projection(
            _event(tenant_id=tenant_id, payload=payload),
            context=_projection_context(_integration_actor_context(tenant_id=tenant_id)),
        )


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (b"bytes", "non-JSON-safe"),
        ({"nested"}, "non-JSON-safe"),
        (object(), "non-JSON-safe"),
        (float("nan"), "finite"),
        (float("inf"), "finite"),
    ],
)
def test_bounded_payload_copy_rejects_non_json_values(value: object, message: str) -> None:
    with pytest.raises((TypeError, ValueError), match=message):
        _copy_json_value(value, depth=0, active_ids=set(), path="payload")


def test_bounded_payload_copy_rejects_cycles_depth_and_size() -> None:
    cyclic: list[object] = []
    cyclic.append(cyclic)
    with pytest.raises(ValueError, match="cycle"):
        _copy_json_value(cyclic, depth=0, active_ids=set(), path="payload")

    deep: object = "leaf"
    for _ in range(8):
        deep = [deep]
    with pytest.raises(ValueError, match="depth"):
        _copy_json_value(deep, depth=0, active_ids=set(), path="payload")

    with pytest.raises(ValueError, match="bounded object size"):
        _copy_json_value(
            {str(index): index for index in range(33)},
            depth=0,
            active_ids=set(),
            path="payload",
        )

    with pytest.raises(ValueError, match="bounded sequence size"):
        _copy_json_value(list(range(33)), depth=0, active_ids=set(), path="payload")

    with pytest.raises(ValueError, match="bounded length"):
        _copy_json_value("x" * 513, depth=0, active_ids=set(), path="payload")


def test_bounded_payload_copy_detaches_before_freezing() -> None:
    original: dict[str, object] = {"safe": {"items": ["before"]}}

    normalized = _copy_json_value(original, depth=0, active_ids=set(), path="payload")
    frozen = _freeze_learning_payload(normalized)
    original["safe"] = {"items": ["after"]}

    assert normalized == {"safe": {"items": ["before"]}}
    assert frozen["safe"]["items"] == ("before",)


def test_validated_release_trace_and_clock_inputs_reject_bad_values() -> None:
    with pytest.raises(ValueError, match="release identity"):
        _validated_release_identity_from_settings(
            SimpleNamespace(environment="test", release_id="local-unreleased")
        )
    with pytest.raises(ValueError, match="trace"):
        _validated_trace_from_request_id("contains whitespace")
    with pytest.raises(ValueError, match="timezone"):
        tenant_id = uuid4()
        _build_validated_learning_event_projection(
            _event(tenant_id=tenant_id),
            context=_projection_context(
                _integration_actor_context(tenant_id=tenant_id),
                now=datetime(2026, 9, 4, 10, 30),
            ),
        )


def test_event_occurrence_cannot_be_in_the_future_of_the_validated_clock() -> None:
    tenant_id = uuid4()
    source = _event(tenant_id=tenant_id)
    future = EventEnvelope(
        name=source.name,
        category=source.category,
        aggregate_type=source.aggregate_type,
        aggregate_id=source.aggregate_id,
        tenant_id=tenant_id,
        payload={},
        occurred_at=NOW.replace(hour=11),
        event_id=source.event_id,
    )
    with pytest.raises(ValueError, match="future"):
        _build_validated_learning_event_projection(
            future,
            context=_projection_context(_integration_actor_context(tenant_id=tenant_id), now=NOW),
        )


def test_existing_event_remains_unchanged_and_contract_output_is_detached() -> None:
    tenant_id = uuid4()
    source = _event(tenant_id=tenant_id)
    source_payload = dict(source.payload)
    projection = _build_validated_learning_event_projection(
        source,
        context=_projection_context(_integration_actor_context(tenant_id=tenant_id)),
    )

    output = projection.to_contract()
    output["payload"]["new"] = "caller mutation"

    assert source.payload == source_payload
    assert projection.to_contract()["payload"] == {}
