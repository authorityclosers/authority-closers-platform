from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from ac_platform.kernel.errors import AuthorizationDenied


@dataclass(frozen=True, slots=True)
class ActorContext:
    person_id: UUID
    session_id: UUID
    tenant_id: UUID | None
    permissions: frozenset[str] = frozenset()

    def require_self(self, subject_person_id: UUID) -> None:
        if self.person_id != subject_person_id:
            raise AuthorizationDenied("The actor may only perform this action for themself.")

    def require_tenant(self, resource_tenant_id: UUID) -> None:
        if self.tenant_id is None or self.tenant_id != resource_tenant_id:
            raise AuthorizationDenied("The selected tenant does not own this resource.")

    def require_permission(self, permission: str) -> None:
        if permission not in self.permissions:
            raise AuthorizationDenied("The actor does not hold the required permission.")
