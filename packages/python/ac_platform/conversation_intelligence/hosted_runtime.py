"""Explicit API composition from immutable, non-secret release approval.

No provider calls, credential loading, worker startup or local proof import.
The release coordinator supplies the approved artifact and its exact digest.
"""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from ac_platform.conversation_intelligence.activation_contract import (
    MAX_APPROVAL_BUNDLE_BYTES,
    HostedApprovalBundle,
    load_hosted_approval_bundle,
)
from ac_platform.conversation_intelligence.application import AUDIOATLAS_HOSTED_RECIPE
from ac_platform.conversation_intelligence.authority import ConversationAuthority
from ac_platform.conversation_intelligence.intake import IntakePolicy
from ac_platform.conversation_intelligence.storage import PrivateLocalRecordingStorage

if TYPE_CHECKING:
    from ac_platform.http.conversation_intake import ConversationIntakeRuntime


class HostedConversationSettings(Protocol):
    """Only the non-secret settings shared by API and dedicated workers."""

    @property
    def environment(self) -> str: ...

    @property
    def operations_tenant_id(self) -> UUID | None: ...

    @property
    def sales_xray_enabled(self) -> bool: ...

    @property
    def sales_xray_approval_path(self) -> str | None: ...

    @property
    def sales_xray_approval_sha256(self) -> str | None: ...

    @property
    def sales_xray_storage_root(self) -> str | None: ...

    @property
    def sales_xray_scratch_root(self) -> str | None: ...


@dataclass(frozen=True)
class PinnedApprovalLoader:
    path: Path
    sha256: str
    environment: str
    operations_tenant_id: UUID

    def __call__(self) -> HostedApprovalBundle:
        try:
            if (
                not self.path.is_absolute()
                or ".." in self.path.parts
                or len(self.sha256) != 64
                or any(c not in "0123456789abcdef" for c in self.sha256)
                or any(p.is_symlink() for p in (self.path, *self.path.parents))
            ):
                raise ValueError
            descriptor = os.open(self.path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(descriptor, "rb") as stream:
                metadata = os.fstat(stream.fileno())
                if (
                    not stat.S_ISREG(metadata.st_mode)
                    or metadata.st_nlink != 1
                    or not 0 < metadata.st_size <= MAX_APPROVAL_BUNDLE_BYTES
                    or (os.name != "nt" and metadata.st_mode & 0o022)
                ):
                    raise ValueError
                raw = stream.read(MAX_APPROVAL_BUNDLE_BYTES + 1)
            if hashlib.sha256(raw).hexdigest() != self.sha256:
                raise ValueError
            bundle = load_hosted_approval_bundle(raw)
            bundle.current(int(datetime.now(UTC).timestamp()), self.environment)
            if bundle.provider_control_tenant_id != self.operations_tenant_id:
                raise ValueError
            if self.environment != "test" and any(
                item.zero_cost_basis == "synthetic" for item in bundle.stages
            ):
                raise ValueError
            return bundle
        except (OSError, ValueError, TypeError):
            raise ValueError("hosted_approval_unavailable") from None


def compose_hosted_intake(settings: HostedConversationSettings) -> ConversationIntakeRuntime | None:
    # Late import keeps the pure authority layer independent of the HTTP graph.
    from ac_platform.http.conversation_intake import ConversationIntakeRuntime

    if not settings.sales_xray_enabled:
        return None
    if settings.environment not in {"staging", "production", "test"}:
        raise ValueError("hosted_conversation_environment_required")
    if not all(
        (
            settings.sales_xray_approval_path,
            settings.sales_xray_approval_sha256,
            settings.sales_xray_storage_root,
            settings.sales_xray_scratch_root,
            settings.operations_tenant_id,
        )
    ):
        raise ValueError("hosted_conversation_configuration_incomplete")
    if not isinstance(settings.operations_tenant_id, UUID):
        raise ValueError("hosted_conversation_configuration_incomplete")
    loader = PinnedApprovalLoader(
        Path(settings.sales_xray_approval_path or ""),
        settings.sales_xray_approval_sha256 or "",
        settings.environment,
        settings.operations_tenant_id,
    )
    bundle = loader()
    authority = ConversationAuthority(
        loader,
        environment=settings.environment,
        operations_tenant_id=settings.operations_tenant_id,
    )
    storage_path, scratch_path = (
        Path(settings.sales_xray_storage_root or ""),
        Path(settings.sales_xray_scratch_root or ""),
    )
    if storage_path.is_relative_to(scratch_path) or scratch_path.is_relative_to(storage_path):
        raise ValueError("hosted_storage_roots_must_be_separate")
    return ConversationIntakeRuntime(
        policy=IntakePolicy(
            budget_scope_id=bundle.budget_scope_id,
            tenant_ids=frozenset(item.tenant_id for item in bundle.allowances),
            authorization_ref=bundle.intake_authorization_ref,
            retention_ref=bundle.intake_retention_ref,
            retention_days=bundle.retention_days,
            acoustic_recipe=AUDIOATLAS_HOSTED_RECIPE,
        ),
        storage=PrivateLocalRecordingStorage(storage_path),
        scratch=PrivateLocalRecordingStorage(scratch_path),
        authority=authority,
    )
