"""Internal processing actors are not login sessions or verified learners."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from ac_platform.kernel.authz import ActorContext


@dataclass(frozen=True, slots=True)
class ProcessingActor:
    person_id: UUID
    tenant_id: UUID
    processing_lease_id: UUID

    @property
    def session_id(self) -> None:
        return None


ConversationActor = ActorContext | ProcessingActor


def actor_columns(actor: ConversationActor) -> dict[str, UUID | None]:
    return {
        "session_id": actor.session_id,
        "processing_lease_id": (
            actor.processing_lease_id if isinstance(actor, ProcessingActor) else None
        ),
    }


def actor_binding(actor: ConversationActor) -> dict[str, str | None]:
    result: dict[str, str | None] = {
        "session_id": str(actor.session_id) if actor.session_id is not None else None
    }
    if isinstance(actor, ProcessingActor):
        result["processing_lease_id"] = str(actor.processing_lease_id)
    return result


def same_actor(row: Any, actor: ConversationActor) -> bool:
    return (
        row.tenant_id == actor.tenant_id
        and row.person_id == actor.person_id
        and row.session_id == actor.session_id
        and getattr(row, "processing_lease_id", None)
        == (actor.processing_lease_id if isinstance(actor, ProcessingActor) else None)
    )


def actor_from_row(row: Any) -> ConversationActor:
    """Rehydrate from an authoritative task/plan row, never an HTTP object."""
    lease = getattr(row, "processing_lease_id", None)
    if type(row.person_id) is not UUID or type(row.tenant_id) is not UUID:
        raise ValueError("processing_actor_scope_invalid")
    if row.session_id is None and type(lease) is UUID:
        return ProcessingActor(row.person_id, row.tenant_id, lease)
    if type(row.session_id) is UUID and lease is None:
        return ActorContext(row.person_id, row.session_id, row.tenant_id)
    raise ValueError("processing_actor_binding_invalid")
