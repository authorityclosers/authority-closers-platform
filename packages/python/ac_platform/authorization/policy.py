"""Explicit capability vocabulary; no role, email or scope implies a wildcard."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from ac_platform.authorization.models import PLATFORM_CAPABILITIES, STUDIO_CAPABILITIES
from ac_platform.kernel.errors import AuthorizationDenied, DomainError

PLATFORM_PERMISSIONS = PLATFORM_CAPABILITIES
STUDIO_PERMISSIONS = STUDIO_CAPABILITIES


class CapabilityDenied(AuthorizationDenied):
    """No current canonical grant authorizes this exact action and scope."""


class CapabilityConflict(DomainError):
    code = "capability_command_conflict"
    title = "The permission change conflicts with current state"
    status = 409


class CapabilityInvalid(DomainError):
    code = "capability_command_invalid"
    title = "The permission change is invalid"
    status = 422


@dataclass(frozen=True, slots=True)
class CapabilityScope:
    kind: str
    tenant_id: UUID | None = None
    program_id: UUID | None = None

    def validate(self, permission: str) -> None:
        if self.kind == "platform":
            valid = (
                permission in PLATFORM_PERMISSIONS
                and self.tenant_id is None
                and self.program_id is None
            )
        elif self.kind == "tenant":
            valid = (
                permission in STUDIO_PERMISSIONS
                and self.tenant_id is not None
                and self.program_id is None
            )
        elif self.kind == "program":
            valid = (
                permission in STUDIO_PERMISSIONS
                and self.tenant_id is not None
                and self.program_id is not None
            )
        else:
            valid = False
        if not valid:
            raise CapabilityInvalid("Use a supported capability with its exact resource scope.")


def grants_action(grant: CapabilityScope, requested: CapabilityScope) -> bool:
    """A program assignment never authorizes an unfiltered tenant collection."""

    if grant.kind == "platform" or requested.kind == "platform":
        return grant == requested
    if grant.tenant_id != requested.tenant_id:
        return False
    return grant.kind == "tenant" or grant == requested
