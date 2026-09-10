"""Explicit platform and scoped Studio capability persistence."""

from ac_platform.authorization.models import (
    PLATFORM_CAPABILITIES,
    STUDIO_CAPABILITIES,
    SUPPORTED_CAPABILITIES,
    CapabilityGrant,
    CapabilityHistoryMutationError,
    CapabilityRevocation,
)

__all__ = [
    "PLATFORM_CAPABILITIES",
    "STUDIO_CAPABILITIES",
    "SUPPORTED_CAPABILITIES",
    "CapabilityGrant",
    "CapabilityHistoryMutationError",
    "CapabilityRevocation",
]
